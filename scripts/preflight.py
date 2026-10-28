#!/usr/bin/env python3
"""Offline production-readiness checks for the private SLPS AI pilot.

This command reads configuration and local files only. It never contacts the
AI provider and never prints secret values.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from source_registry import read_registry
from durable_storage import DurableStorageError, profile_from_mapping
from delivery_boundary import DEFAULT_DELIVERY_TIMEOUT_SECONDS, DeliveryBoundaryError
from delivery_provider_readiness import required_dispatch_marker_retention_seconds
from delivery_reservations import DeliveryReservationError, DeliveryReservationPolicy
MASTER_SHA256 = "88a1077d86f78ee1102031739a5a1d1fcfb3750f2aa81639af528b7db8da97b7"
EXPECTED_START = "gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 120"
PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
ACCOUNT_TABLES = {"account_companies", "account_users", "account_tokens"}
ACCOUNT_USER_COLUMNS = {
    "id", "company_id", "email", "password_hash", "role", "locale",
    "email_verified", "membership_verified", "active", "session_version", "created",
}


@dataclass(frozen=True)
class Check:
    id: str
    level: str
    status: str
    message: str


def check(check_id: str, ok: bool, message_ok: str, message_fail: str, *, level: str = "blocker") -> Check:
    return Check(check_id, level, "pass" if ok else level, message_ok if ok else message_fail)


def source_registry(path: Path) -> tuple[bool, int]:
    sources = read_registry(path)
    return True, len(sources)


def persistent_path_ok(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        code_root = root.resolve()
        temporary_roots = (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"))
        return bool(path.is_absolute()
                    and code_root != resolved and code_root not in resolved.parents
                    and not any(directory == resolved or directory in resolved.parents
                                for directory in temporary_roots))
    except (OSError, RuntimeError):
        return False



SQLITE_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


def _sqlite_sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(path.with_name(path.name + suffix) for suffix in SQLITE_SIDECAR_SUFFIXES)


def _sqlite_sidecar_present(path: Path) -> bool:
    for sidecar in _sqlite_sidecars(path):
        try:
            sidecar.lstat()  # Include dangling links without following them.
        except FileNotFoundError:
            continue
        return True
    return False


def _sqlite_file_identity(path: Path) -> tuple[int, ...]:
    details = path.lstat()
    if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
            or details.st_nlink != 1):
        raise sqlite3.OperationalError("sqlite_snapshot_unavailable")
    return (details.st_dev, details.st_ino, details.st_size,
            details.st_mtime_ns, details.st_ctime_ns)


@contextmanager
def _immutable_sqlite(path: Path):
    """Read only a quiescent main file, never creating SQLite sidecars.

    immutable=1 ignores a WAL; therefore sidecars cause a closed failure rather
    than a pass based on an incomplete main-file snapshot. Operators must stop
    writers and checkpoint through the trusted database owner, not preflight.
    """
    before = _sqlite_file_identity(path)
    if _sqlite_sidecar_present(path):
        raise sqlite3.OperationalError("sqlite_snapshot_unavailable")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2)
    try:
        yield connection
    finally:
        connection.close()
        if _sqlite_sidecar_present(path) or _sqlite_file_identity(path) != before:
            raise sqlite3.OperationalError("sqlite_snapshot_changed")


def _delivery_paths_disjoint(first: Path, second: Path) -> bool:
    # Protect the checkpoint's name space too: it must never masquerade as a
    # database or reserve a sibling which another SQLite file will create.
    for left in (first, *_sqlite_sidecars(first)):
        for right in (second, *_sqlite_sidecars(second)):
            if left == right or left in right.parents or right in left.parents:
                return False
    return True


def inspect_account_db(path: Path) -> tuple[bool, int]:
    """Read an existing account DB without creating or changing it."""
    if not path.is_file() or path.is_symlink():
        return False, 0
    with _immutable_sqlite(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not ACCOUNT_TABLES <= tables:
            return False, 0
        columns = {row[1] for row in connection.execute("PRAGMA table_info(account_users)")}
        if not ACCOUNT_USER_COLUMNS <= columns:
            return False, 0
        eligible = connection.execute(
            """SELECT COUNT(*)
               FROM account_users u JOIN account_companies c ON c.id=u.company_id
               WHERE u.active=1 AND u.email_verified=1
                 AND u.membership_verified=1 AND c.verified=1"""
        ).fetchone()[0]
        return True, int(eligible)


@dataclass(frozen=True)
class ConfiguredAccountDeliveryAdapter:
    """Trusted programmatic capability, never constructed from an env string.

    This declaration proves only explicit binding to an injected adapter. No
    transport method is called and it does not attest real deliverability.
    """
    adapter_id: str
    adapter: object = field(repr=False)


def _delivery_file_path(raw: object, root: Path) -> Path | None:
    if (not isinstance(raw, str) or not raw or raw != raw.strip() or len(raw) > 4096
            or any(ord(character) < 32 or ord(character) == 127
                   or 0xD800 <= ord(character) <= 0xDFFF for character in raw)
            or any(part in {".", ".."} for part in raw.split("/"))):
        return None
    # Reject malformed input before Path or any filesystem inspection. Filesystem
    # encodings may accept surrogateescape values that are not valid Unicode.
    try:
        raw.encode("utf-8", "strict")
        os.fsencode(raw)
    except UnicodeError:
        return None
    path = Path(raw)
    if not path.is_absolute() or not persistent_path_ok(path, root):
        return None
    try:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                details = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(details.st_mode):
                return None
            if current != path and not stat.S_ISDIR(details.st_mode):
                return None
            if current == path and (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                                    or stat.S_IMODE(details.st_mode) & 0o077):
                return None
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _delivery_secret_bytes(raw: object, env: dict[str, str]) -> bytes | None:
    if not isinstance(raw, str) or not raw.strip() or any(ord(character) < 32 for character in raw):
        return None
    try:
        secret = raw.encode("utf-8")
    except UnicodeError:
        return None
    # A diversity guard catches empty/repeated placeholders, not entropy proof.
    if not 32 <= len(secret) <= 256 or len(set(secret)) < 8:
        return None
    if any(raw == env.get(variable) for variable in (
            "SLPS_SESSION_SECRET", "SLPS_PILOT_PASSWORD", "SLPS_PRIVATE_GATE_PASSWORD", "OPENAI_API_KEY")):
        return None
    return secret


def _delivery_secret_matches_db(path: Path, secret: bytes) -> bool:
    """Read an existing fingerprint without constructing/migrating the store."""
    with _immutable_sqlite(path) as connection:
        rows = connection.execute(
            "SELECT secret_fingerprint FROM delivery_reservation_meta WHERE singleton=1 LIMIT 2"
        ).fetchall()
        return bool(len(rows) == 1 and isinstance(rows[0][0], str)
                    and re.fullmatch(r"[0-9a-f]{64}", rows[0][0])
                    and hmac.compare_digest(rows[0][0], hashlib.sha256(secret).hexdigest()))


def account_delivery_checks(env: dict[str, str], root: Path, *, registration_open: bool,
                            delivery_adapter: ConfiguredAccountDeliveryAdapter | None = None) -> list[Check]:
    """Offline prerequisites only; no initialization, provider lookup or send."""
    level = "blocker" if registration_open else "warning"
    results = []
    secret = _delivery_secret_bytes(env.get("SLPS_DELIVERY_RESERVATION_SECRET"), env)
    results.append(check("account_delivery_secret", secret is not None,
        "Segreto delivery presente, distinto e con formato adeguato; il valore non viene emesso.",
        "Serve un segreto delivery stabile, distinto e di 32–256 byte non vuoti; generarlo e conservarlo fuori dal codice.", level=level))
    database = _delivery_file_path(env.get("SLPS_DELIVERY_DB_PATH"), root)
    checkpoint = _delivery_file_path(env.get("SLPS_DELIVERY_CHECKPOINT_PATH"), root)
    for check_id, value, label in (("account_delivery_db_path", database, "database delivery"),
                                   ("account_delivery_checkpoint_path", checkpoint, "checkpoint delivery")):
        results.append(check(check_id, value is not None,
            f"Percorso del {label} esplicito, assoluto e sicuro secondo i controlli locali.",
            f"Serve un percorso {label} assoluto non temporaneo, esterno al codice, senza symlink/hardlink e con file privato se esistente.", level=level))
    other_paths = []
    try:
        for variable in ("SLPS_ACCOUNT_DB_PATH", "SLPS_RATE_DB_PATH", "SLPS_CASE_DB_PATH", "SLPS_HISTORY_ROOT",
                         "SLPS_PROMPT_PATH", "SLPS_SOURCES_PATH"):
            raw = env.get(variable)
            if isinstance(raw, str) and raw.strip():
                other_paths.append(Path(raw).resolve(strict=False))
        pairs = [(database, checkpoint)]
        pairs.extend((item, other) for item in (database, checkpoint) for other in other_paths)
        distinct = bool(database and checkpoint) and all(
            _delivery_paths_disjoint(first, second)
            for first, second in pairs if first is not None and second is not None
        )
    except (OSError, RuntimeError, ValueError):
        distinct = False
    results.append(check("account_delivery_paths_distinct", distinct,
        "Database e checkpoint delivery sono separati fra loro, dagli altri archivi/media e dai nomi SQLite riservati.",
        "Database e checkpoint delivery devono essere distinti e non sovrapposti ad archivi, media, file protetti o sibling SQLite -journal/-wal/-shm.", level=level))
    secret_match = False
    existing_database = bool(database and database.exists())
    if secret and existing_database:
        try:
            secret_match = _delivery_secret_matches_db(database, secret)
        except (OSError, sqlite3.Error):
            pass
    results.append(check("account_delivery_secret_stability", secret_match,
        "Il segreto configurato corrisponde all’impronta del registro delivery esistente.",
        "Stabilità non verificata: registro assente/illeggibile, snapshot non quiescente con sidecar SQLite o impronta non corrispondente. Non rigenerare il segreto a ogni riavvio.", level=level))
    timeout_raw = env.get("SLPS_DELIVERY_TIMEOUT_SECONDS", str(DEFAULT_DELIVERY_TIMEOUT_SECONDS))
    retention_raw = env.get("SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS", str(DeliveryReservationPolicy().outcome_retention_seconds))
    retention_ok = False
    try:
        if (not isinstance(timeout_raw, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", timeout_raw)
                or not isinstance(retention_raw, str) or not re.fullmatch(r"[0-9]+", retention_raw)):
            raise ValueError()
        required = required_dispatch_marker_retention_seconds(float(timeout_raw))
        policy = DeliveryReservationPolicy(outcome_retention_seconds=int(retention_raw))
        retention_ok = policy.outcome_retention_seconds >= required
    except (ValueError, OverflowError, DeliveryBoundaryError, DeliveryReservationError):
        pass
    results.append(check("account_delivery_marker_retention", retention_ok,
        "Retention del marcatore sufficiente: TTL massimo del link + timeout arrotondato + margine condiviso.",
        "Retention/timeout delivery non validi o insufficienti per impedire una seconda consegna durante la validità del link.", level=level))
    configured_id = env.get("SLPS_ACCOUNT_DELIVERY_ADAPTER", "")
    adapter_ok = False
    try:
        adapter_ok = bool(isinstance(configured_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", configured_id)
                          and isinstance(delivery_adapter, ConfiguredAccountDeliveryAdapter)
                          and configured_id == delivery_adapter.adapter_id
                          and callable(getattr(delivery_adapter.adapter, "send", None)))
    except Exception:
        pass
    results.append(check("account_delivery_adapter", adapter_ok,
        "Adapter delivery selezionato e associato esplicitamente a una capability programmatica; nessun invio eseguito.",
        "Nessun adapter delivery configurato: una stringa o un flag di ambiente non attestano un collegamento reale.", level=level))
    results.append(Check("account_delivery_provider_verification", level, level,
        "Controllo offline: montaggio persistente, integrità completa del registro/checkpoint, backup e recapito reale non verificati. La registrazione cliente resta chiusa."))
    return results


def run_checks(env: dict[str, str] | None = None, root: Path = ROOT, *,
               delivery_adapter: ConfiguredAccountDeliveryAdapter | None = None) -> list[Check]:
    env = dict(os.environ if env is None else env)
    results: list[Check] = []

    data_mode = env.get("SLPS_DATA_MODE", "synthetic").strip().lower()
    results.append(check(
        "data_mode", data_mode in {"synthetic", "real"},
        f"Modalità dati valida: {data_mode if data_mode in {'synthetic', 'real'} else 'non valida'}.",
        "SLPS_DATA_MODE deve essere synthetic oppure real.",
    ))
    durable_storage_ready = False
    if data_mode == "real":
        profile_name_ok = env.get("SLPS_DURABLE_PROFILE", "").strip() == "single-instance"
        results.append(check(
            "durable_profile", profile_name_ok,
            "Profilo storage single-instance selezionato.",
            "Per dati reali SLPS_DURABLE_PROFILE deve essere single-instance.",
        ))
        layout_ok = False
        if profile_name_ok:
            layout_env = dict(env)
            layout_env["SLPS_DURABLE_MIN_FREE_BYTES"] = "1"
            try:
                profile_from_mapping(layout_env)
                layout_ok = True
            except DurableStorageError:
                pass
        results.append(check(
            "durable_layout", layout_ok,
            "Tutti i database e i media sono confinati nella radice durevole senza symlink o sovrapposizioni.",
            "Layout durevole incompleto o non sicuro: usa percorsi assoluti distinti sotto SLPS_DURABLE_ROOT.",
        ))
        capacity_ok = False
        if layout_ok:
            try:
                profile_from_mapping(env)
                capacity_ok = True
            except DurableStorageError:
                pass
        results.append(check(
            "durable_capacity", capacity_ok,
            "Riserva minima di spazio disponibile verificata localmente.",
            "La riserva di capacità del volume non è valida o non è disponibile.",
        ))
        durable_storage_ready = profile_name_ok and layout_ok and capacity_ok
        results.append(check(
            "real_data_storage", durable_storage_ready,
            "Profilo locale single-instance completo e confinato.",
            "Dati reali bloccati: il profilo single-instance non è completo e valido.",
        ))
        results.append(Check(
            "storage_provider_verification", "blocker", "blocker",
            "Dati reali bloccati: restart, redeploy e ripristino del volume non sono verificati sul provider.",
        ))
    else:
        results.append(check(
            "real_data_storage", True,
            "Modalità sintetica: gli adapter locali non sono autorizzati a contenere dati reali.",
            "",
        ))

    auth_mode = env.get("SLPS_AUTH_MODE", "pilot")
    auth_mode_valid = isinstance(auth_mode, str) and auth_mode in {"pilot", "accounts"}
    results.append(check("auth_mode", auth_mode_valid,
                         f"Modalità di accesso valida: {auth_mode if auth_mode_valid else 'non valida'}.",
                         "SLPS_AUTH_MODE deve essere pilot oppure accounts."))

    password = env.get("SLPS_PILOT_PASSWORD", "")
    session_secret = env.get("SLPS_SESSION_SECRET", "")
    gate_enabled = env.get("SLPS_PRIVATE_GATE_ENABLED", "false")
    gate_enabled = isinstance(gate_enabled, str) and gate_enabled.strip().lower() == "true"
    results.append(check(
        "private_gate", gate_enabled,
        "Protezione di ingresso per l'ambiente riservato attiva.",
        "Lo staging riservato richiede SLPS_PRIVATE_GATE_ENABLED=true: anche sito e risorse devono essere protetti.",
    ))
    gate_password = env.get("SLPS_PRIVATE_GATE_PASSWORD", "")
    gate_password_valid = (isinstance(gate_password, str) and 16 <= len(gate_password) <= 256
                           and bool(gate_password.strip()))
    results.append(check(
        "private_gate_password", gate_password_valid,
        "Password di ingresso riservato configurata.",
        "SLPS_PRIVATE_GATE_PASSWORD deve contenere da 16 a 256 caratteri non tutti vuoti.",
    ))
    results.append(check(
        "private_gate_secrets_distinct",
        bool(gate_password_valid and gate_password != session_secret and gate_password != password),
        "Password di ingresso distinta dagli altri segreti.",
        "La password di ingresso deve essere distinta dal segreto di sessione e dalla password del pilota.",
    ))
    provider_cap_raw = env.get("SLPS_PROVIDER_REQUESTS_TOTAL", "")
    try:
        provider_cap_valid = (isinstance(provider_cap_raw, str)
                              and bool(re.fullmatch(r"[0-9]+", provider_cap_raw.strip()))
                              and 1 <= int(provider_cap_raw) <= 10000)
    except (TypeError, ValueError):
        provider_cap_valid = False
    results.append(check(
        "provider_request_cap", provider_cap_valid,
        "Tetto totale delle richieste al fornitore configurato, inclusi chiarimenti e tentativi falliti.",
        "SLPS_PROVIDER_REQUESTS_TOTAL è obbligatorio per lo staging: intero da 1 a 10000; nessuna chiamata reale senza limite e consumo autorizzato.",
    ))
    results.append(Check(
        "provider_request_cap_scope", "warning", "warning",
        "Il tetto conta tentativi persistenti e non rimborsa errori potenzialmente fatturati; non è un limite monetario. Costi, quota e persistenza del contatore richiedono verifica separata.",
    ))
    results.append(check("session_secret", len(session_secret) >= 32 and bool(session_secret.strip()),
                         "Segreto di sessione configurato.", "Segreto di sessione assente, vuoto o più corto di 32 caratteri."))
    if auth_mode == "pilot":
        results.append(check("pilot_password", len(password) >= 16 and bool(password.strip()),
                             "Password del pilota configurata.", "Password del pilota assente, vuota o più corta di 16 caratteri."))
        results.append(check("secrets_distinct", bool(password and session_secret and password != session_secret),
                             "Password e segreto di sessione sono distinti.", "Password e segreto di sessione devono essere distinti."))
    results.append(check("api_key", bool(env.get("OPENAI_API_KEY", "").strip()),
                         "Credenziale del fornitore AI presente.", "Credenziale del fornitore AI assente."))
    results.append(check("model", bool(env.get("OPENAI_MODEL", "").strip()),
                         "Modello AI selezionato esplicitamente.", "Modello AI non selezionato."))
    results.append(Check("provider_verification", "warning", "warning",
                         "Controllo offline: autenticazione del fornitore, credito e disponibilità del modello non verificati."))

    if auth_mode == "pilot":
        for check_id, variable, default, label in (
            ("tenant_id", "SLPS_PILOT_TENANT_ID", "pilot", "azienda"),
            ("owner_id", "SLPS_PILOT_OWNER_ID", "owner", "proprietario"),
        ):
            principal = env.get(variable, default)
            valid = isinstance(principal, str) and PRINCIPAL_ID.fullmatch(principal) is not None
            results.append(check(check_id, valid,
                                 f"Identificativo {label} valido per accesso e archivio.",
                                 f"{variable} deve contenere da 1 a 64 caratteri ASCII: lettere, numeri, punto, trattino o underscore."))

    if auth_mode == "accounts":
        registration_raw = env.get("SLPS_ACCOUNT_REGISTRATION_OPEN", "false").strip().lower()
        registration_valid = registration_raw in {"true", "false"}
        registration_open = registration_raw == "true"
        results.append(check("account_registration_setting", registration_valid,
                             "Impostazione apertura registrazioni valida.",
                             "SLPS_ACCOUNT_REGISTRATION_OPEN deve essere true oppure false."))

        account_setting = env.get("SLPS_ACCOUNT_DB_PATH", "").strip()
        account_path = Path(account_setting) if account_setting else None
        account_path_ok = bool(account_path and persistent_path_ok(account_path, root))
        results.append(check("account_db_path", account_path_ok,
                             "Percorso assoluto e non temporaneo configurato per l'archivio account.",
                             "In modalità accounts SLPS_ACCOUNT_DB_PATH deve essere esplicito, assoluto, esterno al codice e non temporaneo."))
        results.append(Check("account_db_volume", "warning", "warning",
                             "Controllo offline: montaggio persistente, backup e ripristino dell'archivio account non verificati sul provider."))

        db_valid, eligible_users = False, 0
        if account_path_ok and account_path.exists():
            try:
                db_valid, eligible_users = inspect_account_db(account_path)
            except (OSError, sqlite3.Error):
                db_valid = False
            results.append(check("account_db_schema", db_valid,
                                 "Archivio account esistente, leggibile e con schema atteso.",
                                 "Archivio account esistente ma illeggibile, non regolare o con schema inatteso."))
            if db_valid:
                try:
                    private_mode = stat.S_IMODE(account_path.stat().st_mode) & 0o077 == 0
                except OSError:
                    private_mode = False
                results.append(check("account_db_permissions", private_mode,
                                     "Permessi locali dell'archivio account limitati al proprietario.",
                                     "L'archivio account esistente è accessibile a gruppo/altri o i permessi non sono verificabili."))
        elif account_path_ok:
            results.append(Check("account_db_schema", "warning", "warning",
                                 "Archivio account non ancora creato: schema e permessi saranno verificabili solo dopo l'inizializzazione controllata."))

        if db_valid:
            results.append(check("account_login_ready", eligible_users > 0,
                                 "È presente almeno un account verificato idoneo al collaudo del login.",
                                 "Nessun account verificato è idoneo al collaudo: email, azienda e rappresentanza devono risultare approvate."))
        else:
            results.append(Check("account_login_ready", "blocker", "blocker",
                                 "Il collaudo account richiede un archivio valido con almeno un account verificato."))

        results.extend(account_delivery_checks(env, root, registration_open=registration_open,
                                              delivery_adapter=delivery_adapter))
        if registration_open:
            results.append(Check("account_delivery", "blocker", "blocker",
                                 "Registrazioni aperte senza consegna verificata: email di verifica, recupero password e inviti aziendali non possono essere recapitati. Non aprire lo staging agli utenti."))
        else:
            results.append(Check("account_delivery", "warning", "warning",
                                 "Registrazioni chiuse: il collaudo può usare account predisposti; verifica email, recupero password e inviti restano non disponibili senza un trasporto configurato e collaudato."))
        results.append(Check("company_verification", "warning", "warning",
                             "La verifica di azienda e rappresentanza resta un'operazione umana; procedura, evidenze e responsabile vanno definiti prima dell'onboarding reale."))

    master_setting = env.get("SLPS_PROMPT_PATH", "").strip()
    master_path = Path(master_setting) if master_setting else root / "private/SLPS_AI_Prompt_Master_v1.8.txt"
    master_ok = False
    try:
        master_ok = hashlib.sha256(master_path.read_bytes()).hexdigest() == MASTER_SHA256
    except OSError:
        pass
    results.append(check("master", master_ok, "Master 1.8 presente e impronta verificata.",
                         "Master 1.8 assente, illeggibile o con impronta diversa da quella approvata."))

    sources_setting = env.get("SLPS_SOURCES_PATH", "").strip()
    if not sources_setting:
        results.append(Check("sources", "warning", "warning",
                             "Registro delle fonti non configurato: il pilota funzionerà senza riferimenti normativi verificati."))
    else:
        try:
            sources_ok, source_count = source_registry(Path(sources_setting))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            sources_ok, source_count = False, 0
        if sources_ok and source_count == 0:
            results.append(Check("sources", "warning", "warning",
                                 "Registro delle fonti valido ma vuoto: il pilota non dispone di riferimenti normativi verificati."))
        else:
            results.append(check("sources", sources_ok, "Registro delle fonti leggibile, valido e non vuoto.",
                                 "Registro delle fonti assente, illeggibile o strutturalmente non valido."))

    cookie_secure = env.get("SLPS_COOKIE_SECURE", "true").strip().lower() == "true"
    results.append(check("secure_cookie", cookie_secure, "Cookie di sessione sicuro attivo.",
                         "In produzione SLPS_COOKIE_SECURE deve essere true."))

    rate_raw = env.get("SLPS_ANALYSES_PER_HOUR", "10").strip()
    try:
        rate = int(rate_raw)
        rate_ok = 1 <= rate <= 100
    except ValueError:
        rate_ok = False
    results.append(check("analysis_limit", rate_ok, "Limite orario delle analisi valido.",
                         "SLPS_ANALYSES_PER_HOUR deve essere un intero tra 1 e 100."))

    history_capacity_raw = env.get("SLPS_MAX_HISTORY_BYTES_PER_TENANT", str(1024 * 1024 * 1024)).strip()
    try:
        history_capacity = int(history_capacity_raw)
        history_capacity_ok = history_capacity >= 1024 * 1024
    except ValueError:
        history_capacity_ok = False
    results.append(check(
        "history_capacity", history_capacity_ok,
        "Limite di spazio per azienda configurato.",
        "SLPS_MAX_HISTORY_BYTES_PER_TENANT deve essere un intero di almeno 1048576 byte.",
    ))

    for check_id, variable, label in (
        ("rate", "SLPS_RATE_DB_PATH", "dei limiti"),
        ("case", "SLPS_CASE_DB_PATH", "dei casi"),
        ("history", "SLPS_HISTORY_ROOT", "dei file originali e derivati"),
    ):
        path_setting = env.get(variable, "")
        if not path_setting.strip():
            results.append(Check(f"{check_id}_path", "warning", "warning",
                                 f"Percorso dell'archivio {label} non configurato: il percorso predefinito non garantisce la persistenza."))
        else:
            path = Path(path_setting)
            results.append(check(f"{check_id}_path", persistent_path_ok(path, root),
                                 f"Percorso assoluto esterno al codice configurato per l'archivio {label}.",
                                 f"{variable} deve essere assoluto, esterno al codice e non temporaneo."))
        results.append(Check(f"{check_id}_volume", "warning", "warning",
                             f"Controllo offline: montaggio e persistenza dell'archivio {label} dopo riavvio o deploy non verificati sul provider."))
    results.append(Check("archive_recovery", "warning", "warning",
                         "La prova sintetica locale di backup/ripristino non verifica snapshot, cifratura e ripristino sul provider di destinazione."))

    procfile = root / "Procfile"
    try:
        start_ok = procfile.read_text(encoding="utf-8").strip() == "web: " + EXPECTED_START
    except OSError:
        start_ok = False
    results.append(check("start_command", start_ok, "Procfile contiene il comando di avvio previsto.",
                         "Procfile assente o diverso dal comando di avvio previsto."))
    return results


def report(checks: list[Check]) -> dict:
    blockers = sum(item.status == "blocker" for item in checks)
    warnings = sum(item.status == "warning" for item in checks)
    ids = {item.id for item in checks}
    profile = "accounts" if "account_db_path" in ids else "pilot" if "pilot_password" in ids else "invalid"
    statuses = {item.id: item.status for item in checks}
    data_real = "durable_profile" in ids
    storage_profile = (
        "blocked" if statuses.get("data_mode") != "pass" else
        "single-instance configured" if data_real and all(statuses.get(item) == "pass" for item in (
            "durable_profile", "durable_layout", "durable_capacity", "real_data_storage"
        )) else "blocked" if data_real else "synthetic"
    )
    return {
        "schema_version": 1,
        "verification_scope": "offline_configuration_only",
        "auth_profile": profile,
        "storage_profile": storage_profile,
        "storage_provider_verified": False,
        "ready": blockers == 0,
        "summary": {"blockers": blockers, "warnings": warnings, "passed": len(checks) - blockers - warnings},
        "checks": [asdict(item) for item in checks],
        "network_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Controllo offline della configurazione del pilota SLPS AI.")
    parser.add_argument("--json", action="store_true", help="Emette JSON senza valori segreti.")
    args = parser.parse_args()
    data = report(run_checks())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("SLPS AI · controllo configurazione (nessuna chiamata AI)")
        for item in data["checks"]:
            marker = {"pass": "OK", "warning": "ATTENZIONE", "blocker": "BLOCCO"}[item["status"]]
            print(f"[{marker}] {item['message']}")
        summary = data["summary"]
        print(f"Esito: {summary['blockers']} blocchi, {summary['warnings']} avvisi, {summary['passed']} controlli superati.")
    return 0 if data["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
