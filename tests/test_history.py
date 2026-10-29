import io
import json
from pathlib import Path
import subprocess

from PIL import Image

import server


def synthetic_photo():
    output = io.BytesIO()
    Image.new("RGB", (24, 16), "blue").save(output, format="PNG")
    return output.getvalue()


def synthetic_video_with_audio(tmp_path):
    target = tmp_path / "with-audio.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=160x90:d=0.4", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=0.4", "-shortest", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(target),
    ], check=True)
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
        "stream=codec_type", "-of", "json", str(target),
    ], check=True, capture_output=True, text=True)
    assert json.loads(probe.stdout)["streams"][0]["codec_type"] == "audio"
    return target.read_bytes()


def make_store(tmp_path, capacity=1024 * 1024):
    return server.CaseStore(tmp_path / "cases.sqlite3", tmp_path / "media", capacity)


def create_case(store, *, tenant="company-a", owner="user-a", assets=None):
    return store.create(
        tenant, owner, "Synthetic context", {"summary": "Synthetic report", "findings": []},
        "a" * 64, 100, assets=assets or [],
    )


def test_original_photo_and_derived_copy_are_private_and_authorized(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    app = server.create_app({
        "TESTING": True,
        "SECRET_KEY": "history-test-session-secret-32-characters",
        "PILOT_PASSWORD": "history-test-password",
        "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
        "PILOT_TENANT_ID": "company-a",
        "PILOT_OWNER_ID": "user-a",
        "PILOT_PLAN": "internal",
    })
    monkeypatch.setattr(
        server, "analizza_immagine",
        lambda *_args: {"summary": "Stored", "findings": []},
    )
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf"]
    csrf = client.post(
        "/api/login", json={"password": "history-test-password"},
        headers={"X-CSRF-Token": csrf},
    ).json["csrf"]
    raw = synthetic_photo()
    created = client.post(
        "/analizza",
        data={"file": (io.BytesIO(raw), "original.png"), "context": "Synthetic"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 200
    case_id = created.json["archive"]["case_id"]
    saved = client.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": csrf}).json["case"]
    assert saved["report"] == {"stored": True, "media_type": "application/json"}
    assert {item["role"] for item in saved["assets"]} == {"original", "normalized"}
    original = next(item for item in saved["assets"] if item["role"] == "original")
    response = client.get(original["download_url"])
    assert response.status_code == 200 and response.data == raw
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert app.test_client().get(original["download_url"]).status_code == 401
    assert client.get(
        original["download_url"], headers={"Sec-Fetch-Site": "cross-site"}
    ).status_code == 403
    assert raw not in Path(app.config["CASE_DB_PATH"]).read_bytes()
    stored = app.extensions["case_store"].asset(case_id, original["id"], "company-a", "user-a")
    assert stored["path"].stat().st_mode & 0o777 == 0o600

    other = server.create_app({
        **dict(app.config), "PILOT_TENANT_ID": "company-b", "PILOT_OWNER_ID": "user-b",
    }).test_client()
    other_csrf = other.get("/api/session").json["csrf"]
    other_csrf = other.post(
        "/api/login", json={"password": "history-test-password"},
        headers={"X-CSRF-Token": other_csrf},
    ).json["csrf"]
    assert other.get(original["download_url"]).status_code == 404
    assert other.get(f"/api/cases/{case_id}", headers={"X-CSRF-Token": other_csrf}).status_code == 404


def test_capacity_blocks_new_upload_without_deleting_history_or_expiring_old_cases(tmp_path):
    store = make_store(tmp_path, capacity=10)
    first_id, failure = create_case(store, assets=[{
        "role": "original", "data": b"12345678", "filename": "first.bin",
        "media_type": "application/octet-stream",
    }])
    assert first_id and failure is None
    assert store.storage_status("company-a") == {
        "used_bytes": 8, "limit_bytes": 10, "remaining_bytes": 2,
        "warning": True, "uploads_blocked": False,
    }
    with store.connect() as db:
        db.execute("UPDATE cases SET created=1 WHERE id=?", (first_id,))
    second_id, failure = create_case(store, assets=[{
        "role": "original", "data": b"abc", "filename": "second.bin",
        "media_type": "application/octet-stream",
    }])
    assert second_id is None and failure == "storage_limit"
    assert store.get(first_id, "company-a", "user-a")["created_at"] == 1
    assert store.asset(
        first_id, store.get(first_id, "company-a", "user-a")["assets"][0]["id"],
        "company-a", "user-a",
    )["path"].read_bytes() == b"12345678"
    assert store.list("company-a", "user-a")[0]["id"] == first_id


def test_delete_and_account_closure_remove_files_only_in_authorized_scope(tmp_path):
    store = make_store(tmp_path)
    asset = lambda payload: [{
        "role": "original", "data": payload, "filename": "asset.bin",
        "media_type": "application/octet-stream",
    }]
    first, _ = create_case(store, owner="user-a", assets=asset(b"first"))
    second, _ = create_case(store, owner="user-a", assets=asset(b"second"))
    colleague, _ = create_case(store, owner="user-b", assets=asset(b"colleague"))
    first_asset = store.asset(
        first, store.get(first, "company-a", "user-a")["assets"][0]["id"],
        "company-a", "user-a",
    )["path"]
    assert not store.delete(first, "company-a", "user-b") and first_asset.exists()
    assert store.delete_owner_history("company-a", "user-a") == 2
    assert not first_asset.exists()
    assert store.get(second, "company-a", "user-a") is None
    assert store.get(colleague, "company-a", "user-b") is not None
    assert store.storage_status("company-a")["used_bytes"] == len(b"colleague")


def test_failed_server_file_removal_keeps_retryable_tombstone_and_never_reports_success(tmp_path, monkeypatch):
    app = server.create_app({
        "TESTING": True,
        "SECRET_KEY": "deletion-test-session-secret-32-characters",
        "PILOT_PASSWORD": "deletion-test-password",
        "SESSION_COOKIE_SECURE": False,
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
        "PILOT_TENANT_ID": "company-a",
        "PILOT_OWNER_ID": "user-a",
        "PILOT_PLAN": "internal",
    })
    store = app.extensions["case_store"]
    case_id, _ = create_case(store, assets=[{
        "role": "original", "data": b"must-be-removed", "filename": "evidence.bin",
        "media_type": "application/octet-stream",
    }])
    asset_id = store.get(case_id, "company-a", "user-a")["assets"][0]["id"]
    original_rmtree = server.shutil.rmtree

    def fail_trash(path, *args, **kwargs):
        if Path(path).parent.name == ".trash":
            raise OSError("synthetic removal failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(server.shutil, "rmtree", fail_trash)
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf"]
    csrf = client.post(
        "/api/login", json={"password": "deletion-test-password"},
        headers={"X-CSRF-Token": csrf},
    ).json["csrf"]
    failed = client.delete(f"/api/cases/{case_id}", headers={"X-CSRF-Token": csrf})
    assert failed.status_code == 503
    assert failed.json["error"]["code"] == "case_deletion_pending"
    assert store.get(case_id, "company-a", "user-a") is None
    assert store.asset(case_id, asset_id, "company-a", "user-a") is None
    pending = client.get("/api/cases", headers={"X-CSRF-Token": csrf}).json["cases"]
    assert pending == [{
        "id": case_id, "created_at": pending[0]["created_at"], "context": "",
        "summary": "Eliminazione da completare", "deletion_pending": True,
    }]
    with store.connect() as db:
        case_count = db.execute("SELECT COUNT(*) FROM cases WHERE id=?", (case_id,)).fetchone()[0]
        deletion = db.execute(
            "SELECT attempts, trash_relative_path FROM case_deletions WHERE case_id=?", (case_id,)
        ).fetchone()
    assert case_count == 1 and deletion["attempts"] == 1
    trash = store._safe_path(deletion["trash_relative_path"])
    assert trash.is_dir() and any(trash.iterdir())

    monkeypatch.setattr(server.shutil, "rmtree", original_rmtree)
    completed = client.delete(f"/api/cases/{case_id}", headers={"X-CSRF-Token": csrf})
    assert completed.status_code == 200 and completed.json == {"deleted": True}
    assert not trash.exists()
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM cases WHERE id=?", (case_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM case_deletions WHERE case_id=?", (case_id,)).fetchone()[0] == 0


def test_verified_backup_restore_preserves_synthetic_video_audio_and_derivatives(tmp_path):
    store = make_store(tmp_path / "source", capacity=10 * 1024 * 1024)
    video = synthetic_video_with_audio(tmp_path)
    case_id, failure = create_case(store, assets=[
        {"role": "original", "data": video, "filename": "scene.mp4", "media_type": "video/mp4"},
        {"role": "audio", "data": b"synthetic-audio-extract", "filename": "audio.m4a", "media_type": "audio/mp4"},
        {"role": "frame", "data": synthetic_photo(), "filename": "frame.png", "media_type": "image/png"},
        {"role": "transcript", "data": "Rumore sintetico".encode(), "filename": "transcript.txt", "media_type": "text/plain"},
    ])
    assert case_id and failure is None
    manifest = store.backup(tmp_path / "backup")
    assert len(manifest["files"]) == 4
    restored = server.CaseStore.restore(
        tmp_path / "backup", tmp_path / "restored" / "cases.sqlite3",
        tmp_path / "restored" / "media", 10 * 1024 * 1024,
    )
    saved = restored.get(case_id, "company-a", "user-a")
    assert saved["analysis"]["summary"] == "Synthetic report"
    by_role = {asset["role"]: asset for asset in saved["assets"]}
    assert restored.asset(case_id, by_role["original"]["id"], "company-a", "user-a")["path"].read_bytes() == video
    assert restored.asset(case_id, by_role["audio"]["id"], "company-a", "user-a")["path"].read_bytes() == b"synthetic-audio-extract"
    assert restored.storage_status("company-a")["used_bytes"] == sum(item["byte_size"] for item in manifest["files"])

    original = tmp_path / "backup" / "media" / manifest["files"][0]["relative_path"]
    original.write_bytes(original.read_bytes() + b"tampered")
    try:
        server.CaseStore.restore(
            tmp_path / "backup", tmp_path / "tampered" / "cases.sqlite3",
            tmp_path / "tampered" / "media", 10 * 1024 * 1024,
        )
    except OSError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("Tampered backup must not restore")
