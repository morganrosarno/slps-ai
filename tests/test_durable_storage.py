import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from accounts import AccountStore
from durable_storage import (
    DurableStorageError, create_snapshot, profile_from_mapping, restore_snapshot,
)
from server import CaseStore, LimitStore, create_app
import durable_storage
from scripts import preflight


PASSWORD = "a-long-local-test-passphrase"


def profile_values(root: Path) -> dict[str, str]:
    return {
        "SLPS_DURABLE_PROFILE": "single-instance",
        "SLPS_DURABLE_ROOT": str(root),
        "SLPS_DURABLE_MIN_FREE_BYTES": "1",
        "SLPS_ACCOUNT_DB_PATH": str(root / "db" / "accounts-billing.sqlite3"),
        "SLPS_RATE_DB_PATH": str(root / "db" / "limits.sqlite3"),
        "SLPS_CASE_DB_PATH": str(root / "db" / "cases.sqlite3"),
        "SLPS_HISTORY_ROOT": str(root / "media"),
    }


def app_config(root: Path, *, mode="real") -> dict:
    env = profile_values(root)
    return {
        "TESTING": True,
        "DATA_MODE": mode,
        "AUTH_MODE": "accounts",
        "SECRET_KEY": "a-session-secret-longer-than-32-characters",
        "DURABLE_PROFILE": env["SLPS_DURABLE_PROFILE"],
        "DURABLE_ROOT": env["SLPS_DURABLE_ROOT"],
        "DURABLE_MIN_FREE_BYTES": env["SLPS_DURABLE_MIN_FREE_BYTES"],
        "ACCOUNT_DB_PATH": env["SLPS_ACCOUNT_DB_PATH"],
        "RATE_DB_PATH": env["SLPS_RATE_DB_PATH"],
        "CASE_DB_PATH": env["SLPS_CASE_DB_PATH"],
        "HISTORY_ROOT": env["SLPS_HISTORY_ROOT"],
    }


def populated_profile(tmp_path: Path):
    root = tmp_path / "volume"
    root.mkdir()
    profile = profile_from_mapping(profile_values(root))
    accounts = AccountStore(profile.account_db)
    user = accounts.register(
        email="owner@example.test", password=PASSWORD, company_name="Synthetic SA",
        company_identifier="CHE-000.000.000", role="Owner", locale="it",
    )
    with accounts.connect() as db:
        db.execute("UPDATE account_companies SET verified=1 WHERE id=?", (user["company_id"],))
        db.execute("UPDATE account_users SET email_verified=1,membership_verified=1 WHERE id=?",
                   (user["id"],))
    limits = LimitStore(profile.rate_db)
    with limits.connect() as db:
        db.execute("INSERT INTO events(kind,scope,created) VALUES ('analysis','tenant-a',1)")
    cases = CaseStore(profile.case_db, profile.media_root, 1024 * 1024,
                      capacity_guard=profile.ensure_capacity)
    case_id, error = cases.create(
        "tenant-a", "owner-a", "synthetic context", {"findings": []}, "f" * 64, 10,
        assets=[{"role": "original", "filename": "synthetic.jpg",
                 "media_type": "image/jpeg", "data": b"synthetic-image"}],
    )
    assert error is None
    return profile, user, case_id


def test_real_mode_requires_complete_valid_profile_before_creating_files(tmp_path):
    root = tmp_path / "volume"; root.mkdir()
    config = app_config(root)
    config["HISTORY_ROOT"] = str(tmp_path / "outside-media")
    with pytest.raises(DurableStorageError, match="outside_durable_root"):
        create_app(config)
    assert list(root.iterdir()) == []


def test_complete_real_profile_still_requires_provider_acceptance_before_files(tmp_path):
    root = tmp_path / "volume"; root.mkdir()
    with pytest.raises(RuntimeError, match="provider_verified"):
        create_app(app_config(root))
    assert list(root.iterdir()) == []


def test_preflight_reports_configured_but_never_provider_verified(tmp_path):
    root = tmp_path / "volume"; root.mkdir()
    env = profile_values(root) | {
        "SLPS_DATA_MODE": "real", "SLPS_AUTH_MODE": "pilot",
        "SLPS_SESSION_SECRET": "s" * 32, "SLPS_PILOT_PASSWORD": "p" * 16,
        "OPENAI_API_KEY": "placeholder", "OPENAI_MODEL": "placeholder",
    }
    checks = preflight.run_checks(env, tmp_path / "code")
    by_id = {item.id: item for item in checks}
    assert all(by_id[item].status == "pass" for item in (
        "durable_profile", "durable_layout", "durable_capacity", "real_data_storage"
    ))
    assert by_id["storage_provider_verification"].status == "blocker"
    report = preflight.report(checks)
    assert report["storage_profile"] == "single-instance configured"
    assert report["storage_provider_verified"] is False
    assert report["ready"] is False


def test_synthetic_defaults_are_unchanged_and_not_certified(tmp_path):
    app = create_app({
        "TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "accounts",
        "SECRET_KEY": "a-session-secret-longer-than-32-characters",
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"),
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
    })
    assert app.extensions["durable_storage_profile"] is None
    assert app.extensions["account_store"].durable is False
    assert app.extensions["case_store"].blob_store.durable is False


@pytest.mark.parametrize("mutation", ["relative", "outside", "duplicate", "overlap"])
def test_profile_rejects_relative_outside_and_overlapping_paths(tmp_path, mutation):
    root = tmp_path / "volume"; root.mkdir()
    values = profile_values(root)
    if mutation == "relative":
        values["SLPS_CASE_DB_PATH"] = "relative/cases.sqlite3"
    elif mutation == "outside":
        values["SLPS_RATE_DB_PATH"] = str(tmp_path / "outside.sqlite3")
    elif mutation == "duplicate":
        values["SLPS_RATE_DB_PATH"] = values["SLPS_CASE_DB_PATH"]
    else:
        values["SLPS_HISTORY_ROOT"] = str(root / "db")
    with pytest.raises(DurableStorageError):
        profile_from_mapping(values)


def test_profile_rejects_symlink_components_and_capacity_shortage(tmp_path, monkeypatch):
    root = tmp_path / "volume"; root.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    values = profile_values(root)
    values["SLPS_CASE_DB_PATH"] = str(root / "linked" / "cases.sqlite3")
    with pytest.raises(DurableStorageError, match="symlink"):
        profile_from_mapping(values)
    values = profile_values(root)
    monkeypatch.setattr(durable_storage.shutil, "disk_usage",
                        lambda _path: SimpleNamespace(free=0))
    with pytest.raises(DurableStorageError, match="capacity_guard"):
        profile_from_mapping(values)


def test_snapshot_requires_quiescence_and_refuses_source_volume_destination(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    with pytest.raises(DurableStorageError, match="quiesced"):
        create_snapshot(profile, tmp_path / "backup")
    with pytest.raises(DurableStorageError, match="inside_source_root"):
        create_snapshot(profile, profile.root / "backup", quiesced=True)


def test_snapshot_rejects_symlinked_destination_component(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir()
    linked = tmp_path / "linked"; linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(DurableStorageError, match="unsafe_symlink"):
        create_snapshot(profile, linked / "backup", quiesced=True)

    assert list(outside.iterdir()) == []


def test_full_snapshot_restore_preserves_migrations_media_and_tenant_isolation(tmp_path):
    profile, user, case_id = populated_profile(tmp_path)
    backup = tmp_path / "backup"
    manifest = create_snapshot(profile, backup, quiesced=True)
    assert {item["name"] for item in manifest["files"] if item["kind"] == "sqlite"} == {
        "accounts_billing", "limits", "cases"
    }
    media = [item for item in manifest["files"] if item["kind"] == "media"]
    assert media and all(item["sha256"] and item["size"] > 0 for item in media)

    empty_target = tmp_path / "restored"
    empty_target.mkdir()
    restored = restore_snapshot(backup, empty_target, min_free_bytes=1)
    accounts = AccountStore(restored.account_db)
    assert accounts.authenticate("owner@example.test", PASSWORD)["id"] == user["id"]
    assert accounts.schema_versions() == (1, 2, 3, 4, 5)
    limits = LimitStore(restored.rate_db)
    assert limits.schema_versions() == (1, 2, 3, 4)
    with limits.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE scope='tenant-a'").fetchone()[0] == 1
    cases = CaseStore(restored.case_db, restored.media_root, 1024 * 1024)
    assert cases.schema_versions() == (1, 2)
    assert cases.get(case_id, "tenant-a", "owner-a") is not None
    assert cases.get(case_id, "tenant-b", "owner-a") is None
    asset = cases.get(case_id, "tenant-a", "owner-a")["assets"][0]
    assert cases.asset(case_id, asset["id"], "tenant-a", "owner-a")["path"].read_bytes() == b"synthetic-image"


def test_restore_rejects_checksum_tampering_without_touching_empty_target(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    backup = tmp_path / "backup"; create_snapshot(profile, backup, quiesced=True)
    media = next(path for path in (backup / "media").rglob("*") if path.is_file())
    media.write_bytes(b"tampered")
    target = tmp_path / "empty"; target.mkdir()
    with pytest.raises(DurableStorageError, match="checksum"):
        restore_snapshot(backup, target, min_free_bytes=1)
    assert target.exists() and list(target.iterdir()) == []


def test_restore_rejects_manifest_path_traversal_and_nonempty_target(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    backup = tmp_path / "backup"; create_snapshot(profile, backup, quiesced=True)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../escape.sqlite3"
    manifest_path.write_text(json.dumps(manifest))
    target = tmp_path / "empty"; target.mkdir()
    with pytest.raises(DurableStorageError, match="manifest_path"):
        restore_snapshot(backup, target, min_free_bytes=1)
    occupied = tmp_path / "occupied"; occupied.mkdir(); (occupied / "keep").write_text("x")
    with pytest.raises(FileExistsError, match="empty"):
        restore_snapshot(backup, occupied, min_free_bytes=1)
    assert (occupied / "keep").read_text() == "x"


def test_restore_rejects_duplicate_or_media_overlapping_manifest_layout(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    backup = tmp_path / "backup"; create_snapshot(profile, backup, quiesced=True)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["layout"]["rate_db"] = manifest["layout"]["case_db"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DurableStorageError, match="layout_overlap"):
        restore_snapshot(backup, tmp_path / "restored", min_free_bytes=1)


def test_restore_rejects_undeclared_nested_manifest_named_file(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    backup = tmp_path / "backup"; create_snapshot(profile, backup, quiesced=True)
    nested = backup / "media" / "undeclared" / "manifest.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")

    with pytest.raises(DurableStorageError, match="inventory_mismatch"):
        restore_snapshot(backup, tmp_path / "restored", min_free_bytes=1)


def test_restore_rejects_symlinked_backup_root_and_target_root(tmp_path):
    profile, _, _ = populated_profile(tmp_path)
    backup = tmp_path / "backup"; create_snapshot(profile, backup, quiesced=True)
    linked_backup = tmp_path / "linked-backup"
    linked_backup.symlink_to(backup, target_is_directory=True)

    with pytest.raises(DurableStorageError, match="backup_directory_missing_or_unsafe"):
        restore_snapshot(linked_backup, tmp_path / "restored-a", min_free_bytes=1)

    outside_target = tmp_path / "outside-target"; outside_target.mkdir()
    linked_target = tmp_path / "linked-target"
    linked_target.symlink_to(outside_target, target_is_directory=True)
    with pytest.raises(DurableStorageError, match="restore_target_unsafe_symlink"):
        restore_snapshot(backup, linked_target, min_free_bytes=1)

    assert linked_target.is_symlink()
    assert list(outside_target.iterdir()) == []


def test_snapshot_and_restore_hash_files_without_unbounded_read_bytes(tmp_path, monkeypatch):
    profile, _, _ = populated_profile(tmp_path)

    def reject_read_bytes(_path):
        raise AssertionError("snapshot hashing must stream files")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    backup = tmp_path / "backup"
    create_snapshot(profile, backup, quiesced=True)
    restored = restore_snapshot(backup, tmp_path / "restored", min_free_bytes=1)

    assert restored.case_db.is_file()
