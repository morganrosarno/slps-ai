"""Private local account store; company verification is an operator decision.

This module sends no mail and calls no external service. Token issuance is an
operator/delivery-adapter primitive, never a token-disclosing HTTP endpoint.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata

from werkzeug.security import check_password_hash, generate_password_hash
from storage_contracts import SQLiteMigration, apply_sqlite_migrations, migration_versions

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


class BillingSandboxConflict(ValueError):
    """A non-transactional checkout simulation cannot be created or changed."""


class VerificationReviewConflict(ValueError):
    """A company or membership review cannot be transitioned safely."""


class VerificationAuthorizationError(PermissionError):
    """The trusted operator review capability is missing or invalid."""


VERIFICATION_REVIEW_KINDS = {"company_representative", "membership"}
VERIFICATION_APPROVAL_CODES = {"identity_and_authority_confirmed", "membership_confirmed"}
VERIFICATION_REJECTION_CODES = {
    "company_identity_unverified", "representative_authority_unverified",
    "membership_unverified", "conflicting_company_record", "insufficient_evidence",
}
VERIFICATION_EVIDENCE_CATEGORIES = {
    "company_representative": {
        "commercial_register_extract", "representative_authority_record",
    },
    "membership": {"membership_authority_record"},
}
VERIFICATION_REQUIRED_APPROVAL_EVIDENCE = {
    "company_representative": {
        "commercial_register_extract", "representative_authority_record",
    },
    "membership": {"membership_authority_record"},
}


BILLING_CATALOG_REVISION = "draft-2026-10-26-v1"
BILLING_CYCLES = {"monthly", "annual"}
BILLING_PLAN_CODES = {
    "tier_essential_v1", "tier_team_v1", "tier_partner_v1",
}


def billing_catalog():
    """Return the immutable draft used by the local checkout simulation.

    Names, prices, VAT and quota periods deliberately remain unapproved.  The
    stable codes can survive later copy changes without pretending that a
    commercial offer already exists.
    """
    plans = [{
        "plan_code": "trial_company_v1",
        "display_name": "Prova aziendale (bozza)",
        "selectable": False,
        "billing_cycles": [],
        "price": {"amount_chf": None, "status": "draft_unapproved"},
        "quota": {"analyses": 1, "period": "once_per_verified_company"},
        "video_status": "not_for_sale",
        "specialist_policy": "not_included",
    }]
    labels = {
        "tier_essential_v1": "Piano 1 (nome da approvare)",
        "tier_team_v1": "Piano 2 (nome da approvare)",
        "tier_partner_v1": "Piano 3 (nome da approvare)",
    }
    for code in ("tier_essential_v1", "tier_team_v1", "tier_partner_v1"):
        plans.append({
            "plan_code": code,
            "display_name": labels[code],
            "selectable": True,
            "billing_cycles": ["monthly", "annual"],
            "price": {"amount_chf": None, "status": "draft_unapproved"},
            "quota": {"analyses": None, "period": "TBD"},
            "video_status": "not_for_sale",
            "specialist_policy": "TBD",
        })
    return {
        "catalog_revision": BILLING_CATALOG_REVISION,
        "status": "draft_unapproved",
        "simulation": True,
        "charged": False,
        "subscription_active": False,
        "plans": plans,
    }


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


def _migrate_accounts_v1(db):
    statements = (
        """CREATE TABLE IF NOT EXISTS account_companies (
               id TEXT PRIMARY KEY, name TEXT NOT NULL,
               identifier TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE,
               verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS account_users (
               id TEXT PRIMARY KEY, company_id TEXT NOT NULL,
               email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
               role TEXT NOT NULL, locale TEXT NOT NULL,
               email_verified INTEGER NOT NULL DEFAULT 0,
               membership_verified INTEGER NOT NULL DEFAULT 0,
               active INTEGER NOT NULL DEFAULT 1,
               session_version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
               FOREIGN KEY(company_id) REFERENCES account_companies(id))""",
        """CREATE TABLE IF NOT EXISTS account_tokens (
               digest TEXT PRIMARY KEY, user_id TEXT NOT NULL,
               purpose TEXT NOT NULL, expires REAL NOT NULL,
               used INTEGER NOT NULL DEFAULT 0,
               FOREIGN KEY(user_id) REFERENCES account_users(id))""",
        """CREATE TABLE IF NOT EXISTS consultation_entitlements (
               company_id TEXT PRIMARY KEY, included INTEGER NOT NULL,
               period_months INTEGER NOT NULL, period_started REAL NOT NULL,
               next_reset REAL NOT NULL, updated REAL NOT NULL,
               FOREIGN KEY(company_id) REFERENCES account_companies(id))""",
        """CREATE TABLE IF NOT EXISTS consultation_policies (
               company_id TEXT PRIMARY KEY,
               included INTEGER NOT NULL CHECK(included IN (0,1)),
               period_months INTEGER NOT NULL CHECK(period_months IN (1,12)),
               updated REAL NOT NULL,
               FOREIGN KEY(company_id) REFERENCES account_companies(id))""",
        """CREATE TABLE IF NOT EXISTS consultation_requests (
               id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
               case_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
               channel TEXT NOT NULL CHECK(channel IN ('phone','whatsapp')),
               status TEXT NOT NULL CHECK(status IN ('reserved','used','cancelled')),
               period_started REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
               used_at REAL, cancelled_at REAL,
               FOREIGN KEY(company_id) REFERENCES account_companies(id),
               FOREIGN KEY(user_id) REFERENCES account_users(id))""",
        "CREATE INDEX IF NOT EXISTS consultation_requests_period ON consultation_requests(company_id,period_started,status)",
        "CREATE INDEX IF NOT EXISTS consultation_requests_user ON consultation_requests(company_id,user_id,created)",
    )
    for statement in statements:
        db.execute(statement)
    # Positional access keeps migrations independent of connection row_factory.
    columns = {row[1] for row in db.execute("PRAGMA table_info(consultation_requests)")}
    if "idempotency_key" not in columns:
        db.execute("ALTER TABLE consultation_requests ADD COLUMN idempotency_key TEXT")
        db.execute("UPDATE consultation_requests SET idempotency_key='legacy:' || id WHERE idempotency_key IS NULL")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS consultation_requests_idempotency
                  ON consultation_requests(company_id,user_id,idempotency_key)""")


def _migrate_billing_v1(db):
    db.execute("""CREATE TABLE IF NOT EXISTS billing_checkout_intents (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
        catalog_revision TEXT NOT NULL, plan_code TEXT NOT NULL, billing_cycle TEXT NOT NULL,
        idempotency_key_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft','confirmed_simulation','cancelled')),
        created REAL NOT NULL, expires REAL NOT NULL, confirmed REAL, cancelled REAL,
        FOREIGN KEY(company_id) REFERENCES account_companies(id),
        FOREIGN KEY(user_id) REFERENCES account_users(id),
        UNIQUE(company_id,user_id,idempotency_key_hash))""")
    db.execute("CREATE INDEX IF NOT EXISTS billing_checkout_owner ON billing_checkout_intents(company_id,user_id,created)")
    db.execute("""CREATE TABLE IF NOT EXISTS billing_checkout_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL,
        company_id TEXT NOT NULL, user_id TEXT NOT NULL, event TEXT NOT NULL,
        created REAL NOT NULL,
        FOREIGN KEY(intent_id) REFERENCES billing_checkout_intents(id))""")


def _migrate_billing_expiry_v1(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(billing_checkout_intents)")}
    if "expired" not in columns:
        db.execute("ALTER TABLE billing_checkout_intents ADD COLUMN expired REAL")


def _verification_event_hash(review_id, sequence, event, decision_code, actor_digest,
                             idempotency_key_hash, created, previous_hash,
                             evidence_bundle_hash=None):
    fields = [review_id, sequence, event, decision_code or "", actor_digest or "",
              idempotency_key_hash, float(created), previous_hash or ""]
    if evidence_bundle_hash is not None:
        fields.append(evidence_bundle_hash)
    payload = json.dumps(
        fields,
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _unchecked_verification_audit(db, review):
    if not review:
        raise VerificationReviewConflict("verification_review_unavailable")
    rows = db.execute(
        """SELECT sequence,event,decision_code,actor_digest,
                  idempotency_key_hash,created,previous_hash,event_hash,
                  evidence_bundle_hash
           FROM account_verification_audit WHERE review_id=?
           ORDER BY sequence""",
        (review["id"],),
    ).fetchall()
    if not rows or len(rows) > 2 or len(rows) != int(review["version"]):
        raise VerificationReviewConflict("verification_audit_invalid")
    previous = None
    for expected_sequence, row in enumerate(rows, start=1):
        expected = _verification_event_hash(
            review["id"], row["sequence"], row["event"], row["decision_code"],
            row["actor_digest"], row["idempotency_key_hash"], row["created"],
            previous, row["evidence_bundle_hash"],
        )
        if (row["sequence"] != expected_sequence or row["previous_hash"] != previous
                or not hmac.compare_digest(row["event_hash"], expected)):
            raise VerificationReviewConflict("verification_audit_invalid")
        previous = row["event_hash"]
    first, last = rows[0], rows[-1]
    if (first["event"] != "submitted" or first["decision_code"] is not None
            or first["actor_digest"] is not None or first["previous_hash"] is not None
            or not hmac.compare_digest(previous, review["audit_head"])):
        raise VerificationReviewConflict("verification_audit_invalid")
    expected_final_events = {
        "pending": {"submitted"},
        "approved": {"approved", "trusted_fixture_approved"},
        "rejected": {"rejected"},
    }
    if last["event"] not in expected_final_events.get(review["status"], set()):
        raise VerificationReviewConflict("verification_audit_invalid")
    if review["status"] == "pending":
        if (len(rows) != 1 or review["decision_key_hash"] is not None
                or review["decision_code"] is not None
                or review["decision_actor_digest"] is not None):
            raise VerificationReviewConflict("verification_audit_invalid")
    elif (review["decision_key_hash"] != last["idempotency_key_hash"]
          or review["decision_code"] != last["decision_code"]
          or review["decision_actor_digest"] != last["actor_digest"]):
        raise VerificationReviewConflict("verification_audit_invalid")
    if last["evidence_bundle_hash"] is not None:
        links = db.execute(
            """SELECT receipt_id,receipt_hash
               FROM account_verification_decision_evidence
               WHERE review_id=? ORDER BY receipt_id""",
            (review["id"],),
        ).fetchall()
        if not links:
            raise VerificationReviewConflict("verification_audit_invalid")
        receipt_hashes = []
        for link in links:
            receipt = db.execute(
                "SELECT * FROM account_verification_evidence_receipts WHERE id=?",
                (link["receipt_id"],),
            ).fetchone()
            if (receipt is None or receipt["review_id"] != review["id"]
                    or not hmac.compare_digest(link["receipt_hash"], receipt["receipt_hash"])
                    or not hmac.compare_digest(receipt["receipt_hash"],
                                               _verification_evidence_hash(receipt))):
                raise VerificationReviewConflict("verification_audit_invalid")
            receipt_hashes.append(receipt["receipt_hash"])
        expected_bundle = _verification_evidence_bundle_hash(review["id"], receipt_hashes)
        if not hmac.compare_digest(last["evidence_bundle_hash"], expected_bundle):
            raise VerificationReviewConflict("verification_audit_invalid")
    elif db.execute(
        "SELECT 1 FROM account_verification_decision_evidence WHERE review_id=? LIMIT 1",
        (review["id"],),
    ).fetchone() is not None:
        raise VerificationReviewConflict("verification_audit_invalid")
    return rows


def _verification_evidence_hash(receipt):
    payload = json.dumps([
        receipt["id"], receipt["review_id"], receipt["category"],
        receipt["content_sha256"], float(receipt["observed_at"]),
        float(receipt["verified_at"]),
        float(receipt["expires_at"]) if receipt["expires_at"] is not None else None,
        receipt["verifier_digest"], receipt["receipt_key_hash"],
        float(receipt["created"]),
    ], ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _verification_evidence_bundle_hash(review_id, receipt_hashes):
    payload = json.dumps(
        [review_id, sorted(receipt_hashes)],
        ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _verified_verification_audit(db, review):
    """Load and validate one review's complete audit chain in ``db``'s snapshot."""
    try:
        return _unchecked_verification_audit(db, review)
    except VerificationReviewConflict:
        raise
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise VerificationReviewConflict("verification_audit_invalid") from exc


def _insert_verification_review(db, company_id, subject_user_id, review_kind, created):
    if review_kind not in VERIFICATION_REVIEW_KINDS:
        raise ValueError("verification_review_kind")
    review_id = secrets.token_hex(16)
    submission_hash = hashlib.sha256(
        f"registration:{review_kind}:{company_id}:{subject_user_id}".encode("ascii")
    ).hexdigest()
    event_hash = _verification_event_hash(
        review_id, 1, "submitted", None, None, submission_hash, created, None
    )
    db.execute(
        """INSERT OR IGNORE INTO account_verification_reviews
           (id,review_kind,company_id,subject_user_id,status,submission_key_hash,
            created,updated,audit_head,version)
           VALUES (?,?,?,?,?,?,?,?,?,1)""",
        (review_id, review_kind, company_id, subject_user_id, "pending",
         submission_hash, created, created, event_hash),
    )
    row = db.execute(
        """SELECT id FROM account_verification_reviews
           WHERE review_kind=? AND company_id=? AND subject_user_id=?""",
        (review_kind, company_id, subject_user_id),
    ).fetchone()
    actual_id = row[0]
    if actual_id == review_id:
        db.execute(
            """INSERT INTO account_verification_audit
               (review_id,sequence,event,decision_code,actor_digest,
                idempotency_key_hash,created,previous_hash,event_hash)
               VALUES (?,1,'submitted',NULL,NULL,?,?,NULL,?)""",
            (review_id, submission_hash, created, event_hash),
        )
    return actual_id


def _migrate_verification_reviews_v1(db):
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_operator_meta (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        secret_fingerprint TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_reviews (
        id TEXT PRIMARY KEY,
        review_kind TEXT NOT NULL CHECK(review_kind IN ('company_representative','membership')),
        company_id TEXT NOT NULL, subject_user_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
        submission_key_hash TEXT NOT NULL,
        decision_key_hash TEXT, decision_code TEXT, decision_actor_digest TEXT,
        created REAL NOT NULL, updated REAL NOT NULL, decided REAL,
        audit_head TEXT NOT NULL, version INTEGER NOT NULL,
        FOREIGN KEY(company_id) REFERENCES account_companies(id),
        FOREIGN KEY(subject_user_id) REFERENCES account_users(id),
        UNIQUE(review_kind,company_id,subject_user_id),
        UNIQUE(decision_key_hash))""")
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        event TEXT NOT NULL CHECK(event IN ('submitted','approved','rejected','trusted_fixture_approved')),
        decision_code TEXT, actor_digest TEXT,
        idempotency_key_hash TEXT NOT NULL, created REAL NOT NULL,
        previous_hash TEXT, event_hash TEXT NOT NULL UNIQUE,
        FOREIGN KEY(review_id) REFERENCES account_verification_reviews(id),
        UNIQUE(review_id,sequence))""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS account_verification_audit_no_update
        BEFORE UPDATE ON account_verification_audit
        BEGIN SELECT RAISE(ABORT,'verification_audit_append_only'); END""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS account_verification_audit_no_delete
        BEFORE DELETE ON account_verification_audit
        BEGIN SELECT RAISE(ABORT,'verification_audit_append_only'); END""")
    db.execute("CREATE INDEX IF NOT EXISTS account_verification_queue ON account_verification_reviews(status,created,id)")
    companies = db.execute(
        "SELECT id,verified,created FROM account_companies ORDER BY created,id"
    ).fetchall()
    for company in companies:
        company_id, verified, company_created = company[0], bool(company[1]), float(company[2])
        users = db.execute(
            """SELECT id,membership_verified,created FROM account_users
               WHERE company_id=? AND active=1 ORDER BY created,id""",
            (company_id,),
        ).fetchall()
        if not users:
            continue
        if not verified:
            _insert_verification_review(
                db, company_id, users[0][0], "company_representative",
                max(company_created, float(users[0][2])),
            )
            for user in users[1:]:
                if not bool(user[1]):
                    _insert_verification_review(
                        db, company_id, user[0], "membership", float(user[2])
                    )
        else:
            for user in users:
                if not bool(user[1]):
                    _insert_verification_review(
                        db, company_id, user[0], "membership", float(user[2])
                    )


def _migrate_verification_evidence_v1(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(account_verification_audit)")}
    if "evidence_bundle_hash" not in columns:
        db.execute("ALTER TABLE account_verification_audit ADD COLUMN evidence_bundle_hash TEXT")
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_evidence_receipts (
        id TEXT PRIMARY KEY, review_id TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN (
            'commercial_register_extract','representative_authority_record',
            'membership_authority_record')),
        content_sha256 TEXT NOT NULL, observed_at REAL NOT NULL,
        verified_at REAL NOT NULL, expires_at REAL,
        verifier_digest TEXT NOT NULL, receipt_key_hash TEXT NOT NULL UNIQUE,
        created REAL NOT NULL, receipt_hash TEXT NOT NULL UNIQUE,
        FOREIGN KEY(review_id) REFERENCES account_verification_reviews(id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS account_verification_decision_evidence (
        review_id TEXT NOT NULL, receipt_id TEXT NOT NULL, receipt_hash TEXT NOT NULL,
        PRIMARY KEY(review_id,receipt_id),
        FOREIGN KEY(review_id) REFERENCES account_verification_reviews(id),
        FOREIGN KEY(receipt_id) REFERENCES account_verification_evidence_receipts(id))""")
    for table in ("account_verification_evidence_receipts",
                  "account_verification_decision_evidence"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT,'verification_evidence_append_only'); END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT,'verification_evidence_append_only'); END""")
    db.execute("""CREATE INDEX IF NOT EXISTS account_verification_evidence_review
                  ON account_verification_evidence_receipts(review_id,category,created,id)""")
ACCOUNT_MIGRATIONS = (
    SQLiteMigration(1, "accounts_and_consultations_v1", hashlib.sha256(b"accounts-v1-20261026").hexdigest(), _migrate_accounts_v1),
    SQLiteMigration(2, "billing_sandbox_v1", hashlib.sha256(b"billing-v1-20261026").hexdigest(), _migrate_billing_v1),
    SQLiteMigration(3, "billing_expiry_v1", hashlib.sha256(b"billing-expiry-v1-20261026").hexdigest(), _migrate_billing_expiry_v1),
    SQLiteMigration(4, "verification_reviews_v1", hashlib.sha256(b"verification-reviews-v1-20261028").hexdigest(), _migrate_verification_reviews_v1),
    SQLiteMigration(5, "verification_evidence_v1", hashlib.sha256(b"verification-evidence-v1-20261028").hexdigest(), _migrate_verification_evidence_v1),
)


class AccountStore:
    durable = False

    def __init__(self, path, *, verification_operator_secret=None,
                 allow_test_verification=False):
        if (verification_operator_secret is not None
                and (not isinstance(verification_operator_secret, bytes)
                     or not 32 <= len(verification_operator_secret) <= 256)):
            raise VerificationAuthorizationError("verification_operator_configuration_invalid")
        if type(allow_test_verification) is not bool:
            raise VerificationAuthorizationError("verification_operator_configuration_invalid")
        self.path = Path(path)
        self._verification_operator_secret = (
            bytes(verification_operator_secret)
            if verification_operator_secret is not None else None
        )
        self._allow_test_verification = allow_test_verification
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
        with self.connect() as db:
            apply_sqlite_migrations(db, "accounts", ACCOUNT_MIGRATIONS)
        self._bind_verification_operator_secret()
        self.path.chmod(0o600)

    def _bind_verification_operator_secret(self):
        if self._verification_operator_secret is None:
            return
        fingerprint = hashlib.sha256(self._verification_operator_secret).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT secret_fingerprint FROM account_verification_operator_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO account_verification_operator_meta VALUES (1,?)",
                    (fingerprint,),
                )
            elif not hmac.compare_digest(str(row[0]), fingerprint):
                raise VerificationAuthorizationError("verification_operator_secret_mismatch")

    def _authorize_verification_operator(self, authorization):
        if (self._verification_operator_secret is None
                or not isinstance(authorization, bytes)
                or not hmac.compare_digest(self._verification_operator_secret, authorization)):
            raise VerificationAuthorizationError("verification_operator_unauthorized")

    def schema_versions(self):
        with self.connect() as db:
            return migration_versions(db, "accounts")

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
                _insert_verification_review(
                    db, company_id, user_id, "company_representative", time.time()
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
        if not self._allow_test_verification:
            raise VerificationAuthorizationError("trusted_fixture_verification_disabled")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT 1 FROM account_users WHERE id=? AND company_id=? AND active=1",
                              (representative_user_id, company_id)).fetchone()
            if not user:
                raise ValueError("representative")
            db.execute("UPDATE account_companies SET verified=1 WHERE id=?", (company_id,))
            db.execute("UPDATE account_users SET membership_verified=1 WHERE id=?", (representative_user_id,))
            review = db.execute(
                """SELECT * FROM account_verification_reviews
                   WHERE review_kind='company_representative' AND company_id=?
                     AND subject_user_id=?""",
                (company_id, representative_user_id),
            ).fetchone()
            if review and review["status"] == "pending":
                now = time.time()
                idem = hashlib.sha256(
                    f"trusted-fixture:{review['id']}".encode("ascii")
                ).hexdigest()
                event_hash = _verification_event_hash(
                    review["id"], review["version"] + 1, "trusted_fixture_approved",
                    "trusted_test_fixture", None, idem, now, review["audit_head"],
                )
                db.execute(
                    """INSERT INTO account_verification_audit
                       (review_id,sequence,event,decision_code,actor_digest,
                        idempotency_key_hash,created,previous_hash,event_hash)
                       VALUES (?,?,?,?,NULL,?,?,?,?)""",
                    (review["id"], review["version"] + 1, "trusted_fixture_approved",
                     "trusted_test_fixture", idem, now, review["audit_head"], event_hash),
                )
                db.execute(
                    """UPDATE account_verification_reviews
                       SET status='approved',decision_key_hash=?,decision_code='trusted_test_fixture',
                           updated=?,decided=?,audit_head=?,version=version+1
                       WHERE id=?""",
                    (idem, now, now, event_hash, review["id"]),
                )

    def add_member(self, company_id, *, email, password, role, locale="it", approved=False):
        """Trusted provisioning only; no public auto-join by company identifier."""
        email = normalize_email(email)
        role = clean_text(role, "role", 100)
        if not valid_password(password) or locale not in LOCALES:
            raise ValueError("member")
        user_id = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT INTO account_users
                       (id,company_id,email,password_hash,role,locale,membership_verified,created)
                       VALUES (?,?,?,?,?,?,?,?)""",
                       (user_id, company_id, email, generate_password_hash(password), role, locale, int(bool(approved)), time.time()))
            if not approved:
                _insert_verification_review(
                    db, company_id, user_id, "membership", time.time()
                )
        return self.get_user(user_id)

    @staticmethod
    def _review_public(row):
        return {
            "id": row["id"], "kind": row["review_kind"],
            "company_id": row["company_id"], "subject_user_id": row["subject_user_id"],
            "status": row["status"], "decision_code": row["decision_code"],
            "created_at_utc": _utc(row["created"]), "updated_at_utc": _utc(row["updated"]),
            "decided_at_utc": _utc(row["decided"]) if row["decided"] is not None else None,
            "version": row["version"],
        }

    def list_verification_reviews(self, *, authorization, status="pending", limit=50):
        """Return a redacted operator queue; no public route calls this method."""
        self._authorize_verification_operator(authorization)
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("verification_review_status")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("verification_review_limit")
        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute(
                """SELECT * FROM account_verification_reviews
                   WHERE status=? ORDER BY created,id LIMIT ?""",
                (status, limit),
            ).fetchall()
            for row in rows:
                _verified_verification_audit(db, row)
        return [self._review_public(row) for row in rows]

    def verification_review_audit(self, review_id, *, authorization):
        """Return the append-only, redacted audit chain for one review."""
        self._authorize_verification_operator(authorization)
        if not isinstance(review_id, str) or not re.fullmatch(r"[a-f0-9]{32}", review_id):
            raise ValueError("verification_review_id")
        with self.connect() as db:
            db.execute("BEGIN")
            review = db.execute(
                "SELECT * FROM account_verification_reviews WHERE id=?", (review_id,)
            ).fetchone()
            rows = _verified_verification_audit(db, review)
        return [{
            "sequence": row["sequence"], "event": row["event"],
            "decision_code": row["decision_code"],
            "operator_digest": row["actor_digest"],
            "created_at_utc": _utc(row["created"]),
            "previous_hash": row["previous_hash"], "event_hash": row["event_hash"],
            "evidence_bound": row["evidence_bundle_hash"] is not None,
        } for row in rows]

    @staticmethod
    def _evidence_public(row):
        return {
            "id": row["id"], "category": row["category"],
            "observed_at_utc": _utc(row["observed_at"]),
            "verified_at_utc": _utc(row["verified_at"]),
            "expires_at_utc": _utc(row["expires_at"]),
            "integrity_verified": True,
        }

    def record_verification_evidence(self, review_id, *, category, content_sha256,
                                     observed_at, verified_at, expires_at,
                                     verifier_ref, idempotency_key, authorization,
                                     now=None):
        """Record only a digest and bounded metadata for evidence inspected offline."""
        self._authorize_verification_operator(authorization)
        if not isinstance(review_id, str) or not re.fullmatch(r"[a-f0-9]{32}", review_id):
            raise ValueError("verification_review_id")
        if not isinstance(content_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
            raise ValueError("verification_evidence_digest")
        verifier_ref = clean_text(verifier_ref, "verification_operator", 80)
        if (not isinstance(idempotency_key, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{31,127}", idempotency_key)):
            raise ValueError("verification_idempotency_key")
        try:
            observed_at = float(observed_at)
            verified_at = float(verified_at)
            expires_at = float(expires_at)
            now = time.time() if now is None else float(now)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("verification_evidence_time") from exc
        if (not all(0 <= value < float("inf") for value in
                    (observed_at, verified_at, expires_at, now))
                or observed_at > verified_at or verified_at > now
                or expires_at <= now):
            raise ValueError("verification_evidence_time")
        secret = self._verification_operator_secret
        verifier_digest = hmac.new(
            secret, ("actor:" + verifier_ref).encode(), hashlib.sha256,
        ).hexdigest()
        receipt_key_hash = hmac.new(
            secret, ("evidence:" + idempotency_key).encode(), hashlib.sha256,
        ).hexdigest()
        receipt_id = secrets.token_hex(16)
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                review = db.execute(
                    "SELECT * FROM account_verification_reviews WHERE id=?", (review_id,),
                ).fetchone()
                if review is None:
                    raise VerificationReviewConflict("verification_review_unavailable")
                _verified_verification_audit(db, review)
                if review["status"] != "pending":
                    raise VerificationReviewConflict("verification_review_already_decided")
                if category not in VERIFICATION_EVIDENCE_CATEGORIES[review["review_kind"]]:
                    raise ValueError("verification_evidence_category")
                existing = db.execute(
                    "SELECT * FROM account_verification_evidence_receipts WHERE receipt_key_hash=?",
                    (receipt_key_hash,),
                ).fetchone()
                if existing is not None:
                    if (existing["review_id"] == review_id
                            and existing["category"] == category
                            and existing["content_sha256"] == content_sha256
                            and existing["observed_at"] == observed_at
                            and existing["verified_at"] == verified_at
                            and existing["expires_at"] == expires_at
                            and existing["verifier_digest"] == verifier_digest
                            and hmac.compare_digest(existing["receipt_hash"],
                                                    _verification_evidence_hash(existing))):
                        return self._evidence_public(existing)
                    raise VerificationReviewConflict("verification_evidence_idempotency_conflict")
                values = {
                    "id": receipt_id, "review_id": review_id, "category": category,
                    "content_sha256": content_sha256, "observed_at": observed_at,
                    "verified_at": verified_at, "expires_at": expires_at,
                    "verifier_digest": verifier_digest,
                    "receipt_key_hash": receipt_key_hash, "created": now,
                }
                values["receipt_hash"] = _verification_evidence_hash(values)
                db.execute(
                    """INSERT INTO account_verification_evidence_receipts
                       (id,review_id,category,content_sha256,observed_at,verified_at,
                        expires_at,verifier_digest,receipt_key_hash,created,receipt_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(values[key] for key in (
                        "id", "review_id", "category", "content_sha256", "observed_at",
                        "verified_at", "expires_at", "verifier_digest",
                        "receipt_key_hash", "created", "receipt_hash",
                    )),
                )
                stored = db.execute(
                    "SELECT * FROM account_verification_evidence_receipts WHERE id=?",
                    (receipt_id,),
                ).fetchone()
                return self._evidence_public(stored)
        except sqlite3.IntegrityError as exc:
            raise VerificationReviewConflict("verification_evidence_idempotency_conflict") from exc

    def decide_verification_review(self, review_id, *, decision, decision_code,
                                   operator_ref, idempotency_key, evidence_receipt_ids,
                                   authorization,
                                   now=None):
        """Trusted, atomic decision; raw operator and idempotency values are not stored."""
        self._authorize_verification_operator(authorization)
        if not isinstance(review_id, str) or not re.fullmatch(r"[a-f0-9]{32}", review_id):
            raise ValueError("verification_review_id")
        if decision not in {"approve", "reject"}:
            raise ValueError("verification_decision")
        allowed = (VERIFICATION_APPROVAL_CODES if decision == "approve"
                   else VERIFICATION_REJECTION_CODES)
        if decision_code not in allowed:
            raise ValueError("verification_decision_code")
        operator_ref = clean_text(operator_ref, "verification_operator", 80)
        if (not isinstance(idempotency_key, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{31,127}", idempotency_key)):
            raise ValueError("verification_idempotency_key")
        if (not isinstance(evidence_receipt_ids, (list, tuple))
                or not evidence_receipt_ids or len(evidence_receipt_ids) > 8
                or any(not isinstance(item, str)
                       or not re.fullmatch(r"[a-f0-9]{32}", item)
                       for item in evidence_receipt_ids)
                or len(set(evidence_receipt_ids)) != len(evidence_receipt_ids)):
            raise ValueError("verification_evidence_receipts")
        now = time.time() if now is None else float(now)
        if not (0 <= now < float("inf")):
            raise ValueError("verification_time")
        secret = self._verification_operator_secret
        actor_digest = hmac.new(secret, ("actor:" + operator_ref).encode(), hashlib.sha256).hexdigest()
        decision_digest = hmac.new(secret, ("decision:" + idempotency_key).encode(), hashlib.sha256).hexdigest()
        status = "approved" if decision == "approve" else "rejected"
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                review = db.execute(
                    "SELECT * FROM account_verification_reviews WHERE id=?", (review_id,)
                ).fetchone()
                if not review:
                    raise VerificationReviewConflict("verification_review_unavailable")
                _verified_verification_audit(db, review)
                if review["decision_key_hash"] == decision_digest:
                    bound = [row[0] for row in db.execute(
                        """SELECT receipt_id FROM account_verification_decision_evidence
                           WHERE review_id=? ORDER BY receipt_id""", (review_id,),
                    ).fetchall()]
                    if (review["status"] == status and review["decision_code"] == decision_code
                            and review["decision_actor_digest"] == actor_digest
                            and bound == sorted(evidence_receipt_ids)):
                        return self._review_public(review)
                    raise VerificationReviewConflict("verification_idempotency_conflict")
                if review["status"] != "pending":
                    raise VerificationReviewConflict("verification_review_already_decided")
                placeholders = ",".join("?" for _ in evidence_receipt_ids)
                receipts = db.execute(
                    f"""SELECT * FROM account_verification_evidence_receipts
                         WHERE id IN ({placeholders}) ORDER BY id""",
                    tuple(evidence_receipt_ids),
                ).fetchall()
                if len(receipts) != len(evidence_receipt_ids):
                    raise VerificationReviewConflict("verification_evidence_unavailable")
                categories = set()
                receipt_hashes = []
                for receipt in receipts:
                    if (receipt["review_id"] != review_id
                            or receipt["category"] not in VERIFICATION_EVIDENCE_CATEGORIES[review["review_kind"]]
                            or receipt["verified_at"] > now or receipt["expires_at"] <= now
                            or not hmac.compare_digest(receipt["receipt_hash"],
                                                       _verification_evidence_hash(receipt))):
                        raise VerificationReviewConflict("verification_evidence_invalid")
                    categories.add(receipt["category"])
                    receipt_hashes.append(receipt["receipt_hash"])
                required = set()
                if decision == "approve":
                    required = VERIFICATION_REQUIRED_APPROVAL_EVIDENCE[review["review_kind"]]
                elif decision_code in {"company_identity_unverified", "conflicting_company_record"}:
                    required = {"commercial_register_extract"}
                elif decision_code == "representative_authority_unverified":
                    required = {"representative_authority_record"}
                elif decision_code == "membership_unverified":
                    required = {"membership_authority_record"}
                if not required.issubset(categories):
                    raise VerificationReviewConflict("verification_evidence_incomplete")
                evidence_bundle_hash = _verification_evidence_bundle_hash(
                    review_id, receipt_hashes,
                )
                if decision == "reject":
                    allowed_rejections = (
                        {"company_identity_unverified", "representative_authority_unverified",
                         "conflicting_company_record", "insufficient_evidence"}
                        if review["review_kind"] == "company_representative"
                        else {"membership_unverified", "insufficient_evidence"}
                    )
                    if decision_code not in allowed_rejections:
                        raise ValueError("verification_decision_code")
                subject = db.execute(
                    """SELECT u.active,u.company_id,c.verified AS company_verified
                       FROM account_users u JOIN account_companies c ON c.id=u.company_id
                       WHERE u.id=? AND u.company_id=?""",
                    (review["subject_user_id"], review["company_id"]),
                ).fetchone()
                if not subject or not subject["active"]:
                    raise VerificationReviewConflict("verification_subject_unavailable")
                if (decision == "approve" and review["review_kind"] == "membership"
                        and not subject["company_verified"]):
                    raise VerificationReviewConflict("verification_company_not_verified")
                if decision == "approve":
                    if review["review_kind"] == "company_representative":
                        if decision_code != "identity_and_authority_confirmed":
                            raise ValueError("verification_decision_code")
                        db.execute(
                            "UPDATE account_companies SET verified=1 WHERE id=?",
                            (review["company_id"],),
                        )
                    elif decision_code != "membership_confirmed":
                        raise ValueError("verification_decision_code")
                    db.execute(
                        "UPDATE account_users SET membership_verified=1 WHERE id=?",
                        (review["subject_user_id"],),
                    )
                event_hash = _verification_event_hash(
                    review_id, review["version"] + 1, status, decision_code,
                    actor_digest, decision_digest, now, review["audit_head"],
                    evidence_bundle_hash,
                )
                db.execute(
                    """INSERT INTO account_verification_audit
                       (review_id,sequence,event,decision_code,actor_digest,
                        idempotency_key_hash,created,previous_hash,event_hash,
                        evidence_bundle_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (review_id, review["version"] + 1, status, decision_code,
                     actor_digest, decision_digest, now, review["audit_head"], event_hash,
                     evidence_bundle_hash),
                )
                db.executemany(
                    """INSERT INTO account_verification_decision_evidence
                       (review_id,receipt_id,receipt_hash) VALUES (?,?,?)""",
                    [(review_id, receipt["id"], receipt["receipt_hash"])
                     for receipt in receipts],
                )
                db.execute(
                    """UPDATE account_verification_reviews
                       SET status=?,decision_key_hash=?,decision_code=?,
                           decision_actor_digest=?,updated=?,decided=?,
                           audit_head=?,version=version+1
                       WHERE id=?""",
                    (status, decision_digest, decision_code, actor_digest, now, now,
                     event_hash, review_id),
                )
                final = db.execute(
                    "SELECT * FROM account_verification_reviews WHERE id=?", (review_id,)
                ).fetchone()
                return self._review_public(final)
        except sqlite3.IntegrityError as exc:
            raise VerificationReviewConflict("verification_idempotency_conflict") from exc

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

    @staticmethod
    def _billing_user(db, company_id, user_id):
        return db.execute(
            """SELECT 1 FROM account_users u JOIN account_companies c ON c.id=u.company_id
               WHERE u.id=? AND u.company_id=? AND u.active=1 AND u.email_verified=1
                 AND u.membership_verified=1 AND c.verified=1""",
            (user_id, company_id),
        ).fetchone()

    @staticmethod
    def _billing_snapshot(plan_code, billing_cycle):
        if plan_code not in BILLING_PLAN_CODES or billing_cycle not in BILLING_CYCLES:
            raise ValueError("billing_selection")
        plan = next(item for item in billing_catalog()["plans"] if item["plan_code"] == plan_code)
        return {
            "catalog_revision": BILLING_CATALOG_REVISION,
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "display_name": plan["display_name"],
            "price": plan["price"],
            "quota": plan["quota"],
            "video_status": plan["video_status"],
            "specialist_policy": plan["specialist_policy"],
            "vat_status": "TBD",
            "terms_version": None,
            "privacy_version": None,
        }

    @staticmethod
    def _billing_payload(row, *, replay=False):
        status = "expired" if row["expired"] is not None else row["status"]
        payload = {
            "checkout_id": row["id"],
            "status": status,
            "selection": json.loads(row["snapshot_json"]),
            "created_at": _utc(row["created"]),
            "expires_at": _utc(row["expires"]),
            "confirmed_at": _utc(row["confirmed"]) if row["confirmed"] is not None else None,
            "cancelled_at": _utc(row["cancelled"]) if row["cancelled"] is not None else None,
            "expired_at": _utc(row["expired"]) if row["expired"] is not None else None,
            "simulation": True,
            "charged": False,
            "subscription_active": False,
        }
        if replay:
            payload["idempotent_replay"] = True
        return payload

    @staticmethod
    def _materialize_billing_expiry(db, company_id, user_id, now):
        """Mark elapsed drafts once and retain the transition in the audit log."""
        due = db.execute(
            """SELECT id FROM billing_checkout_intents
               WHERE company_id=? AND user_id=? AND status='draft'
                 AND expired IS NULL AND expires<=?""",
            (company_id, user_id, now),
        ).fetchall()
        if not due:
            return
        db.executemany(
            """INSERT INTO billing_checkout_audit
               (intent_id,company_id,user_id,event,created) VALUES (?,?,?,'expired',?)""",
            [(row["id"], company_id, user_id, now) for row in due],
        )
        db.executemany(
            "UPDATE billing_checkout_intents SET expired=? WHERE id=? AND expired IS NULL",
            [(now, row["id"]) for row in due],
        )

    def create_checkout_simulation(self, company_id, user_id, plan_code, billing_cycle, *,
                                   idempotency_key, now=None, ttl=1800, max_open_intents=5):
        """Create an immutable local quote.  No entitlement or payment state is touched."""
        now = time.time() if now is None else float(now)
        if isinstance(ttl, bool) or not 60 <= ttl <= 86400:
            raise ValueError("billing_ttl")
        if (isinstance(max_open_intents, bool) or not isinstance(max_open_intents, int)
                or not 1 <= max_open_intents <= 100):
            raise ValueError("billing_open_limit")
        idempotency_key = clean_text(idempotency_key, "idempotency_key", 128)
        snapshot = self._billing_snapshot(plan_code, billing_cycle)
        snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._billing_user(db, company_id, user_id):
                raise ValueError("user")
            self._materialize_billing_expiry(db, company_id, user_id, now)
            previous = db.execute(
                """SELECT * FROM billing_checkout_intents
                   WHERE company_id=? AND user_id=? AND idempotency_key_hash=?""",
                (company_id, user_id, key_hash),
            ).fetchone()
            if previous:
                if previous["payload_hash"] != payload_hash:
                    raise BillingSandboxConflict("idempotency_mismatch")
                db.execute(
                    "INSERT INTO billing_checkout_audit(intent_id,company_id,user_id,event,created) VALUES (?,?,?,?,?)",
                    (previous["id"], company_id, user_id, "idempotency_replay", now),
                )
                return self._billing_payload(previous, replay=True)
            open_count = db.execute(
                """SELECT COUNT(*) FROM billing_checkout_intents
                   WHERE company_id=? AND user_id=? AND status='draft'
                     AND expired IS NULL AND expires>?""",
                (company_id, user_id, now),
            ).fetchone()[0]
            if open_count >= max_open_intents:
                raise BillingSandboxConflict("open_intent_limit")
            intent_id = secrets.token_hex(16)
            db.execute(
                """INSERT INTO billing_checkout_intents
                   (id,company_id,user_id,catalog_revision,plan_code,billing_cycle,
                    idempotency_key_hash,payload_hash,snapshot_json,status,created,expires)
                   VALUES (?,?,?,?,?,?,?,?,?,'draft',?,?)""",
                (intent_id, company_id, user_id, BILLING_CATALOG_REVISION, plan_code,
                 billing_cycle, key_hash, payload_hash, snapshot_json, now, now + ttl),
            )
            db.execute(
                "INSERT INTO billing_checkout_audit(intent_id,company_id,user_id,event,created) VALUES (?,?,?,?,?)",
                (intent_id, company_id, user_id, "created", now),
            )
            row = db.execute("SELECT * FROM billing_checkout_intents WHERE id=?", (intent_id,)).fetchone()
            return self._billing_payload(row)

    def get_checkout_simulation(self, checkout_id, company_id, user_id, *, now=None):
        if not isinstance(checkout_id, str) or len(checkout_id) > 64:
            return None
        now = time.time() if now is None else float(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._billing_user(db, company_id, user_id):
                raise ValueError("user")
            self._materialize_billing_expiry(db, company_id, user_id, now)
            row = db.execute(
                "SELECT * FROM billing_checkout_intents WHERE id=? AND company_id=? AND user_id=?",
                (checkout_id, company_id, user_id),
            ).fetchone()
        return self._billing_payload(row) if row else None

    def transition_checkout_simulation(self, checkout_id, company_id, user_id, target, *, now=None):
        if target not in {"confirmed_simulation", "cancelled"}:
            raise ValueError("billing_status")
        now = time.time() if now is None else float(now)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._billing_user(db, company_id, user_id):
                raise ValueError("user")
            self._materialize_billing_expiry(db, company_id, user_id, now)
            row = db.execute(
                "SELECT * FROM billing_checkout_intents WHERE id=? AND company_id=? AND user_id=?",
                (checkout_id, company_id, user_id),
            ).fetchone()
            if not row:
                raise BillingSandboxConflict("checkout_not_found")
            if row["expired"] is not None:
                raise BillingSandboxConflict("checkout_expired")
            if row["status"] == target:
                return self._billing_payload(row, replay=True)
            if row["status"] != "draft":
                raise BillingSandboxConflict("checkout_already_final")
            if now >= row["expires"]:
                raise BillingSandboxConflict("checkout_expired")
            field = "confirmed" if target == "confirmed_simulation" else "cancelled"
            db.execute(
                f"UPDATE billing_checkout_intents SET status=?,{field}=? WHERE id=?",
                (target, now, checkout_id),
            )
            db.execute(
                "INSERT INTO billing_checkout_audit(intent_id,company_id,user_id,event,created) VALUES (?,?,?,?,?)",
                (checkout_id, company_id, user_id, target, now),
            )
            updated = db.execute("SELECT * FROM billing_checkout_intents WHERE id=?", (checkout_id,)).fetchone()
            return self._billing_payload(updated)
