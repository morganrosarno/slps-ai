"""Fail-closed single-instance persistence and verified snapshot tooling.

The profile supports one application process on one mounted filesystem.  It
does not itself prove that an infrastructure provider retains that mount.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
from typing import Mapping


PROFILE_NAME = "single-instance"
MANIFEST_FORMAT = 1
DEFAULT_MIN_FREE_BYTES = 1024 * 1024 * 1024
DB_KEYS = ("accounts_billing", "limits", "cases")


class DurableStorageError(RuntimeError):
    pass


def _has_symlink(path: Path) -> bool:
    """Inspect every existing component without following a symlink."""
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            if current.is_symlink():
                return True
    except OSError:
        return True
    return False


def _confined(raw: object, root: Path, label: str, *, directory: bool = False) -> Path:
    candidate = Path(str(raw or ""))
    if not str(raw or "").strip():
        raise DurableStorageError(f"missing_{label}")
    if not candidate.is_absolute():
        raise DurableStorageError(f"{label}_must_be_absolute")
    if _has_symlink(candidate):
        raise DurableStorageError(f"unsafe_{label}_symlink")
    resolved = candidate.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise DurableStorageError(f"{label}_outside_durable_root")
    if resolved.exists() and (resolved.is_dir() if directory else resolved.is_file()) is False:
        raise DurableStorageError(f"invalid_{label}_type")
    return resolved


def _min_free(raw: object) -> int:
    try:
        value = int(DEFAULT_MIN_FREE_BYTES if raw in (None, "") else raw)
    except (TypeError, ValueError) as exc:
        raise DurableStorageError("invalid_durable_min_free_bytes") from exc
    if value < 1:
        raise DurableStorageError("invalid_durable_min_free_bytes")
    return value


@dataclass(frozen=True)
class SingleInstanceProfile:
    root: Path
    account_db: Path
    rate_db: Path
    case_db: Path
    media_root: Path
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES
    configured: bool = True
    name: str = PROFILE_NAME

    @property
    def databases(self) -> dict[str, Path]:
        return {"accounts_billing": self.account_db, "limits": self.rate_db,
                "cases": self.case_db}

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def ensure_capacity(self, required_bytes: int = 0) -> None:
        if required_bytes < 0:
            raise DurableStorageError("invalid_required_capacity")
        if shutil.disk_usage(self.root).free < self.min_free_bytes + required_bytes:
            raise DurableStorageError("durable_capacity_guard")


def profile_from_mapping(values: Mapping[str, object], *, env_names: bool = True) -> SingleInstanceProfile:
    """Validate the complete layout before an adapter can create anything."""
    def get(env_name: str, config_name: str) -> object:
        return values.get(env_name if env_names else config_name, "")

    if str(get("SLPS_DURABLE_PROFILE", "DURABLE_PROFILE") or "").strip() != PROFILE_NAME:
        raise DurableStorageError("unsupported_or_missing_durable_profile")
    root_candidate = Path(str(get("SLPS_DURABLE_ROOT", "DURABLE_ROOT") or ""))
    if not root_candidate.is_absolute():
        raise DurableStorageError("durable_root_must_be_absolute")
    if (not root_candidate.exists() or not root_candidate.is_dir()
            or _has_symlink(root_candidate)):
        raise DurableStorageError("durable_root_must_be_existing_real_directory")
    root = root_candidate.resolve(strict=True)
    account = _confined(get("SLPS_ACCOUNT_DB_PATH", "ACCOUNT_DB_PATH"), root, "account_db")
    rate = _confined(get("SLPS_RATE_DB_PATH", "RATE_DB_PATH"), root, "rate_db")
    cases = _confined(get("SLPS_CASE_DB_PATH", "CASE_DB_PATH"), root, "case_db")
    media = _confined(get("SLPS_HISTORY_ROOT", "HISTORY_ROOT"), root, "history_root", directory=True)
    databases = (account, rate, cases)
    if len(set(databases)) != len(databases):
        raise DurableStorageError("durable_database_paths_overlap")
    if any(media == db or media in db.parents or db in media.parents for db in databases):
        raise DurableStorageError("durable_media_database_paths_overlap")
    profile = SingleInstanceProfile(root, account, rate, cases, media,
                                    _min_free(get("SLPS_DURABLE_MIN_FREE_BYTES",
                                                  "DURABLE_MIN_FREE_BYTES")))
    profile.ensure_capacity()
    return profile


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DurableStorageError("invalid_manifest_path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise DurableStorageError("invalid_manifest_path")
    return relative


def _copy_checked(source: Path, target: Path) -> tuple[str, int]:
    before = source.stat()
    digest, size = hashlib.sha256(), 0
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open("rb") as reader, target.open("xb") as writer:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            writer.write(chunk); digest.update(chunk); size += len(chunk)
        writer.flush(); os.fsync(writer.fileno())
    target.chmod(0o600)
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise DurableStorageError("source_changed_during_snapshot")
    return digest.hexdigest(), size


def _file_digest(source: Path) -> tuple[str, int]:
    """Hash a regular file with bounded memory."""
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _sqlite_snapshot(source: Path, target: Path) -> tuple[str, int]:
    if not source.is_file() or source.is_symlink() or _has_symlink(source):
        raise DurableStorageError("snapshot_database_missing_or_unsafe")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    uri = source.resolve(strict=True).as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DurableStorageError("snapshot_database_integrity_failed")
    target.chmod(0o600)
    return _file_digest(target)


def create_snapshot(profile: SingleInstanceProfile, destination: str | Path, *, quiesced: bool = False) -> dict:
    """Create one point-in-time set; the caller must first stop every writer."""
    if not quiesced:
        raise DurableStorageError("snapshot_requires_quiesced_service")
    profile.ensure_capacity()
    destination = Path(destination)
    if not destination.is_absolute():
        raise DurableStorageError("snapshot_destination_must_be_absolute")
    if destination.is_symlink() or _has_symlink(destination):
        raise DurableStorageError("snapshot_destination_unsafe_symlink")
    destination = destination.resolve(strict=False)
    if destination == profile.root or profile.root in destination.parents:
        raise DurableStorageError("snapshot_destination_inside_source_root")
    if destination.exists():
        raise FileExistsError("snapshot_destination_must_not_exist")
    if not destination.parent.exists() or _has_symlink(destination.parent):
        raise DurableStorageError("snapshot_parent_missing_or_unsafe")
    temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}.partial-", dir=destination.parent))
    try:
        files: list[dict[str, object]] = []
        layout = {"account_db": profile.relative(profile.account_db),
                  "rate_db": profile.relative(profile.rate_db),
                  "case_db": profile.relative(profile.case_db),
                  "media_root": profile.relative(profile.media_root)}
        for name, source in profile.databases.items():
            archive = f"databases/{name}.sqlite3"
            digest, size = _sqlite_snapshot(source, temp / archive)
            files.append({"kind": "sqlite", "name": name, "path": archive,
                          "sha256": digest, "size": size})
        if (not profile.media_root.is_dir() or profile.media_root.is_symlink()
                or _has_symlink(profile.media_root)):
            raise DurableStorageError("media_root_missing_or_unsafe")
        for source in sorted(profile.media_root.rglob("*")):
            if source.is_symlink():
                raise DurableStorageError("media_symlink_rejected")
            if source.is_dir():
                continue
            if not source.is_file():
                raise DurableStorageError("media_non_regular_file_rejected")
            relative = source.relative_to(profile.media_root).as_posix()
            archive = f"media/{relative}"
            digest, size = _copy_checked(source, temp / archive)
            files.append({"kind": "media", "path": archive, "relative_path": relative,
                          "sha256": digest, "size": size})
        manifest = {"format": MANIFEST_FORMAT, "profile": PROFILE_NAME,
                    "created_at": int(time.time()), "quiesced": True,
                    "min_free_bytes": profile.min_free_bytes, "layout": layout,
                    "files": sorted(files, key=lambda item: str(item["path"]))}
        (temp / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        (temp / "manifest.json").chmod(0o600)
        os.replace(temp, destination)
        return manifest
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _verified_manifest(backup: Path) -> tuple[dict, list[dict]]:
    if not backup.is_absolute() or not backup.is_dir() or backup.is_symlink() or _has_symlink(backup):
        raise DurableStorageError("backup_directory_missing_or_unsafe")
    try:
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableStorageError("invalid_snapshot_manifest") from exc
    if (not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT
            or manifest.get("profile") != PROFILE_NAME or manifest.get("quiesced") is not True
            or not isinstance(manifest.get("layout"), dict)
            or not isinstance(manifest.get("files"), list)):
        raise DurableStorageError("invalid_snapshot_manifest")
    entries, declared = [], set()
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise DurableStorageError("invalid_snapshot_manifest")
        relative = _safe_relative(item.get("path")); key = relative.as_posix()
        digest, size = item.get("sha256"), item.get("size")
        if (key in declared or item.get("kind") not in {"sqlite", "media"}
                or not isinstance(size, int) or size < 0
                or not isinstance(digest, str) or len(digest) != 64):
            raise DurableStorageError("invalid_snapshot_manifest")
        source = backup.joinpath(*relative.parts)
        if not source.is_file() or source.is_symlink() or _has_symlink(source):
            raise DurableStorageError("snapshot_file_missing_or_unsafe")
        actual_digest, actual_size = _file_digest(source)
        if actual_size != size or actual_digest != digest:
            raise DurableStorageError("snapshot_checksum_mismatch")
        declared.add(key); entries.append(item)
    archive_items = list(backup.rglob("*"))
    if any(path.is_symlink() for path in archive_items):
        raise DurableStorageError("snapshot_symlink_rejected")
    actual = {p.relative_to(backup).as_posix() for p in archive_items
              if p.is_file() and p.relative_to(backup).as_posix() != "manifest.json"}
    if actual != declared:
        raise DurableStorageError("snapshot_inventory_mismatch")
    names = [item.get("name") for item in entries if item["kind"] == "sqlite"]
    if sorted(names) != sorted(DB_KEYS):
        raise DurableStorageError("snapshot_database_inventory_incomplete")
    for key in ("account_db", "rate_db", "case_db", "media_root"):
        _safe_relative(manifest["layout"].get(key))
    layout = {key: _safe_relative(manifest["layout"].get(key)) for key in (
        "account_db", "rate_db", "case_db", "media_root"
    )}
    database_layout = (layout["account_db"], layout["rate_db"], layout["case_db"])
    if len(set(database_layout)) != len(database_layout):
        raise DurableStorageError("snapshot_layout_overlap")
    media = layout["media_root"]
    if any(media == db or media in db.parents or db in media.parents for db in database_layout):
        raise DurableStorageError("snapshot_layout_overlap")
    return manifest, entries


def restore_snapshot(backup: str | Path, target_root: str | Path,
                     *, min_free_bytes: int | None = None) -> SingleInstanceProfile:
    """Validate everything, stage privately, then install into an empty root."""
    backup = Path(backup)
    if not backup.is_absolute() or backup.is_symlink() or _has_symlink(backup):
        raise DurableStorageError("backup_directory_missing_or_unsafe")
    backup = backup.resolve(strict=False)
    target = Path(target_root)
    if not target.is_absolute():
        raise DurableStorageError("restore_target_must_be_absolute")
    if target.is_symlink() or _has_symlink(target):
        raise DurableStorageError("restore_target_unsafe_symlink")
    target = target.resolve(strict=False)
    if target == backup or backup in target.parents or target in backup.parents:
        raise DurableStorageError("restore_backup_target_overlap")
    if target.exists() and (not target.is_dir() or target.is_symlink() or any(target.iterdir())):
        raise FileExistsError("restore_target_must_be_empty")
    if not target.parent.exists() or target.parent.is_symlink() or _has_symlink(target.parent):
        raise DurableStorageError("restore_parent_missing_or_unsafe")
    manifest, entries = _verified_manifest(backup)
    reserve = _min_free(min_free_bytes if min_free_bytes is not None else manifest.get("min_free_bytes"))
    if shutil.disk_usage(target.parent).free < reserve + sum(item["size"] for item in entries):
        raise DurableStorageError("restore_capacity_guard")
    temp = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
    try:
        layout = manifest["layout"]
        paths = {key: temp.joinpath(*_safe_relative(value).parts)
                 for key, value in layout.items()}
        db_targets = {"accounts_billing": paths["account_db"], "limits": paths["rate_db"],
                      "cases": paths["case_db"]}
        for item in entries:
            if item["kind"] != "sqlite":
                continue
            destination = db_targets[item["name"]]
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(backup / item["path"], destination); destination.chmod(0o600)
            with sqlite3.connect(destination) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DurableStorageError("restored_database_integrity_failed")
        paths["media_root"].mkdir(parents=True, exist_ok=True, mode=0o700)
        for item in entries:
            if item["kind"] != "media":
                continue
            relative = _safe_relative(item.get("relative_path"))
            if item["path"] != "media/" + relative.as_posix():
                raise DurableStorageError("invalid_media_inventory_path")
            destination = paths["media_root"].joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(backup / item["path"], destination); destination.chmod(0o600)
        if target.exists():
            target.rmdir()
        os.replace(temp, target)
        profile = SingleInstanceProfile(
            target,
            target.joinpath(*_safe_relative(layout["account_db"]).parts),
            target.joinpath(*_safe_relative(layout["rate_db"]).parts),
            target.joinpath(*_safe_relative(layout["case_db"]).parts),
            target.joinpath(*_safe_relative(layout["media_root"]).parts), reserve)
        profile.ensure_capacity()
        return profile
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
