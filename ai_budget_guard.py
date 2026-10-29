"""Durable, provider-neutral AI usage budget guard.

The guard is deliberately offline.  It contains no endpoint, SDK, credential,
transport, currency price, or provider call.  A future approved adapter may
dispatch only after ``begin_dispatch`` has durably changed a reservation from
``reserved`` to ``dispatched``.  A crash after that transition remains a
potential charge and therefore consumes the full reserved amount until a
usage receipt is reconciled.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from typing import Callable, Iterator


KINDS = frozenset({"vision", "transcription"})
UNCERTAIN_REASONS = frozenset({
    "cancellation_after_dispatch",
    "operator_reconciliation_required",
    "provider_receipt_missing",
    "timeout",
    "transport_error",
})
RELEASE_REASONS = frozenset({"cancelled_before_dispatch", "superseded_before_dispatch"})
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_MAX_USAGE_VALUE = 1_000_000_000_000
_MAX_RATE_VALUE = 1_000_000_000_000


class BudgetGuardError(ValueError):
    """Sanitized, stable guard failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise BudgetGuardError(code, message)


def _integer(value: object, *, minimum: int = 0, maximum: int = _MAX_USAGE_VALUE) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("budget_configuration_invalid", "Configurazione del budget AI non valida.")
    return value


def _identifier(value: object, label: str = "identifier") -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        _fail("budget_identifier_invalid", f"{label} non valido.")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        _fail("budget_binding_invalid", "Digest della sotto-richiesta non valido.")
    return value


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ceil_ratio(value: int, rate: int, denominator: int) -> int:
    if value == 0 or rate == 0:
        return 0
    return (value * rate + denominator - 1) // denominator


@dataclass(frozen=True)
class RateCard:
    """Integer rates in caller-defined micro-units, never a currency claim."""

    input_per_million: int
    output_per_million: int
    image_per_million: int
    audio_per_minute: int
    fixed_per_request: int = 0

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _integer(value, maximum=_MAX_RATE_VALUE)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(asdict(self))


@dataclass(frozen=True)
class Usage:
    input_units: int = 0
    output_units: int = 0
    image_units: int = 0
    audio_milliseconds: int = 0

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            _integer(value)

    def cost(self, rates: RateCard) -> int:
        return (
            rates.fixed_per_request
            + _ceil_ratio(self.input_units, rates.input_per_million, 1_000_000)
            + _ceil_ratio(self.output_units, rates.output_per_million, 1_000_000)
            + _ceil_ratio(self.image_units, rates.image_per_million, 1_000_000)
            + _ceil_ratio(self.audio_milliseconds, rates.audio_per_minute, 60_000)
        )

    def within(self, maximum: "Usage") -> bool:
        return all(asdict(self)[key] <= value for key, value in asdict(maximum).items())


@dataclass(frozen=True)
class BudgetProfile:
    name: str
    ceiling: int
    max_subrequests: int
    max_vision: int
    max_transcription: int

    def __post_init__(self) -> None:
        _identifier(self.name, "profile")
        _integer(self.ceiling, minimum=1, maximum=_MAX_RATE_VALUE)
        _integer(self.max_subrequests, minimum=1, maximum=10_000)
        _integer(self.max_vision, maximum=self.max_subrequests)
        _integer(self.max_transcription, maximum=self.max_subrequests)
        if self.max_vision + self.max_transcription < self.max_subrequests:
            _fail("budget_configuration_invalid", "Limiti delle sotto-richieste incoerenti.")

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(asdict(self))


@dataclass(frozen=True)
class SubrequestPlan:
    kind: str
    ordinal: int
    binding_digest: str = field(repr=False)
    maximum_usage: Usage

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            _fail("budget_kind_invalid", "Tipo di sotto-richiesta non valido.")
        _integer(self.ordinal, minimum=1, maximum=10_000)
        _digest(self.binding_digest)
        if not isinstance(self.maximum_usage, Usage):
            _fail("budget_configuration_invalid", "Uso massimo non valido.")

    def stable_id(self, job_id: str) -> str:
        _identifier(job_id, "job")
        value = {"binding": self.binding_digest, "job": job_id, "kind": self.kind, "ordinal": self.ordinal}
        return "srq_" + _canonical_digest(value)[:40]


@dataclass(frozen=True)
class Reservation:
    job_id: str
    subrequest_id: str
    kind: str
    ordinal: int
    reserved_cost: int
    capability: str = field(repr=False)


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    status: str
    ceiling: int
    liability: int
    remaining: int
    subrequests: int
    vision: int
    transcription: int
    unresolved: int


@dataclass(frozen=True)
class ReceiptMetadata:
    """Sanitized durable outcome; raw receipt IDs and detailed usage stay private."""

    subrequest_id: str
    state: str
    receipt_id_digest: str
    receipt_digest: str
    actual_cost: int


class AIBudgetGuard:
    """SQLite-backed reserve/dispatch/reconcile state machine."""

    def __init__(self, database_path: str | Path, *, rates: RateCard,
                 profile: BudgetProfile, clock: Callable[[], float] = time.time):
        if not isinstance(rates, RateCard) or not isinstance(profile, BudgetProfile) or not callable(clock):
            _fail("budget_configuration_invalid", "Configurazione del budget AI non valida.")
        path = Path(database_path)
        if not path.is_absolute() or path.name in {"", ".", ".."}:
            _fail("budget_configuration_invalid", "Percorso del registro budget non valido.")
        path = Path(os.path.abspath(os.fspath(path)))
        self.path, self.rates, self.profile, self.clock = path, rates, profile, clock
        self._file_identity: tuple[int, int] | None = None
        self._ancestor_identities: tuple[tuple[Path, int, int], ...] = ()
        self._prepare_storage()
        self._initialize()

    @staticmethod
    def _storage_unavailable() -> None:
        raise BudgetGuardError(
            "budget_storage_unavailable", "Registro budget non disponibile."
        ) from None

    @staticmethod
    def _path_components(path: Path) -> tuple[Path, ...]:
        current = Path(path.anchor)
        components = [current]
        for part in path.parts[1:]:
            current = current / part
            components.append(current)
        return tuple(components)

    def _prepare_storage(self) -> None:
        descriptor: int | None = None
        try:
            components = self._path_components(self.path.parent)
            for component in components:
                try:
                    details = os.lstat(component)
                except FileNotFoundError:
                    os.mkdir(component, 0o700)
                    details = os.lstat(component)
                if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                    raise OSError
            parent = os.lstat(self.path.parent)
            if stat.S_IMODE(parent.st_mode) != 0o700:
                raise OSError

            try:
                details = os.lstat(self.path)
            except FileNotFoundError:
                flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(self.path, flags, 0o600)
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
                details = os.fstat(descriptor)
                os.close(descriptor)
                descriptor = None
                directory_flags = os.O_RDONLY
                if hasattr(os, "O_DIRECTORY"):
                    directory_flags |= os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    directory_flags |= os.O_NOFOLLOW
                parent_descriptor = os.open(self.path.parent, directory_flags)
                try:
                    os.fsync(parent_descriptor)
                finally:
                    os.close(parent_descriptor)
            self._assert_safe_file_details(details)
            self._file_identity = (details.st_dev, details.st_ino)
            self._ancestor_identities = tuple(
                (component, item.st_dev, item.st_ino)
                for component in components
                for item in (os.lstat(component),)
            )
            self._assert_storage_identity()
        except (OSError, ValueError):
            self._storage_unavailable()
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    @staticmethod
    def _assert_safe_file_details(details: os.stat_result) -> None:
        if (stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1 or stat.S_IMODE(details.st_mode) != 0o600):
            raise OSError

    def _assert_storage_identity(self) -> None:
        if self._file_identity is None or not self._ancestor_identities:
            raise OSError
        for component, device, inode in self._ancestor_identities:
            details = os.lstat(component)
            if (stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode)
                    or (details.st_dev, details.st_ino) != (device, inode)):
                raise OSError
        parent = os.lstat(self.path.parent)
        if stat.S_IMODE(parent.st_mode) != 0o700:
            raise OSError
        details = os.lstat(self.path)
        self._assert_safe_file_details(details)
        if (details.st_dev, details.st_ino) != self._file_identity:
            raise OSError

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self._assert_storage_identity()
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            self._assert_storage_identity()
            yield connection
            self._assert_storage_identity()
        except BudgetGuardError:
            raise
        except (OSError, sqlite3.Error):
            self._storage_unavailable()
        finally:
            if connection is not None:
                try:
                    connection.close()
                    self._assert_storage_identity()
                except (OSError, sqlite3.Error):
                    self._storage_unavailable()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS budget_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version INTEGER NOT NULL,
                    rate_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS budget_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ('open', 'blocked')),
                    profile_fingerprint TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    ceiling INTEGER NOT NULL,
                    max_subrequests INTEGER NOT NULL,
                    max_vision INTEGER NOT NULL,
                    max_transcription INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS budget_subrequests (
                    subrequest_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES budget_jobs(job_id),
                    kind TEXT NOT NULL CHECK (kind IN ('vision', 'transcription')),
                    ordinal INTEGER NOT NULL,
                    binding_digest TEXT NOT NULL,
                    maximum_usage_json TEXT NOT NULL,
                    reserved_cost INTEGER NOT NULL,
                    actual_usage_json TEXT,
                    actual_cost INTEGER,
                    receipt_id_digest TEXT,
                    receipt_digest TEXT,
                    state TEXT NOT NULL CHECK (state IN
                        ('reserved', 'dispatched', 'uncertain', 'settled', 'released', 'overage')),
                    capability_digest TEXT NOT NULL,
                    reason_code TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    CHECK ((receipt_id_digest IS NULL) = (receipt_digest IS NULL)),
                    CHECK ((state IN ('settled', 'overage')) = (receipt_digest IS NOT NULL)),
                    CHECK ((state IN ('settled', 'overage')) = (actual_cost IS NOT NULL)),
                    CHECK ((state IN ('settled', 'overage')) = (actual_usage_json IS NOT NULL)),
                    UNIQUE(job_id, kind, ordinal)
                );
                CREATE INDEX IF NOT EXISTS budget_subrequests_job ON budget_subrequests(job_id);
            """)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM budget_meta WHERE singleton = 1").fetchone()
            expected = (2, self.rates.fingerprint)
            if row is None:
                connection.execute(
                    "INSERT INTO budget_meta(singleton, schema_version, rate_fingerprint) VALUES(1, ?, ?)",
                    expected,
                )
            elif (row["schema_version"], row["rate_fingerprint"]) != expected:
                _fail("budget_configuration_conflict", "Configurazione diversa dal registro budget esistente.")
            connection.execute("COMMIT")

    def start_job(self, job_id: str, *, profile: BudgetProfile | None = None) -> JobSnapshot:
        job_id = _identifier(job_id, "job")
        selected = self.profile if profile is None else profile
        if not isinstance(selected, BudgetProfile):
            _fail("budget_configuration_invalid", "Profilo del lavoro non valido.")
        with self._transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO budget_jobs(
                    job_id, status, profile_fingerprint, profile_json, ceiling,
                    max_subrequests, max_vision, max_transcription, created_at
                ) VALUES(?, 'open', ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, selected.fingerprint,
                 json.dumps(asdict(selected), sort_keys=True, separators=(",", ":")),
                 selected.ceiling, selected.max_subrequests, selected.max_vision,
                 selected.max_transcription, self._now()),
            )
            row = connection.execute("SELECT profile_fingerprint FROM budget_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row["profile_fingerprint"] != selected.fingerprint:
                _fail("budget_profile_conflict", "Profilo diverso dal lavoro budget esistente.")
            return self._snapshot(connection, job_id)

    def reserve(self, job_id: str, plan: SubrequestPlan) -> Reservation:
        job_id = _identifier(job_id, "job")
        if not isinstance(plan, SubrequestPlan):
            _fail("budget_configuration_invalid", "Piano della sotto-richiesta non valido.")
        subrequest_id = plan.stable_id(job_id)
        reserved_cost = plan.maximum_usage.cost(self.rates)
        if reserved_cost <= 0:
            _fail("budget_reservation_invalid", "La riserva deve essere positiva.")
        capability = secrets.token_urlsafe(32)
        capability_digest = hashlib.sha256(capability.encode()).hexdigest()
        now = self._now()
        with self._transaction() as connection:
            job = connection.execute("SELECT * FROM budget_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if job is None:
                _fail("budget_job_missing", "Lavoro budget non inizializzato.")
            if job["status"] != "open":
                _fail("budget_job_blocked", "Lavoro budget bloccato.")
            if connection.execute("SELECT 1 FROM budget_subrequests WHERE subrequest_id = ?", (subrequest_id,)).fetchone():
                _fail("budget_subrequest_already_recorded", "Sotto-richiesta già registrata; riconciliare prima di ritentare.")
            snapshot = self._snapshot(connection, job_id)
            kind_count = snapshot.vision if plan.kind == "vision" else snapshot.transcription
            kind_limit = job["max_vision"] if plan.kind == "vision" else job["max_transcription"]
            if snapshot.subrequests >= job["max_subrequests"] or kind_count >= kind_limit:
                _fail("budget_call_limit_reached", "Limite delle sotto-richieste raggiunto.")
            if snapshot.liability + reserved_cost > job["ceiling"]:
                _fail("budget_ceiling_exceeded", "Budget residuo insufficiente per la sotto-richiesta.")
            try:
                connection.execute("""
                    INSERT INTO budget_subrequests(
                        subrequest_id, job_id, kind, ordinal, binding_digest, maximum_usage_json,
                        reserved_cost, state, capability_digest, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)
                """, (subrequest_id, job_id, plan.kind, plan.ordinal, plan.binding_digest,
                      self._usage_json(plan.maximum_usage), reserved_cost, capability_digest, now, now))
            except sqlite3.IntegrityError:
                _fail("budget_ordinal_conflict", "Ordinale della sotto-richiesta già utilizzato.")
        return Reservation(job_id, subrequest_id, plan.kind, plan.ordinal, reserved_cost, capability)

    def begin_dispatch(self, reservation: Reservation) -> None:
        self._transition(reservation, "reserved", "dispatched")

    def release_before_dispatch(self, reservation: Reservation, reason_code: str) -> None:
        if reason_code not in RELEASE_REASONS:
            _fail("budget_reason_invalid", "Motivo di rilascio non valido.")
        self._transition(reservation, "reserved", "released", reason_code=reason_code)

    def mark_uncertain(self, reservation: Reservation, reason_code: str) -> None:
        if reason_code not in UNCERTAIN_REASONS:
            _fail("budget_reason_invalid", "Motivo dell'esito incerto non valido.")
        self._transition(reservation, "dispatched", "uncertain", reason_code=reason_code)

    def settle(self, reservation: Reservation, receipt_id: str, usage: Usage) -> ReceiptMetadata:
        return self._settle(reservation, receipt_id, usage, expected_states=("dispatched",))

    def reconcile_uncertain(self, reservation: Reservation, receipt_id: str,
                            usage: Usage) -> ReceiptMetadata:
        return self._settle(reservation, receipt_id, usage, expected_states=("uncertain",))

    def snapshot(self, job_id: str) -> JobSnapshot:
        job_id = _identifier(job_id, "job")
        with self._connection() as connection:
            return self._snapshot(connection, job_id)

    def subrequest_state(self, subrequest_id: str) -> str:
        if not isinstance(subrequest_id, str) or not subrequest_id.startswith("srq_"):
            _fail("budget_identifier_invalid", "Identificativo sotto-richiesta non valido.")
        with self._connection() as connection:
            row = connection.execute("SELECT state FROM budget_subrequests WHERE subrequest_id = ?", (subrequest_id,)).fetchone()
        if row is None:
            _fail("budget_subrequest_missing", "Sotto-richiesta non trovata.")
        return row["state"]

    def receipt(self, subrequest_id: str) -> ReceiptMetadata:
        if (not isinstance(subrequest_id, str) or not subrequest_id.startswith("srq_")
                or len(subrequest_id) != 44):
            _fail("budget_identifier_invalid", "Identificativo sotto-richiesta non valido.")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM budget_subrequests WHERE subrequest_id=?", (subrequest_id,)
            ).fetchone()
            if row is None or row["receipt_digest"] is None:
                _fail("budget_receipt_missing", "Ricevuta di utilizzo non trovata.")
            return self._receipt_metadata(row)

    def _settle(self, reservation: Reservation, receipt_id: str, usage: Usage, *,
                expected_states: tuple[str, ...]) -> ReceiptMetadata:
        if not isinstance(usage, Usage):
            _fail("budget_usage_invalid", "Ricevuta di utilizzo non valida.")
        receipt_id = _identifier(receipt_id, "receipt")
        receipt_id_digest = _canonical_digest({"receipt_id": receipt_id})
        receipt_digest = _canonical_digest({
            "receipt_id": receipt_id,
            "subrequest_id": reservation.subrequest_id if isinstance(reservation, Reservation) else None,
            "usage": asdict(usage),
        })
        with self._transaction() as connection:
            row = self._authorized_row(connection, reservation)
            if row["state"] in {"settled", "overage"}:
                if (secrets.compare_digest(row["receipt_id_digest"], receipt_id_digest)
                        and secrets.compare_digest(row["receipt_digest"], receipt_digest)):
                    return self._receipt_metadata(row)
                _fail("budget_receipt_conflict", "Ricevuta diversa per la sotto-richiesta già riconciliata.")
            if row["state"] not in expected_states:
                _fail("budget_state_conflict", "Stato della sotto-richiesta non riconciliabile.")
            maximum = Usage(**json.loads(row["maximum_usage_json"]))
            actual_cost = usage.cost(self.rates)
            now = self._now()
            if not usage.within(maximum) or actual_cost > row["reserved_cost"]:
                connection.execute(
                    "UPDATE budget_subrequests SET state='overage', actual_usage_json=?, actual_cost=?, receipt_id_digest=?, receipt_digest=?, reason_code='usage_exceeds_reservation', updated_at=? WHERE subrequest_id=?",
                    (self._usage_json(usage), actual_cost, receipt_id_digest, receipt_digest,
                     now, reservation.subrequest_id),
                )
                connection.execute("UPDATE budget_jobs SET status='blocked' WHERE job_id=?", (reservation.job_id,))
            else:
                connection.execute(
                    "UPDATE budget_subrequests SET state='settled', actual_usage_json=?, actual_cost=?, receipt_id_digest=?, receipt_digest=?, reason_code=NULL, updated_at=? WHERE subrequest_id=?",
                    (self._usage_json(usage), actual_cost, receipt_id_digest, receipt_digest,
                     now, reservation.subrequest_id),
                )
            persisted = connection.execute(
                "SELECT * FROM budget_subrequests WHERE subrequest_id=?",
                (reservation.subrequest_id,),
            ).fetchone()
            return self._receipt_metadata(persisted)

    def _transition(self, reservation: Reservation, expected: str, target: str, *, reason_code: str | None = None) -> None:
        with self._transaction() as connection:
            row = self._authorized_row(connection, reservation)
            if row["state"] != expected:
                _fail("budget_state_conflict", "Transizione della sotto-richiesta non valida.")
            connection.execute(
                "UPDATE budget_subrequests SET state=?, reason_code=?, updated_at=? WHERE subrequest_id=?",
                (target, reason_code, self._now(), reservation.subrequest_id),
            )

    def _authorized_row(self, connection: sqlite3.Connection, reservation: Reservation) -> sqlite3.Row:
        if not isinstance(reservation, Reservation) or not isinstance(reservation.capability, str):
            _fail("budget_capability_invalid", "Capacità della riserva non valida.")
        row = connection.execute(
            "SELECT * FROM budget_subrequests WHERE subrequest_id=? AND job_id=?",
            (reservation.subrequest_id, reservation.job_id),
        ).fetchone()
        digest = hashlib.sha256(reservation.capability.encode()).hexdigest()
        if row is None or not secrets.compare_digest(row["capability_digest"], digest):
            _fail("budget_capability_invalid", "Capacità della riserva non valida.")
        if row["kind"] != reservation.kind or row["ordinal"] != reservation.ordinal or row["reserved_cost"] != reservation.reserved_cost:
            _fail("budget_capability_invalid", "Capacità della riserva non valida.")
        return row

    def _snapshot(self, connection: sqlite3.Connection, job_id: str) -> JobSnapshot:
        job = connection.execute("SELECT * FROM budget_jobs WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            _fail("budget_job_missing", "Lavoro budget non inizializzato.")
        row = connection.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN kind='vision' THEN 1 ELSE 0 END) AS vision,
                   SUM(CASE WHEN kind='transcription' THEN 1 ELSE 0 END) AS transcription,
                   SUM(CASE WHEN state IN ('reserved','dispatched','uncertain') THEN reserved_cost
                            WHEN state IN ('settled','overage') THEN actual_cost ELSE 0 END) AS liability,
                   SUM(CASE WHEN state IN ('dispatched','uncertain','overage') THEN 1 ELSE 0 END) AS unresolved
              FROM budget_subrequests WHERE job_id=?
        """, (job_id,)).fetchone()
        liability = int(row["liability"] or 0)
        return JobSnapshot(job_id, job["status"], job["ceiling"], liability,
                           max(0, job["ceiling"] - liability), int(row["total"] or 0),
                           int(row["vision"] or 0), int(row["transcription"] or 0),
                           int(row["unresolved"] or 0))

    @staticmethod
    def _receipt_metadata(row: sqlite3.Row) -> ReceiptMetadata:
        return ReceiptMetadata(
            subrequest_id=row["subrequest_id"],
            state=row["state"],
            receipt_id_digest=row["receipt_id_digest"],
            receipt_digest=row["receipt_digest"],
            actual_cost=int(row["actual_cost"]),
        )

    def _now(self) -> float:
        try:
            value = self.clock()
        except Exception:
            _fail("budget_clock_invalid", "Orologio del budget non disponibile.")
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            _fail("budget_clock_invalid", "Orologio del budget non valido.")
        return float(value)

    @staticmethod
    def _usage_json(usage: Usage) -> str:
        return json.dumps(asdict(usage), sort_keys=True, separators=(",", ":"))
