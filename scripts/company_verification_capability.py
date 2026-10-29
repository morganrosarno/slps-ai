#!/usr/bin/env python3
"""Offline lifecycle for the company-verification operator capability.

This command is deliberately separate from the day-to-day operator command.
It has no transport and imports no web application.  Secrets are accepted only
from inherited file descriptors or environment variables.  Every mutation is
preceded by a verified SQLite rollback copy and guarded by an explicit intent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
import time
from typing import Mapping, TextIO


DB_ENV = "SLPS_ACCOUNT_DB_PATH"
CURRENT_SECRET_ENV = "SLPS_VERIFICATION_CURRENT_SECRET"
NEW_SECRET_ENV = "SLPS_VERIFICATION_NEW_SECRET"
MAX_SECRET_BYTES = 256
MAX_INTENT_BYTES = 4096
CHANGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{15,127}")
FINGERPRINT = re.compile(r"[0-9a-f]{64}")
DATABASE_ID = re.compile(r"[0-9a-f]{32}")
MANIFEST_FORMAT = "slps-verification-capability-rollback-v1"


class LifecycleInputError(ValueError):
    pass


class LifecycleConflict(RuntimeError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LifecycleInputError("invalid_arguments")


def _parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(add_help=False)
    parser.add_argument("--help", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--intent-fd", type=int)
    parser.add_argument("--rollback-db", type=Path)
    parser.add_argument("--current-secret-fd", type=int)
    parser.add_argument("--new-secret-fd", type=int)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("provision", add_help=False)
    commands.add_parser("rotate", add_help=False)
    recover = commands.add_parser("recover", add_help=False)
    recover.add_argument("--source-backup", type=Path, required=True)
    return parser


def _read_limited_fd(fd: int, maximum: int) -> bytes:
    if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
        raise LifecycleInputError("invalid_file_descriptor")
    try:
        with os.fdopen(os.dup(fd), "rb") as stream:
            value = stream.read(maximum + 1)
    except OSError as exc:
        raise LifecycleInputError("unreadable_file_descriptor") from exc
    if len(value) > maximum:
        raise LifecycleInputError("input_too_large")
    return value


def _secret(fd: int | None, env_name: str, env: Mapping[str, str], *, required: bool) -> bytes | None:
    configured = env.get(env_name)
    if fd is not None and configured is not None:
        raise LifecycleInputError("ambiguous_secret_source")
    if fd is not None:
        value = _read_limited_fd(fd, MAX_SECRET_BYTES)
        if value.endswith(b"\r\n"):
            value = value[:-2]
        elif value.endswith(b"\n"):
            value = value[:-1]
    elif configured is not None:
        try:
            value = configured.encode("utf-8")
        except UnicodeError as exc:
            raise LifecycleInputError("invalid_secret") from exc
    elif required:
        raise LifecycleInputError("secret_missing")
    else:
        return None
    if not 32 <= len(value) <= MAX_SECRET_BYTES or b"\x00" in value:
        raise LifecycleInputError("invalid_secret")
    return value


def _intent(fd: int | None, command: str) -> dict[str, object]:
    if fd is None:
        raise LifecycleInputError("intent_missing")
    raw = _read_limited_fd(fd, MAX_INTENT_BYTES)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleInputError("intent_invalid") from exc
    if (not isinstance(document, dict)
            or set(document) != {"operation", "change_id", "expected_generation"}
            or document.get("operation") != command
            or not isinstance(document.get("change_id"), str)
            or not CHANGE_ID.fullmatch(document["change_id"])
            or type(document.get("expected_generation")) is not int
            or not 0 <= document["expected_generation"] <= 2_147_483_647):
        raise LifecycleInputError("intent_invalid")
    return document


def _storage_parent_safe(parent: Path) -> bool:
    """Reject replaceable path chains while permitting sticky shared roots.

    The direct parent must be private.  Higher ancestors may be readable, but a
    group/other-writable ancestor is safe only when its sticky bit prevents an
    unrelated user from renaming this process' child directory (for example
    ``/tmp``).  Rechecking immediately before opening is sufficient here because
    every accepted direct parent is non-writable to group/other; a privileged
    administrator remains outside this local capability boundary.
    """
    absolute = parent.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError:
            return False
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            return False
        mode = stat.S_IMODE(metadata.st_mode)
        if current == absolute:
            if mode & 0o077:
                return False
        elif mode & 0o022 and not mode & stat.S_ISVTX:
            return False
    return True


def _private_regular_file(path: Path, *, nonempty: bool = True) -> Path:
    if not _storage_parent_safe(path.parent):
        raise sqlite3.DatabaseError("file_unavailable")
    try:
        parent_metadata = path.parent.lstat()
    except OSError as exc:
        raise sqlite3.DatabaseError("file_unavailable") from exc
    if (not stat.S_ISDIR(parent_metadata.st_mode)
            or stat.S_ISLNK(parent_metadata.st_mode)
            or stat.S_IMODE(parent_metadata.st_mode) & 0o077):
        raise sqlite3.DatabaseError("file_unavailable")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise sqlite3.DatabaseError("file_unavailable") from exc
    if (not stat.S_ISREG(metadata.st_mode)
            or (nonempty and metadata.st_size == 0)
            or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise sqlite3.DatabaseError("file_unavailable")
    return path.resolve()


def _database_path(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    raw = args.db if args.db is not None else env.get(DB_ENV)
    if raw is None:
        raise LifecycleInputError("database_missing")
    return _private_regular_file(Path(raw).expanduser())


def _safe_new_file(path: Path, source: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise LifecycleInputError("rollback_path_invalid")
    try:
        parent_meta = path.parent.lstat()
    except OSError as exc:
        raise LifecycleInputError("rollback_path_invalid") from exc
    if (not stat.S_ISDIR(parent_meta.st_mode)
            or stat.S_ISLNK(parent_meta.st_mode)
            or stat.S_IMODE(parent_meta.st_mode) & 0o077):
        raise LifecycleInputError("rollback_path_invalid")
    if not _storage_parent_safe(path.parent):
        raise LifecycleInputError("rollback_path_invalid")
    resolved_parent = path.parent.resolve()
    candidate = resolved_parent / path.name
    if candidate == source or candidate.exists() or candidate.is_symlink():
        raise LifecycleInputError("rollback_path_invalid")
    return candidate


def _integrity(path: Path) -> None:
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("PRAGMA integrity_check").fetchall()
    if rows != [("ok",)]:
        raise sqlite3.DatabaseError("database_integrity_failed")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _meta_state(db: sqlite3.Connection) -> tuple[str | None, tuple[str, int] | None]:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_verification_operator_meta'"
    ).fetchone()
    if table is None:
        raise sqlite3.DatabaseError("operator_schema_missing")
    row = db.execute(
        "SELECT secret_fingerprint FROM account_verification_operator_meta WHERE singleton=1"
    ).fetchone()
    fingerprint = None if row is None else row[0]
    if fingerprint is not None and (not isinstance(fingerprint, str)
                                    or not FINGERPRINT.fullmatch(fingerprint)):
        raise sqlite3.DatabaseError("operator_binding_invalid")
    lifecycle_table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_verification_operator_lifecycle'"
    ).fetchone()
    lifecycle = None
    if lifecycle_table is not None:
        life = db.execute(
            "SELECT database_id,generation FROM account_verification_operator_lifecycle WHERE singleton=1"
        ).fetchone()
        if life is not None:
            database_id, generation = life
            if (not isinstance(database_id, str) or not DATABASE_ID.fullmatch(database_id)
                    or type(generation) is not int or generation < 1):
                raise sqlite3.DatabaseError("operator_lifecycle_invalid")
            lifecycle = (database_id, generation)
    return fingerprint, lifecycle


def _ensure_lifecycle_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_operator_lifecycle (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        database_id TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK(generation>=1),
        last_change_hash TEXT NOT NULL,
        updated REAL NOT NULL)""")


def _verified_state(path: Path) -> tuple[str | None, tuple[str, int] | None]:
    _integrity(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        return _meta_state(db)


def _create_rollback(source: Path, destination: Path, *,
                     legacy_database_id: str | None = None,
                     legacy_change_hash: str | None = None) -> dict[str, object]:
    target = _safe_new_file(destination, source)
    manifest_path = target.with_name(target.name + ".capability.json")
    if manifest_path.exists() or manifest_path.is_symlink():
        raise LifecycleInputError("rollback_path_invalid")
    try:
        # O_EXCL makes the destination reservation race-safe.  A crash can leave
        # a partial database without a manifest; recovery rejects that pair.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        with sqlite3.connect(source) as current, sqlite3.connect(target) as backup:
            current.backup(backup)
        if legacy_database_id is not None:
            if (not DATABASE_ID.fullmatch(legacy_database_id)
                    or not isinstance(legacy_change_hash, str)
                    or not FINGERPRINT.fullmatch(legacy_change_hash)):
                raise sqlite3.DatabaseError("legacy_lifecycle_invalid")
            with sqlite3.connect(target, timeout=5) as backup:
                backup.execute("BEGIN IMMEDIATE")
                _ensure_lifecycle_schema(backup)
                _stored, lifecycle = _meta_state(backup)
                if lifecycle is not None:
                    raise sqlite3.DatabaseError("legacy_lifecycle_conflict")
                backup.execute(
                    "INSERT INTO account_verification_operator_lifecycle VALUES(1,?,?,?,?)",
                    (legacy_database_id, 1, legacy_change_hash, time.time()),
                )
        os.chmod(target, 0o600)
        _integrity(target)
        backup_fd = os.open(target, os.O_RDONLY)
        try:
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        fingerprint, lifecycle = _verified_state(target)
        document = {
            "format": MANIFEST_FORMAT,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "database_sha256": _sha256_file(target),
            "size_bytes": target.stat().st_size,
            "binding": "bound" if fingerprint is not None else "unbound",
            "database_id": lifecycle[0] if lifecycle else None,
            "generation": lifecycle[1] if lifecycle else 0,
        }
        mfd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(mfd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return document
    except Exception:
        for candidate in (target, manifest_path):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        raise


def _load_rollback(path: Path) -> tuple[Path, dict[str, object], str, tuple[str, int]]:
    backup = _private_regular_file(path.expanduser())
    manifest_path = _private_regular_file(
        backup.with_name(backup.name + ".capability.json")
    )
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise sqlite3.DatabaseError("rollback_manifest_invalid") from exc
    if (not isinstance(document, dict) or document.get("format") != MANIFEST_FORMAT
            or set(document) != {"format", "created_at_utc", "database_sha256",
                                 "size_bytes", "binding", "database_id", "generation"}
            or document.get("binding") != "bound"
            or not isinstance(document.get("database_sha256"), str)
            or not FINGERPRINT.fullmatch(document["database_sha256"])
            or document.get("size_bytes") != backup.stat().st_size
            or not isinstance(document.get("database_id"), str)
            or not DATABASE_ID.fullmatch(document["database_id"])
            or type(document.get("generation")) is not int
            or document["generation"] < 1
            or not hmac.compare_digest(document["database_sha256"], _sha256_file(backup))):
        raise sqlite3.DatabaseError("rollback_manifest_invalid")
    fingerprint, lifecycle = _verified_state(backup)
    if (fingerprint is None or lifecycle is None
            or lifecycle != (document["database_id"], document["generation"])):
        raise sqlite3.DatabaseError("rollback_manifest_invalid")
    return backup, document, fingerprint, lifecycle


def _fingerprint(secret: bytes) -> str:
    return hashlib.sha256(secret).hexdigest()


def _change_hash(change_id: str) -> str:
    return hashlib.sha256(change_id.encode("ascii")).hexdigest()


def _provision(path: Path, new_secret: bytes, intent: dict[str, object]) -> int:
    if intent["expected_generation"] != 0:
        raise LifecycleConflict("generation_conflict")
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        fingerprint, lifecycle = _meta_state(db)
        if fingerprint is not None or lifecycle is not None:
            raise LifecycleConflict("already_provisioned")
        _ensure_lifecycle_schema(db)
        now = time.time()
        db.execute(
            "INSERT INTO account_verification_operator_meta(singleton,secret_fingerprint) VALUES(1,?)",
            (_fingerprint(new_secret),),
        )
        db.execute(
            "INSERT INTO account_verification_operator_lifecycle VALUES(1,?,?,?,?)",
            (secrets.token_hex(16), 1, _change_hash(intent["change_id"]), now),
        )
        stored, lifecycle = _meta_state(db)
        if not hmac.compare_digest(stored, _fingerprint(new_secret)) or lifecycle[1] != 1:
            raise sqlite3.DatabaseError("provision_verification_failed")
    return 1


def _rotate(path: Path, current_secret: bytes, new_secret: bytes,
            intent: dict[str, object], *, legacy_database_id: str | None = None) -> int:
    if hmac.compare_digest(current_secret, new_secret):
        raise LifecycleInputError("secret_reuse")
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        stored, lifecycle = _meta_state(db)
        if stored is None:
            raise LifecycleConflict("not_provisioned")
        if not hmac.compare_digest(stored, _fingerprint(current_secret)):
            raise LifecycleConflict("authorization_failed")
        _ensure_lifecycle_schema(db)
        if lifecycle is None:
            if intent["expected_generation"] != 1:
                raise LifecycleConflict("generation_conflict")
            if legacy_database_id is None or not DATABASE_ID.fullmatch(legacy_database_id):
                raise LifecycleConflict("lifecycle_unavailable")
            database_id, generation = legacy_database_id, 1
            db.execute(
                "INSERT INTO account_verification_operator_lifecycle VALUES(1,?,?,?,?)",
                (database_id, generation, _change_hash(intent["change_id"]), time.time()),
            )
        else:
            database_id, generation = lifecycle
        if intent["expected_generation"] != generation:
            raise LifecycleConflict("generation_conflict")
        new_generation = generation + 1
        updated = db.execute(
            """UPDATE account_verification_operator_meta SET secret_fingerprint=?
               WHERE singleton=1 AND secret_fingerprint=?""",
            (_fingerprint(new_secret), stored),
        ).rowcount
        db.execute(
            """UPDATE account_verification_operator_lifecycle
               SET generation=?,last_change_hash=?,updated=?
               WHERE singleton=1 AND database_id=? AND generation=?""",
            (new_generation, _change_hash(intent["change_id"]), time.time(),
             database_id, generation),
        )
        verified, verified_lifecycle = _meta_state(db)
        if (updated != 1 or not hmac.compare_digest(verified, _fingerprint(new_secret))
                or verified_lifecycle != (database_id, new_generation)):
            raise sqlite3.DatabaseError("rotation_verification_failed")
    return new_generation


def _recover(path: Path, source: Path, recovery_secret: bytes,
             intent: dict[str, object]) -> int:
    _backup, _manifest, source_fingerprint, source_lifecycle = _load_rollback(source)
    if not hmac.compare_digest(source_fingerprint, _fingerprint(recovery_secret)):
        raise LifecycleConflict("authorization_failed")
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        stored, lifecycle = _meta_state(db)
        if stored is None or lifecycle is None:
            raise LifecycleConflict("recovery_unavailable")
        database_id, generation = lifecycle
        if intent["expected_generation"] != generation:
            raise LifecycleConflict("generation_conflict")
        if source_lifecycle[0] != database_id or source_lifecycle[1] >= generation:
            raise LifecycleConflict("rollback_mismatch")
        if hmac.compare_digest(stored, source_fingerprint):
            raise LifecycleConflict("secret_reuse")
        new_generation = generation + 1
        db.execute(
            "UPDATE account_verification_operator_meta SET secret_fingerprint=? WHERE singleton=1",
            (source_fingerprint,),
        )
        db.execute(
            """UPDATE account_verification_operator_lifecycle
               SET generation=?,last_change_hash=?,updated=?
               WHERE singleton=1 AND database_id=? AND generation=?""",
            (new_generation, _change_hash(intent["change_id"]), time.time(),
             database_id, generation),
        )
        verified, verified_lifecycle = _meta_state(db)
        if (not hmac.compare_digest(verified, source_fingerprint)
                or verified_lifecycle != (database_id, new_generation)):
            raise sqlite3.DatabaseError("recovery_verification_failed")
    return new_generation


def _help_document() -> dict[str, object]:
    return {
        "ok": True,
        "operation": "help",
        "commands": ["provision", "rotate", "recover"],
        "secret_sources": [CURRENT_SECRET_ENV, NEW_SECRET_ENV,
                           "--current-secret-fd", "--new-secret-fd"],
        "intent_source": "--intent-fd",
        "rollback_required": True,
    }


def _execute(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, object]:
    if args.help:
        return _help_document()
    if args.command is None or args.intent_fd is None or args.rollback_db is None:
        raise LifecycleInputError("required_input_missing")
    path = _database_path(args, env)
    intent = _intent(args.intent_fd, args.command)
    current_required = args.command == "rotate"
    current_secret = _secret(
        args.current_secret_fd, CURRENT_SECRET_ENV, env, required=current_required,
    )
    new_secret = _secret(args.new_secret_fd, NEW_SECRET_ENV, env, required=True)

    # Validate authorization and expected state before writing the rollback copy.
    stored, lifecycle = _verified_state(path)
    if args.command == "provision":
        if stored is not None or lifecycle is not None:
            raise LifecycleConflict("already_provisioned")
        if intent["expected_generation"] != 0:
            raise LifecycleConflict("generation_conflict")
    elif args.command == "rotate":
        if stored is None:
            raise LifecycleConflict("not_provisioned")
        if not hmac.compare_digest(stored, _fingerprint(current_secret)):
            raise LifecycleConflict("authorization_failed")
        observed_generation = lifecycle[1] if lifecycle else 1
        if intent["expected_generation"] != observed_generation:
            raise LifecycleConflict("generation_conflict")
    else:
        if stored is None or lifecycle is None:
            raise LifecycleConflict("recovery_unavailable")
        if intent["expected_generation"] != lifecycle[1]:
            raise LifecycleConflict("generation_conflict")
        _source, _manifest, source_fingerprint, source_lifecycle = _load_rollback(
            args.source_backup
        )
        if not hmac.compare_digest(source_fingerprint, _fingerprint(new_secret)):
            raise LifecycleConflict("authorization_failed")
        if source_lifecycle[0] != lifecycle[0] or source_lifecycle[1] >= lifecycle[1]:
            raise LifecycleConflict("rollback_mismatch")
        if stored is not None and hmac.compare_digest(stored, source_fingerprint):
            raise LifecycleConflict("secret_reuse")

    legacy_database_id = None
    if args.command == "rotate" and lifecycle is None:
        legacy_database_id = secrets.token_hex(16)
    rollback = _create_rollback(
        path, args.rollback_db,
        legacy_database_id=legacy_database_id,
        legacy_change_hash=_change_hash(intent["change_id"])
        if legacy_database_id is not None else None,
    )
    if args.command == "provision":
        generation = _provision(path, new_secret, intent)
    elif args.command == "rotate":
        generation = _rotate(
            path, current_secret, new_secret, intent,
            legacy_database_id=legacy_database_id,
        )
    else:
        generation = _recover(path, args.source_backup, new_secret, intent)
    verified, verified_lifecycle = _verified_state(path)
    if (verified is None or verified_lifecycle is None
            or verified_lifecycle[1] != generation
            or not hmac.compare_digest(verified, _fingerprint(new_secret))):
        raise sqlite3.DatabaseError("final_verification_failed")
    return {
        "ok": True,
        "operation": args.command,
        "generation": generation,
        "binding_verified": True,
        "rollback_created": True,
        "rollback_verified": rollback["database_sha256"] is not None,
        "rollback_binding": rollback["binding"],
    }


def _error_document(exc: Exception) -> tuple[int, dict[str, object]]:
    if isinstance(exc, LifecycleInputError):
        return 2, {"ok": False, "error": {"code": "invalid_input"}}
    if isinstance(exc, LifecycleConflict):
        allowed = {
            "already_provisioned", "not_provisioned", "authorization_failed",
            "generation_conflict", "rollback_mismatch", "recovery_unavailable",
            "secret_reuse", "lifecycle_unavailable",
        }
        code = str(exc)
        return 3, {"ok": False, "error": {
            "code": code if code in allowed else "lifecycle_conflict",
        }}
    if isinstance(exc, (sqlite3.Error, OSError)):
        return 4, {"ok": False, "error": {"code": "storage_unavailable"}}
    return 6, {"ok": False, "error": {"code": "internal_failure"}}


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None,
         stdout: TextIO = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        document = _execute(args, os.environ if env is None else env)
        status = 0
    except Exception as exc:
        status, document = _error_document(exc)
    json.dump(document, stdout, sort_keys=True, separators=(",", ":"))
    stdout.write("\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
