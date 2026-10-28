"""End-to-end synthetic registration: durable no-send first, pending review next."""
from contextlib import ExitStack
import socket
from unittest import mock

import pytest
import server
from accounts import AccountStore
from account_delivery_runtime import synthetic_registration_capability
from account_registration_nosend import install_synthetic_registration_workflow


DATA = {"email": "synthetic@example.test", "password": "synthetic-nosend-password-only",
        "company_name": "Synthetic No Send", "role": "Representative", "locale": "it"}
OPERATOR = b"synthetic-nosend-operator-capability-42"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_a, **_k: pytest.fail("No AI"))
    app = server.create_app({"TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "accounts",
        "ACCOUNT_REGISTRATION_OPEN": True, "ACCOUNT_REGISTRATION_TEST_CAPABILITY": synthetic_registration_capability(),
        "SECRET_KEY": "synthetic-nosend-session-secret-over32characters", "SESSION_COOKIE_SECURE": False,
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"), "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"), "HISTORY_ROOT": str(tmp_path / "media")})
    install_synthetic_registration_workflow(app)
    return app


def register(app, extra=None):
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf"]
    return client.post("/api/accounts/register", json={**DATA, **(extra or {})}, headers={"X-CSRF-Token": csrf})


def counts(app):
    with app.extensions["account_store"].connect() as db:
        return tuple(db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                     for name in ("account_companies", "account_users", "account_tokens", "account_verification_reviews"))


def test_durable_rejection_precedes_atomic_pending_review_with_zero_network_or_token(app):
    workflow = app.extensions["synthetic_registration_workflow"]
    original = workflow.accounts.register

    def after_nosend(**kwargs):
        assert workflow.adapter.calls == 1
        db = workflow.ledger._connect()
        try:
            assert db.execute("SELECT outcome_status,outcome_code FROM delivery_reservations").fetchall() == [("failed", "transport_rejected")]
        finally:
            db.close()
        return original(**kwargs)

    with ExitStack() as stack:
        blocked = []
        for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
            blocked.append(stack.enter_context(mock.patch.object(socket, name, side_effect=AssertionError("No socket or DNS"))))
        stack.enter_context(mock.patch.object(workflow.accounts, "register", side_effect=after_nosend))
        response = register(app)
    assert response.status_code == 202 and response.json["delivery_configured"] is False
    assert counts(app) == (1, 1, 0, 1)
    for call in blocked:
        call.assert_not_called()
    operator = AccountStore(app.config["ACCOUNT_DB_PATH"], verification_operator_secret=OPERATOR)
    reviews = operator.list_verification_reviews(authorization=OPERATOR)
    assert len(reviews) == 1 and reviews[0]["status"] == "pending"
    audit = operator.verification_review_audit(reviews[0]["id"], authorization=OPERATOR)
    assert len(audit) == 1 and audit[0]["event"] == "submitted"
    user = operator.authenticate(DATA["email"], DATA["password"])
    assert not user["company_verified"] and not user["membership_verified"] and not user["email_verified"]
    assert "token" not in response.text and "transport_accepted" not in response.text


@pytest.mark.parametrize("result", [{"status": "accepted", "code": "transport_accepted"},
                                    {"status": "uncertain", "code": "dispatch_started"}, {}, None])
def test_unexpected_coordinator_outcome_never_creates_an_account(app, result):
    workflow = app.extensions["synthetic_registration_workflow"]
    with mock.patch.object(workflow.coordinator, "dispatch", return_value=result):
        response = register(app)
    assert response.status_code == 503 and response.json["registered"] is False
    assert counts(app) == (0, 0, 0, 0)


def test_coordinator_exception_is_redacted_and_precedes_account_mutation(app, caplog):
    workflow = app.extensions["synthetic_registration_workflow"]
    with mock.patch.object(workflow.coordinator, "dispatch", side_effect=RuntimeError("sensitive-private-secret")):
        response = register(app)
    assert response.status_code == 503 and counts(app) == (0, 0, 0, 0)
    assert "sensitive-private-secret" not in response.text + caplog.text


def test_account_transaction_failure_rolls_back_pending_state_and_replay_never_reinvokes_adapter(app):
    accounts = app.extensions["account_store"]
    with accounts.connect() as db:
        db.execute("CREATE TRIGGER synthetic_abort BEFORE INSERT ON account_users BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    assert register(app).status_code == 409
    assert counts(app) == (0, 0, 0, 0)
    with accounts.connect() as db:
        db.execute("DROP TRIGGER synthetic_abort")
    assert register(app).status_code == 503
    assert counts(app) == (0, 0, 0, 0)
    assert app.extensions["synthetic_registration_workflow"].adapter.calls == 1


def test_bare_capability_or_http_fields_cannot_promise_registration_without_workflow(app):
    app.extensions.pop("synthetic_registration_workflow")
    info = app.test_client().get("/api/session").json
    assert info["registration_open"] is False
    assert register(app, {"synthetic_registration_workflow": True}).status_code == 503
    assert counts(app) == (0, 0, 0, 0)
