"""Single-owner SLPS pilot. No uploaded image is written to disk."""
from datetime import timedelta
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import io
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
import warnings

from flask import Flask, Request, jsonify, render_template, request, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from slps_ai import AnalysisError, analizza_immagine, is_analysis_configured

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_CONTEXT_CHARS = 8_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


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


def normalize_image(raw):
    """Validate content, reject animation, orient and remove all metadata."""
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("La foto deve avere una dimensione massima di 10 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ALLOWED_FORMATS:
                    raise ValueError("Usa una foto JPEG, PNG o WebP.")
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
                if result.tell() > MAX_FILE_BYTES:
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
        SESSION_COOKIE_SECURE=os.getenv("SLPS_COOKIE_SECURE", "true").lower() != "false",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES + 128 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=8,
        RATE_DB_PATH=os.getenv("SLPS_RATE_DB_PATH", str(Path(app.instance_path) / "limits.sqlite3")),
        ANALYSES_PER_HOUR=int(os.getenv("SLPS_ANALYSES_PER_HOUR", "10")),
        ANALYSIS_LEASE_SECONDS=180,
    )
    if test_config:
        app.config.update(test_config)
    store = LimitStore(app.config["RATE_DB_PATH"])
    app.extensions["limit_store"] = store

    def auth_configured():
        secret = app.config.get("SECRET_KEY")
        password = app.config.get("PILOT_PASSWORD")
        return bool(
            isinstance(secret, (str, bytes)) and len(secret) >= 32 and secret.strip()
            and isinstance(password, str) and len(password) >= 16 and password.strip()
        )

    def error(code, message, status):
        return jsonify(error={"code": code, "message": message}), status

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

    def protect(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not auth_configured():
                return error("configuration_missing", "Accesso pilota non ancora configurato.", 503)
            if not session.get("authenticated"):
                return error("authentication_required", "Accedi per utilizzare il progetto pilota.", 401)
            if not same_origin() or not csrf_valid():
                return error("invalid_csrf", "Sessione scaduta: ricarica la pagina e riprova.", 403)
            return fn(*args, **kwargs)
        return wrapped

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/api/session")
    def session_info():
        ready = is_analysis_configured()
        if not auth_configured():
            return jsonify(authenticated=False, csrf=None, configured=False, auth_configured=False, analysis_configured=ready)
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(authenticated=bool(session.get("authenticated")), csrf=session["csrf"], configured=ready, auth_configured=True, analysis_configured=ready)

    @app.post("/api/login")
    def login():
        if not auth_configured():
            return error("configuration_missing", "Accesso pilota non ancora configurato.", 503)
        if not same_origin() or not csrf_valid():
            return error("invalid_csrf", "Ricarica la pagina prima di accedere.", 403)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("password"), str) or len(payload["password"]) > 1024:
            return error("invalid_request", "Inserisci la password di accesso.", 400)
        success = hmac.compare_digest(payload["password"].encode(), str(app.config["PILOT_PASSWORD"]).encode())
        scope = hmac.new(str(app.config["SECRET_KEY"]).encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
        if not store.login(scope, success):
            return error("login_rate_limited", "Troppi tentativi. Attendi 15 minuti prima di riprovare.", 429)
        if not success:
            return error("invalid_credentials", "Password non valida.", 401)
        session.clear()
        session.permanent = True
        session["authenticated"] = True
        session["csrf"] = secrets.token_urlsafe(32)
        ready = is_analysis_configured()
        return jsonify(authenticated=True, csrf=session["csrf"], configured=ready, auth_configured=True, analysis_configured=ready)

    @app.post("/api/logout")
    @protect
    def logout():
        session.clear()
        return jsonify(authenticated=False)

    @app.post("/analizza")
    @protect
    def analizza():
        if not is_analysis_configured():
            return error("analysis_configuration_missing", "Il servizio di analisi non è ancora configurato.", 503)
        files = request.files.getlist("file")
        if len(files) != 1 or not files[0].filename:
            return error("invalid_file", "Seleziona una sola fotografia.", 400)
        context = request.form.get("context", "")
        if len(context) > MAX_CONTEXT_CHARS:
            return error("invalid_context", "Il contesto deve contenere al massimo 8000 caratteri.", 400)
        try:
            raw = files[0].stream.read(MAX_FILE_BYTES + 1)
            image, mime_type, width, height = normalize_image(raw)
        except ValueError as exc:
            return error("invalid_image", str(exc), 400)
        token, failure = store.reserve_analysis(app.config["ANALYSES_PER_HOUR"], app.config["ANALYSIS_LEASE_SECONDS"])
        if failure == "busy":
            return error("analysis_busy", "Un'analisi è già in corso. Attendi il risultato.", 409)
        if failure:
            return error("analysis_rate_limited", "Limite orario raggiunto. Attendi prima di avviare altre analisi.", 429)
        try:
            result = analizza_immagine(image, mime_type, context)
            return jsonify(analysis=result, image={"width": width, "height": height})
        except AnalysisError as exc:
            return error(exc.code, exc.message, exc.status)
        finally:
            store.release_analysis(token)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc):
        return error("file_too_large", "La foto deve avere una dimensione massima di 10 MB.", 413)

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
