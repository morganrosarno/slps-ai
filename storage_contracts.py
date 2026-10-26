"""Versioned SQLite migrations and persistence boundaries for local adapters.

The protocols define the application-facing surface.  They do not claim that
SQLite or a local filesystem is durable enough for real customer data.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any, Callable, Iterable, Protocol, runtime_checkable


MigrationAction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class SQLiteMigration:
    version: int
    name: str
    checksum: str
    apply: MigrationAction


def apply_sqlite_migrations(
    db: sqlite3.Connection, namespace: str, migrations: Iterable[SQLiteMigration]
) -> tuple[int, ...]:
    """Apply ordered migrations, one immediate transaction per version.

    Existing schemas are reconciled by idempotent migration functions before a
    version is recorded in the same transaction.  Any failure rolls back both
    schema/data changes and that version record.
    """
    items = tuple(migrations)
    versions = tuple(item.version for item in items)
    if (not namespace or any(version < 1 for version in versions)
            or versions != tuple(sorted(set(versions)))):
        raise ValueError("invalid_migration_set")
    if db.in_transaction:
        raise sqlite3.OperationalError("migration_requires_idle_connection")
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   namespace TEXT NOT NULL,
                   version INTEGER NOT NULL,
                   name TEXT NOT NULL,
                   checksum TEXT NOT NULL,
                   applied_at REAL NOT NULL,
                   PRIMARY KEY(namespace, version)
               )"""
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    applied: list[int] = []
    known = set(versions)
    for migration in items:
        try:
            db.execute("BEGIN IMMEDIATE")
            recorded = {
                int(row[0]): (str(row[1]), str(row[2]))
                for row in db.execute(
                    "SELECT version,name,checksum FROM schema_migrations WHERE namespace=?",
                    (namespace,),
                )
            }
            if any(version not in known for version in recorded):
                raise sqlite3.DatabaseError("unknown_schema_version")
            existing = recorded.get(migration.version)
            if existing is not None:
                if existing != (migration.name, migration.checksum):
                    raise sqlite3.DatabaseError("migration_checksum_mismatch")
                db.commit()
                continue
            migration.apply(db)
            db.execute(
                """INSERT INTO schema_migrations
                   (namespace,version,name,checksum,applied_at) VALUES (?,?,?,?,?)""",
                (namespace, migration.version, migration.name, migration.checksum, time.time()),
            )
            db.commit()
            applied.append(migration.version)
        except Exception:
            db.rollback()
            raise
    return tuple(applied)


def migration_versions(db: sqlite3.Connection, namespace: str) -> tuple[int, ...]:
    try:
        return tuple(
            int(row[0]) for row in db.execute(
                "SELECT version FROM schema_migrations WHERE namespace=? ORDER BY version",
                (namespace,),
            )
        )
    except sqlite3.OperationalError:
        return ()


@runtime_checkable
class AccountIdentityPort(Protocol):
    durable: bool
    def register(self, **values: Any) -> dict[str, Any]: ...
    def get_user(self, user_id: str) -> dict[str, Any] | None: ...
    def authenticate(self, email: str, password: str) -> dict[str, Any] | None: ...
    def consultation_status(self, company_id: str, user_id: str) -> dict[str, Any]: ...


@runtime_checkable
class BillingSandboxPort(Protocol):
    durable: bool
    def create_checkout_simulation(self, company_id: str, user_id: str,
                                   plan_code: str, billing_cycle: str, **values: Any) -> dict[str, Any]: ...
    def get_checkout_simulation(self, checkout_id: str, company_id: str,
                                user_id: str, **values: Any) -> dict[str, Any] | None: ...
    def transition_checkout_simulation(self, checkout_id: str, company_id: str,
                                       user_id: str, target: str, **values: Any) -> dict[str, Any]: ...


@runtime_checkable
class BlobStore(Protocol):
    durable: bool
    root: Path
    def resolve(self, relative_path: str | Path) -> Path: ...
    def make_dir(self, relative_path: str | Path) -> Path: ...
    def write(self, relative_path: str | Path, data: bytes) -> Path: ...
    def replace(self, source: str | Path, target: str | Path) -> None: ...
    def remove_tree(self, relative_path: str | Path) -> None: ...


@runtime_checkable
class CaseArchivePort(Protocol):
    durable: bool
    blob_store: BlobStore
    def create(self, tenant_id: str, owner_id: str, context: str,
               analysis: dict[str, Any], image_sha256: str | None,
               max_cases: int, assets: list[dict[str, Any]] | None = None) -> tuple[str | None, str | None]: ...
    def list(self, tenant_id: str, owner_id: str) -> list[dict[str, Any]]: ...
    def get(self, case_id: str, tenant_id: str, owner_id: str) -> dict[str, Any] | None: ...
    def delete(self, case_id: str, tenant_id: str, owner_id: str) -> bool: ...
    def storage_status(self, tenant_id: str) -> dict[str, Any]: ...


class LocalBlobStore:
    """Private local blob adapter.  It is deliberately not durability-certified."""
    durable = False

    def __init__(self, root: str | Path):
        # All paths returned by this adapter share one absolute base.  This is
        # important when callers configure a relative media root.
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for relative in (Path(".staging"), Path(".trash")):
            self.make_dir(relative)

    def resolve(self, relative_path: str | Path) -> Path:
        target = (self.root / Path(relative_path)).resolve()
        root = self.root.resolve()
        if target == root or root not in target.parents:
            raise OSError("Unsafe blob path")
        return target

    def make_dir(self, relative_path: str | Path) -> Path:
        target = self.resolve(relative_path)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            target.chmod(0o700)
        except OSError:
            pass
        return target

    def write(self, relative_path: str | Path, data: bytes) -> Path:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Blob data must be bytes")
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(bytes(data))
            stream.flush()
            os.fsync(stream.fileno())
        return target

    def replace(self, source: str | Path, target: str | Path) -> None:
        destination = self.resolve(target)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(self.resolve(source), destination)

    def remove_tree(self, relative_path: str | Path) -> None:
        shutil.rmtree(self.resolve(relative_path), ignore_errors=True)


def require_durable_storage(data_mode: str, *adapter_types: type[Any]) -> None:
    """Fail before adapter construction when real data would use local stores."""
    if data_mode not in {"synthetic", "real"}:
        raise ValueError("SLPS_DATA_MODE must be synthetic or real")
    if data_mode == "real" and not adapter_types:
        raise RuntimeError("real_data_requires_durable_storage")
    if data_mode == "real" and any(not bool(getattr(adapter, "durable", False))
                                    for adapter in adapter_types):
        raise RuntimeError("real_data_requires_durable_storage")
