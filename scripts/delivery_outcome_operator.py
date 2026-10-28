#!/usr/bin/env python3
"""Protected offline operator for the account-delivery outcome ledger.

The command has no transport, provider SDK or network client. Sensitive keys
enter through a bounded JSON file descriptor and are never emitted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_reservations import DeliveryReservationError, SQLiteDeliveryReservationStore


DB_ENV = "SLPS_DELIVERY_DB_PATH"
CHECKPOINT_ENV = "SLPS_DELIVERY_CHECKPOINT_PATH"
SECRET_ENV = "SLPS_DELIVERY_RESERVATION_SECRET"
MAX_REQUEST_BYTES = 4096
MAX_SECRET_BYTES = 256


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db")
    parser.add_argument("--checkpoint")
    parser.add_argument("--secret-fd", type=int)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "record"):
        command = commands.add_parser(name, add_help=False)
        command.add_argument("--request-fd", type=int, required=True)
    return parser


def _read_fd(fd: int, maximum: int) -> bytes:
    if type(fd) is not int or fd < 0:
        raise DeliveryReservationError("delivery_operator_input_invalid")
    data = bytearray()
    while True:
        chunk = os.read(fd, min(1024, maximum + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > maximum:
            raise DeliveryReservationError("delivery_operator_input_invalid")
    return bytes(data)


def _secret(args: argparse.Namespace) -> bytes:
    configured = os.environ.get(SECRET_ENV)
    if args.secret_fd is not None:
        if configured is not None:
            raise DeliveryReservationError("delivery_operator_configuration_invalid")
        secret = _read_fd(args.secret_fd, MAX_SECRET_BYTES).rstrip(b"\r\n")
    else:
        try:
            secret = configured.encode("utf-8") if configured is not None else b""
        except UnicodeError:
            secret = b""
    if not 32 <= len(secret) <= MAX_SECRET_BYTES:
        raise DeliveryReservationError("delivery_operator_authorization_failed")
    return secret


def _protected_file(value: str, error: str) -> Path:
    path = Path(value).expanduser().absolute()
    try:
        details = path.lstat()
    except OSError:
        raise DeliveryReservationError(error) from None
    if (not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode)
            or details.st_nlink != 1):
        raise DeliveryReservationError(error)
    return path


def _database(args: argparse.Namespace) -> Path:
    return _protected_file(args.db or os.environ.get(DB_ENV, ""),
                           "delivery_operator_storage_unavailable")


def _checkpoint(args: argparse.Namespace, database: Path) -> Path:
    value = args.checkpoint or os.environ.get(CHECKPOINT_ENV, "")
    if not value:
        value = str(database.with_name(database.name + ".checkpoint"))
    return _protected_file(value, "delivery_operator_storage_unavailable")


def _request(fd: int) -> dict:
    try:
        value = json.loads(_read_fd(fd, MAX_REQUEST_BYTES))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DeliveryReservationError("delivery_operator_input_invalid") from None
    if not isinstance(value, dict):
        raise DeliveryReservationError("delivery_operator_input_invalid")
    return value


def execute(args: argparse.Namespace) -> dict:
    request = _request(args.request_fd)
    allowed = ({"idempotency_key"} if args.command == "status" else {
        "idempotency_key", "status", "code", "reconciliation_key", "provider_reference",
    })
    if set(request) - allowed or "idempotency_key" not in request:
        raise DeliveryReservationError("delivery_operator_input_invalid")
    database = _database(args)
    store = SQLiteDeliveryReservationStore(
        database, checkpoint_path=_checkpoint(args, database), key_secret=_secret(args),
    )
    if args.command == "status":
        return {"ok": True, "operation": "status",
                "delivery": store.outcome_status(request["idempotency_key"])}
    if not {"status", "code", "reconciliation_key"} <= set(request):
        raise DeliveryReservationError("delivery_operator_input_invalid")
    outcome = store.record_outcome(
        request["idempotency_key"], status=request["status"], code=request["code"],
        reconciliation_key=request["reconciliation_key"],
        provider_reference=request.get("provider_reference", ""),
    )
    return {"ok": True, "operation": "record", "outcome": outcome}


def main() -> int:
    try:
        result = execute(_parser().parse_args())
        status = 0
    except DeliveryReservationError as exc:
        code = str(exc)
        if "authorization" in code or "schema" in code:
            public = "authorization_failed"
        elif "conflict" in code:
            public = "outcome_conflict"
        elif "missing" in code:
            public = "reservation_missing"
        elif "expired" in code:
            public = "outcome_expired"
        elif "integrity" in code:
            public = "integrity_invalid"
        elif "input" in code or "invalid" in code:
            public = "input_invalid"
        else:
            public = "storage_unavailable"
        result, status = {"ok": False, "error": {"code": public}}, 3
    except (OSError, ValueError, TypeError):
        result, status = {"ok": False, "error": {"code": "input_invalid"}}, 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
