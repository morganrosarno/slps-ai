import hashlib
import io
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import pytest

from accounts import AccountConflict, AccountStore, ConsultationConflict
import server

PASSWORD = "a-long-local-test-passphrase"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_: {"summary": "Synthetic account test", "findings": []})
    return server.create_app({
        "TESTING": True, "AUTH_MODE": "accounts", "ACCOUNT_REGISTRATION_OPEN": True,
        "SECRET_KEY": "a-session-secret-longer-than-32-characters", "PILOT_PASSWORD": None,
        "SESSION_COOKIE_SECURE": False, "ACCOUNT_DB_PATH": str(tmp_path / "accounts.db"),
        "RATE_DB_PATH": str(tmp_path / "limits.db"), "CASE_DB_PATH": str(tmp_path / "cases.db"),
        "PILOT_PLAN": "internal", "TRIAL_ANALYSES_TOTAL": 100,
    })


def csrf(client):
    return client.get("/api/session").json["csrf"]


def post(client, url, data, token=None, **kwargs):
    return client.post(url, json=data, headers={"X-CSRF-Token": token or csrf(client)}, **kwargs)


def register_data(**kwargs):
    return {"email": "owner@example.test", "password": PASSWORD,
            "company_name": "Synthetic Company", "company_identifier": "CHE-123.456.789",
            "role": "Representative", "locale": "it", **kwargs}


def provision(app, email="owner@example.test", company="Synthetic Company", identifier="CHE123456789", verified=True):
    store = app.extensions["account_store"]
    user = store.register(**register_data(email=email, company_name=company, company_identifier=identifier))
    if verified:
        assert store.consume_token(store.issue_token(user["id"], "email"), "email")
        store.verify_company(user["company_id"], user["id"])
    return store.get_user(user["id"])


def login(client, email="owner@example.test", password=PASSWORD):
    return post(client, "/api/login", {"email": email, "password": password})


def enable_consultation(app, user, months=12):
    app.extensions["account_store"].assign_consultation_policy(
        user["company_id"], included=1, period_months=months
    )


def analyze(client, token):
    f = io.BytesIO(); Image.new("RGB", (30, 20), "red").save(f, "PNG"); f.seek(0)
    return client.post("/analizza", data={"file": (f, "photo.png")}, headers={"X-CSRF-Token": token})


def test_account_auth_requires_only_session_secret_and_registration_closed_by_default(app):
    client = app.test_client()
    info = client.get("/api/session").json
    assert info["auth_configured"] and info["auth_mode"] == "accounts"
    assert info["registration_open"]
    app.config["ACCOUNT_REGISTRATION_OPEN"] = False
    assert post(client, "/api/accounts/register", register_data()).status_code == 503


def test_registration_pending_no_tokens_no_provider(app, monkeypatch):
    client = app.test_client()
    response = post(client, "/api/accounts/register", register_data())
    assert response.status_code == 202
    assert response.json == {"registered": True, "verification_required": True, "delivery_configured": False}
    assert not client.get("/api/session").json["authenticated"]
    state = login(client).json
    assert state["authenticated"] and state["verification_required"] and not state["configured"]
    assert not state["account"]["email_verified"] and not state["account"]["company"]["verified"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_: pytest.fail("pending account called provider"))
    assert analyze(client, state["csrf"]).status_code == 403
    assert client.get("/api/cases", headers={"X-CSRF-Token": state["csrf"]}).status_code == 403
    assert client.post("/api/logout", headers={"X-CSRF-Token": state["csrf"]}).status_code == 200


def test_registration_requires_csrf_and_same_origin(app):
    client = app.test_client()
    assert client.post("/api/accounts/register", json=register_data()).status_code == 403
    assert client.post("/api/accounts/register", json=register_data(), headers={"X-CSRF-Token": csrf(client), "Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/accounts/register", data="not-json", headers={"X-CSRF-Token": csrf(client)}).status_code == 400


@pytest.mark.parametrize("field,value", [("email", "invalid"), ("password", "short"), ("company_name", ""), ("company_identifier", "a?"), ("role", ""), ("locale", "xx")])
def test_registration_validates_profile(app, field, value):
    assert post(app.test_client(), "/api/accounts/register", register_data(**{field: value})).status_code == 400


def test_duplicate_company_or_email_cannot_create_or_join(app):
    store = app.extensions["account_store"]
    first = provision(app)
    with pytest.raises(AccountConflict):
        store.register(**register_data(email="second@example.test", company_identifier="che 123 456 789"))
    with pytest.raises(AccountConflict):
        store.register(**register_data(company_name="Different", company_identifier="CHE987654321"))
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM account_companies").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM account_users").fetchone()[0] == 1
    assert store.get_user(first["id"])["company_verified"]


def test_email_confirmation_not_company_verification_and_session_refreshes(app):
    store = app.extensions["account_store"]; user = provision(app, verified=False)
    client = app.test_client(); state = login(client).json
    raw = store.issue_token(user["id"], "email")
    assert post(client, "/api/accounts/verify-email", {"token": raw}, state["csrf"]).json["email_verified"]
    state = client.get("/api/session").json
    assert state["account"]["email_verified"] and state["verification_required"]
    assert not state["account"]["company"]["verified"] and not state["account"]["membership_verified"]
    store.verify_company(user["company_id"], user["id"])
    assert client.get("/api/session").json["account"]["eligible_for_analysis"]


def test_company_verified_but_member_unapproved_still_blocked(app):
    store = app.extensions["account_store"]; user = provision(app)
    member = store.add_member(user["company_id"], email="member@example.test", password=PASSWORD, role="Employee")
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    client = app.test_client(); state = login(client, member["email"]).json
    assert state["account"]["company"]["verified"] and state["verification_required"]
    assert analyze(client, state["csrf"]).status_code == 403


def test_company_trial_shared_across_approved_accounts_and_cannot_be_internal(app):
    store = app.extensions["account_store"]; owner = provision(app)
    member = store.add_member(owner["company_id"], email="member@example.test", password=PASSWORD, role="Employee", approved=True)
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    a, b = app.test_client(), app.test_client()
    sa, sb = login(a).json, login(b, member["email"]).json
    assert sa["entitlement"]["plan"] == "trial" and sa["entitlement"]["analyses_total"] == 1
    assert not sa["entitlement"]["export_allowed"]
    result = analyze(a, sa["csrf"])
    assert result.status_code == 200
    assert analyze(b, sb["csrf"]).status_code == 402
    assert b.get("/api/session").json["entitlement"]["analyses_remaining"] == 0
    # Owner-private archive remains an explicit temporary limitation.
    assert b.get("/api/cases", headers={"X-CSRF-Token": sb["csrf"]}).json["cases"] == []


def test_cross_company_case_access_denied_and_cookie_identity_rehydrated(app):
    auser = provision(app)
    buser = provision(app, email="b@example.test", company="Other Synthetic", identifier="CHE987654321")
    a, b = app.test_client(), app.test_client()
    sa, sb = login(a).json, login(b, buser["email"]).json
    case_id = analyze(a, sa["csrf"]).json["archive"]["case_id"]
    with b.session_transaction() as cookie:
        cookie["tenant_id"], cookie["owner_id"] = auser["company_id"], auser["id"]
    assert b.get("/api/cases/"+case_id, headers={"X-CSRF-Token": sb["csrf"]}).status_code == 404
    with b.session_transaction() as cookie:
        assert cookie["tenant_id"] == buser["company_id"] and cookie["owner_id"] == buser["id"]


def test_password_reset_single_use_invalidates_all_old_sessions(app):
    store = app.extensions["account_store"]; user = provision(app)
    a, b = app.test_client(), app.test_client(); sa, sb = login(a).json, login(b).json
    raw = store.issue_token(user["id"], "reset")
    new_password = "a-new-local-test-password"
    anon = app.test_client()
    response = post(anon, "/api/accounts/password-reset/confirm", {"token": raw, "password": new_password})
    assert response.status_code == 200
    assert not a.get("/api/session").json["authenticated"]
    assert b.get("/api/cases", headers={"X-CSRF-Token": sb["csrf"]}).status_code == 401
    assert post(anon, "/api/accounts/password-reset/confirm", {"token": raw, "password": new_password}).status_code == 400
    assert store.authenticate(user["email"], PASSWORD) is None
    assert store.authenticate(user["email"], new_password)


def test_tokens_hashed_bound_to_purpose_expiring_and_invalidated_on_reissue(app, monkeypatch):
    store = app.extensions["account_store"]; user = provision(app, verified=False)
    raw = store.issue_token(user["id"], "email")
    with store.connect() as db:
        token = db.execute("SELECT * FROM account_tokens").fetchone()
        assert token["digest"] == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in tuple(token)
    assert not store.consume_token(raw, "reset", PASSWORD)
    fresh = store.issue_token(user["id"], "email")
    assert not store.consume_token(raw, "email")
    with store.connect() as db:
        db.execute("UPDATE account_tokens SET expires=0")
    assert not store.consume_token(fresh, "email")
    latest = store.issue_token(user["id"], "email")
    assert store.consume_token(latest, "email") and not store.consume_token(latest, "email")
    assert PASSWORD.encode() not in Path(app.config["ACCOUNT_DB_PATH"]).read_bytes()


def test_reset_request_generic_and_no_delivery_claim(app):
    user = provision(app)
    a, b = app.test_client(), app.test_client()
    first = post(a, "/api/accounts/password-reset", {"email": user["email"]})
    missing = post(b, "/api/accounts/password-reset", {"email": "missing@example.test"})
    assert first.status_code == missing.status_code == 202
    assert first.json == missing.json and first.json["delivery_configured"] is False
    with app.extensions["account_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM account_tokens WHERE purpose='reset'").fetchone()[0] == 0


def test_login_throttles_before_password_hash(app, monkeypatch):
    client = app.test_client(); csrf(client)
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    monkeypatch.setattr(app.extensions["account_store"], "authenticate", lambda *_: pytest.fail("hash work after rate limit"))
    assert login(client).status_code == 429


def test_successful_other_account_cannot_reset_target_login_throttle(app, monkeypatch):
    provision(app)
    provision(app, email="other@example.test", company="Other", identifier="CHE222333444")
    client = app.test_client()
    for _ in range(5):
        assert login(client, email="OWNER@EXAMPLE.TEST", password="wrong").status_code == 401
        assert login(client, email="other@example.test").status_code == 200
    monkeypatch.setattr(app.extensions["account_store"], "authenticate", lambda *_: pytest.fail("hash after target throttle"))
    assert login(client).status_code == 429


def test_account_login_rejects_oversized_payload_before_hash(app, monkeypatch):
    client = app.test_client()
    monkeypatch.setattr(app.extensions["account_store"], "authenticate", lambda *_: pytest.fail("oversized request reached hash"))
    assert post(client, "/api/login", {"email": "owner@example.test", "password": PASSWORD, "padding": "x" * 9000}).status_code == 400


def test_legacy_pilot_cookie_rejected_in_account_mode(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(authenticated=True, tenant_id="pilot", owner_id="owner", csrf="old")
    assert client.get("/api/session").json["authenticated"] is False
    assert client.get("/api/cases", headers={"X-CSRF-Token": "old"}).status_code == 401


def test_company_verification_revocation_blocks_existing_session(app):
    store = app.extensions["account_store"]; user = provision(app)
    client = app.test_client(); state = login(client).json
    with store.connect() as db:
        db.execute("UPDATE account_companies SET verified=0 WHERE id=?", (user["company_id"],))
    assert client.get("/api/session").json["verification_required"]
    assert analyze(client, state["csrf"]).status_code == 403


def test_account_cookie_not_accepted_after_switch_to_pilot(app):
    provision(app); client = app.test_client(); state = login(client).json
    app.config.update(AUTH_MODE="pilot", PILOT_PASSWORD="a-separate-pilot-password")
    assert not client.get("/api/session").json["authenticated"]
    assert client.get("/api/cases", headers={"X-CSRF-Token": state["csrf"]}).status_code == 401


def test_consultation_ledger_atomic_idempotent_and_persistent(app):
    store = app.extensions["account_store"]; owner = provision(app)
    enable_consultation(app, owner, 12)
    member = store.add_member(owner["company_id"], email="member@example.test", password=PASSWORD,
                              role="Employee", approved=True)
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    member = store.get_user(member["id"])
    def reserve(user, key):
        try:
            return store.reserve_consultation(owner["company_id"], user["id"], "case-atomic", "phone",
                                              idempotency_key=key)
        except ConsultationConflict as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: reserve(*pair), [(owner, "atomic-owner-key"), (member, "atomic-member-key")]))
    successes = [value for value in results if isinstance(value, dict)]
    assert len(successes) == 1
    assert results.count("consultation_unavailable") == 1
    winner = owner if isinstance(results[0], dict) else member
    key = "atomic-owner-key" if winner is owner else "atomic-member-key"
    replay = reserve(winner, key)
    assert replay["request_id"] == successes[0]["request_id"] and replay["idempotent_replay"]
    assert replay["reserved"] == 1 and replay["used"] == 0 and replay["balance"] == 0
    # A new store instance sees the same company ledger: logout/process restart does not reset it.
    reopened = AccountStore(app.config["ACCOUNT_DB_PATH"])
    status = reopened.consultation_status(owner["company_id"], winner["id"])
    assert status["reserved"] == 1 and status["balance"] == 0


def test_consultation_policy_is_per_company_persistent_and_disabled_by_default(app):
    store = app.extensions["account_store"]
    annual = provision(app)
    monthly = provision(app, email="monthly@example.test", company="Monthly Co", identifier="CHE444333222")
    disabled = provision(app, email="disabled@example.test", company="Disabled Co", identifier="CHE111333555")
    store.assign_consultation_policy(annual["company_id"], included=1, period_months=12)
    store.assign_consultation_policy(monthly["company_id"], included=1, period_months=1)
    reopened = AccountStore(app.config["ACCOUNT_DB_PATH"])
    assert reopened.consultation_status(annual["company_id"], annual["id"])["period_months"] == 12
    assert reopened.consultation_status(monthly["company_id"], monthly["id"])["period_months"] == 1
    off = reopened.consultation_status(disabled["company_id"], disabled["id"])
    assert off["included"] == 0 and off["balance"] == 0
    with pytest.raises(ConsultationConflict):
        reopened.reserve_consultation(disabled["company_id"], disabled["id"], "case-off", "phone",
                                      idempotency_key="disabled-company-key")


def test_consultation_used_cancelled_and_calendar_reset_semantics(app):
    store = app.extensions["account_store"]; user = provision(app)
    store.assign_consultation_policy(user["company_id"], included=1, period_months=1, now=1_700_000_000)
    first = store.reserve_consultation(user["company_id"], user["id"], "case-one", "phone",
                                      idempotency_key="case-one-reserve", now=1_700_000_000)
    assert store.mark_consultation_used(first["request_id"], user["company_id"], user["id"], now=1_700_000_010)
    assert store.mark_consultation_used(first["request_id"], user["company_id"], user["id"], now=1_700_000_011)
    used = store.consultation_status(user["company_id"], user["id"], now=1_700_000_020)
    assert (used["reserved"], used["used"], used["balance"]) == (0, 1, 0)
    second = store.reserve_consultation(user["company_id"], user["id"], "case-two", "whatsapp",
                                       idempotency_key="case-two-reserve", now=1_703_000_000)
    assert store.cancel_consultation(second["request_id"], user["company_id"], user["id"], now=1_703_000_010)
    assert store.cancel_consultation(second["request_id"], user["company_id"], user["id"], now=1_703_000_011)
    current = store.consultation_status(user["company_id"], user["id"], now=1_703_000_020)
    assert (current["reserved"], current["used"], current["cancelled"], current["balance"]) == (0, 0, 1, 0)
    assert {item["status"] for item in current["requests"]} == {"used", "cancelled"}
    reset = store.consultation_status(user["company_id"], user["id"], now=1_706_000_000)
    assert (reset["reserved"], reset["used"], reset["cancelled"], reset["balance"]) == (0, 0, 0, 1)
    assert len(reset["requests"]) == 2  # history survives the reset


def test_consultation_api_authorization_no_contact_leak_or_side_effect(app, monkeypatch):
    owner = provision(app); client = app.test_client(); state = login(client).json
    enable_consultation(app, owner, 12)
    case_id = analyze(client, state["csrf"]).json["archive"]["case_id"]
    pending = provision(app, email="pending@example.test", company="Pending Co", identifier="CHE555666777", verified=False)
    pending_client = app.test_client(); pending_state = login(pending_client, pending["email"]).json
    assert pending_client.get("/api/consultations").status_code == 403

    calls = []
    monkeypatch.setattr(server, "analizza_immagine", lambda *_: calls.append("provider"))
    view = client.get("/api/consultations")
    assert view.status_code == 200 and view.json["hypothesis"] is True
    assert view.json["consultation"]["balance"] == 1
    response = client.post("/api/consultations", json={"case_id": case_id, "channel": "whatsapp"},
                           headers={"X-CSRF-Token": state["csrf"], "Idempotency-Key": "browser-request-001"})
    assert response.status_code == 201
    assert response.json["recorded"] and not response.json["contacted"] and not response.json["charged"]
    assert response.json["message"] == "Richiesta registrata. Nessun messaggio o chiamata è stato inviato."
    wire = response.get_data(as_text=True).lower()
    assert "tel:" not in wire and "wa.me" not in wire and "phone_number" not in wire
    assert calls == []
    replay = client.post("/api/consultations", json={"case_id": case_id, "channel": "whatsapp"},
                         headers={"X-CSRF-Token": state["csrf"], "Idempotency-Key": "browser-request-001"})
    assert replay.status_code == 200 and replay.json["consultation"]["reserved"] == 1
    assert client.post("/api/consultations", json={"case_id": case_id, "channel": "phone"},
                       headers={"Idempotency-Key": "missing-csrf-key"}).status_code == 403
    assert client.post("/api/consultations/" + response.json["consultation"]["request_id"] + "/used",
                       headers={"X-CSRF-Token": state["csrf"]}).status_code == 404


def test_consultation_case_and_request_isolation(app):
    store = app.extensions["account_store"]; owner = provision(app)
    enable_consultation(app, owner, 12)
    member = store.add_member(owner["company_id"], email="member@example.test", password=PASSWORD,
                              role="Employee", approved=True)
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    a, b = app.test_client(), app.test_client(); sa, sb = login(a).json, login(b, member["email"]).json
    case_id = analyze(a, sa["csrf"]).json["archive"]["case_id"]
    denied = b.post("/api/consultations", json={"case_id": case_id, "channel": "phone"},
                    headers={"X-CSRF-Token": sb["csrf"], "Idempotency-Key": "member-cross-case"})
    assert denied.status_code == 404
    assert b.get("/api/consultations").json["consultation"]["balance"] == 1
    outsider = provision(app, email="outside@example.test", company="Outside Co", identifier="CHE888999000")
    outside_client = app.test_client(); outside_state = login(outside_client, outsider["email"]).json
    outside_case = analyze(outside_client, outside_state["csrf"]).json["archive"]["case_id"]
    cross_company = a.post("/api/consultations", json={"case_id": outside_case, "channel": "phone"},
                           headers={"X-CSRF-Token": sa["csrf"], "Idempotency-Key": "cross-company-case"})
    assert cross_company.status_code == 404
    assert a.get("/api/consultations").json["consultation"]["balance"] == 1
    own = a.post("/api/consultations", json={"case_id": case_id, "channel": "phone"},
                 headers={"X-CSRF-Token": sa["csrf"], "Idempotency-Key": "owner-own-case-001"})
    request_id = own.json["consultation"]["request_id"]
    assert b.post(f"/api/consultations/{request_id}/cancel", json={},
                  headers={"X-CSRF-Token": sb["csrf"]}).status_code == 404
    assert a.get("/api/consultations").json["consultation"]["reserved"] == 1
