"""Durable, fail-closed SQLite reservations for the unwired delivery boundary.

This adapter performs no delivery and has no provider dependency. It stores
only an HMAC digest of each idempotency key. A stable, application-injected
secret is required so a restart cannot accidentally create a second key
space; a secret mismatch therefore fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
from typing import Callable


OUTCOME_CODES = {
    "accepted": frozenset({"transport_accepted"}),
    "failed": frozenset({
        "transport_rejected", "transport_failed", "invalid_response", "expired",
    }),
    "uncertain": frozenset({
        "timeout", "acknowledgement_lost", "cancelled_after_dispatch",
    }),
}


class DeliveryReservationError(RuntimeError):
    """Sanitized storage failure suitable for the delivery boundary."""


@dataclass(frozen=True)
class DeliveryReservationPolicy:
    """Explicit resource and lifetime bounds for durable reservations."""

    max_reservations: int = 50_000
    reservation_retention_seconds: int = 7 * 24 * 60 * 60
    outcome_retention_seconds: int = 30 * 24 * 60 * 60
    busy_timeout_seconds: float = 5.0

    def __post_init__(self):
        if (type(self.max_reservations) is not int
                or not 1 <= self.max_reservations <= 1_000_000):
            raise DeliveryReservationError("delivery_reservation_policy_invalid")
        if (type(self.reservation_retention_seconds) is not int
                or not 60 <= self.reservation_retention_seconds <= 30 * 24 * 60 * 60
                or type(self.outcome_retention_seconds) is not int
                or not 60 <= self.outcome_retention_seconds <= 365 * 24 * 60 * 60):
            raise DeliveryReservationError("delivery_reservation_policy_invalid")
        if (type(self.busy_timeout_seconds) not in {int, float}
                or not math.isfinite(self.busy_timeout_seconds)
                or not 0.05 <= self.busy_timeout_seconds <= 30):
            raise DeliveryReservationError("delivery_reservation_policy_invalid")


class SQLiteDeliveryReservationStore:
    """Atomic reservation store with bounded, expiry-only reclamation.

    Capacity is checked inside the same ``BEGIN IMMEDIATE`` transaction as the
    insert. Only rows whose configured retention has elapsed are reclaimed;
    active reservations are never evicted to make room. Full, locked, corrupt,
    unavailable or misconfigured storage fails closed.
    """

    durable = True
    _SCHEMA_VERSION = "3"
    _V1_COLUMNS = (("key_digest", "BLOB", 1), ("reserved_at", "REAL", 0),
                   ("expires_at", "REAL", 0))
    _V2_COLUMNS = _V1_COLUMNS + (
        ("outcome_count", "INTEGER", 0), ("outcome_head", "BLOB", 0),
        ("outcome_status", "TEXT", 0), ("outcome_code", "TEXT", 0),
        ("outcome_updated_at", "REAL", 0),
        ("provider_reference_present", "INTEGER", 0),
    )
    _V3_COLUMNS = _V2_COLUMNS + (("outcome_expires_at", "REAL", 0),)

    def __init__(self, database_path: str | Path, *, key_secret: bytes,
                 checkpoint_path: str | Path | None = None,
                 policy: DeliveryReservationPolicy = DeliveryReservationPolicy(),
                 clock: Callable[[], float] = time.time):
        if (not isinstance(database_path, (str, Path)) or not isinstance(key_secret, bytes)
                or not 32 <= len(key_secret) <= 256 or not isinstance(policy, DeliveryReservationPolicy)
                or not callable(clock)):
            raise DeliveryReservationError("delivery_reservation_configuration_invalid")
        self._path = Path(database_path).expanduser().absolute()
        self._checkpoint_path = (Path(checkpoint_path).expanduser().absolute()
                                 if checkpoint_path is not None else
                                 self._path.with_name(self._path.name + ".checkpoint"))
        if self._checkpoint_path == self._path:
            raise DeliveryReservationError("delivery_reservation_configuration_invalid")
        self._secret = bytes(key_secret)
        self.policy = policy
        self._clock = clock
        self._secret_fingerprint = hashlib.sha256(self._secret).hexdigest()
        self._prepare_path()
        self._initialize_schema()

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(durable=True, "
                f"max_reservations={self.policy.max_reservations}, "
                f"reservation_retention_seconds={self.policy.reservation_retention_seconds}, "
                f"outcome_retention_seconds={self.policy.outcome_retention_seconds})")

    def _prepare_path(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for ancestor in (
                    self._path.parent, *self._path.parent.parents,
                    self._checkpoint_path.parent, *self._checkpoint_path.parent.parents):
                if ancestor.is_symlink():
                    raise OSError
            self._path.parent.chmod(0o700)
            self._checkpoint_path.parent.chmod(0o700)
            if not self._path.exists():
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(self._path, flags, 0o600)
                os.close(descriptor)
            self._assert_safe_file()
            if self._checkpoint_path.exists():
                self._assert_safe_checkpoint()
        except OSError:
            raise DeliveryReservationError("delivery_reservation_storage_unavailable") from None

    def _assert_safe_file(self) -> None:
        details = self._path.lstat()
        if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or details.st_nlink != 1):
            raise OSError

    def _assert_safe_checkpoint(self) -> None:
        details = self._checkpoint_path.lstat()
        if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or details.st_nlink != 1 or details.st_size > 2048):
            raise OSError

    def _connect(self) -> sqlite3.Connection:
        try:
            self._assert_safe_file()
            db = sqlite3.connect(
                str(self._path), timeout=self.policy.busy_timeout_seconds,
                isolation_level=None, check_same_thread=False,
            )
            db.execute(f"PRAGMA busy_timeout={int(self.policy.busy_timeout_seconds * 1000)}")
            db.execute("PRAGMA foreign_keys=ON")
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                db.close()
                raise
            self._assert_safe_file()
            return db
        except (OSError, sqlite3.Error):
            raise DeliveryReservationError("delivery_reservation_storage_unavailable") from None

    @staticmethod
    def _rollback(db: sqlite3.Connection) -> None:
        try:
            if db.in_transaction:
                db.rollback()
        except sqlite3.Error:
            pass

    @staticmethod
    def _feed_digest(mac: hmac.HMAC, value: object) -> None:
        if value is None:
            payload = b"N"
        elif isinstance(value, bytes):
            payload = b"B" + value
        elif type(value) is int:
            payload = b"I" + str(value).encode("ascii")
        elif type(value) is float and math.isfinite(value):
            payload = b"F" + value.hex().encode("ascii")
        elif isinstance(value, str):
            payload = b"S" + value.encode("utf-8")
        else:
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        mac.update(len(payload).to_bytes(8, "big")); mac.update(payload)

    def _state_digest(self, db: sqlite3.Connection) -> bytes:
        mac = hmac.new(self._secret, b"slps-delivery-ledger-state-v1\0", hashlib.sha256)
        metadata = db.execute(
            "SELECT schema_version,secret_fingerprint FROM delivery_reservation_meta WHERE singleton=1"
        ).fetchone()
        if metadata is None:
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        self._feed_digest(mac, "metadata")
        for value in metadata:
            self._feed_digest(mac, value)
        reservation_columns = (
            "key_digest,reserved_at,expires_at,outcome_count,outcome_head,outcome_status,"
            "outcome_code,outcome_updated_at,provider_reference_present,outcome_expires_at"
        )
        for row in db.execute(
                f"SELECT {reservation_columns} FROM delivery_reservations ORDER BY key_digest"):
            self._feed_digest(mac, "reservation")
            for value in row:
                self._feed_digest(mac, value)
        for row in db.execute(
                """SELECT key_digest,sequence,status,code,reconciliation_digest,
                          provider_reference_digest,recorded_at,previous_hash,event_hash
                   FROM delivery_outcome_events ORDER BY key_digest,sequence"""):
            self._feed_digest(mac, "event")
            for value in row:
                self._feed_digest(mac, value)
        return mac.digest()

    def _checkpoint_auth(self, revision: int, digest: bytes) -> str:
        payload = b"slps-delivery-checkpoint-v1\0" + str(revision).encode("ascii") + b"\0" + digest
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def _write_checkpoint(self, revision: int, digest: bytes) -> None:
        document = {
            "format": 1, "revision": revision, "state_digest": digest.hex(),
            "authentication": self._checkpoint_auth(revision, digest),
        }
        descriptor = None
        temporary = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{self._checkpoint_path.name}.", suffix=".tmp",
                dir=self._checkpoint_path.parent,
            )
            temporary = Path(name)
            os.fchmod(descriptor, 0o600)
            payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError
                written += count
            os.fsync(descriptor); os.close(descriptor); descriptor = None
            os.replace(temporary, self._checkpoint_path); temporary = None
            self._checkpoint_path.chmod(0o600)
            parent_fd = os.open(self._checkpoint_path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            self._assert_safe_checkpoint()
        except (OSError, TypeError, ValueError):
            raise DeliveryReservationError("delivery_outcome_checkpoint_unavailable") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read_checkpoint(self) -> tuple[int, bytes]:
        try:
            self._assert_safe_checkpoint()
            document = json.loads(self._checkpoint_path.read_text(encoding="ascii"))
            revision = document["revision"]
            digest_hex = document["state_digest"]
            authentication = document["authentication"]
            digest = bytes.fromhex(digest_hex)
            if (set(document) != {"format", "revision", "state_digest", "authentication"}
                    or document["format"] != 1 or type(revision) is not int or revision < 1
                    or not isinstance(digest_hex, str) or len(digest_hex) != 64
                    or digest_hex != digest_hex.lower() or len(digest) != 32
                    or not isinstance(authentication, str)
                    or not hmac.compare_digest(authentication,
                                               self._checkpoint_auth(revision, digest))):
                raise ValueError
            return revision, digest
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeError):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid") from None

    def _verify_checkpoint(self, db: sqlite3.Connection) -> tuple[int, bytes]:
        row = db.execute(
            "SELECT ledger_revision,ledger_digest FROM delivery_reservation_meta WHERE singleton=1"
        ).fetchone()
        if (row is None or type(row[0]) is not int or row[0] < 1
                or not isinstance(row[1], bytes) or len(row[1]) != 32):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        actual = self._state_digest(db)
        checkpoint_revision, checkpoint_digest = self._read_checkpoint()
        if (not hmac.compare_digest(row[1], actual) or checkpoint_revision != row[0]
                or not hmac.compare_digest(checkpoint_digest, actual)):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        return row[0], actual

    def _advance_checkpoint(self, db: sqlite3.Connection, previous_revision: int) -> None:
        digest = self._state_digest(db)
        revision = previous_revision + 1
        db.execute(
            "UPDATE delivery_reservation_meta SET ledger_revision=?,ledger_digest=? WHERE singleton=1",
            (revision, digest),
        )
        self._write_checkpoint(revision, digest)

    def _initialize_schema(self) -> None:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_reservation_meta (
                       singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                       schema_version TEXT NOT NULL,
                       secret_fingerprint TEXT NOT NULL,
                       ledger_revision INTEGER NOT NULL,
                       ledger_digest BLOB
                   )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_reservations (
                       key_digest BLOB PRIMARY KEY NOT NULL CHECK(length(key_digest)=32),
                       reserved_at REAL NOT NULL,
                       expires_at REAL NOT NULL CHECK(expires_at > reserved_at),
                       outcome_count INTEGER NOT NULL DEFAULT 0 CHECK(outcome_count >= 0),
                       outcome_head BLOB CHECK(outcome_head IS NULL OR length(outcome_head)=32),
                       outcome_status TEXT CHECK(outcome_status IS NULL OR outcome_status IN ('accepted','failed','uncertain')),
                       outcome_code TEXT,
                       outcome_updated_at REAL,
                       provider_reference_present INTEGER NOT NULL DEFAULT 0 CHECK(provider_reference_present IN (0,1)),
                       outcome_expires_at REAL
                   ) WITHOUT ROWID"""
            )
            columns = tuple((row[1], row[2], row[5]) for row in db.execute(
                "PRAGMA table_info(delivery_reservations)"
            ))
            row = db.execute(
                "SELECT schema_version,secret_fingerprint FROM delivery_reservation_meta WHERE singleton=1"
            ).fetchone()
            migrated = False
            if row is None:
                if columns != self._V3_COLUMNS:
                    raise sqlite3.DatabaseError("unexpected_reservation_schema")
                db.execute(
                    "INSERT INTO delivery_reservation_meta VALUES (1,?,?,0,NULL)",
                    (self._SCHEMA_VERSION, self._secret_fingerprint),
                )
                migrated = True
            elif (str(row[0]) in {"1", "2"}
                  and hmac.compare_digest(str(row[1]), self._secret_fingerprint)):
                if str(row[0]) == "1":
                    if columns != self._V1_COLUMNS:
                        raise sqlite3.DatabaseError("unexpected_reservation_schema")
                    for statement in (
                    "ALTER TABLE delivery_reservations ADD COLUMN outcome_count INTEGER NOT NULL DEFAULT 0 CHECK(outcome_count >= 0)",
                    "ALTER TABLE delivery_reservations ADD COLUMN outcome_head BLOB CHECK(outcome_head IS NULL OR length(outcome_head)=32)",
                    "ALTER TABLE delivery_reservations ADD COLUMN outcome_status TEXT CHECK(outcome_status IS NULL OR outcome_status IN ('accepted','failed','uncertain'))",
                    "ALTER TABLE delivery_reservations ADD COLUMN outcome_code TEXT",
                    "ALTER TABLE delivery_reservations ADD COLUMN outcome_updated_at REAL",
                    "ALTER TABLE delivery_reservations ADD COLUMN provider_reference_present INTEGER NOT NULL DEFAULT 0 CHECK(provider_reference_present IN (0,1))",
                    ):
                        db.execute(statement)
                elif columns != self._V2_COLUMNS:
                    raise sqlite3.DatabaseError("unexpected_reservation_schema")
                db.execute("ALTER TABLE delivery_reservations ADD COLUMN outcome_expires_at REAL")
                meta_columns = {item[1] for item in db.execute(
                    "PRAGMA table_info(delivery_reservation_meta)"
                )}
                if "ledger_revision" not in meta_columns:
                    db.execute("ALTER TABLE delivery_reservation_meta ADD COLUMN ledger_revision INTEGER NOT NULL DEFAULT 0")
                if "ledger_digest" not in meta_columns:
                    db.execute("ALTER TABLE delivery_reservation_meta ADD COLUMN ledger_digest BLOB")
                db.execute(
                    """UPDATE delivery_reservations SET outcome_expires_at=outcome_updated_at+?
                       WHERE outcome_count > 0""",
                    (self.policy.outcome_retention_seconds,),
                )
                db.execute(
                    "UPDATE delivery_reservation_meta SET schema_version=? WHERE singleton=1",
                    (self._SCHEMA_VERSION,),
                )
                migrated = True
            elif (str(row[0]) != self._SCHEMA_VERSION
                  or not hmac.compare_digest(str(row[1]), self._secret_fingerprint)):
                raise sqlite3.DatabaseError("reservation_metadata_mismatch")
            columns = tuple((item[1], item[2], item[5]) for item in db.execute(
                "PRAGMA table_info(delivery_reservations)"
            ))
            if columns != self._V3_COLUMNS:
                raise sqlite3.DatabaseError("unexpected_reservation_schema")
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_outcome_events (
                       key_digest BLOB NOT NULL REFERENCES delivery_reservations(key_digest) ON DELETE CASCADE,
                       sequence INTEGER NOT NULL CHECK(sequence >= 1),
                       status TEXT NOT NULL CHECK(status IN ('accepted','failed','uncertain')),
                       code TEXT NOT NULL,
                       reconciliation_digest BLOB NOT NULL CHECK(length(reconciliation_digest)=32),
                       provider_reference_digest BLOB CHECK(provider_reference_digest IS NULL OR length(provider_reference_digest)=32),
                       recorded_at REAL NOT NULL,
                       previous_hash BLOB CHECK(previous_hash IS NULL OR length(previous_hash)=32),
                       event_hash BLOB NOT NULL CHECK(length(event_hash)=32),
                       PRIMARY KEY(key_digest, sequence),
                       UNIQUE(key_digest, reconciliation_digest)
                   ) WITHOUT ROWID"""
            )
            event_columns = tuple((item[1], item[2], item[5]) for item in db.execute(
                "PRAGMA table_info(delivery_outcome_events)"
            ))
            if event_columns != (
                    ("key_digest", "BLOB", 1), ("sequence", "INTEGER", 2),
                    ("status", "TEXT", 0), ("code", "TEXT", 0),
                    ("reconciliation_digest", "BLOB", 0),
                    ("provider_reference_digest", "BLOB", 0),
                    ("recorded_at", "REAL", 0), ("previous_hash", "BLOB", 0),
                    ("event_hash", "BLOB", 0)):
                raise sqlite3.DatabaseError("unexpected_outcome_schema")
            if db.execute("SELECT COUNT(*) FROM delivery_reservation_meta").fetchone()[0] != 1:
                raise sqlite3.DatabaseError("unexpected_reservation_metadata")
            if migrated:
                if self._checkpoint_path.exists():
                    raise DeliveryReservationError("delivery_outcome_integrity_invalid")
                digest = self._state_digest(db)
                db.execute(
                    "UPDATE delivery_reservation_meta SET ledger_revision=1,ledger_digest=? WHERE singleton=1",
                    (digest,),
                )
                self._write_checkpoint(1, digest)
            else:
                self._verify_checkpoint(db)
            db.commit()
        except DeliveryReservationError:
            self._rollback(db)
            raise
        except sqlite3.Error:
            self._rollback(db)
            raise DeliveryReservationError("delivery_reservation_schema_invalid") from None
        finally:
            db.close()

    def _now(self) -> float:
        try:
            value = self._clock()
        except Exception:
            raise DeliveryReservationError("delivery_reservation_clock_unavailable") from None
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise DeliveryReservationError("delivery_reservation_clock_unavailable")
        return float(value)

    @staticmethod
    def _key(value: object, label: str) -> str:
        if (not isinstance(value, str) or not 32 <= len(value) <= 128
                or any(ord(character) < 33 or ord(character) > 126 for character in value)):
            raise DeliveryReservationError(label)
        return value

    def _key_digest(self, key: str) -> bytes:
        # Preserve the v1 digest namespace so existing reservations survive the
        # schema migration and remain duplicate-suppressed after restart.
        return hmac.new(self._secret, key.encode("ascii"), hashlib.sha256).digest()

    def _reconciliation_digest(self, key: str) -> bytes:
        return hmac.new(
            self._secret, b"reconciliation\0" + key.encode("ascii"), hashlib.sha256,
        ).digest()

    def _provider_digest(self, value: str) -> bytes | None:
        if not value:
            return None
        return hmac.new(
            self._secret, b"provider-reference\0" + value.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def _event_hash(self, *, key_digest: bytes, sequence: int, status: str,
                    code: str, reconciliation_digest: bytes,
                    provider_reference_digest: bytes | None, recorded_at: float,
                    previous_hash: bytes | None, reserved_at: float,
                    expires_at: float) -> bytes:
        parts = (
            b"slps-delivery-outcome-v1", key_digest, str(sequence).encode("ascii"),
            status.encode("ascii"), code.encode("ascii"), reconciliation_digest,
            provider_reference_digest or b"", float(recorded_at).hex().encode("ascii"),
            previous_hash or b"", float(reserved_at).hex().encode("ascii"),
            float(expires_at).hex().encode("ascii"),
        )
        return hmac.new(self._secret, b"\0".join(parts), hashlib.sha256).digest()

    def _validated_events(self, db: sqlite3.Connection, reservation) -> list:
        try:
            count = reservation["outcome_count"]
            reserved_at = float(reservation["reserved_at"])
            expires_at = float(reservation["expires_at"])
            outcome_expires_at = reservation["outcome_expires_at"]
            reference_present = reservation["provider_reference_present"]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid") from None
        if (type(count) is not int or not 0 <= count <= 2
                or type(reference_present) is not int
                or reference_present not in {0, 1}
                or not math.isfinite(reserved_at) or reserved_at < 0
                or not math.isfinite(expires_at) or expires_at <= reserved_at):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        rows = db.execute(
            """SELECT sequence,status,code,reconciliation_digest,
                      provider_reference_digest,recorded_at,previous_hash,event_hash
               FROM delivery_outcome_events WHERE key_digest=? ORDER BY sequence""",
            (reservation["key_digest"],),
        ).fetchall()
        if len(rows) != count:
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        if not rows:
            if any(reservation[name] is not None for name in (
                    "outcome_head", "outcome_status", "outcome_code", "outcome_updated_at")):
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            if reference_present != 0:
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            if outcome_expires_at is not None:
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            return []
        try:
            retained_until = float(outcome_expires_at)
        except (TypeError, ValueError, OverflowError):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid") from None
        if not math.isfinite(retained_until):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        previous = None
        previous_time = -1.0
        for expected, row in enumerate(rows, start=1):
            status, code = row["status"], row["code"]
            try:
                recorded = float(row["recorded_at"])
            except (TypeError, ValueError, OverflowError):
                raise DeliveryReservationError("delivery_outcome_integrity_invalid") from None
            provider_digest = row["provider_reference_digest"]
            previous_hash = row["previous_hash"]
            event_hash = row["event_hash"]
            if (type(row["sequence"]) is not int or row["sequence"] != expected
                    or not isinstance(status, str) or status not in OUTCOME_CODES
                    or code not in OUTCOME_CODES[status]
                    or not isinstance(row["reconciliation_digest"], bytes)
                    or len(row["reconciliation_digest"]) != 32
                    or provider_digest is not None
                    and (not isinstance(provider_digest, bytes) or len(provider_digest) != 32)
                    or previous_hash is not None
                    and (not isinstance(previous_hash, bytes) or len(previous_hash) != 32)
                    or not isinstance(event_hash, bytes) or len(event_hash) != 32
                    or not math.isfinite(recorded) or recorded < reserved_at
                    or expected == 1 and recorded >= expires_at
                    or expected > 1 and recorded >= retained_until
                    or recorded < previous_time or previous_hash != previous):
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            expected_hash = self._event_hash(
                key_digest=reservation["key_digest"], sequence=expected,
                status=status, code=code,
                reconciliation_digest=row["reconciliation_digest"],
                provider_reference_digest=provider_digest, recorded_at=recorded,
                previous_hash=previous, reserved_at=reserved_at, expires_at=expires_at,
            )
            if not hmac.compare_digest(event_hash, expected_hash):
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            if expected > 1 and (rows[expected - 2]["status"] != "uncertain"
                                 or status == "uncertain"):
                raise DeliveryReservationError("delivery_outcome_integrity_invalid")
            previous, previous_time = event_hash, recorded
        last = rows[-1]
        try:
            updated_at = float(reservation["outcome_updated_at"])
        except (TypeError, ValueError, OverflowError):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid") from None
        if (not isinstance(reservation["outcome_head"], bytes)
                or len(reservation["outcome_head"]) != 32
                or reservation["outcome_head"] != last["event_hash"]
                or reservation["outcome_status"] != last["status"]
                or reservation["outcome_code"] != last["code"]
                or not math.isfinite(updated_at)
                or not math.isfinite(retained_until) or retained_until <= updated_at
                or updated_at != float(last["recorded_at"])
                or reference_present
                != int(last["provider_reference_digest"] is not None)):
            raise DeliveryReservationError("delivery_outcome_integrity_invalid")
        return rows

    @staticmethod
    def _public_event(row) -> dict[str, object]:
        recorded = datetime.fromtimestamp(float(row["recorded_at"]), timezone.utc)
        return {
            "sequence": int(row["sequence"]),
            "status": row["status"],
            "code": row["code"],
            "recorded_at_utc": recorded.isoformat().replace("+00:00", "Z"),
            "final": row["status"] in {"accepted", "failed"},
            "provider_reference_present": row["provider_reference_digest"] is not None,
            "chain_valid": True,
        }

    def reserve_once(self, key: str) -> bool:
        """Atomically reserve ``key`` once for the configured retention window."""
        key = self._key(key, "delivery_reservation_key_invalid")
        now = self._now()
        expires_at = now + self.policy.reservation_retention_seconds
        if not math.isfinite(expires_at):
            raise DeliveryReservationError("delivery_reservation_clock_unavailable")
        digest = self._key_digest(key)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            revision, _ = self._verify_checkpoint(db)
            deleted = db.execute(
                """DELETE FROM delivery_reservations
                   WHERE (outcome_count=0 AND expires_at <= ?)
                      OR (outcome_count>0 AND expires_at <= ? AND outcome_expires_at <= ?)""",
                (now, now, now),
            ).rowcount
            if db.execute(
                "SELECT 1 FROM delivery_reservations WHERE key_digest=?", (digest,)
            ).fetchone() is not None:
                if deleted:
                    self._advance_checkpoint(db, revision)
                db.commit()
                return False
            count = int(db.execute("SELECT COUNT(*) FROM delivery_reservations").fetchone()[0])
            if count >= self.policy.max_reservations:
                raise DeliveryReservationError("delivery_reservation_capacity_exhausted")
            db.execute(
                "INSERT INTO delivery_reservations(key_digest,reserved_at,expires_at) VALUES (?,?,?)",
                (digest, now, expires_at),
            )
            self._advance_checkpoint(db, revision)
            db.commit()
            return True
        except DeliveryReservationError:
            self._rollback(db)
            raise
        except sqlite3.Error:
            self._rollback(db)
            raise DeliveryReservationError("delivery_reservation_storage_unavailable") from None
        finally:
            db.close()

    def record_outcome(self, key: str, *, status: str, code: str,
                       reconciliation_key: str,
                       provider_reference: str = "") -> dict[str, object]:
        """Append or idempotently replay one redacted outcome reconciliation.

        An initial uncertain event may be reconciled once to a final accepted or
        failed event. Final outcomes never change. Raw keys and provider references
        are HMACed and are never returned.
        """
        key = self._key(key, "delivery_reservation_key_invalid")
        reconciliation_key = self._key(
            reconciliation_key, "delivery_reconciliation_key_invalid",
        )
        if (not isinstance(status, str) or not isinstance(code, str)
                or status not in OUTCOME_CODES or code not in OUTCOME_CODES[status]):
            raise DeliveryReservationError("delivery_outcome_invalid")
        if (not isinstance(provider_reference, str) or len(provider_reference) > 256
                or any(ord(character) < 32 for character in provider_reference)):
            raise DeliveryReservationError("delivery_outcome_invalid")
        now = self._now()
        retained_until = now + self.policy.outcome_retention_seconds
        if not math.isfinite(retained_until):
            raise DeliveryReservationError("delivery_reservation_clock_unavailable")
        digest = self._key_digest(key)
        reconciliation_digest = self._reconciliation_digest(reconciliation_key)
        provider_digest = self._provider_digest(provider_reference)
        db = self._connect()
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            revision, _ = self._verify_checkpoint(db)
            reservation = db.execute(
                "SELECT * FROM delivery_reservations WHERE key_digest=?", (digest,),
            ).fetchone()
            if reservation is None:
                raise DeliveryReservationError("delivery_reservation_missing")
            rows = self._validated_events(db, reservation)
            if not rows and float(reservation["expires_at"]) <= now:
                raise DeliveryReservationError("delivery_reservation_missing")
            if rows and float(reservation["outcome_expires_at"]) <= now:
                raise DeliveryReservationError("delivery_outcome_expired")
            replay = db.execute(
                """SELECT sequence,status,code,reconciliation_digest,
                          provider_reference_digest,recorded_at,previous_hash,event_hash
                   FROM delivery_outcome_events
                   WHERE key_digest=? AND reconciliation_digest=?""",
                (digest, reconciliation_digest),
            ).fetchone()
            if replay is not None:
                if (replay["status"] != status or replay["code"] != code
                        or replay["provider_reference_digest"] != provider_digest):
                    raise DeliveryReservationError("delivery_outcome_conflict")
                db.commit()
                return self._public_event(replay)
            if rows and (rows[-1]["status"] != "uncertain" or status == "uncertain"):
                raise DeliveryReservationError("delivery_outcome_conflict")
            sequence = len(rows) + 1
            previous = rows[-1]["event_hash"] if rows else None
            event_hash = self._event_hash(
                key_digest=digest, sequence=sequence, status=status, code=code,
                reconciliation_digest=reconciliation_digest,
                provider_reference_digest=provider_digest, recorded_at=now,
                previous_hash=previous, reserved_at=float(reservation["reserved_at"]),
                expires_at=float(reservation["expires_at"]),
            )
            db.execute(
                """INSERT INTO delivery_outcome_events
                   (key_digest,sequence,status,code,reconciliation_digest,
                    provider_reference_digest,recorded_at,previous_hash,event_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (digest, sequence, status, code, reconciliation_digest,
                 provider_digest, now, previous, event_hash),
            )
            db.execute(
                """UPDATE delivery_reservations
                   SET outcome_count=?,outcome_head=?,outcome_status=?,outcome_code=?,
                       outcome_updated_at=?,provider_reference_present=?,outcome_expires_at=?
                   WHERE key_digest=?""",
                (sequence, event_hash, status, code, now,
                 int(provider_digest is not None), retained_until,
                 digest),
            )
            reservation = db.execute(
                "SELECT * FROM delivery_reservations WHERE key_digest=?", (digest,),
            ).fetchone()
            validated = self._validated_events(db, reservation)
            self._advance_checkpoint(db, revision)
            db.commit()
            return self._public_event(validated[-1])
        except DeliveryReservationError:
            self._rollback(db)
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError):
            self._rollback(db)
            raise DeliveryReservationError("delivery_outcome_storage_unavailable") from None
        finally:
            db.close()

    def outcome_status(self, key: str) -> dict[str, object]:
        """Return reservation and latest outcome metadata without sensitive values."""
        key = self._key(key, "delivery_reservation_key_invalid")
        now = self._now()
        digest = self._key_digest(key)
        db = self._connect()
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            self._verify_checkpoint(db)
            reservation = db.execute(
                "SELECT * FROM delivery_reservations WHERE key_digest=?", (digest,),
            ).fetchone()
            if reservation is None:
                raise DeliveryReservationError("delivery_reservation_missing")
            rows = self._validated_events(db, reservation)
            if rows and float(reservation["outcome_expires_at"]) <= now:
                raise DeliveryReservationError("delivery_outcome_expired")
            reserved = datetime.fromtimestamp(float(reservation["reserved_at"]), timezone.utc)
            expires = datetime.fromtimestamp(float(reservation["expires_at"]), timezone.utc)
            result = {
                "reservation_status": "expired" if float(reservation["expires_at"]) <= now else "active",
                "reserved_at_utc": reserved.isoformat().replace("+00:00", "Z"),
                "expires_at_utc": expires.isoformat().replace("+00:00", "Z"),
                "outcome": self._public_event(rows[-1]) if rows else None,
                "outcome_retained_until_utc": (
                    datetime.fromtimestamp(float(reservation["outcome_expires_at"]), timezone.utc)
                    .isoformat().replace("+00:00", "Z") if rows else None
                ),
                "chain_valid": True,
            }
            db.commit()
            return result
        except DeliveryReservationError:
            self._rollback(db)
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError):
            self._rollback(db)
            raise DeliveryReservationError("delivery_outcome_storage_unavailable") from None
        finally:
            db.close()
