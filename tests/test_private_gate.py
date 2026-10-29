"""Private-environment boundary and conservative provider dispatch accounting."""
from concurrent.futures import ThreadPoolExecutor
import io
import re

from PIL import Image
import pytest

import server


GATE_PASSWORD = "synthetic-private-gate-password"
PILOT_PASSWORD = "synthetic-pilot-password"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    return server.create_app({
        "TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "pilot",
        "PRIVATE_GATE_ENABLED": True, "PRIVATE_GATE_PASSWORD": GATE_PASSWORD,
        "PROVIDER_REQUESTS_TOTAL": 3,
        "SECRET_KEY": "synthetic-gate-session-secret-at-least-32-characters",
        "PILOT_PASSWORD": PILOT_PASSWORD, "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
        "PILOT_PLAN": "trial", "TRIAL_ANALYSES_TOTAL": 1,
    })


def gate_login(client, target="/app/"):
    response = client.get("/private-access", query_string={"next": target})
    token = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    assert GATE_PASSWORD not in response.text
    assert "nonce-" in response.headers["Content-Security-Policy"]
    return client.post("/private-access", query_string={"next": target},
                       data={"csrf": token, "password": GATE_PASSWORD})


def pilot_login(client):
    csrf = client.get("/api/session").json["csrf"]
    response = client.post("/api/login", json={"password": PILOT_PASSWORD},
                           headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    return response.json["csrf"]


def analyze(client, csrf, **fields):
    image = io.BytesIO(); Image.new("RGB", (24, 16), "blue").save(image, "PNG"); image.seek(0)
    return client.post("/analizza", data={"file": (image, "fixture.png", "image/png"), **fields},
                       headers={"X-CSRF-Token": csrf})


def test_gate_blocks_every_surface_but_health_until_authenticated(app):
    client = app.test_client()
    assert client.get("/healthz").json == {"status": "ok"}
    for path in ("/", "/app/", "/register", "/account", "/account/checkout", "/static/app.js", "/static/style.css"):
        response = client.get(path)
        assert response.status_code == 302 and response.location.startswith("/private-access?")
    for path in ("/api/session", "/api/cases", "/api/sandbox/billing/plans"):
        response = client.get(path)
        assert response.status_code == 401 and response.json["error"]["code"] == "private_access_required"
    assert client.post("/analizza").status_code == 401
    response = gate_login(client)
    assert response.status_code == 303 and response.location == "/app/"
    csrf = pilot_login(client)
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/session").json["authenticated"]
    assert client.post("/api/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/").status_code == 200  # app logout preserves environment access
    assert client.get("/api/session").json["authenticated"] is False
    app.config["PRIVATE_GATE_PASSWORD"] = "a-new-synthetic-private-password"
    assert client.get("/api/session").status_code == 401  # rotation revokes prior gate sessions


@pytest.mark.parametrize("target", ["https://outside.invalid/", "//outside.invalid/", "/\\outside.invalid/", "/%2foutside.invalid/", "/app/?secret=untrusted", "/private-access"])
def test_gate_never_uses_untrusted_return_urls(app, target):
    response = gate_login(app.test_client(), target)
    assert response.status_code == 303 and response.location == "/"


def test_gate_rejects_csrf_cross_origin_and_throttles_password_attempts(app):
    client = app.test_client()
    assert client.post("/private-access", data={"password": GATE_PASSWORD}).status_code == 403
    page = client.get("/private-access")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert client.post("/private-access", data={"csrf": "非ASCII", "password": GATE_PASSWORD}).status_code == 403
    assert client.post("/private-access", data={"csrf": csrf, "password": GATE_PASSWORD},
                       headers={"Origin": "https://outside.invalid"}).status_code == 403
    for _ in range(5):
        assert client.post("/private-access", data={"csrf": csrf, "password": "wrong"}).status_code == 401
    assert client.post("/private-access", data={"csrf": csrf, "password": GATE_PASSWORD}).status_code == 429


@pytest.mark.parametrize("setting,value", [("PRIVATE_GATE_PASSWORD", "short"), ("PRIVATE_GATE_PASSWORD", PILOT_PASSWORD), ("SECRET_KEY", "short"), ("PROVIDER_REQUESTS_TOTAL", None), ("PROVIDER_REQUESTS_TOTAL", "invalid")])
def test_gate_invalid_configuration_never_exposes_app(app, setting, value):
    app.config[setting] = value
    assert app.test_client().get("/").status_code == 503
    assert app.test_client().get("/healthz").status_code == 200


def test_provider_cap_counts_failures_and_clarifications_and_survives_recreation(app, monkeypatch):
    client = app.test_client(); gate_login(client); csrf = pilot_login(client)
    calls = []
    def provider(*_):
        calls.append(1)
        if len(calls) == 1:
            raise server.AnalysisError("provider_timeout", "Synthetic timeout", 504)
        return {"summary": "Synthetic report", "findings": []}
    monkeypatch.setattr(server, "analizza_immagine", provider)
    assert analyze(client, csrf).status_code == 504
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1
    initial = analyze(client, csrf)
    assert initial.status_code == 200
    case_id = initial.json["archive"]["case_id"]
    assert analyze(client, csrf, request_kind="clarification", case_id=case_id).status_code == 200
    assert app.extensions["limit_store"].provider_request_count() == 3
    # Internal plan bypasses the company trial only; it must not bypass total dispatch cap.
    reopened = server.create_app({**dict(app.config), "PILOT_PLAN": "internal"})
    returning = reopened.test_client(); gate_login(returning); token = pilot_login(returning)
    denied = analyze(returning, token)
    assert denied.status_code == 503 and denied.json["error"]["code"] == "provider_request_cap_reached"
    assert len(calls) == 3
    assert reopened.extensions["limit_store"].provider_request_count() == 3
    with reopened.extensions["limit_store"].connect() as db:
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_gate_survives_account_login_logout_and_validates_padded_settings(app):
    accounts_app = server.create_app({**dict(app.config), "AUTH_MODE": "accounts",
                                      "PRIVATE_GATE_ENABLED": " true ", "PROVIDER_REQUESTS_TOTAL": "003"})
    store = accounts_app.extensions["account_store"]
    user = store.register(email="gate-owner@example.test", password=PILOT_PASSWORD,
                          company_name="Synthetic Gate Company", company_identifier="",
                          role="Representative", locale="it")
    store.consume_token(store.issue_token(user["id"], "email"), "email")
    store.verify_company(user["company_id"], user["id"])
    client = accounts_app.test_client()
    assert gate_login(client).status_code == 303
    csrf = client.get("/api/session").json["csrf"]
    login = client.post("/api/login", json={"email": user["email"], "password": PILOT_PASSWORD},
                        headers={"X-CSRF-Token": csrf})
    assert login.status_code == 200 and login.json["authenticated"]
    assert client.get("/app/").status_code == 200
    assert client.post("/api/logout", headers={"X-CSRF-Token": login.json["csrf"]}).status_code == 200
    assert client.get("/api/session").status_code == 200
    assert client.get("/api/session").json["authenticated"] is False


def test_total_dispatch_reservation_is_atomic_and_has_no_time_reset(tmp_path):
    path = tmp_path / "limits.sqlite3"
    store = server.LimitStore(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: server.LimitStore(path).reserve_provider_request(3), range(8)))
    assert sum(outcomes) == 3
    assert store.provider_request_count() == 3
    # Pruning the hourly/login events never changes the independent lifetime counter.
    store.login("synthetic", False)
    assert server.LimitStore(path).reserve_provider_request(3) is False
    assert server.LimitStore(path).provider_request_count() == 3
