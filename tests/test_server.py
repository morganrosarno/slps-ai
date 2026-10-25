import io
from pathlib import Path
import sqlite3

from PIL import Image
import pytest

import server


def photo(fmt="PNG", size=(48, 32), exif=None):
    output = io.BytesIO()
    kwargs = {"exif": exif} if exif else {}
    Image.new("RGB", size, "red").save(output, format=fmt, **kwargs)
    return output.getvalue()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    return server.create_app({
        "TESTING": True,
        "SECRET_KEY": "test-session-secret-32-characters-long",
        "PILOT_PASSWORD": "test-password-16-chars",
        "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "PILOT_TENANT_ID": "tenant-a",
        "PILOT_OWNER_ID": "owner-a",
        "ANALYSES_PER_HOUR": 2,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, password="test-password-16-chars"):
    token = client.get("/api/session").json["csrf"]
    return client.post("/api/login", json={"password": password}, headers={"X-CSRF-Token": token})


def post_image(client, token, raw=None, filename="photo.png", context=""):
    return client.post("/analizza", data={
        "file": (io.BytesIO(photo() if raw is None else raw), filename),
        "context": context,
    }, headers={"X-CSRF-Token": token})


def test_unconfigured_auth_fails_closed(app, client):
    app.config["SECRET_KEY"] = None
    app.config["PILOT_PASSWORD"] = None
    state = client.get("/api/session").json
    assert state["configured"] is False
    assert state["csrf"] is None
    assert client.post("/api/login", json={"password": "x"}).status_code == 503
    assert post_image(client, "x").status_code == 503


@pytest.mark.parametrize("field,value", [("SECRET_KEY", "short"), ("PILOT_PASSWORD", "short"), ("PILOT_PASSWORD", " " * 32)])
def test_weak_auth_configuration_fails_closed(app, client, field, value):
    app.config[field] = value
    assert client.get("/api/session").json["auth_configured"] is False
    assert login(client).status_code == 503


def test_missing_provider_does_not_disable_login(client, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: False)
    state = client.get("/api/session").json
    assert not state["configured"]
    assert state["auth_configured"]
    state = login(client).json
    assert state["auth_configured"] and not state["configured"]
    token = state["csrf"]
    response = post_image(client, token)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "analysis_configuration_missing"


def test_anonymous_analysis_never_calls_provider(client, monkeypatch):
    def forbidden(*_args):
        pytest.fail("Provider called without authentication")
    monkeypatch.setattr(server, "analizza_immagine", forbidden)
    assert post_image(client, "x").status_code == 401


def test_login_requires_csrf_and_rejects_cross_origin(client):
    assert client.post("/api/login", json={"password": "test-password-16-chars"}).status_code == 403
    token = client.get("/api/session").json["csrf"]
    response = client.post("/api/login", json={"password": "test-password-16-chars"}, headers={"X-CSRF-Token": token, "Origin": "https://attacker.invalid"})
    assert response.status_code == 403


def test_login_rotates_csrf_and_logout_invalidates_session(client):
    before = client.get("/api/session").json["csrf"]
    response = login(client)
    token = response.json["csrf"]
    assert token != before
    assert client.get("/api/session").json["authenticated"]
    assert client.post("/api/logout").status_code == 403
    assert client.post("/api/logout", headers={"X-CSRF-Token": token}).status_code == 200
    assert not client.get("/api/session").json["authenticated"]
    assert post_image(client, token).status_code == 401


def test_five_failed_logins_block_further_attempts(client):
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    assert login(client).status_code == 429


def test_login_limit_survives_app_restart(app):
    first = app.test_client()
    for _ in range(5):
        login(first, "wrong")
    restarted = server.create_app(dict(app.config)).test_client()
    assert login(restarted).status_code == 429


def test_analysis_requires_csrf(client, monkeypatch):
    login(client)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    assert post_image(client, "invalid").status_code == 403


def test_file_bytes_reach_provider_and_filename_is_never_written(client, tmp_path, monkeypatch):
    token = login(client).json["csrf"]
    target = tmp_path / "unexpected.py"
    seen = {}
    def analyze(raw, mime, context):
        seen.update(raw=raw, mime=mime, context=context)
        return {"summary": "test"}
    monkeypatch.setattr(server, "analizza_immagine", analyze)
    response = post_image(client, token, filename=str(target), context="Contesto fornito")
    assert response.status_code == 200
    assert response.json["analysis"]["summary"] == "test"
    assert response.json["image"] == {"width": 48, "height": 32}
    assert response.json["archive"]["saved"] is True
    assert seen["mime"] == "image/jpeg"
    assert seen["context"] == "Contesto fornito"
    assert Image.open(io.BytesIO(seen["raw"])).size == (48, 32)
    assert not target.exists()


def test_analysis_is_archived_without_photograph(client, app, monkeypatch):
    token = login(client).json["csrf"]
    monkeypatch.setattr(
        server,
        "analizza_immagine",
        lambda *_args: {"summary": "Caso archiviato", "findings": []},
    )
    response = post_image(client, token, context="Solo informazioni necessarie")
    case_id = response.json["archive"]["case_id"]

    listing = client.get("/api/cases", headers={"X-CSRF-Token": token})
    assert listing.status_code == 200
    assert len(listing.json["cases"]) == 1
    assert listing.json["cases"][0]["id"] == case_id
    assert listing.json["cases"][0]["context"] == "Solo informazioni necessarie"
    assert listing.json["cases"][0]["summary"] == "Caso archiviato"
    saved = client.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token})
    assert saved.status_code == 200
    assert saved.json["case"]["analysis"]["summary"] == "Caso archiviato"
    assert "image" not in saved.json["case"]
    assert photo() not in Path(app.config["CASE_DB_PATH"]).read_bytes()


def test_case_routes_deny_cross_tenant_and_cross_owner(app, monkeypatch):
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: {"summary": "Privato", "findings": []})
    tenant_a = app.test_client()
    token_a = login(tenant_a).json["csrf"]
    case_id = post_image(tenant_a, token_a).json["archive"]["case_id"]

    tenant_b_app = server.create_app({
        **dict(app.config),
        "PILOT_TENANT_ID": "tenant-b",
        "PILOT_OWNER_ID": "owner-b",
    })
    tenant_b = tenant_b_app.test_client()
    token_b = login(tenant_b).json["csrf"]
    assert tenant_b.get("/api/cases", headers={"X-CSRF-Token": token_b}).json["cases"] == []
    foreign = tenant_b.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token_b})
    missing = tenant_b.get("/api/cases/missing-case", headers={"X-CSRF-Token": token_b})
    assert (foreign.status_code, foreign.json) == (missing.status_code, missing.json)
    assert (foreign.status_code, foreign.json) == (
        404,
        {"error": {"code": "case_not_found", "message": "Caso non disponibile."}},
    )
    foreign_delete = tenant_b.delete("/api/cases/" + case_id, headers={"X-CSRF-Token": token_b})
    missing_delete = tenant_b.delete("/api/cases/missing-case", headers={"X-CSRF-Token": token_b})
    assert (foreign_delete.status_code, foreign_delete.json) == (
        missing_delete.status_code,
        missing_delete.json,
    )
    assert foreign_delete.status_code == 404

    owner_b_app = server.create_app({
        **dict(app.config),
        "PILOT_TENANT_ID": "tenant-a",
        "PILOT_OWNER_ID": "owner-b",
    })
    owner_b = owner_b_app.test_client()
    token_owner_b = login(owner_b).json["csrf"]
    assert owner_b.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token_owner_b}).status_code == 404

    assert tenant_a.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token_a}).status_code == 200


def test_owner_can_delete_only_own_case(client, monkeypatch):
    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: {"summary": "Elimina", "findings": []})
    case_id = post_image(client, token).json["archive"]["case_id"]
    assert client.delete("/api/cases/" + case_id, headers={"X-CSRF-Token": token}).json == {"deleted": True}
    assert client.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token}).status_code == 404


def test_case_routes_require_authentication_and_delete_requires_csrf(client, monkeypatch):
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/cases/missing-case").status_code == 401
    assert client.delete("/api/cases/missing-case").status_code == 401

    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: {"summary": "Protetto", "findings": []})
    case_id = post_image(client, token).json["archive"]["case_id"]
    assert client.delete("/api/cases/" + case_id).status_code == 403
    assert client.get("/api/cases/" + case_id, headers={"X-CSRF-Token": token}).status_code == 200


def test_archive_failure_preserves_paid_analysis_and_releases_lease(client, app, monkeypatch):
    token = login(client).json["csrf"]
    calls = []
    monkeypatch.setattr(
        server,
        "analizza_immagine",
        lambda *_args: calls.append(1) or {"summary": "Analisi riuscita", "findings": []},
    )
    monkeypatch.setattr(
        app.extensions["case_store"],
        "create",
        lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("private-db-detail")),
    )

    response = post_image(client, token)
    assert response.status_code == 200
    assert response.json["analysis"]["summary"] == "Analisi riuscita"
    assert response.json["archive"] == {
        "saved": False,
        "case_id": None,
        "message": "Risultato non archiviato per un problema temporaneo.",
    }
    assert "private-db-detail" not in response.text
    assert calls == [1]
    lease, reason = app.extensions["limit_store"].reserve_analysis(10, 180)
    assert lease and reason is None
    app.extensions["limit_store"].release_analysis(lease)


def test_case_limit_preserves_analysis_but_reports_unsaved(app, monkeypatch):
    app.config["MAX_CASES_PER_OWNER"] = 1
    app.config["ANALYSES_PER_HOUR"] = 10
    client = app.test_client()
    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: {"summary": "Limite", "findings": []})
    assert post_image(client, token).json["archive"]["saved"] is True
    second = post_image(client, token)
    assert second.status_code == 200
    assert second.json["analysis"]["summary"] == "Limite"
    assert second.json["archive"]["saved"] is False
    assert "Archivio pieno" in second.json["archive"]["message"]


@pytest.mark.parametrize("field,value", [
    ("PILOT_TENANT_ID", "../other"),
    ("PILOT_OWNER_ID", ""),
    ("PILOT_OWNER_ID", "x" * 65),
])
def test_invalid_archive_principal_fails_closed(app, field, value):
    app.config[field] = value
    client = app.test_client()
    assert client.get("/api/session").json["auth_configured"] is False


def test_large_multipart_upload_never_spools_to_disk(app):
    # Werkzeug ordinarily spools files larger than 500 KB to a temp file.
    with app.test_request_context("/analizza", method="POST", data={"file": (io.BytesIO(b"x" * 700_000), "photo.jpg")}):
        assert isinstance(server.request.files["file"].stream, io.BytesIO)


@pytest.mark.parametrize("payload", [b"not an image", b"<svg></svg>", photo("GIF"), photo()[:50]])
def test_invalid_image_content_rejected(client, monkeypatch, payload):
    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Invalid photo sent"))
    response = post_image(client, token, payload)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_image"


def test_oversized_upload_rejected(client):
    token = login(client).json["csrf"]
    response = post_image(client, token, b"x" * (server.MAX_FILE_BYTES + 200_000))
    assert response.status_code == 413
    assert response.is_json


def test_pixel_limit_and_animation_rejected(monkeypatch):
    monkeypatch.setattr(server, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match="megapixel"):
        server.normalize_image(photo())
    monkeypatch.setattr(server, "MAX_IMAGE_PIXELS", 25_000_000)
    animated = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(animated, format="PNG", save_all=True, append_images=[Image.new("RGB", (4, 4), "blue")])
    with pytest.raises(ValueError, match="animate"):
        server.normalize_image(animated.getvalue())


def test_exif_is_stripped_and_orientation_applied():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private comment"
    normalized, mime, width, height = server.normalize_image(photo("JPEG", exif=exif))
    image = Image.open(io.BytesIO(normalized))
    assert not image.getexif()
    assert (width, height) == (32, 48)
    assert mime == "image/jpeg"


def test_context_limit(client, monkeypatch):
    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    assert post_image(client, token, context="x" * 8001).status_code == 400


def test_analysis_limit_reserves_before_provider(client, app, monkeypatch):
    token = login(client).json["csrf"]
    calls = []
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: calls.append(1) or {"summary": "ok"})
    assert post_image(client, token).status_code == 200
    assert post_image(client, token).status_code == 200
    assert post_image(client, token).status_code == 429
    assert len(calls) == 2


def test_concurrent_analysis_rejected(client, app, monkeypatch):
    token = login(client).json["csrf"]
    lease, _ = app.extensions["limit_store"].reserve_analysis(10, 180)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Parallel call"))
    assert post_image(client, token).status_code == 409
    app.extensions["limit_store"].release_analysis(lease)


def test_unexpected_provider_error_is_sanitized_and_lease_released(client, app, monkeypatch):
    token = login(client).json["csrf"]
    def fail(*_args):
        raise RuntimeError("sensitive-provider-secret")
    monkeypatch.setattr(server, "analizza_immagine", fail)
    response = post_image(client, token)
    assert response.status_code == 500
    assert "sensitive-provider-secret" not in response.text
    lease, reason = app.extensions["limit_store"].reserve_analysis(10, 180)
    assert lease and reason is None


def test_provider_error_is_not_returned_as_success(client, monkeypatch):
    token = login(client).json["csrf"]
    def fail(*_args):
        raise server.AnalysisError("quota_exhausted", "Credito API esaurito.", 429)
    monkeypatch.setattr(server, "analizza_immagine", fail)
    response = post_image(client, token)
    assert response.status_code == 429
    assert response.json == {"error": {"code": "quota_exhausted", "message": "Credito API esaurito."}}


def test_security_headers_and_cookie_flags(app):
    app.config["SESSION_COOKIE_SECURE"] = True
    response = app.test_client().get("/api/session", base_url="https://localhost")
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]


def test_unknown_route_returns_json(client):
    response = client.post("/missing")
    assert response.status_code == 404
    assert "error" in response.json
