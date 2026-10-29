#!/usr/bin/env python3
"""Offline synthetic preflight rehearsal; never an activation command.

No application configuration is read or changed. The only files created are a
synthetic ledger and checkpoint in a fresh directory outside the source tree;
the directory is removed before the sanitized result is returned.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import io
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from delivery_boundary import DEFAULT_DELIVERY_TIMEOUT_SECONDS
from delivery_provider_readiness import required_dispatch_marker_retention_seconds
from delivery_reservations import DeliveryReservationPolicy, SQLiteDeliveryReservationStore
from scripts import preflight


class RehearsalFailure(RuntimeError):
    """Private diagnostic details never enter the public result."""


class NoSendAdapter:
    """Capability shape only; calling send makes the rehearsal fail."""

    def __init__(self):
        self.send_calls = 0

    def send(self, *_args, **_kwargs):
        self.send_calls += 1
        raise RehearsalFailure()


def _require(condition: bool) -> None:
    if not condition:
        raise RehearsalFailure()


@contextmanager
def _workspace_parent(raw: Path | None):
    """Validate without writing, then pin the existing parent until cleanup."""
    value = os.fspath(ROOT.parent if raw is None else raw)
    _require(isinstance(value, str) and bool(value) and len(value) <= 4096)
    _require(not any(ord(character) < 32 or ord(character) == 127
                     or 0xD800 <= ord(character) <= 0xDFFF for character in value))
    value.encode("utf-8", "strict")
    os.fsencode(value)
    parent = Path(value)
    _require(parent.is_absolute() and str(parent) == value)
    _require(parent.resolve(strict=True) == parent and preflight.persistent_path_ok(parent, ROOT))
    ancestry = []
    for current in (parent, *parent.parents):
        details = current.lstat()
        _require(stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode))
        ancestry.append((current, details.st_dev, details.st_ino, details.st_uid, details.st_mode))
    first = ancestry[0]
    _require(first[3] == os.geteuid() and not stat.S_IMODE(first[4]) & 0o022)

    def unchanged():
        for current, *identity in ancestry:
            details = current.lstat()
            _require([details.st_dev, details.st_ino, details.st_uid, details.st_mode] == identity)

    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        _require((details.st_dev, details.st_ino, details.st_uid, details.st_mode) == first[1:])
        unchanged()
        # TemporaryDirectory has no dir_fd parameter. /proc anchors its mkdir
        # and cleanup to the already validated directory, even if renamed.
        anchor = Path("/proc/self/fd") / str(descriptor)
        _require(anchor.resolve(strict=True) == parent)
        yield parent, anchor, unchanged
    finally:
        os.close(descriptor)


def _snapshot(directory: Path) -> dict:
    result = {}
    for path in directory.rglob("*"):
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        _require(stat.S_ISREG(details.st_mode) and details.st_nlink == 1
                 and stat.S_IMODE(details.st_mode) == 0o600)
        result[str(path.relative_to(directory))] = (
            path.read_bytes(), details.st_size, details.st_mtime_ns, details.st_ctime_ns,
        )
    return result


def _check_map(settings: dict, adapter, *, registration_open: bool, guard) -> dict:
    guard()
    result = preflight.account_delivery_checks(
        settings, ROOT, registration_open=registration_open, delivery_adapter=adapter,
    )
    guard()
    _require(len({item.id for item in result}) == len(result))
    return {item.id: item for item in result}


def _exercise(directory: Path, adapter: NoSendAdapter, *, guard) -> dict:
    guard()  # A caller/wrapper may have replaced the parent immediately before entry.
    # Deliberately synthetic and unrelated to any configured application secret.
    secret = "synthetic-activation-rehearsal-reservation-key-only-42"
    database = directory / "ledger" / "delivery.sqlite3"
    checkpoint = directory / "checkpoint" / "delivery.json"
    required_retention = required_dispatch_marker_retention_seconds(DEFAULT_DELIVERY_TIMEOUT_SECONDS)
    guard()
    SQLiteDeliveryReservationStore(
        database, checkpoint_path=checkpoint, key_secret=secret.encode("ascii"),
        policy=DeliveryReservationPolicy(outcome_retention_seconds=required_retention),
    )
    guard()
    _require(database.is_file() and checkpoint.is_file())
    _require(not preflight._sqlite_sidecar_present(database))
    guard()
    before = _snapshot(directory)
    guard()
    _require(len(before) == 2)
    settings = {
        "SLPS_ACCOUNT_REGISTRATION_OPEN": "false",
        "SLPS_DELIVERY_RESERVATION_SECRET": secret,
        "SLPS_DELIVERY_DB_PATH": str(database),
        "SLPS_DELIVERY_CHECKPOINT_PATH": str(checkpoint),
        "SLPS_DELIVERY_TIMEOUT_SECONDS": str(DEFAULT_DELIVERY_TIMEOUT_SECONDS),
        "SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS": str(required_retention),
        "SLPS_ACCOUNT_DELIVERY_ADAPTER": "synthetic-never-send",
    }
    capability = preflight.ConfiguredAccountDeliveryAdapter("synthetic-never-send", adapter)
    provider_check = "account_delivery_provider_verification"
    closed = _check_map(settings, capability, registration_open=False, guard=guard)
    local = set(closed) - {provider_check}
    _require(len(local) == 7 and all(closed[key].status == "pass" for key in local))
    _require(closed[provider_check].status == "warning")

    # Hypothetical strict validation only: no setting or application is opened.
    opening = _check_map(settings, capability, registration_open=True, guard=guard)
    _require({key for key, item in opening.items() if item.status == "blocker"} == {provider_check})
    _require(all(opening[key].status == "pass" for key in local))

    probes = (
        ("account_delivery_secret", {"SLPS_DELIVERY_RESERVATION_SECRET": ""}, capability),
        ("account_delivery_db_path", {"SLPS_DELIVERY_DB_PATH": "relative.sqlite3"}, capability),
        ("account_delivery_checkpoint_path", {"SLPS_DELIVERY_CHECKPOINT_PATH": "relative.json"}, capability),
        ("account_delivery_paths_distinct", {"SLPS_DELIVERY_CHECKPOINT_PATH": str(database)}, capability),
        ("account_delivery_secret_stability", {
            "SLPS_DELIVERY_RESERVATION_SECRET": "different-synthetic-activation-reservation-key-43",
        }, capability),
        ("account_delivery_marker_retention", {
            "SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS": str(required_retention - 1),
        }, capability),
        ("account_delivery_adapter", {}, None),
    )
    _require({key for key, _, _ in probes} == local)
    for failed_check, overrides, probe_adapter in probes:
        probe_settings = {**settings, **overrides}
        still_closed = _check_map(probe_settings, probe_adapter, registration_open=False, guard=guard)
        strict = _check_map(probe_settings, probe_adapter, registration_open=True, guard=guard)
        _require(still_closed[failed_check].status == "warning")
        _require(strict[failed_check].status == "blocker")
        _require(strict[provider_check].status == "blocker")
        _require(probe_settings["SLPS_ACCOUNT_REGISTRATION_OPEN"] == "false")

    _require(settings["SLPS_ACCOUNT_REGISTRATION_OPEN"] == "false")
    guard()
    _require(_snapshot(directory) == before and adapter.send_calls == 0)
    guard()
    return {
        "local_prerequisites": {"passed": len(local), "total": len(local)},
        "failed_prerequisite_probes": {"blocked": len(probes), "total": len(probes)},
        "provider_verification_blocks_opening": True,
        "quiescent_state": True,
        "state_unchanged_during_checks": True,
    }


def _remove_known_lexical_child(directory: Path, identity: tuple) -> bool:
    """Remove only our original private inode; never delete an unknown substitute."""
    try:
        details = directory.lstat()
    except FileNotFoundError:
        return True
    if (not directory.name.startswith("slps-delivery-rehearsal-")
            or not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode)
            or details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700
            or (details.st_dev, details.st_ino, details.st_uid, details.st_mode) != identity):
        return False
    shutil.rmtree(directory)
    return not directory.exists()


def run_rehearsal(*, workspace_parent: Path | None = None) -> dict:
    """Return bounded diagnostics only; ignore all real environment settings.

    The optional parent is for isolated tests. It must already exist, be owned
    by this user, be canonical and not group/other-writable, and be outside the
    code and forbidden temporary roots. No permissions are changed for it.
    This proves no real mount, backup, credential or delivery capability.
    """
    adapter = NoSendAdapter()
    network_attempts = 0
    directory = None
    temporary_state_removed = True
    result = {}

    def network_forbidden(*_args, **_kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise RehearsalFailure()

    try:
        with ExitStack() as stack:
            for name in ("socket", "create_connection", "getaddrinfo",
                         "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
                stack.enter_context(patch.object(socket, name, network_forbidden))
            with _workspace_parent(workspace_parent) as (parent, anchor, unchanged):
                cleanup_path = None
                child_identity = None
                child_descriptor = None
                try:
                    unchanged()
                    with TemporaryDirectory(prefix="slps-delivery-rehearsal-", dir=anchor) as temporary:
                        cleanup_path = Path(temporary)
                        temporary_state_removed = False
                        unchanged()
                        directory = parent / cleanup_path.name
                        _require(directory.samefile(cleanup_path)
                                 and stat.S_IMODE(directory.lstat().st_mode) == 0o700)
                        child_descriptor = os.open(cleanup_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                        details = os.fstat(child_descriptor)
                        _require(details.st_uid == os.geteuid() and stat.S_IMODE(details.st_mode) == 0o700)
                        child_identity = (details.st_dev, details.st_ino, details.st_uid, details.st_mode)

                        def guard():
                            unchanged()
                            for child in (cleanup_path, directory):
                                current = child.lstat()
                                _require((current.st_dev, current.st_ino, current.st_uid, current.st_mode)
                                         == child_identity)

                        result = _exercise(directory, adapter, guard=guard)
                        guard()
                finally:
                    try:
                        pinned_removed = cleanup_path is None or not cleanup_path.exists()
                        lexical_removed = directory is None or (
                            _remove_known_lexical_child(directory, child_identity)
                            if child_identity is not None else not directory.exists())
                        original_unlinked = child_descriptor is None or os.fstat(child_descriptor).st_nlink == 0
                        temporary_state_removed = pinned_removed and lexical_removed and original_unlinked
                    finally:
                        if child_descriptor is not None:
                            os.close(child_descriptor)
                _require(temporary_state_removed and network_attempts == 0 and adapter.send_calls == 0)
        result["result"] = "passed"
    except Exception:
        # Never echo exceptions, file names, secret material or internal IDs.
        result = {"result": "failed", "error": "offline_rehearsal_failed"}
    result.update({
        "scope": "offline_synthetic_rehearsal_only",
        "registration_open": False,
        "application_wired": False,
        "provider_verified": False,
        "persistent_storage_verified": False,
        "temporary_state_removed": temporary_state_removed,
        "network_attempts": network_attempts,
        "adapter_send_calls": adapter.send_calls,
        "real_messages_sent": 0,
    })
    return result


def main() -> int:
    result = run_rehearsal()
    try:
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    except Exception:
        # Do not echo or retry a failed write, including at interpreter shutdown.
        sys.stdout = io.StringIO()
        return 2
    return 0 if result["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
