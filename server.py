"""Private SLPS pilot with opt-in company accounts and protected case history."""
from datetime import timedelta
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time
from urllib.parse import urlsplit
import warnings

from flask import Flask, Request, g, jsonify, redirect, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from slps_ai import AnalysisError, analizza_immagine, is_analysis_configured
from accounts import (AccountConflict, AccountStore, BillingSandboxConflict,
                      ConsultationConflict, billing_catalog, normalize_email)
from media import MediaError, inspect_video, media_tools_available
from storage_contracts import (LocalBlobStore, SQLiteMigration,
                               apply_sqlite_migrations, migration_versions,
                               require_durable_storage)

MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_CONTEXT_CHARS = 8_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
IMAGE_MEDIA = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
VIDEO_MEDIA = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}
FORMAT_MEDIA = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_CASE_JSON_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_HISTORY_BYTES = 1024 * 1024 * 1024
HISTORY_WARNING_RATIO = 0.80
ASSET_ROLES = {"original", "normalized", "crop", "frame", "audio", "transcript", "derived"}


class CaseDeletionPending(RuntimeError):
    """A case is hidden, but server-side file removal still needs a retry."""


class MemoryUploadRequest(Request):
    """Prevent Werkzeug's default 500 KB spooling from writing photo bytes."""
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return io.BytesIO()


def _migrate_limit_events_v1(db):
    db.execute("CREATE TABLE IF NOT EXISTS events (kind TEXT, scope TEXT, created REAL)")
    db.execute("CREATE INDEX IF NOT EXISTS events_lookup ON events(kind,scope,created)")
    db.execute("CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, token TEXT, expires REAL)")


def _migrate_trial_usage_v1(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS trial_usage (scope TEXT PRIMARY KEY, used INTEGER NOT NULL)"
    )


def _migrate_trial_clarifications_v1(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS trial_clarifications (scope TEXT PRIMARY KEY, used INTEGER NOT NULL)"
    )


def _migrate_provider_attempts_v1(db):
    db.execute("CREATE TABLE IF NOT EXISTS provider_attempts (id INTEGER PRIMARY KEY CHECK(id=1), used INTEGER NOT NULL CHECK(used>=0))")
    db.execute("INSERT OR IGNORE INTO provider_attempts VALUES (1,0)")


LIMIT_MIGRATIONS = (
    SQLiteMigration(1, "limit_events_and_leases_v1", hashlib.sha256(b"limit-events-leases-v1-20261026").hexdigest(), _migrate_limit_events_v1),
    SQLiteMigration(2, "trial_usage_v1", hashlib.sha256(b"trial-usage-v1-20261026").hexdigest(), _migrate_trial_usage_v1),
    SQLiteMigration(3, "trial_clarifications_v1", hashlib.sha256(b"trial-clarifications-v1-20261026").hexdigest(), _migrate_trial_clarifications_v1),
    SQLiteMigration(4, "provider_attempts_v1", hashlib.sha256(b"provider-attempts-v1-20261026").hexdigest(), _migrate_provider_attempts_v1),
)


class LimitStore:
    """Atomic limits shared by workers on one server, retained on restart."""
    durable = False

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            apply_sqlite_migrations(db, "limits", LIMIT_MIGRATIONS)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def schema_versions(self):
        with self.connect() as db:
            return migration_versions(db, "limits")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def login(self, scope, success, limit=5, window=900):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM events WHERE created < ?", (now - 86400,))
            count = db.execute("SELECT COUNT(*) FROM events WHERE kind='login' AND scope=? AND created>?", (scope, now - window)).fetchone()[0]
            if count >= limit:
                return False
            if success:
                db.execute("DELETE FROM events WHERE kind='login' AND scope=?", (scope,))
            else:
                db.execute("INSERT INTO events VALUES ('login', ?, ?)", (scope, now))
        return True

    def reserve_analysis(self, limit, lease_seconds):
        now = time.time()
        token = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM events WHERE created < ?", (now - 86400,))
            db.execute("DELETE FROM leases WHERE expires < ?", (now,))
            if db.execute("SELECT 1 FROM leases WHERE name='analysis'").fetchone():
                return None, "busy"
            count = db.execute("SELECT COUNT(*) FROM events WHERE kind='analysis' AND created>?", (now - 3600,)).fetchone()[0]
            if count >= limit:
                return None, "limit"
            db.execute("INSERT INTO events VALUES ('analysis', 'owner', ?)", (now,))
            db.execute("INSERT INTO leases VALUES ('analysis', ?, ?)", (token, now + lease_seconds))
        return token, None

    def release_analysis(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM leases WHERE name='analysis' AND token=?", (token,))

    def reserve_provider_request(self, limit):
        """Count dispatch attempts durably, without refunding uncertain failures.

        None is uncapped synthetic compatibility mode. A positive cap is required
        by private-staging preflight; this counts requests, never currency.
        """
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 10000):
            return False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT used FROM provider_attempts WHERE id=1").fetchone()[0]
            if limit is not None and used >= limit:
                return False
            db.execute("UPDATE provider_attempts SET used=used+1 WHERE id=1")
        return True

    def provider_request_count(self):
        with self.connect() as db:
            return int(db.execute("SELECT used FROM provider_attempts WHERE id=1").fetchone()[0])

    def reserve_media(self, scope, limit=6, window=900, lease_seconds=90):
        now = time.time()
        token = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM events WHERE created < ?", (now - 86400,))
            db.execute("DELETE FROM leases WHERE expires < ?", (now,))
            if db.execute("SELECT 1 FROM leases WHERE name='media-processing'").fetchone():
                return None, "busy"
            count = db.execute("SELECT COUNT(*) FROM events WHERE kind='media' AND scope=? AND created>?", (scope, now - window)).fetchone()[0]
            if count >= limit:
                return None, "limit"
            db.execute("INSERT INTO events VALUES ('media', ?, ?)", (scope, now))
            db.execute("INSERT INTO leases VALUES ('media-processing', ?, ?)", (token, now + lease_seconds))
        return token, None

    def release_media(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM leases WHERE name='media-processing' AND token=?", (token,))

    @staticmethod
    def _trial_lease_name(scope):
        return "trial:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def trial_status(self, scope, limit):
        with self.connect() as db:
            row = db.execute("SELECT used FROM trial_usage WHERE scope=?", (scope,)).fetchone()
        used = int(row[0]) if row else 0
        return used, max(0, limit - used)

    def reserve_trial(self, scope, limit, lease_seconds):
        """Reserve one total trial use without counting provider failures."""
        now = time.time()
        token = secrets.token_urlsafe(24)
        name = self._trial_lease_name(scope)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM leases WHERE expires < ?", (now,))
            if db.execute("SELECT 1 FROM leases WHERE name=?", (name,)).fetchone():
                return None, "busy"
            row = db.execute("SELECT used FROM trial_usage WHERE scope=?", (scope,)).fetchone()
            if (int(row[0]) if row else 0) >= limit:
                return None, "limit"
            db.execute("INSERT INTO leases VALUES (?, ?, ?)", (name, token, now + lease_seconds))
        return token, None

    def complete_trial(self, scope, token):
        name = self._trial_lease_name(scope)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute(
                "SELECT 1 FROM leases WHERE name=? AND token=?", (name, token)
            ).fetchone()
            if not lease:
                return False
            db.execute(
                """INSERT INTO trial_usage(scope, used) VALUES (?, 1)
                   ON CONFLICT(scope) DO UPDATE SET used=used+1""",
                (scope,),
            )
            db.execute("DELETE FROM leases WHERE name=? AND token=?", (name, token))
        return True

    def release_trial(self, scope, token):
        with self.connect() as db:
            db.execute(
                "DELETE FROM leases WHERE name=? AND token=?",
                (self._trial_lease_name(scope), token),
            )

    def clarification_status(self, scope):
        with self.connect() as db:
            row = db.execute(
                "SELECT used FROM trial_clarifications WHERE scope=?", (scope,)
            ).fetchone()
        used = int(row[0]) if row else 0
        return used, max(0, 1 - used)

    def reserve_clarification(self, scope, lease_seconds):
        now = time.time()
        token = secrets.token_urlsafe(24)
        name = "clarification:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM leases WHERE expires < ?", (now,))
            if db.execute("SELECT 1 FROM leases WHERE name=?", (name,)).fetchone():
                return None, "busy"
            row = db.execute(
                "SELECT used FROM trial_clarifications WHERE scope=?", (scope,)
            ).fetchone()
            if (int(row[0]) if row else 0) >= 1:
                return None, "limit"
            db.execute("INSERT INTO leases VALUES (?, ?, ?)", (name, token, now + lease_seconds))
        return token, None

    def complete_clarification(self, scope, token):
        name = "clarification:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM leases WHERE name=? AND token=?", (name, token)
            ).fetchone():
                return False
            db.execute(
                """INSERT INTO trial_clarifications(scope, used) VALUES (?, 1)
                   ON CONFLICT(scope) DO UPDATE SET used=used+1""",
                (scope,),
            )
            db.execute("DELETE FROM leases WHERE name=? AND token=?", (name, token))
        return True

    def release_clarification(self, scope, token):
        name = "clarification:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()
        with self.connect() as db:
            db.execute("DELETE FROM leases WHERE name=? AND token=?", (name, token))


def _migrate_cases_v1(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS cases (
               id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
               created REAL NOT NULL, context TEXT NOT NULL,
               analysis_json TEXT NOT NULL, image_sha256 TEXT)"""
    )
    # Positional access keeps migrations independent of connection row_factory.
    columns = {row[1] for row in db.execute("PRAGMA table_info(cases)")}
    if "image_sha256" not in columns:
        db.execute("ALTER TABLE cases ADD COLUMN image_sha256 TEXT")
    db.execute(
        "CREATE INDEX IF NOT EXISTS cases_owner_created ON cases(tenant_id,owner_id,created DESC)"
    )


def _migrate_case_assets_v1(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS case_assets (
               id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
               tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
               role TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
               byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
               sha256 TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
               created REAL NOT NULL,
               FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS assets_scope_case
           ON case_assets(tenant_id,owner_id,case_id,created)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS case_deletions (
               case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
               owner_id TEXT NOT NULL, trash_relative_path TEXT NOT NULL UNIQUE,
               requested REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
               last_error REAL,
               FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE)"""
    )


CASE_MIGRATIONS = (
    SQLiteMigration(1, "case_archive_v1", hashlib.sha256(b"case-archive-v1-20261026").hexdigest(), _migrate_cases_v1),
    SQLiteMigration(2, "case_assets_v1", hashlib.sha256(b"case-assets-v1-20261026").hexdigest(), _migrate_case_assets_v1),
)


class CaseStore:
    """Private case archive with file assets scoped by tenant and owner.

    Binary media never enters SQLite. It is stored under generated identifiers,
    while the database contains only metadata and report JSON. The application
    currently authorizes the same owner-private view used by the existing case
    routes; tenant scoping also makes cross-company access fail closed.
    """
    durable = False

    def __init__(self, path, media_root=None, max_history_bytes=DEFAULT_MAX_HISTORY_BYTES):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.media_root = Path(media_root or (self.path.parent / "history-media"))
        self.blob_store = LocalBlobStore(self.media_root)
        self.media_root = self.blob_store.root
        self.max_history_bytes = int(max_history_bytes)
        if self.max_history_bytes < 1:
            raise ValueError("History capacity must be positive")
        with self.connect() as db:
            apply_sqlite_migrations(db, "cases", CASE_MIGRATIONS)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def schema_versions(self):
        with self.connect() as db:
            return migration_versions(db, "cases")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _asset_payload(asset):
        if not isinstance(asset, dict) or asset.get("role") not in ASSET_ROLES:
            raise ValueError("Invalid history asset role")
        data = asset.get("data")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("History assets must contain bytes")
        media_type = str(asset.get("media_type", "application/octet-stream")).lower()[:128]
        if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media_type):
            raise ValueError("Invalid history asset media type")
        filename = Path(str(asset.get("filename") or "asset")).name[:255] or "asset"
        filename = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", filename).strip(" .") or "asset"
        return bytes(data), asset["role"], filename, media_type

    def _safe_path(self, relative_path):
        return self.blob_store.resolve(relative_path)

    def _write_private(self, path, data):
        return self.blob_store.write(Path(path).relative_to(self.media_root), data)

    def create(self, tenant_id, owner_id, context, analysis, image_sha256, max_cases, assets=None):
        encoded = json.dumps(analysis, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_CASE_JSON_BYTES:
            return None, "too_large"
        now = time.time()
        case_id = secrets.token_urlsafe(18)
        prepared = []
        total_new_bytes = 0
        stage_relative = Path(".staging") / secrets.token_urlsafe(18)
        stage = self.blob_store.make_dir(stage_relative)
        final_relative = Path("cases") / case_id
        final = self._safe_path(final_relative)
        try:
            for asset in assets or []:
                data, role, filename, media_type = self._asset_payload(asset)
                asset_id = secrets.token_urlsafe(18)
                stored_name = asset_id + ".bin"
                self._write_private(stage / stored_name, data)
                prepared.append({
                    "id": asset_id, "role": role, "filename": filename,
                    "media_type": media_type, "byte_size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "relative_path": str(final_relative / stored_name),
                })
                total_new_bytes += len(data)
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                count = db.execute(
                    "SELECT COUNT(*) FROM cases WHERE tenant_id=? AND owner_id=?",
                    (tenant_id, owner_id),
                ).fetchone()[0]
                if count >= max_cases:
                    return None, "limit"
                used = db.execute(
                    "SELECT COALESCE(SUM(byte_size), 0) FROM case_assets WHERE tenant_id=?",
                    (tenant_id,),
                ).fetchone()[0]
                if used + total_new_bytes > self.max_history_bytes:
                    return None, "storage_limit"
                db.execute(
                    """INSERT INTO cases
                       (id, tenant_id, owner_id, created, context, analysis_json, image_sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (case_id, tenant_id, owner_id, now, context, encoded, image_sha256),
                )
                for asset in prepared:
                    db.execute(
                        """INSERT INTO case_assets
                           (id, case_id, tenant_id, owner_id, role, filename, media_type,
                            byte_size, sha256, relative_path, created)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (asset["id"], case_id, tenant_id, owner_id, asset["role"],
                         asset["filename"], asset["media_type"], asset["byte_size"],
                         asset["sha256"], asset["relative_path"], now),
                    )
                self.blob_store.replace(stage_relative, final_relative)
        except Exception:
            self.blob_store.remove_tree(final_relative)
            raise
        finally:
            self.blob_store.remove_tree(stage_relative)
        return case_id, None

    @staticmethod
    def _public_asset(row):
        return {
            "id": row["id"], "role": row["role"], "filename": row["filename"],
            "media_type": row["media_type"], "byte_size": row["byte_size"],
            "sha256": row["sha256"],
        }

    def storage_status(self, tenant_id):
        with self.connect() as db:
            used = int(db.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM case_assets WHERE tenant_id=?",
                (tenant_id,),
            ).fetchone()[0])
        remaining = max(0, self.max_history_bytes - used)
        return {
            "used_bytes": used,
            "limit_bytes": self.max_history_bytes,
            "remaining_bytes": remaining,
            "warning": used >= int(self.max_history_bytes * HISTORY_WARNING_RATIO),
            "uploads_blocked": used >= self.max_history_bytes,
        }

    def list(self, tenant_id, owner_id):
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.id, c.created, c.context, c.analysis_json,
                          d.case_id AS deletion_pending
                   FROM cases c
                   LEFT JOIN case_deletions d ON d.case_id=c.id
                   WHERE c.tenant_id=? AND c.owner_id=?
                   ORDER BY c.created DESC""",
                (tenant_id, owner_id),
            ).fetchall()
        cases = []
        for row in rows:
            if row["deletion_pending"]:
                cases.append({
                    "id": row["id"],
                    "created_at": row["created"],
                    "context": "",
                    "summary": "Eliminazione da completare",
                    "deletion_pending": True,
                })
                continue
            analysis = json.loads(row["analysis_json"])
            meta = analysis.get("meta", {}) if isinstance(analysis, dict) else {}
            cases.append({
                "id": row["id"],
                "created_at": row["created"],
                "context": row["context"],
                "summary": analysis.get("summary", "") if isinstance(analysis, dict) else "",
                "kind": meta.get("case_kind", "risk_analysis") if isinstance(meta, dict) else "risk_analysis",
            })
        return cases

    def get(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            row = db.execute(
                """SELECT c.id, c.created, c.context, c.analysis_json
                   FROM cases c
                   WHERE c.id=? AND c.tenant_id=? AND c.owner_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM case_deletions d WHERE d.case_id=c.id
                     )""",
                (case_id, tenant_id, owner_id),
            ).fetchone()
            assets = db.execute(
                """SELECT id, role, filename, media_type, byte_size, sha256
                   FROM case_assets WHERE case_id=? AND tenant_id=? AND owner_id=?
                   ORDER BY created, id""",
                (case_id, tenant_id, owner_id),
            ).fetchall() if row else []
        if not row:
            return None
        public_assets = [self._public_asset(asset) for asset in assets]
        for asset in public_assets:
            asset["download_url"] = f"/api/cases/{case_id}/assets/{asset['id']}"
        return {
            "id": row["id"],
            "created_at": row["created"],
            "context": row["context"],
            "analysis": json.loads(row["analysis_json"]),
            "assets": public_assets,
            "report": {"stored": True, "media_type": "application/json"},
        }

    def asset(self, case_id, asset_id, tenant_id, owner_id):
        with self.connect() as db:
            row = db.execute(
                """SELECT a.id, a.role, a.filename, a.media_type, a.byte_size,
                          a.sha256, a.relative_path
                   FROM case_assets a
                   WHERE a.id=? AND a.case_id=? AND a.tenant_id=? AND a.owner_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM case_deletions d WHERE d.case_id=a.case_id
                     )""",
                (asset_id, case_id, tenant_id, owner_id),
            ).fetchone()
        if not row:
            return None
        relative = Path(row["relative_path"])
        if len(relative.parts) != 3 or relative.parts[:2] != ("cases", case_id):
            return None
        path = self._safe_path(row["relative_path"])
        if not path.is_file() or path.is_symlink():
            return None
        result = self._public_asset(row)
        result["path"] = path
        return result

    def image_sha256(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            row = db.execute(
                """SELECT c.image_sha256 FROM cases c
                   WHERE c.id=? AND c.tenant_id=? AND c.owner_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM case_deletions d WHERE d.case_id=c.id
                     )""",
                (case_id, tenant_id, owner_id),
            ).fetchone()
        return row["image_sha256"] if row else None

    def delete(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            authorized = db.execute(
                "SELECT 1 FROM cases WHERE id=? AND tenant_id=? AND owner_id=?",
                (case_id, tenant_id, owner_id),
            ).fetchone()
            if not authorized:
                return False
            deletion = db.execute(
                """SELECT trash_relative_path FROM case_deletions
                   WHERE case_id=? AND tenant_id=? AND owner_id=?""",
                (case_id, tenant_id, owner_id),
            ).fetchone()
            if deletion:
                trash_relative = deletion["trash_relative_path"]
            else:
                trash_relative = str(Path(".trash") / (case_id + "-" + secrets.token_urlsafe(12)))
                db.execute(
                    """INSERT INTO case_deletions
                       (case_id, tenant_id, owner_id, trash_relative_path, requested)
                       VALUES (?, ?, ?, ?, ?)""",
                    (case_id, tenant_id, owner_id, trash_relative, time.time()),
                )
        final = self._safe_path(Path("cases") / case_id)
        try:
            trash_path = Path(trash_relative)
            if (len(trash_path.parts) != 2 or trash_path.parts[0] != ".trash"
                    or not trash_path.name.startswith(case_id + "-")):
                raise OSError("Invalid deletion tombstone path")
            trash = self._safe_path(trash_path)
            if final.exists() and trash.exists():
                raise OSError("History deletion paths are inconsistent")
            if final.exists():
                self.blob_store.replace(Path("cases") / case_id, trash_path)
            if trash.exists():
                self.blob_store.remove_tree(trash_path)
        except OSError as exc:
            with self.connect() as db:
                db.execute(
                    """UPDATE case_deletions
                       SET attempts=attempts+1, last_error=?
                       WHERE case_id=? AND tenant_id=? AND owner_id=?""",
                    (time.time(), case_id, tenant_id, owner_id),
                )
            raise CaseDeletionPending("Case file deletion requires retry") from exc
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                cursor = db.execute(
                    "DELETE FROM cases WHERE id=? AND tenant_id=? AND owner_id=?",
                    (case_id, tenant_id, owner_id),
                )
                if cursor.rowcount != 1:
                    raise CaseDeletionPending("Case record deletion requires retry")
        except sqlite3.Error as exc:
            raise CaseDeletionPending("Case record deletion requires retry") from exc
        return True

    def delete_owner_history(self, tenant_id, owner_id):
        """Delete all owner-visible history for an approved account-closure job."""
        with self.connect() as db:
            case_ids = [row[0] for row in db.execute(
                "SELECT id FROM cases WHERE tenant_id=? AND owner_id=?",
                (tenant_id, owner_id),
            ).fetchall()]
        deleted = 0
        for case_id in case_ids:
            deleted += int(self.delete(case_id, tenant_id, owner_id))
        return deleted

    def backup(self, destination):
        """Create a verified local snapshot without placing media in the database."""
        destination = Path(destination)
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError("Backup destination is not empty")
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination.chmod(0o700)
        backup_db = destination / "cases.sqlite3"
        with sqlite3.connect(self.path) as source, sqlite3.connect(backup_db) as target:
            source.backup(target)
        media_backup = destination / "media"
        media_backup.mkdir(mode=0o700)
        with sqlite3.connect(backup_db) as db:
            rows = db.execute("SELECT relative_path, sha256, byte_size FROM case_assets").fetchall()
        files = []
        for relative_path, expected_hash, expected_size in rows:
            source = self._safe_path(relative_path)
            target = media_backup / relative_path
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target)
            target.chmod(0o600)
            data = target.read_bytes()
            if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_hash:
                raise OSError("Backup verification failed")
            files.append({"relative_path": relative_path, "sha256": expected_hash, "byte_size": expected_size})
        database_bytes = backup_db.read_bytes()
        manifest = {
            "format": 1,
            "created_at": time.time(),
            "database_sha256": hashlib.sha256(database_bytes).hexdigest(),
            "database_bytes": len(database_bytes),
            "files": files,
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        (destination / "manifest.json").chmod(0o600)
        backup_db.chmod(0o600)
        return manifest

    @classmethod
    def restore(cls, backup, target_db, target_media_root, max_history_bytes=DEFAULT_MAX_HISTORY_BYTES):
        """Verify and restore a snapshot into empty destinations."""
        backup, target_db, target_media_root = Path(backup), Path(target_db), Path(target_media_root)
        if target_db.exists() or (target_media_root.exists() and any(target_media_root.iterdir())):
            raise FileExistsError("Restore destination must be empty")
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
            raise ValueError("Unsupported backup manifest")
        database_source = backup / "cases.sqlite3"
        database_bytes = database_source.read_bytes()
        if (len(database_bytes) != manifest.get("database_bytes")
                or hashlib.sha256(database_bytes).hexdigest() != manifest.get("database_sha256")):
            raise OSError("Backup database checksum mismatch")
        with sqlite3.connect(database_source) as db:
            indexed = {
                (row[0], row[1], row[2])
                for row in db.execute("SELECT relative_path, sha256, byte_size FROM case_assets")
            }
        declared = {
            (item.get("relative_path"), item.get("sha256"), item.get("byte_size"))
            for item in manifest["files"] if isinstance(item, dict)
        }
        if indexed != declared or len(declared) != len(manifest["files"]):
            raise OSError("Backup manifest does not match database")
        for item in manifest["files"]:
            source = (backup / "media" / item["relative_path"]).resolve()
            media_backup = (backup / "media").resolve()
            if media_backup not in source.parents or not source.is_file() or source.is_symlink():
                raise OSError("Unsafe backup asset")
            data = source.read_bytes()
            if len(data) != item["byte_size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise OSError("Backup asset checksum mismatch")
        target_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(database_source, target_db)
        target_db.chmod(0o600)
        target_media_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for item in manifest["files"]:
            source = backup / "media" / item["relative_path"]
            target = target_media_root / item["relative_path"]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target)
            target.chmod(0o600)
        return cls(target_db, target_media_root, max_history_bytes)


def normalize_image(raw, expected_mime=None, max_bytes=MAX_FILE_BYTES):
    """Validate content, reject animation, orient and remove all metadata."""
    if not raw or len(raw) > max_bytes:
        raise ValueError("La foto deve avere una dimensione massima di 10 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ALLOWED_FORMATS:
                    raise ValueError("Usa una foto JPEG, PNG o WebP.")
                if expected_mime and FORMAT_MEDIA.get(image.format) != expected_mime:
                    raise ValueError("Il contenuto della foto non corrisponde al tipo e all’estensione del file.")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("La foto supera il limite di 25 megapixel.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Sono ammesse fotografie singole, non immagini animate.")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                oriented = ImageOps.exif_transpose(image)
                rgb = Image.new("RGB", oriented.size, "white")
                if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    rgb.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgb.paste(oriented.convert("RGB"))
                result = io.BytesIO()
                rgb.save(result, format="JPEG", quality=95, subsampling=0)
                if result.tell() > max_bytes:
                    raise ValueError("La foto elaborata supera 10 MB: riduci la risoluzione e riprova.")
                return result.getvalue(), "image/jpeg", rgb.width, rgb.height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("La foto supera il limite di dimensione consentito.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Il file non è una fotografia valida o risulta danneggiato.") from exc


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.request_class = MemoryUploadRequest
    app.config.update(
        SECRET_KEY=os.getenv("SLPS_SESSION_SECRET"),
        PILOT_PASSWORD=os.getenv("SLPS_PILOT_PASSWORD"),
        AUTH_MODE=os.getenv("SLPS_AUTH_MODE", "pilot"),
        PRIVATE_GATE_ENABLED=os.getenv("SLPS_PRIVATE_GATE_ENABLED", "false"),
        PRIVATE_GATE_PASSWORD=os.getenv("SLPS_PRIVATE_GATE_PASSWORD"),
        PROVIDER_REQUESTS_TOTAL=os.getenv("SLPS_PROVIDER_REQUESTS_TOTAL"),
        DATA_MODE=os.getenv("SLPS_DATA_MODE", "synthetic"),
        ACCOUNT_REGISTRATION_OPEN=os.getenv("SLPS_ACCOUNT_REGISTRATION_OPEN", "false").lower() == "true",
        BILLING_SANDBOX_ENABLED=os.getenv("SLPS_BILLING_SANDBOX_ENABLED", "false").lower() == "true",
        BILLING_SANDBOX_MAX_OPEN_INTENTS=int(os.getenv("SLPS_BILLING_SANDBOX_MAX_OPEN_INTENTS", "5")),
        ACCOUNT_DB_PATH=os.getenv("SLPS_ACCOUNT_DB_PATH", str(Path(app.instance_path) / "accounts.sqlite3")),
        SESSION_COOKIE_SECURE=os.getenv("SLPS_COOKIE_SECURE", "true").lower() != "false",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES + 128 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=8,
        MAX_IMAGE_BYTES=int(os.getenv("SLPS_MAX_IMAGE_BYTES", str(MAX_FILE_BYTES))),
        MAX_VIDEO_BYTES=int(os.getenv("SLPS_MAX_VIDEO_BYTES", str(DEFAULT_MAX_VIDEO_BYTES))),
        MAX_VIDEO_SECONDS=int(os.getenv("SLPS_MAX_VIDEO_SECONDS", "30")),
        RATE_DB_PATH=os.getenv("SLPS_RATE_DB_PATH", str(Path(app.instance_path) / "limits.sqlite3")),
        CASE_DB_PATH=os.getenv("SLPS_CASE_DB_PATH", str(Path(app.instance_path) / "cases.sqlite3")),
        HISTORY_ROOT=os.getenv("SLPS_HISTORY_ROOT"),
        MAX_HISTORY_BYTES_PER_TENANT=int(os.getenv(
            "SLPS_MAX_HISTORY_BYTES_PER_TENANT", str(DEFAULT_MAX_HISTORY_BYTES)
        )),
        PILOT_TENANT_ID=os.getenv("SLPS_PILOT_TENANT_ID", "pilot"),
        PILOT_OWNER_ID=os.getenv("SLPS_PILOT_OWNER_ID", "owner"),
        MAX_CASES_PER_OWNER=int(os.getenv("SLPS_MAX_CASES_PER_OWNER", "100")),
        ANALYSES_PER_HOUR=int(os.getenv("SLPS_ANALYSES_PER_HOUR", "10")),
        PILOT_PLAN=os.getenv("SLPS_PILOT_PLAN", "trial"),
        TRIAL_ANALYSES_TOTAL=int(os.getenv("SLPS_TRIAL_ANALYSES_TOTAL", "1")),
        ANALYSIS_LEASE_SECONDS=180,
    )
    if test_config:
        app.config.update(test_config)
    gate_setting = app.config["PRIVATE_GATE_ENABLED"]
    if isinstance(gate_setting, str) and gate_setting.strip().lower() in {"true", "false"}:
        gate_setting = gate_setting.strip().lower() == "true"
    if type(gate_setting) is not bool:
        raise ValueError("invalid_private_gate_setting")
    app.config["PRIVATE_GATE_ENABLED"] = gate_setting
    if not app.config.get("HISTORY_ROOT"):
        app.config["HISTORY_ROOT"] = str(Path(app.config["CASE_DB_PATH"]).parent / "history-media")
    # This check must happen before constructors create SQLite files or media
    # directories.  Current adapters are only certified for synthetic data.
    require_durable_storage(
        app.config["DATA_MODE"], AccountStore, LimitStore, CaseStore, LocalBlobStore
    )
    app.config["MAX_CONTENT_LENGTH"] = max(
        app.config["MAX_IMAGE_BYTES"], app.config["MAX_VIDEO_BYTES"]
    ) + 128 * 1024
    store = LimitStore(app.config["RATE_DB_PATH"])
    case_store = CaseStore(
        app.config["CASE_DB_PATH"],
        app.config["HISTORY_ROOT"],
        app.config["MAX_HISTORY_BYTES_PER_TENANT"],
    )
    app.extensions["limit_store"] = store
    app.extensions["case_store"] = case_store
    accounts = AccountStore(app.config["ACCOUNT_DB_PATH"]) if app.config["AUTH_MODE"] == "accounts" else None
    app.extensions["account_store"] = accounts
    # Explicit application-facing persistence ports.  The current local
    # adapter implements both contracts; future durable adapters can replace
    # it without changing route code.
    app.extensions["account_identity_port"] = accounts
    app.extensions["billing_sandbox_port"] = accounts

    def account_mode():
        return app.config["AUTH_MODE"] == "accounts"

    def provider_request_limit():
        raw = app.config.get("PROVIDER_REQUESTS_TOTAL")
        if raw is None or raw == "":
            return None
        try:
            if isinstance(raw, bool):
                return 0
            text = str(raw).strip()
            if not re.fullmatch(r"[0-9]+", text):
                return 0
            value = int(text)
            return value if 1 <= value <= 10000 else 0
        except (ValueError, TypeError):
            return 0

    def gate_configured():
        password, secret = app.config.get("PRIVATE_GATE_PASSWORD"), app.config.get("SECRET_KEY")
        return bool(isinstance(password, str) and 16 <= len(password) <= 256 and password.strip()
                    and isinstance(secret, str) and len(secret) >= 32 and secret.strip()
                    and password not in {secret, app.config.get("PILOT_PASSWORD")}
                    and provider_request_limit() not in {None, 0})

    def gate_fingerprint():
        return hmac.new(app.config["SECRET_KEY"].encode(),
                        ("private-gate:" + app.config["PRIVATE_GATE_PASSWORD"]).encode(),
                        hashlib.sha256).hexdigest()

    def clear_auth_session():
        # Site-preview access and application identity are separate credentials.
        gate = session.get("private_gate")
        session.clear()
        if gate:
            session["private_gate"] = gate

    def safe_gate_return(value):
        # Exact application paths exclude schemes, network paths, escapes and
        # query/fragment secrets; no user-provided URL is used as a Location.
        return value if value in {"/", "/app", "/app/", "/account", "/register", "/account/checkout"} else "/"

    @app.before_request
    def private_environment_gate():
        if not app.config["PRIVATE_GATE_ENABLED"] or request.endpoint == "health":
            return None
        if not gate_configured():
            return error("private_gate_configuration_missing", "Accesso riservato non ancora configurato.", 503)
        if request.endpoint == "private_access":
            return None
        fingerprint = session.get("private_gate", "")
        if isinstance(fingerprint, str) and hmac.compare_digest(fingerprint, gate_fingerprint()):
            return None
        if request.path.startswith("/api/") or request.method not in {"GET", "HEAD"} or request.path == "/analizza":
            return error("private_access_required", "Accedi prima all’ambiente riservato.", 401)
        return redirect(url_for("private_access", next=safe_gate_return(request.path)))

    @app.route("/private-access", methods=["GET", "POST"])
    def private_access():
        if not app.config["PRIVATE_GATE_ENABLED"]:
            return redirect("/")
        target = safe_gate_return(request.args.get("next", "/"))
        message, status = None, 200
        if "private_gate_csrf" not in session:
            session["private_gate_csrf"] = secrets.token_urlsafe(32)
        if request.method == "POST":
            if (request.content_length or 0) > 8192:
                return error("invalid_request", "Richiesta troppo grande.", 413)
            supplied_csrf = request.form.get("csrf", "")
            expected_csrf = session.get("private_gate_csrf")
            if (not same_origin() or len(supplied_csrf) > 128 or not isinstance(expected_csrf, str)
                    or not hmac.compare_digest(supplied_csrf.encode(), expected_csrf.encode())):
                return error("invalid_csrf", "Ricarica la pagina e riprova.", 403)
            password = request.form.get("password", "")
            scope = "private-gate:" + hmac.new(app.config["SECRET_KEY"].encode(),
                (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
            if not store.login(scope, False):
                message, status = "Troppi tentativi. Attendi 15 minuti prima di riprovare.", 429
            elif len(password) <= 256 and hmac.compare_digest(password.encode(), app.config["PRIVATE_GATE_PASSWORD"].encode()):
                with store.connect() as db:
                    db.execute("DELETE FROM events WHERE kind='login' AND scope=?", (scope,))
                session.clear()
                session.permanent = True
                session["private_gate"] = gate_fingerprint()
                return redirect(target, code=303)
            else:
                message, status = "Accesso non riuscito. Controlla la password riservata.", 401
        g.private_gate_nonce = secrets.token_urlsafe(18)
        return render_template("private_access.html", csrf=session["private_gate_csrf"],
                               target=target, message=message, nonce=g.private_gate_nonce), status

    def plan():
        # A legacy pilot configuration must never grant account users internal access.
        return "trial" if account_mode() else app.config["PILOT_PLAN"]

    def trial_total():
        return 1 if account_mode() else app.config["TRIAL_ANALYSES_TOTAL"]

    def auth_configured():
        secret = app.config.get("SECRET_KEY")
        common = bool(
            isinstance(secret, (str, bytes)) and len(secret) >= 32 and secret.strip()
            and app.config["AUTH_MODE"] in {"pilot", "accounts"}
            and 0 <= app.config.get("TRIAL_ANALYSES_TOTAL", -1) <= 100
            and 1024 <= app.config.get("MAX_IMAGE_BYTES", 0) <= 100 * 1024 * 1024
            and 1024 <= app.config.get("MAX_VIDEO_BYTES", 0) <= 1024 * 1024 * 1024
            and 1 <= app.config.get("MAX_VIDEO_SECONDS", 0) <= 3600
            and 1 <= app.config.get("MAX_HISTORY_BYTES_PER_TENANT", 0)
        )
        if account_mode():
            return common and accounts is not None
        password = app.config.get("PILOT_PASSWORD")
        tenant_id, owner_id = app.config.get("PILOT_TENANT_ID"), app.config.get("PILOT_OWNER_ID")
        return bool(common
            and isinstance(password, str) and len(password) >= 16 and password.strip()
            and isinstance(tenant_id, str) and PRINCIPAL_ID.fullmatch(tenant_id)
            and isinstance(owner_id, str) and PRINCIPAL_ID.fullmatch(owner_id)
            and app.config.get("PILOT_PLAN") in {"trial", "internal"})

    def validate_session_mode():
        if session.get("authenticated") and session.get("auth_mode") != app.config["AUTH_MODE"]:
            clear_auth_session()

    def current_account():
        validate_session_mode()
        if not account_mode() or not session.get("authenticated"):
            return None
        user = accounts.get_user(session.get("account_user_id"))
        if not user or session.get("account_session_version") != user["session_version"]:
            clear_auth_session()
            return None
        # Always restore trusted identity from storage, not request/cookie fields.
        session["tenant_id"], session["owner_id"] = user["company_id"], user["id"]
        return user

    def principal_scope():
        if account_mode():
            return "company:" + session.get("tenant_id", "")
        return f'{session.get("tenant_id", "")}:{session.get("owner_id", "")}'

    def entitlement():
        current_plan = plan()
        if current_plan != "trial":
            return {
                "plan": current_plan,
                "analyses_total": None,
                "analyses_used": None,
                "analyses_remaining": None,
                "export_allowed": True,
            }
        total = trial_total()
        used, remaining = store.trial_status(principal_scope(), total)
        clarification_used, clarification_remaining = store.clarification_status(principal_scope())
        return {
            "plan": "trial",
            "analyses_total": total,
            "analyses_used": used,
            "analyses_remaining": remaining,
            "clarifications_included_per_account": 1,
            "clarifications_used": clarification_used,
            "clarifications_remaining": clarification_remaining,
            "export_allowed": False,
        }

    def media_capabilities():
        local_video_tools = media_tools_available()
        return {
            "image_max_bytes": app.config["MAX_IMAGE_BYTES"],
            "video_max_bytes": app.config["MAX_VIDEO_BYTES"],
            "video_max_seconds": app.config["MAX_VIDEO_SECONDS"],
            "video_intake_enabled": local_video_tools,
            "audio_extraction_enabled": local_video_tools,
            "video_analysis_enabled": False,
        }

    def session_payload(authenticated, csrf, ready):
        payload = {
            "authenticated": authenticated,
            "csrf": csrf,
            "configured": ready,
            "auth_configured": True,
            "analysis_configured": ready,
            "media": media_capabilities(),
            "auth_mode": app.config["AUTH_MODE"],
            "registration_open": bool(account_mode() and app.config["ACCOUNT_REGISTRATION_OPEN"]),
            "delivery_configured": False,
        }
        if authenticated:
            payload["entitlement"] = entitlement()
            if account_mode():
                public = accounts.public(current_account())
                payload["account"] = public
                payload["verification_required"] = not bool(public and public["eligible_for_analysis"])
                payload["configured"] = bool(ready and not payload["verification_required"])
                payload["billing_sandbox_available"] = bool(
                    app.config["BILLING_SANDBOX_ENABLED"]
                    and public and public["eligible_for_analysis"]
                )
        return payload

    def error(code, message, status, **extra):
        return jsonify(error={"code": code, "message": message}, **extra), status

    def csrf_valid():
        expected = session.get("csrf")
        supplied = request.headers.get("X-CSRF-Token", "")
        return bool(expected and len(supplied) <= 128 and hmac.compare_digest(str(expected).encode(), supplied.encode()))

    def same_origin():
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        origin = request.headers.get("Origin")
        if not origin:
            return True
        try:
            parts = urlsplit(origin)
            return parts.netloc == request.host and parts.scheme in ("http", "https")
        except ValueError:
            return False

    def protect(fn=None, *, allow_unverified=False, require_csrf=True):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if not auth_configured():
                    return error("configuration_missing", "Accesso non ancora configurato.", 503)
                validate_session_mode()
                user = current_account() if account_mode() else None
                if (account_mode() and not user) or not session.get("authenticated") or not session.get("tenant_id") or not session.get("owner_id"):
                    return error("authentication_required", "Accedi per utilizzare il progetto pilota.", 401)
                if not same_origin() or (require_csrf and not csrf_valid()):
                    return error("invalid_csrf", "Sessione scaduta: ricarica la pagina e riprova.", 403)
                if account_mode() and not allow_unverified and not accounts.public(user)["eligible_for_analysis"]:
                    return error("account_verification_required", "Completa la verifica dell’email, dell’azienda e del tuo ruolo prima di analizzare o aprire casi.", 403)
                return view(*args, **kwargs)
            return wrapped
        return decorator(fn) if fn is not None else decorator

    def billing_sandbox(view):
        """Hide every sandbox route unless the explicit local flag is enabled."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not app.config.get("BILLING_SANDBOX_ENABLED") or not account_mode():
                return error("billing_sandbox_unavailable", "Simulazione non disponibile.", 404)
            return view(*args, **kwargs)
        return wrapped

    def account_request():
        if not auth_configured() or not account_mode():
            return error("account_service_unavailable", "Registrazione account non disponibile in questo ambiente.", 503)
        if not same_origin() or not csrf_valid():
            return error("invalid_csrf", "Ricarica la pagina prima di continuare.", 403)
        if request.content_length and request.content_length > 8192:
            return error("invalid_request", "Richiesta troppo grande.", 400)
        if not isinstance(request.get_json(silent=True), dict):
            return error("invalid_request", "Richiesta non valida.", 400)
        return None

    def attempt_scope(kind):
        return kind + ":" + hmac.new(str(app.config["SECRET_KEY"]).encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        if getattr(g, "private_gate_nonce", None):
            response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace(
                "style-src 'self'", "style-src 'self' 'nonce-" + g.private_gate_nonce + "'")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def home():
        return render_template("landing.html", accounts_mode=account_mode(),
                               registration_open=bool(account_mode() and auth_configured() and app.config["ACCOUNT_REGISTRATION_OPEN"]))

    @app.get("/register")
    @app.get("/account")
    def account_page():
        return render_template("account.html")

    @app.get("/account/checkout")
    def checkout_page():
        if (not account_mode() or not auth_configured()
                or not app.config.get("BILLING_SANDBOX_ENABLED")):
            return redirect("/account")
        validate_session_mode()
        user = current_account()
        if (not session.get("authenticated") or not user
                or not accounts.public(user)["eligible_for_analysis"]):
            return redirect("/account")
        return render_template("checkout.html")

    @app.get("/app/")
    @app.get("/app")
    def workspace():
        if account_mode():
            if not auth_configured():
                return redirect("/account")
            user = current_account()
            if not user or not accounts.public(user)["eligible_for_analysis"]:
                return redirect("/account")
        return render_template("index.html")

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/api/session")
    def session_info():
        ready = is_analysis_configured()
        if not auth_configured():
            return jsonify(authenticated=False, csrf=None, configured=False, auth_configured=False, analysis_configured=ready, media=media_capabilities(), auth_mode=app.config["AUTH_MODE"], registration_open=False)
        validate_session_mode()
        if account_mode():
            current_account()
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(**session_payload(bool(session.get("authenticated")), session["csrf"], ready))

    @app.post("/api/login")
    def login():
        if not auth_configured():
            return error("configuration_missing", "Accesso pilota non ancora configurato.", 503)
        if not same_origin() or not csrf_valid():
            return error("invalid_csrf", "Ricarica la pagina prima di accedere.", 403)
        if account_mode() and request.content_length and request.content_length > 8192:
            return error("invalid_request", "Richiesta troppo grande.", 400)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("password"), str) or len(payload["password"]) > 1024:
            return error("invalid_request", "Inserisci la password di accesso.", 400)
        scope = hmac.new(str(app.config["SECRET_KEY"]).encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
        if account_mode():
            # Reject throttled attempts before the intentionally expensive hash.
            try:
                email_identity = normalize_email(payload.get("email"))
            except ValueError:
                email_identity = "invalid"
            email_scope = "account-login:" + hmac.new(
                str(app.config["SECRET_KEY"]).encode(), email_identity.encode(), hashlib.sha256
            ).hexdigest()
            if not store.login(scope, False) or not store.login(email_scope, False):
                return error("login_rate_limited", "Troppi tentativi. Attendi 15 minuti prima di riprovare.", 429)
            user = accounts.authenticate(payload.get("email"), payload["password"])
            success = bool(user)
            if success:
                with store.connect() as db:
                    db.execute("DELETE FROM events WHERE kind='login' AND scope IN (?, ?)", (scope, email_scope))
        else:
            user = None
            success = hmac.compare_digest(payload["password"].encode(), str(app.config["PILOT_PASSWORD"]).encode())
            if not store.login(scope, success):
                return error("login_rate_limited", "Troppi tentativi. Attendi 15 minuti prima di riprovare.", 429)
        if not success:
            return error("invalid_credentials", "Password non valida.", 401)
        clear_auth_session()
        session.permanent = True
        session["authenticated"] = True
        session["auth_mode"] = app.config["AUTH_MODE"]
        if account_mode():
            session["account_user_id"] = user["id"]
            session["account_session_version"] = user["session_version"]
            session["tenant_id"], session["owner_id"] = user["company_id"], user["id"]
        else:
            session["tenant_id"] = app.config["PILOT_TENANT_ID"]
            session["owner_id"] = app.config["PILOT_OWNER_ID"]
        session["csrf"] = secrets.token_urlsafe(32)
        ready = is_analysis_configured()
        return jsonify(**session_payload(True, session["csrf"], ready))

    @app.post("/api/accounts/register")
    def register_account():
        failure = account_request()
        if failure:
            return failure
        if not app.config["ACCOUNT_REGISTRATION_OPEN"]:
            return error("registration_closed", "La registrazione non è ancora aperta.", 503)
        if not store.login(attempt_scope("registration"), False):
            return error("registration_rate_limited", "Troppi tentativi. Riprova più tardi.", 429)
        data = request.get_json()
        try:
            accounts.register(email=data.get("email"), password=data.get("password"),
                              company_name=data.get("company_name"), company_identifier=data.get("company_identifier", ""),
                              role=data.get("role"), locale=data.get("locale", "it"))
        except AccountConflict:
            return error("registration_unavailable", "Registrazione non disponibile con questi dati. Accedi oppure richiedi assistenza per l’azienda esistente.", 409)
        except (ValueError, TypeError):
            return error("invalid_registration", "Controlla email, azienda, ruolo, lingua e password (16–256 caratteri).", 400)
        return jsonify(registered=True, verification_required=True, delivery_configured=False), 202

    @app.post("/api/accounts/verify-email")
    def verify_account_email():
        failure = account_request()
        if failure:
            return failure
        if not store.login(attempt_scope("verify"), False, limit=10):
            return error("verification_rate_limited", "Troppi tentativi. Riprova più tardi.", 429)
        if not accounts.consume_token(request.get_json().get("token"), "email"):
            return error("invalid_token", "Codice non valido o scaduto.", 400)
        return jsonify(email_verified=True, company_verification_required=True)

    @app.post("/api/accounts/password-reset")
    def request_password_reset():
        failure = account_request()
        if failure:
            return failure
        if not store.login(attempt_scope("reset-request"), False):
            return error("reset_rate_limited", "Troppi tentativi. Riprova più tardi.", 429)
        # No delivery adapter exists yet. Never return or persist plaintext tokens,
        # and never pretend that a reset email was sent.
        return jsonify(accepted=True, delivery_configured=False,
                       message="Se l’account esiste, il recupero richiede il canale di consegna riservato; l’invio email non è attivo in questo ambiente."), 202

    @app.post("/api/accounts/password-reset/confirm")
    def confirm_password_reset():
        failure = account_request()
        if failure:
            return failure
        if not store.login(attempt_scope("reset-confirm"), False):
            return error("reset_rate_limited", "Troppi tentativi. Riprova più tardi.", 429)
        data = request.get_json()
        if not accounts.consume_token(data.get("token"), "reset", data.get("password")):
            return error("invalid_token", "Codice non valido/scaduto o password non valida (16–256 caratteri).", 400)
        clear_auth_session()
        return jsonify(reset=True, authenticated=False)

    @app.post("/api/logout")
    @protect(allow_unverified=True)
    def logout():
        clear_auth_session()
        return jsonify(authenticated=False)

    @app.get("/api/cases")
    @protect
    def list_cases():
        return jsonify(
            cases=case_store.list(session["tenant_id"], session["owner_id"]),
            storage=case_store.storage_status(session["tenant_id"]),
        )

    def consultation_state(user):
        return accounts.consultation_status(user["company_id"], user["id"])

    def checkout_state(checkout_id, user):
        state = accounts.get_checkout_simulation(checkout_id, user["company_id"], user["id"])
        if not state:
            return error("checkout_not_found", "Simulazione non disponibile.", 404)
        return jsonify(checkout=state)

    @app.get("/api/sandbox/billing/plans")
    @billing_sandbox
    @protect(require_csrf=False)
    def sandbox_billing_plans():
        return jsonify(**billing_catalog())

    @app.post("/api/sandbox/billing/checkout-simulations")
    @billing_sandbox
    @protect
    def create_checkout_simulation():
        data = request.get_json(silent=True)
        allowed = {"plan_code", "billing_cycle"}
        if (not isinstance(data, dict) or set(data) - allowed or set(data) != allowed or
                (request.content_length and request.content_length > 2048)):
            return error("invalid_checkout", "Selezione non valida; i dati di pagamento non sono accettati.", 400)
        key = request.headers.get("Idempotency-Key", "")
        if not 12 <= len(key) <= 128:
            return error("invalid_idempotency_key", "Chiave di ripetizione non valida.", 400)
        user = current_account()
        try:
            state = accounts.create_checkout_simulation(
                user["company_id"], user["id"], data.get("plan_code"),
                data.get("billing_cycle"), idempotency_key=key,
                max_open_intents=app.config["BILLING_SANDBOX_MAX_OPEN_INTENTS"],
            )
        except BillingSandboxConflict as exc:
            if str(exc) == "idempotency_mismatch":
                return error("idempotency_mismatch", "Richiesta duplicata non coerente.", 409)
            if str(exc) == "open_intent_limit":
                return error("open_intent_limit", "Concludi o attendi la scadenza delle simulazioni aperte.", 409)
            return error("checkout_unavailable", "Simulazione non disponibile.", 409)
        except (ValueError, TypeError):
            return error("invalid_checkout", "Piano o ciclo non valido.", 400)
        replay = state.pop("idempotent_replay", False)
        return jsonify(checkout=state), 200 if replay else 201

    @app.get("/api/sandbox/billing/checkout-simulations/<checkout_id>")
    @billing_sandbox
    @protect(require_csrf=False)
    def get_checkout_simulation(checkout_id):
        return checkout_state(checkout_id, current_account())

    def transition_checkout(checkout_id, target):
        user = current_account()
        try:
            state = accounts.transition_checkout_simulation(
                checkout_id, user["company_id"], user["id"], target,
            )
        except BillingSandboxConflict as exc:
            code = str(exc)
            if code == "checkout_expired":
                return error("checkout_expired", "La simulazione è scaduta.", 409)
            if code == "checkout_already_final":
                return error("checkout_already_final", "La simulazione è già conclusa.", 409)
            return error("checkout_not_found", "Simulazione non disponibile.", 404)
        except ValueError:
            return error("checkout_not_found", "Simulazione non disponibile.", 404)
        replay = state.pop("idempotent_replay", False)
        return jsonify(checkout=state, idempotent_replay=replay)

    @app.post("/api/sandbox/billing/checkout-simulations/<checkout_id>/confirm")
    @billing_sandbox
    @protect
    def confirm_checkout_simulation(checkout_id):
        return transition_checkout(checkout_id, "confirmed_simulation")

    @app.post("/api/sandbox/billing/checkout-simulations/<checkout_id>/cancel")
    @billing_sandbox
    @protect
    def cancel_checkout_simulation(checkout_id):
        return transition_checkout(checkout_id, "cancelled")

    @app.get("/api/consultations")
    @protect(require_csrf=False)
    def consultations():
        if not account_mode():
            return error("consultations_unavailable", "Funzione non disponibile in questo accesso.", 404)
        user = current_account()
        state = consultation_state(user)
        cases = [
            {"id": item["id"], "created_at": item["created_at"], "summary": item.get("summary", "")}
            for item in case_store.list(session["tenant_id"], session["owner_id"])
            if not item.get("deletion_pending")
        ]
        return jsonify(consultation=state, cases=cases, hypothesis=True,
                       message="Disponibilità sperimentale separata dalla fatturazione.")

    @app.post("/api/consultations")
    @protect
    def reserve_consultation():
        if not account_mode():
            return error("consultations_unavailable", "Funzione non disponibile in questo accesso.", 404)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or (request.content_length and request.content_length > 2048):
            return error("invalid_request", "Richiesta non valida.", 400)
        case_id, channel = data.get("case_id"), data.get("channel")
        key = request.headers.get("Idempotency-Key", "")
        if (not isinstance(case_id, str) or len(case_id) > 64 or
                channel not in {"phone", "whatsapp"} or not 12 <= len(key) <= 128):
            return error("invalid_consultation", "Scegli un caso e un canale validi.", 400)
        # Owner-private case authorization is checked before consuming allowance.
        if not case_store.get(case_id, session["tenant_id"], session["owner_id"]):
            return error("case_not_found", "Caso non disponibile.", 404)
        user = current_account()
        try:
            state = accounts.reserve_consultation(
                user["company_id"], user["id"], case_id, channel,
                idempotency_key=key,
            )
        except (ConsultationConflict, ValueError) as exc:
            code = str(exc)
            if code == "idempotency_mismatch":
                return error("idempotency_mismatch", "Richiesta duplicata non coerente.", 409)
            return error("consultation_unavailable", "Nessuna richiesta inclusa disponibile in questo periodo.", 409)
        replay = state.pop("idempotent_replay", False)
        return jsonify(
            recorded=True, contacted=False, charged=False, consultation=state,
            message="Richiesta registrata. Nessun messaggio o chiamata è stato inviato.",
        ), 200 if replay else 201

    @app.post("/api/consultations/<request_id>/cancel")
    @protect
    def cancel_consultation(request_id):
        if not account_mode() or len(request_id) > 64:
            return error("consultation_not_found", "Richiesta non disponibile.", 404)
        user = current_account()
        try:
            accounts.cancel_consultation(request_id, user["company_id"], user["id"])
        except (ConsultationConflict, ValueError):
            return error("consultation_not_found", "Richiesta non disponibile o già conclusa.", 404)
        return jsonify(cancelled=True, credited=False, consultation=consultation_state(user),
                       message="Richiesta annullata. La disponibilità non cambia: la politica è ancora da definire.")

    @app.get("/api/cases/<case_id>")
    @protect
    def get_case(case_id):
        if len(case_id) > 64:
            return error("case_not_found", "Caso non disponibile.", 404)
        case = case_store.get(case_id, session["tenant_id"], session["owner_id"])
        if not case:
            return error("case_not_found", "Caso non disponibile.", 404)
        return jsonify(case=case)

    @app.get("/api/cases/<case_id>/assets/<asset_id>")
    @protect(require_csrf=False)
    def get_case_asset(case_id, asset_id):
        if len(case_id) > 64 or len(asset_id) > 64:
            return error("asset_not_found", "File del caso non disponibile.", 404)
        asset = case_store.asset(
            case_id, asset_id, session["tenant_id"], session["owner_id"]
        )
        if not asset:
            return error("asset_not_found", "File del caso non disponibile.", 404)
        inline = asset["media_type"].startswith(("image/", "video/", "audio/"))
        return send_file(
            asset["path"], mimetype=asset["media_type"],
            as_attachment=not inline,
            download_name=asset["filename"], conditional=False, max_age=0,
        )

    @app.delete("/api/cases/<case_id>")
    @protect
    def delete_case(case_id):
        if len(case_id) > 64:
            return error("case_not_found", "Caso non disponibile.", 404)
        try:
            deleted = case_store.delete(
                case_id, session["tenant_id"], session["owner_id"]
            )
        except CaseDeletionPending:
            return error(
                "case_deletion_pending",
                "Il caso non è più consultabile, ma la rimozione dei file non è completata. Riprova l’eliminazione.",
                503,
            )
        if not deleted:
            return error("case_not_found", "Caso non disponibile.", 404)
        return jsonify(deleted=True)

    @app.post("/api/media/inspect")
    @protect
    def inspect_uploaded_media():
        media_started = time.monotonic()
        media_token, media_failure = store.reserve_media(principal_scope())
        if media_failure == "busy":
            return error("media_busy", "È già in corso una verifica video. Riprova tra poco.", 429)
        if media_failure == "limit":
            return error("media_rate_limited", "Troppe verifiche video in pochi minuti. Riprova più tardi.", 429)
        try:
            files = request.files.getlist("file")
            if len(files) != 1 or not files[0].filename:
                return error("invalid_file", "Seleziona un solo video.", 400)
            upload = files[0]
            extension = Path(upload.filename).suffix.lower()
            declared_mime = (upload.mimetype or "").lower()
            if VIDEO_MEDIA.get(extension) != declared_mime:
                return error("invalid_media", "Tipo MIME ed estensione non corrispondono. Usa MP4, WebM o MOV.", 400)
            if request.content_length and request.content_length > app.config["MAX_VIDEO_BYTES"] + 128 * 1024:
                return error("file_too_large", "Il video supera il limite configurato.", 413)
            context = request.form.get("context", "")
            if len(context) > MAX_CONTEXT_CHARS:
                return error("invalid_context", "Il contesto deve contenere al massimo 8000 caratteri.", 400)
            raw = upload.stream.read(app.config["MAX_VIDEO_BYTES"] + 1)
            if time.monotonic() - media_started > 20:
                return error("media_processing_timeout", "Il caricamento ha superato il tempo consentito. Riprova con un file più piccolo o una connessione stabile.", 422)
            try:
                media = inspect_video(
                    raw,
                    expected_mime=declared_mime,
                    max_bytes=app.config["MAX_VIDEO_BYTES"],
                    max_seconds=app.config["MAX_VIDEO_SECONDS"],
                    include_artifacts=True,
                )
            except MediaError as exc:
                return error(exc.code, str(exc), exc.status)
        finally:
            store.release_media(media_token)
        artifacts = media.pop("_artifacts", {"frames": [], "audio": None})
        frame_metadata = [
            {"timestamp_seconds": frame["timestamp_seconds"]}
            for frame in media["frames"]
        ]
        technical_record = {
            "summary": "Verifica tecnica di video e audio",
            "findings": [],
            "questions": [],
            "sources": [],
            "needs_clarification": False,
            "meta": {
                "case_kind": "video_technical_verification",
                "analysis_performed": False,
                "transcription_performed": media["transcription"]["status"] == "available",
                "video_inspection": {
                    "validated": media["validated"],
                    "mime_type": media["mime_type"],
                    "duration_seconds": media["duration_seconds"],
                    "video": media["video"],
                    "frames": frame_metadata,
                    "sampling": media["sampling"],
                    "audio": media["audio"],
                    "transcription": media["transcription"],
                },
            },
        }
        history_assets = [{
            "role": "original", "data": raw,
            "filename": upload.filename, "media_type": declared_mime,
        }]
        for index, frame in enumerate(artifacts.get("frames") or [], start=1):
            history_assets.append({
                "role": "frame", "data": frame["data"],
                "filename": f"frame-{index:02d}-{frame['timestamp_seconds']:.3f}s.jpg",
                "media_type": frame["media_type"],
            })
        audio_artifact = artifacts.get("audio")
        if audio_artifact:
            history_assets.append({
                "role": "audio", "data": audio_artifact["data"],
                "filename": "audio-extract.wav", "media_type": audio_artifact["media_type"],
            })
        transcript = media.get("transcription") or {}
        if transcript.get("status") == "available" and transcript.get("text"):
            history_assets.append({
                "role": "transcript", "data": transcript["text"].encode("utf-8"),
                "filename": "transcript.txt", "media_type": "text/plain",
            })
        try:
            case_id, archive_failure = case_store.create(
                session["tenant_id"], session["owner_id"], context,
                technical_record, None, app.config["MAX_CASES_PER_OWNER"],
                assets=history_assets,
            )
            archive = {
                "saved": bool(case_id), "case_id": case_id,
                "kind": "video_technical_verification",
                "storage": case_store.storage_status(session["tenant_id"]),
            }
            if archive_failure == "limit":
                archive["message"] = "Archivio pieno: elimina un caso prima di salvare questa verifica. La verifica tecnica resta visibile in questa pagina."
            elif archive_failure == "storage_limit":
                archive["message"] = "Spazio archivio esaurito: i casi esistenti restano disponibili, ma questo video e le evidenze non sono stati salvati. La verifica tecnica resta visibile in questa pagina."
            elif archive_failure:
                archive["message"] = "Verifica tecnica non archiviata perché il rapporto supera il limite. La verifica resta visibile in questa pagina."
        except (sqlite3.Error, OSError, TypeError, ValueError):
            app.logger.error("Video technical history unavailable after successful inspection")
            archive = {
                "saved": False, "case_id": None,
                "kind": "video_technical_verification",
                "message": "Verifica tecnica completata, ma video ed evidenze non sono stati archiviati per un problema temporaneo.",
            }
        if archive["saved"]:
            if media["audio"]["status"] == "absent":
                retention_message = (
                    "Il video originale è conservato nel caso protetto. "
                    "Il file non contiene una traccia audio."
                )
            else:
                retention_message = (
                    "Il video originale è conservato nel caso protetto e la traccia audio "
                    "presente nel contenitore è stata mantenuta; stato e qualità restano da verificare."
                )
            media["original_retention"] = {
                "status": "archived",
                "message": retention_message,
            }
        else:
            media["original_retention"] = {
                "status": "not_saved",
                "message": archive["message"],
            }
        message = "Video verificato; la parte audio non ha potuto essere verificata." if media["audio"]["status"] == "error" else "Video e audio verificati localmente."
        return jsonify(
            media=media,
            archive=archive,
            analysis_available=False,
            trial_consumed=False,
            message=message + " L’analisi AI e la trascrizione non sono ancora state eseguite.",
        )

    @app.post("/analizza")
    @protect
    def analizza():
        if not is_analysis_configured():
            return error("analysis_configuration_missing", "Il servizio di analisi non è ancora configurato.", 503)
        files = request.files.getlist("file")
        if len(files) != 1 or not files[0].filename:
            return error("invalid_file", "Seleziona un solo file foto o video.", 400)
        upload = files[0]
        extension = Path(upload.filename).suffix.lower()
        declared_mime = (upload.mimetype or "").lower()
        if extension in VIDEO_MEDIA or declared_mime.startswith("video/"):
            if VIDEO_MEDIA.get(extension) != declared_mime:
                return error(
                    "invalid_media",
                    "Tipo MIME ed estensione del video non corrispondono. Usa MP4, WebM o MOV.",
                    400,
                )
            if request.content_length and request.content_length > app.config["MAX_VIDEO_BYTES"] + 128 * 1024:
                return error("file_too_large", "Il video supera il limite configurato.", 413)
            return error(
                "video_pipeline_unavailable",
                "Formato ed estensione del video riconosciuti; contenuto e durata non sono validati. L’analisi video è in preparazione: il file non è stato inviato al motore AI e non ha consumato la prova gratuita.",
                501,
            )
        if IMAGE_MEDIA.get(extension) != declared_mime:
            return error(
                "invalid_media",
                "Tipo MIME ed estensione della foto non corrispondono. Usa JPG, PNG o WebP.",
                400,
            )
        context = request.form.get("context", "")
        if len(context) > MAX_CONTEXT_CHARS:
            return error("invalid_context", "Il contesto deve contenere al massimo 8000 caratteri.", 400)
        request_kind = request.form.get("request_kind", "initial")
        if request_kind not in {"initial", "clarification"}:
            return error("invalid_request_kind", "Tipo di richiesta non valido.", 400)
        clarification_image_sha256 = None
        if request_kind == "clarification":
            case_id = request.form.get("case_id", "")
            if case_id and len(case_id) <= 64:
                clarification_image_sha256 = case_store.image_sha256(
                    case_id, session["tenant_id"], session["owner_id"]
                )
            if not clarification_image_sha256:
                return error(
                    "clarification_case_required",
                    "Il chiarimento gratuito richiede un caso salvato dallo stesso account e compatibile con la verifica dell’immagine.",
                    400,
                )
        try:
            raw = upload.stream.read(app.config["MAX_IMAGE_BYTES"] + 1)
            if len(raw) > app.config["MAX_IMAGE_BYTES"]:
                return error("file_too_large", "La foto supera il limite configurato.", 413)
            image, mime_type, width, height = normalize_image(
                raw, expected_mime=declared_mime, max_bytes=app.config["MAX_IMAGE_BYTES"]
            )
        except ValueError as exc:
            return error("invalid_image", str(exc), 400)
        image_sha256 = hashlib.sha256(image).hexdigest()
        if clarification_image_sha256 and not hmac.compare_digest(
            clarification_image_sha256, image_sha256
        ):
            return error(
                "clarification_image_mismatch",
                "Per il chiarimento usa la stessa fotografia dell’analisi iniziale. Il file diverso non è stato inviato e non ha consumato la prova.",
                400,
            )
        trial_token = None
        trial_kind = None
        trial_completed = False
        if plan() == "trial":
            if request_kind == "clarification":
                used, _remaining = store.trial_status(
                    principal_scope(), trial_total()
                )
                if used < 1:
                    return error(
                        "clarification_case_required",
                        "Completa prima l’analisi iniziale gratuita.",
                        400,
                    )
                trial_kind = "clarification"
                trial_token, trial_failure = store.reserve_clarification(
                    principal_scope(), app.config["ANALYSIS_LEASE_SECONDS"]
                )
            else:
                trial_kind = "analysis"
                trial_token, trial_failure = store.reserve_trial(
                    principal_scope(),
                    trial_total(),
                    app.config["ANALYSIS_LEASE_SECONDS"],
                )
            if trial_failure == "busy":
                return error("analysis_busy", "Un’analisi è già in corso per questo account.", 409)
            if trial_failure:
                return error(
                    "trial_exhausted",
                    "La prova gratuita include una sola analisi e un solo ciclo di chiarimento sullo stesso caso. Per continuare serve un piano successivo.",
                    402,
                    entitlement=entitlement(),
                )
        token, failure = store.reserve_analysis(app.config["ANALYSES_PER_HOUR"], app.config["ANALYSIS_LEASE_SECONDS"])
        if failure == "busy":
            if trial_token:
                (store.release_clarification if trial_kind == "clarification" else store.release_trial)(principal_scope(), trial_token)
            return error("analysis_busy", "Un'analisi è già in corso. Attendi il risultato.", 409)
        if failure:
            if trial_token:
                (store.release_clarification if trial_kind == "clarification" else store.release_trial)(principal_scope(), trial_token)
            return error("analysis_rate_limited", "Limite orario raggiunto. Attendi prima di avviare altre analisi.", 429)
        try:
            if not store.reserve_provider_request(provider_request_limit()):
                return error("provider_request_cap_reached", "Limite totale delle richieste al motore raggiunto o non valido. Nessuna nuova richiesta è stata inviata.", 503)
            result = analizza_immagine(image, mime_type, context)
            if trial_token:
                complete = store.complete_clarification if trial_kind == "clarification" else store.complete_trial
                if not complete(principal_scope(), trial_token):
                    raise RuntimeError("Trial reservation expired before completion")
                trial_completed = True
            try:
                case_id, archive_failure = case_store.create(
                    session["tenant_id"],
                    session["owner_id"],
                    context,
                    result,
                    image_sha256,
                    app.config["MAX_CASES_PER_OWNER"],
                    assets=[
                        {
                            "role": "original", "data": raw,
                            "filename": upload.filename, "media_type": declared_mime,
                        },
                        {
                            "role": "normalized", "data": image,
                            "filename": "normalized.jpg", "media_type": mime_type,
                        },
                    ],
                )
                archive = {
                    "saved": bool(case_id),
                    "case_id": case_id,
                    "clarification_available": bool(case_id),
                    "storage": case_store.storage_status(session["tenant_id"]),
                }
                if archive_failure == "limit":
                    archive["message"] = "Archivio pieno: elimina un caso prima di salvarne un altro."
                elif archive_failure == "storage_limit":
                    archive["message"] = (
                        "Spazio archivio esaurito: i casi esistenti restano disponibili, "
                        "ma questo nuovo caricamento non è stato salvato."
                    )
                elif archive_failure:
                    archive["message"] = "Risultato non archiviato: dimensione superiore al limite."
            except (sqlite3.Error, OSError, TypeError):
                # The paid analysis already succeeded: never discard it because
                # the optional pilot archive is temporarily unavailable.
                app.logger.error("Case archive unavailable after successful analysis")
                archive = {
                    "saved": False,
                    "case_id": None,
                    "clarification_available": False,
                    "message": "Risultato non archiviato per un problema temporaneo.",
                }
            if plan() == "trial" and not archive["saved"]:
                archive["message"] = (
                    archive.get("message", "Risultato non archiviato.")
                    + " Il chiarimento incluso richiede un caso salvato e non è disponibile per questo risultato."
                )
            return jsonify(
                analysis=result,
                image={"width": width, "height": height},
                archive=archive,
                entitlement=entitlement(),
            )
        except AnalysisError as exc:
            return error(exc.code, exc.message, exc.status)
        finally:
            store.release_analysis(token)
            if trial_token and not trial_completed:
                release = store.release_clarification if trial_kind == "clarification" else store.release_trial
                release(principal_scope(), trial_token)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return error("file_too_large", "Il file supera il limite configurato per foto o video.", 413)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return error("http_error", "Richiesta non valida o risorsa non disponibile.", exc.code or 500)

    @app.errorhandler(Exception)
    def unexpected_error(_exc):
        app.logger.error("Unhandled pilot request error")
        return error("internal_error", "Operazione non completata. Riprova più tardi.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", debug=False)
