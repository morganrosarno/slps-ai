"""Private SLPS pilot with opt-in company accounts; photos stay in memory."""
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
import sqlite3
import time
from urllib.parse import urlsplit
import warnings

from flask import Flask, Request, jsonify, redirect, render_template, request, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from slps_ai import AnalysisError, analizza_immagine, is_analysis_configured
from accounts import AccountConflict, AccountStore, normalize_email
from media import MediaError, inspect_video, media_tools_available

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


class MemoryUploadRequest(Request):
    """Prevent Werkzeug's default 500 KB spooling from writing photo bytes."""
    def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
        return io.BytesIO()


class LimitStore:
    """Atomic limits shared by workers on one server, retained on restart."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS events (kind TEXT, scope TEXT, created REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS events_lookup ON events(kind, scope, created)")
            db.execute("CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, token TEXT, expires REAL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS trial_usage (scope TEXT PRIMARY KEY, used INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS trial_clarifications (scope TEXT PRIMARY KEY, used INTEGER NOT NULL)"
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

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


class CaseStore:
    """Archive results without photographs, scoped by tenant and owner."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    created REAL NOT NULL,
                    context TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    image_sha256 TEXT
                )"""
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(cases)").fetchall()}
            if "image_sha256" not in columns:
                db.execute("ALTER TABLE cases ADD COLUMN image_sha256 TEXT")
            db.execute(
                "CREATE INDEX IF NOT EXISTS cases_owner_created "
                "ON cases(tenant_id, owner_id, created DESC)"
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, tenant_id, owner_id, context, analysis, image_sha256, max_cases):
        encoded = json.dumps(analysis, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_CASE_JSON_BYTES:
            return None, "too_large"
        now = time.time()
        case_id = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM cases WHERE tenant_id=? AND owner_id=?",
                (tenant_id, owner_id),
            ).fetchone()[0]
            if count >= max_cases:
                return None, "limit"
            db.execute(
                """INSERT INTO cases
                   (id, tenant_id, owner_id, created, context, analysis_json, image_sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (case_id, tenant_id, owner_id, now, context, encoded, image_sha256),
            )
        return case_id, None

    def list(self, tenant_id, owner_id):
        with self.connect() as db:
            rows = db.execute(
                """SELECT id, created, context, analysis_json
                   FROM cases
                   WHERE tenant_id=? AND owner_id=?
                   ORDER BY created DESC""",
                (tenant_id, owner_id),
            ).fetchall()
        cases = []
        for row in rows:
            analysis = json.loads(row["analysis_json"])
            cases.append({
                "id": row["id"],
                "created_at": row["created"],
                "context": row["context"],
                "summary": analysis.get("summary", "") if isinstance(analysis, dict) else "",
            })
        return cases

    def get(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            row = db.execute(
                """SELECT id, created, context, analysis_json
                   FROM cases
                   WHERE id=? AND tenant_id=? AND owner_id=?""",
                (case_id, tenant_id, owner_id),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "created_at": row["created"],
            "context": row["context"],
            "analysis": json.loads(row["analysis_json"]),
        }

    def image_sha256(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            row = db.execute(
                """SELECT image_sha256 FROM cases
                   WHERE id=? AND tenant_id=? AND owner_id=?""",
                (case_id, tenant_id, owner_id),
            ).fetchone()
        return row["image_sha256"] if row else None

    def delete(self, case_id, tenant_id, owner_id):
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM cases WHERE id=? AND tenant_id=? AND owner_id=?",
                (case_id, tenant_id, owner_id),
            )
        return cursor.rowcount == 1


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
        ACCOUNT_REGISTRATION_OPEN=os.getenv("SLPS_ACCOUNT_REGISTRATION_OPEN", "false").lower() == "true",
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
    app.config["MAX_CONTENT_LENGTH"] = max(
        app.config["MAX_IMAGE_BYTES"], app.config["MAX_VIDEO_BYTES"]
    ) + 128 * 1024
    store = LimitStore(app.config["RATE_DB_PATH"])
    case_store = CaseStore(app.config["CASE_DB_PATH"])
    app.extensions["limit_store"] = store
    app.extensions["case_store"] = case_store
    accounts = AccountStore(app.config["ACCOUNT_DB_PATH"]) if app.config["AUTH_MODE"] == "accounts" else None
    app.extensions["account_store"] = accounts

    def account_mode():
        return app.config["AUTH_MODE"] == "accounts"

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
            session.clear()

    def current_account():
        validate_session_mode()
        if not account_mode() or not session.get("authenticated"):
            return None
        user = accounts.get_user(session.get("account_user_id"))
        if not user or session.get("account_session_version") != user["session_version"]:
            session.clear()
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

    def protect(fn=None, *, allow_unverified=False):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if not auth_configured():
                    return error("configuration_missing", "Accesso non ancora configurato.", 503)
                validate_session_mode()
                user = current_account() if account_mode() else None
                if (account_mode() and not user) or not session.get("authenticated") or not session.get("tenant_id") or not session.get("owner_id"):
                    return error("authentication_required", "Accedi per utilizzare il progetto pilota.", 401)
                if not same_origin() or not csrf_valid():
                    return error("invalid_csrf", "Sessione scaduta: ricarica la pagina e riprova.", 403)
                if account_mode() and not allow_unverified and not accounts.public(user)["eligible_for_analysis"]:
                    return error("account_verification_required", "Completa la verifica dell’email, dell’azienda e del tuo ruolo prima di analizzare o aprire casi.", 403)
                return view(*args, **kwargs)
            return wrapped
        return decorator(fn) if fn is not None else decorator

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
        session.clear()
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
        session.clear()
        return jsonify(reset=True, authenticated=False)

    @app.post("/api/logout")
    @protect(allow_unverified=True)
    def logout():
        session.clear()
        return jsonify(authenticated=False)

    @app.get("/api/cases")
    @protect
    def list_cases():
        return jsonify(cases=case_store.list(session["tenant_id"], session["owner_id"]))

    @app.get("/api/cases/<case_id>")
    @protect
    def get_case(case_id):
        if len(case_id) > 64:
            return error("case_not_found", "Caso non disponibile.", 404)
        case = case_store.get(case_id, session["tenant_id"], session["owner_id"])
        if not case:
            return error("case_not_found", "Caso non disponibile.", 404)
        return jsonify(case=case)

    @app.delete("/api/cases/<case_id>")
    @protect
    def delete_case(case_id):
        if len(case_id) > 64 or not case_store.delete(
            case_id, session["tenant_id"], session["owner_id"]
        ):
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
            raw = upload.stream.read(app.config["MAX_VIDEO_BYTES"] + 1)
            if time.monotonic() - media_started > 20:
                return error("media_processing_timeout", "Il caricamento ha superato il tempo consentito. Riprova con un file più piccolo o una connessione stabile.", 422)
            try:
                media = inspect_video(
                    raw,
                    expected_mime=declared_mime,
                    max_bytes=app.config["MAX_VIDEO_BYTES"],
                    max_seconds=app.config["MAX_VIDEO_SECONDS"],
                )
            except MediaError as exc:
                return error(exc.code, str(exc), exc.status)
        finally:
            store.release_media(media_token)
        message = "Video verificato; la parte audio non ha potuto essere verificata." if media["audio"]["status"] == "error" else "Video e audio verificati localmente."
        return jsonify(
            media=media,
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
                )
                archive = {
                    "saved": bool(case_id),
                    "case_id": case_id,
                    "clarification_available": bool(case_id),
                }
                if archive_failure == "limit":
                    archive["message"] = "Archivio pieno: elimina un caso prima di salvarne un altro."
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
