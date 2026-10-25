#!/usr/bin/env python3
"""Offline production-readiness checks for the private SLPS AI pilot.

This command reads configuration and local files only. It never contacts the
AI provider and never prints secret values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
MASTER_SHA256 = "88a1077d86f78ee1102031739a5a1d1fcfb3750f2aa81639af528b7db8da97b7"
EXPECTED_START = "gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 1 --timeout 120"
PRINCIPAL_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class Check:
    id: str
    level: str
    status: str
    message: str


def check(check_id: str, ok: bool, message_ok: str, message_fail: str, *, level: str = "blocker") -> Check:
    return Check(check_id, level, "pass" if ok else level, message_ok if ok else message_fail)


def source_registry(path: Path) -> tuple[bool, int]:
    raw = path.read_bytes()
    if len(raw) > 200_000:
        return False, 0
    sources = json.loads(raw)
    if not isinstance(sources, list) or len(sources) > 30:
        return False, 0
    ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            return False, 0
        for key in ("id", "title", "url", "verified_at", "excerpt"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                return False, 0
        url = urlparse(source["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return False, 0
        if source["id"] in ids or len(source["excerpt"]) > 20_000:
            return False, 0
        datetime.fromisoformat(source["verified_at"].replace("Z", "+00:00"))
        ids.add(source["id"])
    return True, len(sources)


def run_checks(env: dict[str, str] | None = None, root: Path = ROOT) -> list[Check]:
    env = dict(os.environ if env is None else env)
    results: list[Check] = []

    password = env.get("SLPS_PILOT_PASSWORD", "")
    session_secret = env.get("SLPS_SESSION_SECRET", "")
    results.append(check("pilot_password", len(password) >= 16 and bool(password.strip()),
                         "Password del pilota configurata.", "Password del pilota assente, vuota o più corta di 16 caratteri."))
    results.append(check("session_secret", len(session_secret) >= 32 and bool(session_secret.strip()),
                         "Segreto di sessione configurato.", "Segreto di sessione assente, vuoto o più corto di 32 caratteri."))
    results.append(check("secrets_distinct", bool(password and session_secret and password != session_secret),
                         "Password e segreto di sessione sono distinti.", "Password e segreto di sessione devono essere distinti."))
    results.append(check("api_key", bool(env.get("OPENAI_API_KEY", "").strip()),
                         "Credenziale del fornitore AI presente.", "Credenziale del fornitore AI assente."))
    results.append(check("model", bool(env.get("OPENAI_MODEL", "").strip()),
                         "Modello AI selezionato esplicitamente.", "Modello AI non selezionato."))
    results.append(Check("provider_verification", "warning", "warning",
                         "Controllo offline: autenticazione del fornitore, credito e disponibilità del modello non verificati."))

    for check_id, variable, default, label in (
        ("tenant_id", "SLPS_PILOT_TENANT_ID", "pilot", "azienda"),
        ("owner_id", "SLPS_PILOT_OWNER_ID", "owner", "proprietario"),
    ):
        principal = env.get(variable, default)
        valid = isinstance(principal, str) and PRINCIPAL_ID.fullmatch(principal) is not None
        results.append(check(check_id, valid,
                             f"Identificativo {label} valido per accesso e archivio.",
                             f"{variable} deve contenere da 1 a 64 caratteri ASCII: lettere, numeri, punto, trattino o underscore."))

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

    for check_id, variable, label in (
        ("rate", "SLPS_RATE_DB_PATH", "dei limiti"),
        ("case", "SLPS_CASE_DB_PATH", "dei casi"),
    ):
        path_setting = env.get(variable, "")
        if not path_setting.strip():
            results.append(Check(f"{check_id}_path", "warning", "warning",
                                 f"Percorso dell'archivio {label} non configurato: il percorso predefinito non garantisce la persistenza."))
        else:
            path = Path(path_setting)
            try:
                resolved = path.resolve()
                code_root = root.resolve()
                temporary_roots = (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"))
                unsafe = (not path.is_absolute() or code_root == resolved or code_root in resolved.parents
                          or any(directory == resolved or directory in resolved.parents for directory in temporary_roots))
            except (OSError, RuntimeError):
                unsafe = True
            results.append(check(f"{check_id}_path", not unsafe,
                                 f"Percorso assoluto esterno al codice configurato per l'archivio {label}.",
                                 f"{variable} deve essere assoluto, esterno al codice e non temporaneo."))
        results.append(Check(f"{check_id}_volume", "warning", "warning",
                             f"Controllo offline: montaggio e persistenza dell'archivio {label} dopo riavvio o deploy non verificati sul provider."))
    results.append(Check("archive_recovery", "warning", "warning",
                         "Controllo offline: backup e ripristino dell'archivio dei casi non verificati; richiedono una prova separata."))

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
    return {
        "schema_version": 1,
        "verification_scope": "offline_configuration_only",
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
