import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from accounts import AccountStore, BillingSandboxConflict
import server


PASSWORD = "a-long-local-test-passphrase"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    return server.create_app({
        "TESTING": True,
        "AUTH_MODE": "accounts",
        "ACCOUNT_REGISTRATION_OPEN": True,
        "BILLING_SANDBOX_ENABLED": True,
        "SECRET_KEY": "a-session-secret-longer-than-32-characters",
        "PILOT_PASSWORD": None,
        "SESSION_COOKIE_SECURE": False,
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.db"),
        "RATE_DB_PATH": str(tmp_path / "limits.db"),
        "CASE_DB_PATH": str(tmp_path / "cases.db"),
    })


def register(store, email="owner@example.test", company="Synthetic Company",
             identifier="CHE123456789", verified=True):
    user = store.register(
        email=email, password=PASSWORD, company_name=company,
        company_identifier=identifier, role="Representative", locale="it",
    )
    if verified:
        store.consume_token(store.issue_token(user["id"], "email"), "email")
        store.verify_company(user["company_id"], user["id"])
    return store.get_user(user["id"])


def login(client, email="owner@example.test"):
    csrf = client.get("/api/session").json["csrf"]
    return client.post("/api/login", json={"email": email, "password": PASSWORD},
                       headers={"X-CSRF-Token": csrf}).json


def create(client, csrf, *, plan="tier_team_v1", cycle="monthly", key="checkout-test-key-001", extra=None):
    payload = {"plan_code": plan, "billing_cycle": cycle}
    if extra:
        payload.update(extra)
    return client.post(
        "/api/sandbox/billing/checkout-simulations", json=payload,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
    )


def test_flag_off_hides_every_route_before_auth_and_changes_nothing(app):
    app.config["BILLING_SANDBOX_ENABLED"] = False
    client = app.test_client()
    paths = [
        ("get", "/api/sandbox/billing/plans"),
        ("post", "/api/sandbox/billing/checkout-simulations"),
        ("get", "/api/sandbox/billing/checkout-simulations/unknown"),
        ("post", "/api/sandbox/billing/checkout-simulations/unknown/confirm"),
        ("post", "/api/sandbox/billing/checkout-simulations/unknown/cancel"),
    ]
    for method, path in paths:
        response = getattr(client, method)(path, json={} if method == "post" else None)
        assert response.status_code == 404
        assert response.json["error"]["code"] == "billing_sandbox_unavailable"
    with app.extensions["account_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM billing_checkout_intents").fetchone()[0] == 0


def test_catalog_is_draft_stable_and_contains_no_approved_price(app):
    user = register(app.extensions["account_store"])
    client = app.test_client(); login(client, user["email"])
    response = client.get("/api/sandbox/billing/plans")
    assert response.status_code == 200
    body = response.json
    assert body["simulation"] is True and body["charged"] is False
    assert body["subscription_active"] is False and body["status"] == "draft_unapproved"
    assert {plan["plan_code"] for plan in body["plans"]} == {
        "trial_company_v1", "tier_essential_v1", "tier_team_v1", "tier_partner_v1",
    }
    for plan in body["plans"]:
        assert plan["price"] == {"amount_chf": None, "status": "draft_unapproved"}
        if plan["selectable"]:
            assert plan["quota"]["period"] == "TBD"


def test_verified_account_can_create_replay_confirm_without_plan_or_quota_mutation(app):
    store = app.extensions["account_store"]; user = register(store)
    client = app.test_client(); state = login(client, user["email"]); csrf = state["csrf"]
    before_entitlement = client.get("/api/session").json["entitlement"]
    first = create(client, csrf)
    assert first.status_code == 201
    checkout = first.json["checkout"]
    assert checkout["status"] == "draft"
    assert checkout["simulation"] is True and checkout["charged"] is False
    assert checkout["subscription_active"] is False
    assert checkout["selection"]["plan_code"] == "tier_team_v1"
    assert checkout["selection"]["quota"] == {"analyses": None, "period": "TBD"}
    replay = create(client, csrf)
    assert replay.status_code == 200
    assert replay.json["checkout"]["checkout_id"] == checkout["checkout_id"]

    confirmed = client.post(
        f'/api/sandbox/billing/checkout-simulations/{checkout["checkout_id"]}/confirm',
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json["checkout"]["status"] == "confirmed_simulation"
    assert confirmed.json["checkout"]["subscription_active"] is False
    again = client.post(
        f'/api/sandbox/billing/checkout-simulations/{checkout["checkout_id"]}/confirm',
        headers={"X-CSRF-Token": csrf},
    )
    assert again.json["idempotent_replay"] is True
    assert client.get("/api/session").json["entitlement"] == before_entitlement
    with app.extensions["limit_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM trial_usage").fetchone()[0] == 0
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM billing_checkout_intents").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM billing_checkout_audit WHERE event='confirmed_simulation'").fetchone()[0] == 1


def test_idempotency_conflict_rejects_different_selection_and_stores_only_hash(app):
    store = app.extensions["account_store"]; user = register(store)
    client = app.test_client(); csrf = login(client, user["email"])["csrf"]
    assert create(client, csrf, key="same-idempotency-key").status_code == 201
    conflict = create(client, csrf, plan="tier_partner_v1", key="same-idempotency-key")
    assert conflict.status_code == 409 and conflict.json["error"]["code"] == "idempotency_mismatch"
    raw = open(app.config["ACCOUNT_DB_PATH"], "rb").read()
    assert b"same-idempotency-key" not in raw


def test_concurrent_same_command_creates_one_intent(app):
    store = app.extensions["account_store"]; user = register(store)

    def attempt(_):
        return store.create_checkout_simulation(
            user["company_id"], user["id"], "tier_essential_v1", "annual",
            idempotency_key="atomic-checkout-key",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results[0]["checkout_id"] == results[1]["checkout_id"]
    assert sum(bool(item.get("idempotent_replay")) for item in results) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM billing_checkout_intents").fetchone()[0] == 1


def test_owner_and_company_isolation_including_same_company_member(app):
    store = app.extensions["account_store"]; owner = register(store)
    member = store.add_member(owner["company_id"], email="member@example.test", password=PASSWORD,
                              role="Employee", approved=True)
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    outsider = register(store, email="outside@example.test", company="Outside",
                       identifier="CHE999888777")
    a, b, c = app.test_client(), app.test_client(), app.test_client()
    sa, sb, sc = login(a), login(b, member["email"]), login(c, outsider["email"])
    intent = create(a, sa["csrf"]).json["checkout"]
    path = f'/api/sandbox/billing/checkout-simulations/{intent["checkout_id"]}'
    assert b.get(path).status_code == 404
    assert c.get(path).status_code == 404
    assert b.post(path + "/confirm", headers={"X-CSRF-Token": sb["csrf"]}).status_code == 404
    assert c.post(path + "/cancel", headers={"X-CSRF-Token": sc["csrf"]}).status_code == 404
    assert a.get(path).status_code == 200


def test_unverified_csrf_card_fields_invalid_selection_and_expiry_are_rejected(app):
    store = app.extensions["account_store"]
    pending = register(store, verified=False)
    pending_client = app.test_client(); pending_csrf = login(pending_client, pending["email"])["csrf"]
    assert create(pending_client, pending_csrf).status_code == 403

    user = register(store, email="verified@example.test", company="Verified",
                    identifier="CHE111222333")
    client = app.test_client(); csrf = login(client, user["email"])["csrf"]
    assert create(client, csrf, extra={"card_number": "4242424242424242"}).status_code == 400
    assert client.post("/api/sandbox/billing/checkout-simulations", json={
        "plan_code": "tier_team_v1", "billing_cycle": "monthly",
    }, headers={"Idempotency-Key": "missing-csrf-key"}).status_code == 403
    assert create(client, csrf, plan="trial_company_v1", key="trial-cannot-buy").status_code == 400
    assert create(client, csrf, cycle="weekly", key="weekly-not-allowed").status_code == 400

    expired = store.create_checkout_simulation(
        user["company_id"], user["id"], "tier_team_v1", "monthly",
        idempotency_key="expired-checkout-key", now=1_700_000_000, ttl=60,
    )
    with pytest.raises(BillingSandboxConflict, match="checkout_expired"):
        store.transition_checkout_simulation(
            expired["checkout_id"], user["company_id"], user["id"],
            "confirmed_simulation", now=1_700_000_061,
        )


def test_store_reopen_preserves_immutable_snapshot_and_no_payment_columns(app):
    store = app.extensions["account_store"]; user = register(store)
    created = store.create_checkout_simulation(
        user["company_id"], user["id"], "tier_partner_v1", "annual",
        idempotency_key="persistent-checkout-key",
    )
    reopened = AccountStore(app.config["ACCOUNT_DB_PATH"])
    saved = reopened.get_checkout_simulation(created["checkout_id"], user["company_id"], user["id"])
    assert saved["selection"] == created["selection"]
    with reopened.connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(billing_checkout_intents)")}
    assert not columns.intersection({"card_number", "pan", "cvc", "payment_token", "provider"})
