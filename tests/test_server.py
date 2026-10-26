import io
from pathlib import Path
import sqlite3
import subprocess

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
        "PILOT_PLAN": "internal",
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


def post_media(client, token, raw, filename, mime, **fields):
    return client.post("/analizza", data={
        "file": (io.BytesIO(raw), filename, mime),
        **fields,
    }, headers={"X-CSRF-Token": token})


def inspect_media(client, token, raw, filename="clip.mp4", mime="video/mp4"):
    return client.post("/api/media/inspect", data={
        "file": (io.BytesIO(raw), filename, mime),
    }, headers={"X-CSRF-Token": token})


def short_video(tmp_path, *, with_audio=True):
    target = tmp_path / ("video-audio.mp4" if with_audio else "video-no-audio.mp4")
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=160x90:d=0.8",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.8", "-shortest"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    command += [str(target)]
    subprocess.run(command, check=True)
    return target.read_bytes()


def trial_app(tmp_path, monkeypatch, hourly=10):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    return server.create_app({
        "TESTING": True,
        "SECRET_KEY": "trial-session-secret-32-characters-long",
        "PILOT_PASSWORD": "trial-password-16-chars",
        "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "trial-limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "trial-cases.sqlite3"),
        "PILOT_TENANT_ID": "trial-tenant",
        "PILOT_OWNER_ID": "trial-owner",
        "ANALYSES_PER_HOUR": hourly,
        "PILOT_PLAN": "trial",
        "TRIAL_ANALYSES_TOTAL": 1,
    })


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
    target = tmp_path / "unexpected.png"
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
        "clarification_available": False,
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


def test_media_contract_rejects_mime_extension_and_content_mismatch(client, monkeypatch):
    token = login(client).json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    declared = post_media(client, token, photo("PNG"), "photo.jpg", "image/png")
    assert declared.status_code == 400
    assert declared.json["error"]["code"] == "invalid_media"
    content = post_media(client, token, photo("JPEG"), "photo.png", "image/png")
    assert content.status_code == 400
    assert content.json["error"]["code"] == "invalid_image"


def test_video_is_recognized_but_never_sent_or_charged(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    response = post_media(client, token, b"synthetic-video", "clip.mp4", "video/mp4")
    assert response.status_code == 501
    assert response.json["error"]["code"] == "video_pipeline_unavailable"
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1


def test_video_intake_validates_frames_and_audio_without_provider_or_trial(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    raw = short_video(tmp_path)
    response = inspect_media(client, token, raw)
    assert response.status_code == 200
    assert response.json["media"]["validated"] is True
    assert response.json["media"]["audio"]["status"] == "ready_for_transcription"
    assert response.json["media"]["transcription"]["status"] == "not_performed"
    assert response.json["media"]["original_retention"]["status"] == "archived"
    assert response.json["archive"]["saved"] is True
    assert response.json["archive"]["kind"] == "video_technical_verification"
    assert response.json["trial_consumed"] is False
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1

    case_id = response.json["archive"]["case_id"]
    listing = client.get("/api/cases", headers={"X-CSRF-Token": token}).json["cases"]
    assert listing[0]["id"] == case_id
    assert listing[0]["kind"] == "video_technical_verification"
    saved = client.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": token}).json["case"]
    assert saved["analysis"]["meta"]["analysis_performed"] is False
    assert saved["analysis"]["meta"]["transcription_performed"] is False
    assert saved["analysis"]["findings"] == []
    roles = [asset["role"] for asset in saved["assets"]]
    assert roles.count("original") == 1
    assert roles.count("frame") == len(response.json["media"]["frames"])
    assert roles.count("audio") == 1
    original = next(asset for asset in saved["assets"] if asset["role"] == "original")
    original_response = client.get(original["download_url"])
    assert original_response.status_code == 200
    assert original_response.data == raw
    assert original_response.headers["Content-Disposition"].startswith("inline;")


def test_video_history_quota_failure_keeps_existing_case_and_trial(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    app.extensions["case_store"].max_history_bytes = 64
    store = app.extensions["case_store"]
    existing, failure = store.create(
        "trial-tenant", "trial-owner", "existing",
        {"summary": "Existing", "findings": []}, None, 100,
        assets=[{"role": "original", "data": b"keep", "filename": "keep.bin", "media_type": "application/octet-stream"}],
    )
    assert existing and failure is None
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    response = inspect_media(client, token, short_video(tmp_path))
    assert response.status_code == 200
    assert response.json["media"]["validated"] is True
    assert response.json["media"]["original_retention"]["status"] == "not_saved"
    assert response.json["archive"]["saved"] is False
    assert "casi esistenti restano disponibili" in response.json["archive"]["message"]
    assert store.get(existing, "trial-tenant", "trial-owner") is not None
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1


def test_archived_video_without_audio_never_claims_an_audio_track(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    response = inspect_media(client, token, short_video(tmp_path, with_audio=False))
    assert response.status_code == 200
    assert response.json["archive"]["saved"] is True
    assert response.json["media"]["audio"]["status"] == "absent"
    message = response.json["media"]["original_retention"]["message"]
    assert "non contiene una traccia audio" in message
    assert "traccia audio incorporata" not in message
    saved = client.get(
        f"/api/cases/{response.json['archive']['case_id']}",
        headers={"X-CSRF-Token": token},
    ).json["case"]
    assert "audio" not in {asset["role"] for asset in saved["assets"]}


def test_video_history_is_owner_private_and_survives_verified_backup(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    owner = app.test_client()
    token = login(owner, "trial-password-16-chars").json["csrf"]
    raw = short_video(tmp_path)
    created = inspect_media(owner, token, raw)
    case_id = created.json["archive"]["case_id"]
    saved = owner.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": token}).json["case"]
    original = next(asset for asset in saved["assets"] if asset["role"] == "original")

    other_app = server.create_app({
        **dict(app.config), "PILOT_TENANT_ID": "other-company", "PILOT_OWNER_ID": "other-owner",
    })
    other = other_app.test_client()
    other_token = login(other, "trial-password-16-chars").json["csrf"]
    assert other.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": other_token}).status_code == 404
    assert other.get(original["download_url"]).status_code == 404

    backup = tmp_path / "video-backup"
    manifest = app.extensions["case_store"].backup(backup)
    restored = server.CaseStore.restore(
        backup, tmp_path / "restored" / "cases.sqlite3",
        tmp_path / "restored" / "media", 1024 * 1024 * 1024,
    )
    restored_case = restored.get(case_id, "trial-tenant", "trial-owner")
    assert restored_case["analysis"]["meta"]["case_kind"] == "video_technical_verification"
    restored_original = next(asset for asset in restored_case["assets"] if asset["role"] == "original")
    assert restored.asset(case_id, restored_original["id"], "trial-tenant", "trial-owner")["path"].read_bytes() == raw
    assert len(manifest["files"]) == len(saved["assets"])

    assert owner.delete(f"/api/cases/{case_id}", headers={"X-CSRF-Token": token}).json == {"deleted": True}
    assert owner.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": token}).status_code == 404


def test_video_intake_refuses_parallel_decoder_job(client):
    token = login(client).json["csrf"]
    store = client.application.extensions["limit_store"]
    lease, failure = store.reserve_media("another-account")
    assert lease and failure is None
    try:
        response = inspect_media(client, token, b"not-decoded")
    finally:
        store.release_media(lease)
    assert response.status_code == 429
    assert response.json["error"]["code"] == "media_busy"


def test_video_intake_does_not_start_decoder_after_slow_parse(client, monkeypatch):
    token = login(client).json["csrf"]
    moments = iter((100.0, 121.0))
    monkeypatch.setattr(server.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(server, "inspect_video", lambda *_args, **_kwargs: pytest.fail("Decoder started"))
    response = inspect_media(client, token, b"already-too-late")
    assert response.status_code == 422
    assert response.json["error"]["code"] == "media_processing_timeout"


def test_trial_allows_one_success_and_blocks_second_before_provider(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    calls = []
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: calls.append(1) or {"summary": "ok", "findings": []})
    first = post_image(client, token)
    assert first.status_code == 200
    assert first.json["entitlement"]["analyses_remaining"] == 0
    assert first.json["entitlement"]["export_allowed"] is False
    second = post_image(client, token)
    assert second.status_code == 402
    assert second.json["error"]["code"] == "trial_exhausted"
    assert len(calls) == 1


def test_failed_provider_call_does_not_consume_trial(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    monkeypatch.setattr(
        server,
        "analizza_immagine",
        lambda *_args: (_ for _ in ()).throw(server.AnalysisError("temporary", "Riprova.", 503)),
    )
    assert post_image(client, token).status_code == 503
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1


def test_trial_includes_one_clarification_for_saved_case_only(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    calls = []
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: calls.append(1) or {"summary": "ok", "findings": []})
    initial = post_image(client, token)
    case_id = initial.json["archive"]["case_id"]
    clarification = post_media(
        client, token, photo(), "photo.png", "image/png",
        request_kind="clarification", case_id=case_id, context="Chiarimento",
    )
    assert clarification.status_code == 200
    assert clarification.json["entitlement"]["clarifications_remaining"] == 0
    again = post_media(
        client, token, photo(), "photo.png", "image/png",
        request_kind="clarification", case_id=case_id,
    )
    assert again.status_code == 402
    assert len(calls) == 2


def test_trial_clarification_rejects_a_different_image_before_provider_and_quota(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    calls = []
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: calls.append(1) or {"summary": "ok", "findings": []})
    initial = post_image(client, token)
    case_id = initial.json["archive"]["case_id"]
    mismatch = post_media(
        client, token, photo(size=(49, 32)), "photo.png", "image/png",
        request_kind="clarification", case_id=case_id,
    )
    assert mismatch.status_code == 400
    assert mismatch.json["error"]["code"] == "clarification_image_mismatch"
    assert len(calls) == 1
    assert client.get("/api/session").json["entitlement"]["clarifications_remaining"] == 1
    accepted = post_media(
        client, token, photo(), "photo.png", "image/png",
        request_kind="clarification", case_id=case_id,
    )
    assert accepted.status_code == 200
    assert len(calls) == 2


def test_trial_archive_failure_explains_clarification_dependency_without_export_hint(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: {"summary": "ok", "findings": []})
    monkeypatch.setattr(
        app.extensions["case_store"],
        "create",
        lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("unavailable")),
    )
    response = post_image(client, token)
    assert response.status_code == 200
    assert response.json["archive"]["clarification_available"] is False
    assert "richiede un caso salvato" in response.json["archive"]["message"]
    assert "Esporta" not in response.json["archive"]["message"]


def test_trial_and_hourly_limits_are_separate(tmp_path, monkeypatch):
    app = trial_app(tmp_path, monkeypatch, hourly=0)
    client = app.test_client()
    token = login(client, "trial-password-16-chars").json["csrf"]
    monkeypatch.setattr(server, "analizza_immagine", lambda *_args: pytest.fail("Provider called"))
    response = post_image(client, token)
    assert response.status_code == 429
    assert response.json["error"]["code"] == "analysis_rate_limited"
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1
