"""Durable, fail-closed SQLite reservations for the unwired delivery boundary.

This adapter performs no delivery and has no provider dependency. It stores
only an HMAC digest of each idempotency key. A stable, application-injected
secret is required so a restart cannot accidentally create a second key
space; a secret mismatch therefore fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
from typing import Callable


class DeliveryReservationError(RuntimeError):
    """Sanitized storage failure suitable for the delivery boundary."""


@dataclass(frozen=True)
class DeliveryReservationPolicy:
    """Explicit resource and lifetime bounds for durable reservations."""

    max_reservations: int = 50_000
    retention_seconds: int = 7 * 24 * 60 * 60
    busy_timeout_seconds: float = 5.0

    def __post_init__(self):
        if (type(self.max_reservations) is not int
                or not 1 <= self.max_reservations <= 1_000_000):
            raise DeliveryReservationError("delivery_reservation_policy_invalid")
        if (type(self.retention_seconds) is not int
                or not 60 <= self.retention_seconds <= 30 * 24 * 60 * 60):
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
    _SCHEMA_VERSION = "1"

    def __init__(self, database_path: str | Path, *, key_secret: bytes,
                 policy: DeliveryReservationPolicy = DeliveryReservationPolicy(),
                 clock: Callable[[], float] = time.time):
        if (not isinstance(database_path, (str, Path)) or not isinstance(key_secret, bytes)
                or not 32 <= len(key_secret) <= 256 or not isinstance(policy, DeliveryReservationPolicy)
                or not callable(clock)):
            raise DeliveryReservationError("delivery_reservation_configuration_invalid")
        self._path = Path(database_path).expanduser().absolute()
        self._secret = bytes(key_secret)
        self.policy = policy
        self._clock = clock
        self._secret_fingerprint = hashlib.sha256(self._secret).hexdigest()
        self._prepare_path()
        self._initialize_schema()

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(durable=True, "
                f"max_reservations={self.policy.max_reservations}, "
                f"retention_seconds={self.policy.retention_seconds})")

    def _prepare_path(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for ancestor in (self._path.parent, *self._path.parent.parents):
                if ancestor.is_symlink():
                    raise OSError
            self._path.parent.chmod(0o700)
            if self._path.exists():
                self._assert_safe_file()
            else:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(self._path, flags, 0o600)
                os.close(descriptor)
                self._assert_safe_file()
        except OSError:
            raise DeliveryReservationError("delivery_reservation_storage_unavailable") from None

    def _assert_safe_file(self) -> None:
        details = self._path.lstat()
        if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or details.st_nlink != 1):
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

    def _initialize_schema(self) -> None:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_reservation_meta (
                       singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                       schema_version TEXT NOT NULL,
                       secret_fingerprint TEXT NOT NULL
                   )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS delivery_reservations (
                       key_digest BLOB PRIMARY KEY NOT NULL CHECK(length(key_digest)=32),
                       reserved_at REAL NOT NULL,
                       expires_at REAL NOT NULL CHECK(expires_at > reserved_at)
                   ) WITHOUT ROWID"""
            )
            columns = tuple((row[1], row[2], row[5]) for row in db.execute(
                "PRAGMA table_info(delivery_reservations)"
            ))
            if columns != (("key_digest", "BLOB", 1), ("reserved_at", "REAL", 0),
                           ("expires_at", "REAL", 0)):
                raise sqlite3.DatabaseError("unexpected_reservation_schema")
            row = db.execute(
                "SELECT schema_version,secret_fingerprint FROM delivery_reservation_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO delivery_reservation_meta VALUES (1,?,?)",
                    (self._SCHEMA_VERSION, self._secret_fingerprint),
                )
            elif (row[0] != self._SCHEMA_VERSION
                  or not hmac.compare_digest(str(row[1]), self._secret_fingerprint)):
                raise sqlite3.DatabaseError("reservation_metadata_mismatch")
            if db.execute("SELECT COUNT(*) FROM delivery_reservation_meta").fetchone()[0] != 1:
                raise sqlite3.DatabaseError("unexpected_reservation_metadata")
            db.commit()
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

    def reserve_once(self, key: str) -> bool:
        """Atomically reserve ``key`` once for the configured retention window."""
        if (not isinstance(key, str) or not 32 <= len(key) <= 128
                or any(ord(character) < 33 or ord(character) > 126 for character in key)):
            raise DeliveryReservationError("delivery_reservation_key_invalid")
        now = self._now()
        expires_at = now + self.policy.retention_seconds
        if not math.isfinite(expires_at):
            raise DeliveryReservationError("delivery_reservation_clock_unavailable")
        digest = hmac.new(self._secret, key.encode("ascii"), hashlib.sha256).digest()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM delivery_reservations WHERE expires_at <= ?", (now,))
            if db.execute(
                "SELECT 1 FROM delivery_reservations WHERE key_digest=?", (digest,)
            ).fetchone() is not None:
                db.commit()
                return False
            count = int(db.execute("SELECT COUNT(*) FROM delivery_reservations").fetchone()[0])
            if count >= self.policy.max_reservations:
                raise DeliveryReservationError("delivery_reservation_capacity_exhausted")
            db.execute(
                "INSERT INTO delivery_reservations(key_digest,reserved_at,expires_at) VALUES (?,?,?)",
                (digest, now, expires_at),
            )
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
