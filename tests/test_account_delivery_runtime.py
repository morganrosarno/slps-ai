"""Runtime registration cannot advertise or mutate around the delivery gate."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

import account_delivery_runtime as runtime
from delivery_reservations import SQLiteDeliveryReservationStore
from scripts import preflight
import server

PASSWORD = "synthetic-runtime-registration-password"
DATA = {"email": "fixture@example.test", "password": PASSWORD,
        "company_name": "Synthetic Interlock", "role": "Representative", "locale": "it"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_a, **_k: pytest.fail("No provider"))
    return server.create_app({
        "TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "accounts",
        "SECRET_KEY": "synthetic-runtime-session-secret-over-32-characters",
        "SESSION_COOKIE_SECURE": False, "ACCOUNT_REGISTRATION_OPEN": True,
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"),
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"), "HISTORY_ROOT": str(tmp_path / "media"),
    })


def post(client, payload=None):
    csrf = client.get("/api/session").json["csrf"]
    return client.post("/api/accounts/register", json=DATA if payload is None else payload,
                       headers={"X-CSRF-Token": csrf})


def counts(app):
    with app.extensions["account_store"].connect() as db:
        return tuple(db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                     for name in ("account_users", "account_companies", "account_tokens", "account_verification_reviews"))


def assert_blocked(app):
    client = app.test_client()
    before = counts(app)
    info = client.get("/api/session").json
    assert info["registration_open"] is False and info["registration_status"] == "delivery_unavailable"
    assert info["delivery_configured"] is False
    assert 'href="/register"' not in client.get("/").text
    result = post(client)
    assert result.status_code == 503 and result.json["error"]["code"] == "account_delivery_unavailable"
    assert result.json["registration_open"] is False and result.json["delivery_configured"] is False
    assert counts(app) == before
    return result


def test_open_flag_is_blocked_before_registration_rate_token_or_provider_effect(app):
    with mock.patch.object(app.extensions["account_store"], "register") as register, \
            mock.patch.object(app.extensions["account_store"], "issue_token") as token, \
            mock.patch.object(app.extensions["limit_store"], "login") as rate:
        assert_blocked(app)
    register.assert_not_called(); token.assert_not_called(); rate.assert_not_called()
    with app.extensions["limit_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE kind='login'").fetchone()[0] == 0


def test_locally_valid_preflight_and_nominal_adapter_still_require_provider_verification(app):
    with TemporaryDirectory(prefix="slps-interlock-test-", dir=Path(server.__file__).resolve().parent.parent) as directory:
        database, checkpoint = Path(directory) / "delivery.sqlite3", Path(directory) / "checkpoint.json"
        secret = "synthetic-runtime-delivery-reservation-secret-only-42"
        SQLiteDeliveryReservationStore(database, checkpoint_path=checkpoint, key_secret=secret.encode())
        adapter = mock.Mock()
        adapter.send.side_effect = AssertionError("Must not send")
        app.config.update({"DELIVERY_RESERVATION_SECRET": secret,
                           "DELIVERY_DB_PATH": str(database), "DELIVERY_CHECKPOINT_PATH": str(checkpoint),
                           "ACCOUNT_DELIVERY_ADAPTER": "synthetic-adapter",
                           "ACCOUNT_DELIVERY_ADAPTER_CAPABILITY": preflight.ConfiguredAccountDeliveryAdapter("synthetic-adapter", adapter)})
        settings = {env: app.config.get(key) for env, key in runtime._CONFIG_KEYS.items()}
        checks = preflight.account_delivery_checks(settings, Path(server.__file__).resolve().parent,
                                                   registration_open=True,
                                                   delivery_adapter=app.config["ACCOUNT_DELIVERY_ADAPTER_CAPABILITY"])
        assert {item.id for item in checks if item.status != "pass"} == {"account_delivery_provider_verification"}
        before = database.read_bytes(), checkpoint.read_bytes()
        assert_blocked(app)
        assert (database.read_bytes(), checkpoint.read_bytes()) == before
        adapter.send.assert_not_called()


@pytest.mark.parametrize("capability", [None, True, "synthetic_test_only", {}, object()])
def test_string_boolean_mapping_or_arbitrary_capability_never_enables_registration(app, capability):
    app.config["ACCOUNT_REGISTRATION_TEST_CAPABILITY"] = capability
    assert_blocked(app)


@pytest.mark.parametrize("testing,data_mode", [(False, "synthetic"), (1, "synthetic"), ("true", "synthetic"),
                                               (True, "real"), (True, "Synthetic")])
def test_fixture_capability_requires_exact_testing_and_synthetic_mode(app, testing, data_mode):
    app.config.update(TESTING=testing, DATA_MODE=data_mode,
                      ACCOUNT_REGISTRATION_TEST_CAPABILITY=runtime.synthetic_registration_capability())
    assert_blocked(app)


def test_explicit_fixture_creates_only_pending_account_and_removal_revokes_immediately(app):
    app.config["ACCOUNT_REGISTRATION_TEST_CAPABILITY"] = runtime.synthetic_registration_capability()
    client = app.test_client()
    info = client.get("/api/session").json
    assert info["registration_open"] and info["registration_status"] == "synthetic_test_only"
    assert info["delivery_configured"] is False
    assert 'href="/register"' in client.get("/").text
    assert post(client).status_code == 202 and counts(app)[:3] == (1, 1, 0)
    app.config["ACCOUNT_REGISTRATION_TEST_CAPABILITY"] = None
    result = post(client, {**DATA, "email": "other@example.test", "company_name": "Another Synthetic"})
    assert result.status_code == 503 and counts(app)[:3] == (1, 1, 0)


def test_existing_pending_account_can_login_while_registration_is_blocked(app):
    user = app.extensions["account_store"].register(**DATA)
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf"]
    result = client.post("/api/login", json={"email": user["email"], "password": PASSWORD},
                         headers={"X-CSRF-Token": csrf})
    assert result.status_code == 200 and result.json["authenticated"]
    assert result.json["registration_open"] is False and result.json["verification_required"]


def test_explicit_closure_retains_its_distinct_response(app):
    app.config["ACCOUNT_REGISTRATION_OPEN"] = False
    client = app.test_client()
    assert client.get("/api/session").json["registration_status"] == "closed"
    assert post(client).json["error"]["code"] == "registration_closed"


def test_preflight_error_is_redacted_and_keeps_all_surfaces_closed(app, monkeypatch, caplog):
    canary = "sensitive-provider-secret-private-path"
    monkeypatch.setattr(runtime, "account_delivery_checks", mock.Mock(side_effect=RuntimeError(canary)))
    result = assert_blocked(app)
    assert canary not in result.text and canary not in caplog.text


def test_incomplete_or_duplicate_preflight_cannot_be_treated_as_ready(app, monkeypatch):
    valid = [preflight.Check(key, "blocker", "pass", "not exposed") for key in sorted(runtime._REQUIRED_CHECKS)]
    for checks in ([], valid[:-1], valid[:-1] + [valid[0]]):
        monkeypatch.setattr(runtime, "account_delivery_checks", lambda *_a, **_k: checks)
        assert_blocked(app)


def test_env_or_json_cannot_inject_fixture_capability(app, monkeypatch):
    monkeypatch.setenv("SLPS_ACCOUNT_REGISTRATION_TEST_CAPABILITY", "true")
    result = post(app.test_client(), {**DATA, "ACCOUNT_REGISTRATION_TEST_CAPABILITY": True})
    assert result.status_code == 503 and counts(app)[:3] == (0, 0, 0)


def test_csrf_still_precedes_delivery_gate(app):
    response = app.test_client().post("/api/accounts/register", json=DATA,
                                      headers={"Origin": "https://other.example"})
    assert response.status_code == 403 and response.json["error"]["code"] == "invalid_csrf"
    assert counts(app)[:3] == (0, 0, 0)
