#!/usr/bin/env python3
"""Protected offline operator interface for company verification reviews.

The command has no transport and imports no server application. Capability and
decision material are accepted from environment variables or inherited file
descriptors, never as command-line values. Every response is a small JSON
projection that excludes personal data and stored digests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from typing import Mapping, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accounts import (  # noqa: E402
    AccountStore,
    VERIFICATION_APPROVAL_CODES,
    VERIFICATION_EVIDENCE_CATEGORIES,
    VERIFICATION_REJECTION_CODES,
    VerificationAuthorizationError,
    VerificationReviewConflict,
)


SECRET_ENV = "SLPS_VERIFICATION_OPERATOR_SECRET"
OPERATOR_ENV = "SLPS_VERIFICATION_OPERATOR_REF"
IDEMPOTENCY_ENV = "SLPS_VERIFICATION_IDEMPOTENCY_KEY"
DB_ENV = "SLPS_ACCOUNT_DB_PATH"
MAX_SECRET_BYTES = 256
MAX_DECISION_INPUT_BYTES = 4096
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_METADATA_BYTES = 4096


class OperatorInputError(ValueError):
    """Input is absent, ambiguous or outside the offline command contract."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise OperatorInputError("invalid_arguments")


def _parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(add_help=False)
    parser.add_argument("--help", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--secret-fd", type=int)
    commands = parser.add_subparsers(dest="command")

    queue = commands.add_parser("list", add_help=False)
    queue.add_argument("--limit", type=int, default=50)

    audit = commands.add_parser("audit", add_help=False)
    audit.add_argument("review_id")

    dossier = commands.add_parser("dossier", add_help=False)
    dossier.add_argument("review_id")

    evidence = commands.add_parser("evidence", add_help=False)
    evidence.add_argument("review_id")
    evidence.add_argument(
        "--category", required=True,
        choices=sorted(set().union(*VERIFICATION_EVIDENCE_CATEGORIES.values())),
    )
    evidence.add_argument("--evidence-fd", type=int, required=True)
    evidence.add_argument("--receipt-fd", type=int, required=True)

    approve = commands.add_parser("approve", add_help=False)
    approve.add_argument("review_id")
    approve.add_argument("--reason", required=True, choices=sorted(VERIFICATION_APPROVAL_CODES))
    approve.add_argument("--decision-fd", type=int)
    approve.add_argument("--evidence-receipt", action="append")

    reject = commands.add_parser("reject", add_help=False)
    reject.add_argument("review_id")
    reject.add_argument("--reason", required=True, choices=sorted(VERIFICATION_REJECTION_CODES))
    reject.add_argument("--decision-fd", type=int)
    reject.add_argument("--evidence-receipt", action="append")
    return parser


def _read_limited_fd(fd: int, maximum: int) -> bytes:
    if isinstance(fd, bool) or fd < 0:
        raise OperatorInputError("invalid_file_descriptor")
    try:
        with os.fdopen(os.dup(fd), "rb") as stream:
            value = stream.read(maximum + 1)
    except OSError as exc:
        raise OperatorInputError("unreadable_file_descriptor") from exc
    if len(value) > maximum:
        raise OperatorInputError("input_too_large")
    return value


def _capability(args: argparse.Namespace, env: Mapping[str, str]) -> bytes:
    configured = env.get(SECRET_ENV)
    if args.secret_fd is not None:
        if configured is not None:
            raise VerificationAuthorizationError("ambiguous_operator_secret")
        secret = _read_limited_fd(args.secret_fd, MAX_SECRET_BYTES)
        if secret.endswith(b"\r\n"):
            secret = secret[:-2]
        elif secret.endswith(b"\n"):
            secret = secret[:-1]
    elif configured is not None:
        try:
            secret = configured.encode("utf-8")
        except UnicodeError as exc:
            raise VerificationAuthorizationError("operator_secret_invalid") from exc
    else:
        raise VerificationAuthorizationError("operator_secret_missing")
    if not 32 <= len(secret) <= MAX_SECRET_BYTES:
        raise VerificationAuthorizationError("operator_secret_invalid")
    return secret


def _decision_input(args: argparse.Namespace, env: Mapping[str, str]) -> tuple[str, str]:
    operator_ref = env.get(OPERATOR_ENV)
    idempotency_key = env.get(IDEMPOTENCY_ENV)
    if args.decision_fd is not None:
        if operator_ref is not None or idempotency_key is not None:
            raise OperatorInputError("ambiguous_decision_input")
        raw = _read_limited_fd(args.decision_fd, MAX_DECISION_INPUT_BYTES)
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorInputError("invalid_decision_input") from exc
        if not isinstance(document, dict) or set(document) != {"operator_ref", "idempotency_key"}:
            raise OperatorInputError("invalid_decision_input")
        operator_ref = document["operator_ref"]
        idempotency_key = document["idempotency_key"]
    if not isinstance(operator_ref, str) or not isinstance(idempotency_key, str):
        raise OperatorInputError("decision_input_missing")
    return operator_ref, idempotency_key


def _utc_timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OperatorInputError("invalid_evidence_time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise OperatorInputError("invalid_evidence_time") from exc
    if parsed.tzinfo != timezone.utc:
        raise OperatorInputError("invalid_evidence_time")
    return parsed.timestamp()


def _evidence_input(args: argparse.Namespace) -> tuple[str, str, float, float, float, str]:
    content = _read_limited_fd(args.evidence_fd, MAX_EVIDENCE_BYTES)
    if not content:
        raise OperatorInputError("empty_evidence")
    raw = _read_limited_fd(args.receipt_fd, MAX_EVIDENCE_METADATA_BYTES)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OperatorInputError("invalid_evidence_metadata") from exc
    expected = {
        "verifier_ref", "idempotency_key", "observed_at_utc",
        "verified_at_utc", "expires_at_utc",
    }
    if not isinstance(document, dict) or set(document) != expected:
        raise OperatorInputError("invalid_evidence_metadata")
    return (
        document["verifier_ref"], document["idempotency_key"],
        _utc_timestamp(document["observed_at_utc"]),
        _utc_timestamp(document["verified_at_utc"]),
        _utc_timestamp(document["expires_at_utc"]),
        hashlib.sha256(content).hexdigest(),
    )


def _database_path(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    raw = args.db if args.db is not None else env.get(DB_ENV)
    if raw is None:
        raise OperatorInputError("database_missing")
    path = Path(raw).expanduser()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise sqlite3.DatabaseError("database_unavailable") from exc
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0
            or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise sqlite3.DatabaseError("database_unavailable")
    return path.resolve()


def _verify_sqlite_file(path: Path) -> None:
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error:
        raise
    if rows != [("ok",)]:
        raise sqlite3.DatabaseError("database_integrity_failed")


def _verify_existing_capability_binding(path: Path, secret: bytes) -> None:
    """Require a pre-provisioned match before AccountStore can run any migration."""
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        table = db.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='account_verification_operator_meta'"""
        ).fetchone()
        if table is None:
            raise VerificationAuthorizationError("verification_operator_unprovisioned")
        row = db.execute(
            """SELECT secret_fingerprint
               FROM account_verification_operator_meta WHERE singleton=1"""
        ).fetchone()
    if row is None:
        raise VerificationAuthorizationError("verification_operator_unprovisioned")
    fingerprint = row[0]
    expected = hashlib.sha256(secret).hexdigest()
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)):
        raise sqlite3.DatabaseError("database_integrity_failed")
    if not hmac.compare_digest(fingerprint, expected):
        raise VerificationAuthorizationError("verification_operator_unauthorized")


def _public_review(review: dict[str, object]) -> dict[str, object]:
    return {
        "review_id": review["id"],
        "kind": review["kind"],
        "status": review["status"],
        "decision_code": review["decision_code"],
        "created_at_utc": review["created_at_utc"],
        "updated_at_utc": review["updated_at_utc"],
        "decided_at_utc": review["decided_at_utc"],
        "version": review["version"],
    }


def _help_document() -> dict[str, object]:
    return {
        "ok": True,
        "operation": "help",
        "commands": ["list", "audit", "dossier", "evidence", "approve", "reject"],
        "capability_sources": [SECRET_ENV, "--secret-fd"],
        "database_sources": [DB_ENV, "--db"],
        "decision_sources": [[OPERATOR_ENV, IDEMPOTENCY_ENV], "--decision-fd"],
        "evidence_sources": ["--evidence-fd", "--receipt-fd"],
    }


def _execute(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, object]:
    if args.help:
        return _help_document()
    if args.command is None:
        raise OperatorInputError("command_missing")
    secret = _capability(args, env)
    path = _database_path(args, env)
    _verify_sqlite_file(path)
    _verify_existing_capability_binding(path, secret)
    store = AccountStore(path, verification_operator_secret=secret)
    _verify_sqlite_file(path)
    if args.command == "list":
        reviews = store.list_verification_reviews(
            authorization=secret, status="pending", limit=args.limit,
        )
        return {
            "ok": True,
            "operation": "list",
            "count": len(reviews),
            "reviews": [_public_review(review) for review in reviews],
        }
    if args.command == "audit":
        events = store.verification_review_audit(args.review_id, authorization=secret)
        return {
            "ok": True,
            "operation": "audit",
            "review_id": args.review_id,
            "chain_valid": True,
            "events": [{
                "sequence": event["sequence"],
                "event": event["event"],
                "decision_code": event["decision_code"],
                "created_at_utc": event["created_at_utc"],
                "evidence_bound": event["evidence_bound"],
            } for event in events],
        }
    if args.command == "dossier":
        return {
            "ok": True,
            "operation": "dossier",
            "dossier": store.verification_decision_dossier(
                args.review_id, authorization=secret,
            ),
        }
    if args.command == "evidence":
        (verifier_ref, idempotency_key, observed_at, verified_at, expires_at,
         content_sha256) = _evidence_input(args)
        receipt = store.record_verification_evidence(
            args.review_id, category=args.category,
            content_sha256=content_sha256, observed_at=observed_at,
            verified_at=verified_at, expires_at=expires_at,
            verifier_ref=verifier_ref, idempotency_key=idempotency_key,
            authorization=secret,
        )
        return {
            "ok": True, "operation": "evidence",
            "receipt": {
                "receipt_id": receipt["id"], "category": receipt["category"],
                "observed_at_utc": receipt["observed_at_utc"],
                "verified_at_utc": receipt["verified_at_utc"],
                "expires_at_utc": receipt["expires_at_utc"],
                "integrity_verified": receipt["integrity_verified"],
            },
        }
    operator_ref, idempotency_key = _decision_input(args, env)
    review = store.decide_verification_review(
        args.review_id,
        decision=args.command,
        decision_code=args.reason,
        operator_ref=operator_ref,
        idempotency_key=idempotency_key,
        evidence_receipt_ids=args.evidence_receipt,
        authorization=secret,
    )
    return {
        "ok": True,
        "operation": args.command,
        "review": _public_review(review),
    }


def _error_document(exc: Exception) -> tuple[int, dict[str, object]]:
    if isinstance(exc, VerificationAuthorizationError):
        return 3, {"ok": False, "error": {"code": "authorization_failed"}}
    if isinstance(exc, VerificationReviewConflict):
        code = str(exc)
        if code == "verification_audit_invalid":
            return 4, {"ok": False, "error": {"code": "audit_invalid"}}
        if code == "verification_evidence_invalid":
            return 4, {"ok": False, "error": {"code": "evidence_invalid"}}
        allowed = {
            "verification_review_unavailable",
            "verification_review_already_decided",
            "verification_idempotency_conflict",
            "verification_company_not_verified",
            "verification_subject_unavailable",
            "verification_evidence_unavailable",
            "verification_evidence_invalid",
            "verification_evidence_incomplete",
            "verification_evidence_idempotency_conflict",
        }
        return 5, {"ok": False, "error": {
            "code": code if code in allowed else "review_conflict",
        }}
    if isinstance(exc, sqlite3.Error):
        return 4, {"ok": False, "error": {"code": "database_unavailable"}}
    if isinstance(exc, (OperatorInputError, ValueError, OSError)):
        return 2, {"ok": False, "error": {"code": "invalid_input"}}
    return 6, {"ok": False, "error": {"code": "internal_failure"}}


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None,
         stdout: TextIO = sys.stdout) -> int:
    environment = os.environ if env is None else env
    try:
        args = _parser().parse_args(argv)
        document = _execute(args, environment)
        status = 0
    except Exception as exc:
        status, document = _error_document(exc)
    json.dump(document, stdout, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    stdout.write("\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
