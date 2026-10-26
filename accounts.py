"""Private local account store; company verification is an operator decision.

This module sends no mail and calls no external service. Token issuance is an
operator/delivery-adapter primitive, never a token-disclosing HTTP endpoint.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata

from werkzeug.security import check_password_hash, generate_password_hash

LOCALES = {"it", "de", "fr", "en"}
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("email")
    value = value.strip().casefold()
    if len(value) > 254 or not EMAIL.fullmatch(value):
        raise ValueError("email")
    return value


def valid_password(value):
    return isinstance(value, str) and 16 <= len(value) <= 256 and bool(value.strip())


def clean_text(value, name, maximum):
    if not isinstance(value, str):
        raise ValueError(name)
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(name)
    return value


def company_identity(name, identifier):
    name = clean_text(name, "company_name", 160)
    if identifier is None:
        identifier = ""
    if not isinstance(identifier, str) or len(identifier) > 80:
        raise ValueError("company_identifier")
    identifier = re.sub(r"[\s.\-]", "", unicodedata.normalize("NFKC", identifier)).upper()
    if identifier and not re.fullmatch(r"[A-Z0-9]{3,64}", identifier):
        raise ValueError("company_identifier")
    # A name match only prevents trivial duplicates; it does NOT verify a firm.
    key = "id:" + identifier if identifier else "name:" + name.casefold()
    return name, identifier, key


class AccountConflict(ValueError):
    pass


class ConsultationConflict(ValueError):
    """A consultation entitlement cannot be reserved or transitioned."""


def _future_period(start, months):
    """Return a UTC timestamp exactly ``months`` calendar months after start."""
    value = datetime.fromtimestamp(start, timezone.utc)
    month = value.month - 1 + months
    year, month = value.year + month // 12, month % 12 + 1
    days = (31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return value.replace(year=year, month=month, day=min(value.day, days[month - 1])).timestamp()


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class AccountStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account_companies (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    identifier TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE,
                    verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_users (
                    id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL, locale TEXT NOT NULL,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    membership_verified INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    session_version INTEGER NOT NULL DEFAULT 1,
                    created REAL NOT NULL,
                    FOREIGN KEY(company_id) REFERENCES account_companies(id)
                );
                CREATE TABLE IF NOT EXISTS account_tokens (
                    digest TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    purpose TEXT NOT NULL, expires REAL NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES account_users(id)
                );
                CREATE TABLE IF NOT EXISTS consultation_entitlements (
                    company_id TEXT PRIMARY KEY,
                    included INTEGER NOT NULL,
                    period_months INTEGER NOT NULL,
                    period_started REAL NOT NULL,
                    next_reset REAL NOT NULL,
                    updated REAL NOT NULL,
                    FOREIGN KEY(company_id) REFERENCES account_companies(id)
                );
                CREATE TABLE IF NOT EXISTS consultation_policies (
                    company_id TEXT PRIMARY KEY,
                    included INTEGER NOT NULL CHECK(included IN (0,1)),
                    period_months INTEGER NOT NULL CHECK(period_months IN (1,12)),
                    updated REAL NOT NULL,
                    FOREIGN KEY(company_id) REFERENCES account_companies(id)
                );
                CREATE TABLE IF NOT EXISTS consultation_requests (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    channel TEXT NOT NULL CHECK(channel IN ('phone','whatsapp')),
                    status TEXT NOT NULL CHECK(status IN ('reserved','used','cancelled')),
                    period_started REAL NOT NULL,
                    created REAL NOT NULL,
                    updated REAL NOT NULL,
                    used_at REAL,
                    cancelled_at REAL,
                    FOREIGN KEY(company_id) REFERENCES account_companies(id),
                    FOREIGN KEY(user_id) REFERENCES account_users(id)
                );
                CREATE INDEX IF NOT EXISTS consultation_requests_period
                    ON consultation_requests(company_id, period_started, status);
                CREATE INDEX IF NOT EXISTS consultation_requests_user
                    ON consultation_requests(company_id, user_id, created);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(consultation_requests)")}
            if "idempotency_key" not in columns:
                db.execute("ALTER TABLE consultation_requests ADD COLUMN idempotency_key TEXT")
                db.execute("UPDATE consultation_requests SET idempotency_key='legacy:' || id WHERE idempotency_key IS NULL")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS consultation_requests_idempotency
                          ON consultation_requests(company_id,user_id,idempotency_key)""")
        self.path.chmod(0o600)

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

    def register(self, *, email, password, company_name, company_identifier="", role, locale="it"):
        email = normalize_email(email)
        if not valid_password(password):
            raise ValueError("password")
        role = clean_text(role, "role", 100)
        if locale not in LOCALES:
            raise ValueError("locale")
        name, identifier, identity = company_identity(company_name, company_identifier)
        company_id, user_id = secrets.token_hex(16), secrets.token_hex(16)
        password_hash = generate_password_hash(password)
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO account_companies(id,name,identifier,identity_key,created) VALUES (?,?,?,?,?)",
                    (company_id, name, identifier, identity, time.time()),
                )
                db.execute(
                    """INSERT INTO account_users(id,company_id,email,password_hash,role,locale,created)
                       VALUES (?,?,?,?,?,?,?)""",
                    (user_id, company_id, email, password_hash, role, locale, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            # Neither auto-join a known company nor disclose the conflicting field.
            raise AccountConflict("registration_unavailable") from exc
        return self.get_user(user_id)

    def get_user(self, user_id):
        if not isinstance(user_id, str) or len(user_id) > 64:
            return None
        with self.connect() as db:
            row = db.execute(
                """SELECT u.*, c.name AS company_name, c.identifier AS company_identifier,
                          c.verified AS company_verified
                   FROM account_users u JOIN account_companies c ON c.id=u.company_id
                   WHERE u.id=? AND u.active=1""", (user_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def public(user):
        if not user:
            return None
        eligible = bool(user["email_verified"] and user["membership_verified"] and user["company_verified"])
        return {
            "id": user["id"], "email": user["email"], "role": user["role"], "locale": user["locale"],
            "email_verified": bool(user["email_verified"]),
            "membership_verified": bool(user["membership_verified"]),
            "company": {"id": user["company_id"], "name": user["company_name"],
                        "identifier": user["company_identifier"], "verified": bool(user["company_verified"])},
            "eligible_for_analysis": eligible,
        }

    def authenticate(self, email, password):
        try:
            email = normalize_email(email)
        except ValueError:
            email = ""
        if not isinstance(password, str) or len(password) > 256:
            password = ""
        with self.connect() as db:
            row = db.execute("SELECT id,password_hash FROM account_users WHERE email=? AND active=1", (email,)).fetchone()
        good = check_password_hash(row["password_hash"] if row else self._dummy_hash, password)
        return self.get_user(row["id"]) if row and good else None

    def issue_token(self, user_id, purpose, ttl=1800):
        """Trusted local/delivery-adapter operation. Raw token is never stored."""
        if purpose not in {"email", "reset"} or not 1 <= ttl <= 86400:
            raise ValueError("token_configuration")
        if not self.get_user(user_id):
            return None
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose=?", (user_id, purpose))
            db.execute("INSERT INTO account_tokens(digest,user_id,purpose,expires) VALUES (?,?,?,?)",
                       (digest, user_id, purpose, time.time() + ttl))
        return raw

    def consume_token(self, raw, purpose, new_password=None):
        if not isinstance(raw, str) or not 20 <= len(raw) <= 256 or purpose not in {"email", "reset"}:
            return False
        if purpose == "reset" and not valid_password(new_password):
            return False
        hashed = generate_password_hash(new_password) if purpose == "reset" else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT t.user_id FROM account_tokens t JOIN account_users u ON u.id=t.user_id
                   WHERE t.digest=? AND t.purpose=? AND t.used=0 AND t.expires>? AND u.active=1""",
                (hashlib.sha256(raw.encode()).hexdigest(), purpose, time.time()),
            ).fetchone()
            if not row:
                return False
            if purpose == "email":
                db.execute("UPDATE account_users SET email_verified=1 WHERE id=?", (row["user_id"],))
                db.execute("UPDATE account_tokens SET used=1 WHERE digest=?", (hashlib.sha256(raw.encode()).hexdigest(),))
            else:
                db.execute("UPDATE account_users SET password_hash=?,session_version=session_version+1 WHERE id=?", (hashed, row["user_id"]))
                db.execute("DELETE FROM account_tokens WHERE user_id=?", (row["user_id"],))
        return True

    def verify_company(self, company_id, representative_user_id):
        """Trusted operator action after actual company/representation checks.

        This is intentionally not exposed as an HTTP endpoint or auto-invoked by
        email confirmation. Local tests simulate the operator decision.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT 1 FROM account_users WHERE id=? AND company_id=? AND active=1",
                              (representative_user_id, company_id)).fetchone()
            if not user:
                raise ValueError("representative")
            db.execute("UPDATE account_companies SET verified=1 WHERE id=?", (company_id,))
            db.execute("UPDATE account_users SET membership_verified=1 WHERE id=?", (representative_user_id,))

    def add_member(self, company_id, *, email, password, role, locale="it", approved=False):
        """Trusted provisioning only; no public auto-join by company identifier."""
        email = normalize_email(email)
        role = clean_text(role, "role", 100)
        if not valid_password(password) or locale not in LOCALES:
            raise ValueError("member")
        user_id = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("""INSERT INTO account_users
                       (id,company_id,email,password_hash,role,locale,membership_verified,created)
                       VALUES (?,?,?,?,?,?,?,?)""",
                       (user_id, company_id, email, generate_password_hash(password), role, locale, int(bool(approved)), time.time()))
        return self.get_user(user_id)

    @staticmethod
    def _consultation_policy(included, period_months):
        if isinstance(included, bool) or included not in {0, 1}:
            raise ValueError("consultation_included")
        if isinstance(period_months, bool) or period_months not in {1, 12}:
            raise ValueError("consultation_period")
        return included, period_months

    def assign_consultation_policy(self, company_id, *, included, period_months, now=None):
        """Trusted provisioning only; intentionally has no public HTTP endpoint."""
        included, period_months = self._consultation_policy(included, period_months)
        now = time.time() if now is None else float(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM account_companies WHERE id=?", (company_id,)).fetchone():
                raise ValueError("company")
            db.execute(
                """INSERT INTO consultation_policies(company_id,included,period_months,updated)
                   VALUES (?,?,?,?) ON CONFLICT(company_id) DO UPDATE SET
                   included=excluded.included,period_months=excluded.period_months,
                   updated=excluded.updated""",
                (company_id, included, period_months, now),
            )

    @staticmethod
    def _stored_consultation_policy(db, company_id):
        row = db.execute(
            "SELECT included,period_months FROM consultation_policies WHERE company_id=?",
            (company_id,),
        ).fetchone()
        return (row["included"], row["period_months"]) if row else (0, 12)

    def _consultation_user(self, db, company_id, user_id):
        return db.execute(
            """SELECT 1 FROM account_users u JOIN account_companies c ON c.id=u.company_id
               WHERE u.id=? AND u.company_id=? AND u.active=1 AND u.email_verified=1
                 AND u.membership_verified=1 AND c.verified=1""",
            (user_id, company_id),
        ).fetchone()

    def _ensure_consultation_period(self, db, company_id, now):
        company = db.execute("SELECT 1 FROM account_companies WHERE id=?", (company_id,)).fetchone()
        if not company:
            raise ValueError("company")
        included, period_months = self._stored_consultation_policy(db, company_id)
        row = db.execute(
            "SELECT * FROM consultation_entitlements WHERE company_id=?", (company_id,)
        ).fetchone()
        if row is None or now >= row["next_reset"]:
            started, next_reset = now, _future_period(now, period_months)
            db.execute(
                """INSERT INTO consultation_entitlements
                   (company_id,included,period_months,period_started,next_reset,updated)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(company_id) DO UPDATE SET included=excluded.included,
                   period_months=excluded.period_months,period_started=excluded.period_started,
                   next_reset=excluded.next_reset,updated=excluded.updated""",
                (company_id, included, period_months, started, next_reset, now),
            )
        elif row["included"] != included or row["period_months"] != period_months:
            # Configuration is a draft hypothesis. Preserve the current period and
            # past requests while updating only its allowance/cadence metadata.
            next_reset = _future_period(row["period_started"], period_months)
            if now >= next_reset:
                started, next_reset = now, _future_period(now, period_months)
            else:
                started = row["period_started"]
            db.execute(
                """UPDATE consultation_entitlements SET included=?,period_months=?,
                   period_started=?,next_reset=?,updated=? WHERE company_id=?""",
                (included, period_months, started, next_reset, now, company_id),
            )
        return db.execute(
            "SELECT * FROM consultation_entitlements WHERE company_id=?", (company_id,)
        ).fetchone()

    @staticmethod
    def _consultation_payload(db, entitlement, user_id):
        counts = {"reserved": 0, "used": 0, "cancelled": 0}
        for row in db.execute(
            """SELECT status,COUNT(*) AS amount FROM consultation_requests
               WHERE company_id=? AND period_started=? AND status IN ('reserved','used','cancelled')
               GROUP BY status""",
            (entitlement["company_id"], entitlement["period_started"]),
        ):
            counts[row["status"]] = row["amount"]
        requests = [dict(row) for row in db.execute(
            """SELECT id,case_id,user_id,channel,status,period_started,created,updated,used_at,cancelled_at
               FROM consultation_requests WHERE company_id=? AND user_id=?
               ORDER BY created DESC,id DESC LIMIT 50""",
            (entitlement["company_id"], user_id),
        ).fetchall()]
        included = entitlement["included"]
        return {
            "included": included,
            "reserved": counts["reserved"],
            "used": counts["used"],
            "cancelled": counts["cancelled"],
            # Draft policy: cancellation records the outcome but never silently
            # restores an allowance. Carryover/refund rules remain undecided.
            "balance": max(0, included - counts["reserved"] - counts["used"] - counts["cancelled"]),
            "next_reset": _utc(entitlement["next_reset"]),
            "period_started": _utc(entitlement["period_started"]),
            "period_months": entitlement["period_months"],
            "requests": requests,
        }

    def consultation_status(self, company_id, user_id, *, now=None):
        now = time.time() if now is None else float(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._consultation_user(db, company_id, user_id):
                raise ValueError("user")
            entitlement = self._ensure_consultation_period(db, company_id, now)
            return self._consultation_payload(db, entitlement, user_id)

    def reserve_consultation(self, company_id, user_id, case_id, channel, *, idempotency_key,
                             now=None):
        """Atomically reserve one company allowance; this performs no contact."""
        now = time.time() if now is None else float(now)
        case_id = clean_text(case_id, "case_id", 64)
        idempotency_key = clean_text(idempotency_key, "idempotency_key", 128)
        if channel not in {"phone", "whatsapp"}:
            raise ValueError("channel")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._consultation_user(db, company_id, user_id):
                raise ValueError("user")
            entitlement = self._ensure_consultation_period(db, company_id, now)
            previous = db.execute(
                """SELECT id,case_id,channel FROM consultation_requests
                   WHERE company_id=? AND user_id=? AND idempotency_key=?""",
                (company_id, user_id, idempotency_key),
            ).fetchone()
            if previous:
                if previous["case_id"] != case_id or previous["channel"] != channel:
                    raise ConsultationConflict("idempotency_mismatch")
                payload = self._consultation_payload(db, entitlement, user_id)
                payload["request_id"] = previous["id"]
                payload["idempotent_replay"] = True
                return payload
            state = self._consultation_payload(db, entitlement, user_id)
            if state["balance"] < 1:
                raise ConsultationConflict("consultation_unavailable")
            request_id = secrets.token_hex(16)
            db.execute(
                """INSERT INTO consultation_requests
                   (id,company_id,user_id,case_id,idempotency_key,channel,status,period_started,created,updated)
                   VALUES (?,?,?,?,?,?,'reserved',?,?,?)""",
                (request_id, company_id, user_id, case_id, idempotency_key, channel,
                 entitlement["period_started"], now, now),
            )
            entitlement = db.execute(
                "SELECT * FROM consultation_entitlements WHERE company_id=?", (company_id,)
            ).fetchone()
            payload = self._consultation_payload(db, entitlement, user_id)
            payload["request_id"] = request_id
            return payload

    def _transition_consultation(self, request_id, company_id, user_id, target, now=None):
        if target not in {"used", "cancelled"}:
            raise ValueError("status")
        now = time.time() if now is None else float(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._consultation_user(db, company_id, user_id):
                raise ValueError("user")
            row = db.execute(
                """SELECT * FROM consultation_requests
                   WHERE id=? AND company_id=? AND user_id=?""",
                (request_id, company_id, user_id),
            ).fetchone()
            if not row:
                raise ConsultationConflict("consultation_not_found")
            if row["status"] == target:
                return True
            if row["status"] != "reserved":
                raise ConsultationConflict("consultation_already_final")
            field = "used_at" if target == "used" else "cancelled_at"
            db.execute(
                f"UPDATE consultation_requests SET status=?,updated=?,{field}=? WHERE id=?",
                (target, now, now, request_id),
            )
            return True

    def mark_consultation_used(self, request_id, company_id, user_id, *, now=None):
        """Trusted fulfilment transition; intentionally not a public HTTP action."""
        return self._transition_consultation(request_id, company_id, user_id, "used", now)

    def cancel_consultation(self, request_id, company_id, user_id, *, now=None):
        return self._transition_consultation(request_id, company_id, user_id, "cancelled", now)
