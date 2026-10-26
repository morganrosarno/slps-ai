import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from accounts import ACCOUNT_MIGRATIONS, AccountStore
from server import CASE_MIGRATIONS, LIMIT_MIGRATIONS, CaseStore, LimitStore
import server
from scripts import preflight
from storage_contracts import (
    AccountIdentityPort, BillingSandboxPort, BlobStore, CaseArchivePort,
    LocalBlobStore, SQLiteMigration, apply_sqlite_migrations,
)


PASSWORD = "a-long-local-test-passphrase"


def _account_adapter(tmp_path):
    return AccountStore(tmp_path / "accounts.sqlite3")


def _case_adapter(tmp_path):
    return CaseStore(tmp_path / "cases.sqlite3", tmp_path / "media", 1024 * 1024)


def _limit_adapter(tmp_path):
    return LimitStore(tmp_path / "limits.sqlite3")


@pytest.mark.parametrize(
    ("factory", "namespace", "versions"),
    [
        (_account_adapter, "accounts", (1, 2, 3)),
        (_case_adapter, "cases", (1, 2)),
        (_limit_adapter, "limits", (1, 2, 3)),
    ],
)
def test_sqlite_adapters_share_versioned_idempotent_migration_contract(
    tmp_path, factory, namespace, versions
):
    adapter = factory(tmp_path)
    assert adapter.schema_versions() == versions
    with adapter.connect() as db:
        rows = db.execute(
            """SELECT version,name,checksum FROM schema_migrations
               WHERE namespace=? ORDER BY version""",
            (namespace,),
        ).fetchall()
    assert tuple(row[0] for row in rows) == versions
    assert all(row[1] and len(row[2]) == 64 for row in rows)
    reopened = factory(tmp_path)
    assert reopened.schema_versions() == versions
    with reopened.connect() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE namespace=?", (namespace,)
        ).fetchone()[0] == len(versions)


@pytest.mark.parametrize(
    ("namespace", "migrations"),
    [
        ("accounts", ACCOUNT_MIGRATIONS),
        ("cases", CASE_MIGRATIONS),
        ("limits", LIMIT_MIGRATIONS),
    ],
)
def test_migrations_do_not_depend_on_sqlite_row_factory(namespace, migrations):
    db = sqlite3.connect(":memory:")
    assert db.row_factory is None
    apply_sqlite_migrations(db, namespace, migrations)
    assert tuple(row[0] for row in db.execute(
        "SELECT version FROM schema_migrations WHERE namespace=? ORDER BY version",
        (namespace,),
    )) == tuple(migration.version for migration in migrations)
    db.close()


def test_account_and_case_adapters_implement_explicit_ports(tmp_path):
    accounts = _account_adapter(tmp_path)
    cases = _case_adapter(tmp_path)
    assert isinstance(accounts, AccountIdentityPort)
    assert isinstance(accounts, BillingSandboxPort)
    assert isinstance(cases, CaseArchivePort)
    assert isinstance(cases.blob_store, BlobStore)
    assert accounts.durable is False
    assert cases.durable is False
    assert cases.blob_store.durable is False


def test_accounts_mode_exposes_explicit_identity_and_billing_ports(tmp_path):
    app = server.create_app({
        "TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "accounts",
        "SECRET_KEY": "a-session-secret-longer-than-32-characters",
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "RATE_DB_PATH": str(tmp_path / "rate.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
    })
    store = app.extensions["account_store"]
    assert app.extensions["account_identity_port"] is store
    assert app.extensions["billing_sandbox_port"] is store
    assert isinstance(app.extensions["account_identity_port"], AccountIdentityPort)
    assert isinstance(app.extensions["billing_sandbox_port"], BillingSandboxPort)


def test_local_blob_contract_is_private_exclusive_and_confined(tmp_path):
    blobs = LocalBlobStore(tmp_path / "blobs")
    target = blobs.write(Path("cases") / "case-1" / "asset.bin", b"synthetic")
    assert target.read_bytes() == b"synthetic"
    assert target.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        blobs.write(Path("cases") / "case-1" / "asset.bin", b"replacement")
    with pytest.raises(OSError):
        blobs.resolve("../outside")
    blobs.make_dir(Path(".staging") / "move")
    blobs.write(Path(".staging") / "move" / "asset.bin", b"move")
    blobs.replace(Path(".staging") / "move", Path("cases") / "case-2")
    assert blobs.resolve(Path("cases") / "case-2" / "asset.bin").read_bytes() == b"move"
    blobs.remove_tree(Path("cases") / "case-2")
    assert not blobs.resolve(Path("cases") / "case-2").exists()


def test_relative_history_root_can_create_read_and_delete_asset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = CaseStore("state/cases.sqlite3", "relative-history", 1024 * 1024)
    assert store.media_root == (tmp_path / "relative-history").resolve()
    case_id, error = store.create(
        "tenant-a", "owner-a", "synthetic context", {"findings": []}, "f" * 64, 10,
        assets=[{
            "role": "original", "filename": "synthetic.jpg",
            "media_type": "image/jpeg", "data": b"synthetic-image",
        }],
    )
    assert error is None
    case = store.get(case_id, "tenant-a", "owner-a")
    assert case is not None and len(case["assets"]) == 1
    asset = store.asset(case_id, case["assets"][0]["id"], "tenant-a", "owner-a")
    assert asset["path"].read_bytes() == b"synthetic-image"
    assert store.delete(case_id, "tenant-a", "owner-a") is True
    assert store.get(case_id, "tenant-a", "owner-a") is None
    assert not (store.media_root / "cases" / case_id).exists()


def test_migration_failure_rolls_back_schema_and_version_together(tmp_path):
    path = tmp_path / "failure.sqlite3"
    db = sqlite3.connect(path)

    def broken(connection):
        connection.execute("CREATE TABLE partial_change(id INTEGER)")
        raise RuntimeError("synthetic migration failure")

    migration = SQLiteMigration(
        1, "broken_v1", hashlib.sha256(b"broken-v1").hexdigest(), broken
    )
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        apply_sqlite_migrations(db, "failure", (migration,))
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "partial_change" not in tables
    assert db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE namespace='failure'"
    ).fetchone()[0] == 0
    db.close()


def test_migrations_reject_checksum_drift_and_future_versions(tmp_path):
    path = tmp_path / "identity.sqlite3"
    db = sqlite3.connect(path)
    first = SQLiteMigration(
        1, "stable_v1", hashlib.sha256(b"stable-v1").hexdigest(),
        lambda connection: connection.execute("CREATE TABLE stable(id INTEGER)"),
    )
    apply_sqlite_migrations(db, "identity", (first,))
    changed = SQLiteMigration(1, "stable_v1", hashlib.sha256(b"changed").hexdigest(), first.apply)
    with pytest.raises(sqlite3.DatabaseError, match="migration_checksum_mismatch"):
        apply_sqlite_migrations(db, "identity", (changed,))
    db.execute(
        """INSERT INTO schema_migrations(namespace,version,name,checksum,applied_at)
           VALUES ('identity',99,'future','future',0)"""
    )
    db.commit()
    with pytest.raises(sqlite3.DatabaseError, match="unknown_schema_version"):
        apply_sqlite_migrations(db, "identity", (first,))
    db.close()


def test_historical_account_and_billing_database_bootstraps_without_data_loss(tmp_path):
    path = tmp_path / "historical.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE account_companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, identifier TEXT NOT NULL,
            identity_key TEXT NOT NULL UNIQUE, verified INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL);
        CREATE TABLE account_users (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL, locale TEXT NOT NULL,
            email_verified INTEGER NOT NULL DEFAULT 0,
            membership_verified INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1,
            created REAL NOT NULL);
        CREATE TABLE consultation_requests (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
            case_id TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
            period_started REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            used_at REAL, cancelled_at REAL);
        CREATE TABLE billing_checkout_intents (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
            catalog_revision TEXT NOT NULL, plan_code TEXT NOT NULL,
            billing_cycle TEXT NOT NULL, idempotency_key_hash TEXT NOT NULL,
            payload_hash TEXT NOT NULL, snapshot_json TEXT NOT NULL,
            status TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
            confirmed REAL, cancelled REAL,
            UNIQUE(company_id,user_id,idempotency_key_hash));
        CREATE TABLE billing_checkout_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
            company_id TEXT NOT NULL, user_id TEXT NOT NULL, event TEXT NOT NULL,
            created REAL NOT NULL);
    """)
    db.execute(
        "INSERT INTO account_companies VALUES ('c1','Synthetic AG','CHE1','id:CHE1',1,1)"
    )
    db.execute(
        """INSERT INTO account_users VALUES
           ('u1','c1','owner@example.test','hash','Owner','it',1,1,1,1,1)"""
    )
    snapshot = json.dumps({"plan_code": "tier_team_v1"})
    db.execute(
        """INSERT INTO billing_checkout_intents VALUES
           ('b1','c1','u1','draft-old','tier_team_v1','monthly','key','payload',?,
            'draft',1,9999999999,NULL,NULL)""",
        (snapshot,),
    )
    db.commit(); db.close()

    store = AccountStore(path)
    assert store.schema_versions() == (1, 2, 3)
    with store.connect() as migrated:
        assert migrated.execute("SELECT name FROM account_companies WHERE id='c1'").fetchone()[0] == "Synthetic AG"
        row = migrated.execute("SELECT snapshot_json,expired FROM billing_checkout_intents WHERE id='b1'").fetchone()
        assert row[0] == snapshot and row[1] is None
        legacy = migrated.execute("PRAGMA table_info(consultation_requests)").fetchall()
        assert "idempotency_key" in {column[1] for column in legacy}


def test_historical_limit_database_bootstraps_without_data_loss(tmp_path):
    path = tmp_path / "historical-limits.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE events (kind TEXT, scope TEXT, created REAL);
        CREATE INDEX events_lookup ON events(kind, scope, created);
        CREATE TABLE leases (name TEXT PRIMARY KEY, token TEXT, expires REAL);
        CREATE TABLE trial_usage (scope TEXT PRIMARY KEY, used INTEGER NOT NULL);
        CREATE TABLE trial_clarifications (scope TEXT PRIMARY KEY, used INTEGER NOT NULL);
        INSERT INTO events VALUES ('analysis','synthetic-owner',1);
        INSERT INTO leases VALUES ('analysis','synthetic-token',9999999999);
        INSERT INTO trial_usage VALUES ('synthetic-owner',2);
        INSERT INTO trial_clarifications VALUES ('synthetic-owner',1);
    """)
    db.close()

    store = LimitStore(path)
    assert store.schema_versions() == (1, 2, 3)
    with store.connect() as migrated:
        assert migrated.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert migrated.execute("SELECT token FROM leases").fetchone()[0] == "synthetic-token"
        assert migrated.execute("SELECT used FROM trial_usage").fetchone()[0] == 2
        assert migrated.execute("SELECT used FROM trial_clarifications").fetchone()[0] == 1


def test_real_data_mode_fails_before_local_files_or_directories_are_created(tmp_path):
    account = tmp_path / "account" / "accounts.sqlite3"
    cases = tmp_path / "cases" / "cases.sqlite3"
    rate = tmp_path / "rate" / "rate.sqlite3"
    media = tmp_path / "media"
    with pytest.raises(RuntimeError, match="real_data_requires_durable_storage"):
        server.create_app({
            "TESTING": True, "DATA_MODE": "real", "AUTH_MODE": "accounts",
            "SECRET_KEY": "a-session-secret-longer-than-32-characters",
            "ACCOUNT_DB_PATH": str(account), "CASE_DB_PATH": str(cases),
            "RATE_DB_PATH": str(rate), "HISTORY_ROOT": str(media),
        })
    assert not account.exists() and not cases.exists() and not rate.exists()
    assert not media.exists()


def test_preflight_blocks_real_data_with_current_local_adapters(tmp_path):
    env = {
        "SLPS_DATA_MODE": "real", "SLPS_AUTH_MODE": "pilot",
        "SLPS_SESSION_SECRET": "s" * 32, "SLPS_PILOT_PASSWORD": "p" * 16,
        "OPENAI_API_KEY": "placeholder", "OPENAI_MODEL": "placeholder",
    }
    checks = {item.id: item for item in preflight.run_checks(env, tmp_path)}
    assert checks["data_mode"].status == "pass"
    assert checks["real_data_storage"].status == "blocker"
    assert preflight.report(list(checks.values()))["ready"] is False
