from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import shutil

import pytest

from delivery_reservations import (DeliveryReservationError, DeliveryReservationPolicy,
                                   SQLiteDeliveryReservationStore)


SECRET = b"synthetic-test-secret-only-32-bytes!!"
KEY = "delivery:synthetic:" + "k" * 40
RECONCILIATION = "delivery-outcome:" + "r" * 40


def store(tmp_path, *, now=1_000.0, cap=50_000, retention=600,
          outcome_retention=3_600, secret=SECRET):
    clock = now if callable(now) else lambda: now
    return SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3", key_secret=secret,
        policy=DeliveryReservationPolicy(
            max_reservations=cap, reservation_retention_seconds=retention,
            outcome_retention_seconds=outcome_retention,
        ),
        clock=clock,
    )


def test_reservation_survives_restart_and_database_never_contains_raw_key(tmp_path):
    first = store(tmp_path)
    assert first.reserve_once(KEY) is True
    second = store(tmp_path)
    assert second.reserve_once(KEY) is False
    raw = (tmp_path / "private" / "delivery.sqlite3").read_bytes()
    assert KEY.encode() not in raw
    assert "synthetic-test-secret" not in repr(second)
    assert oct(os.stat(tmp_path / "private" / "delivery.sqlite3").st_mode & 0o777) == "0o600"


def test_same_key_has_one_winner_across_concurrent_store_instances(tmp_path):
    path = tmp_path / "private" / "delivery.sqlite3"
    first = store(tmp_path)
    stores = [first] + [SQLiteDeliveryReservationStore(path, key_secret=SECRET,
        policy=first.policy, clock=lambda: 1_000.0) for _ in range(11)]
    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        results = list(pool.map(lambda item: item.reserve_once(KEY), stores))
    assert results.count(True) == 1
    assert results.count(False) == len(stores) - 1


def test_capacity_never_evicts_an_active_reservation(tmp_path):
    reservations = store(tmp_path, cap=2)
    keys = [f"delivery:synthetic:{character * 40}" for character in "abc"]
    assert reservations.reserve_once(keys[0])
    assert reservations.reserve_once(keys[1])
    with pytest.raises(DeliveryReservationError, match="capacity_exhausted"):
        reservations.reserve_once(keys[2])
    assert reservations.reserve_once(keys[0]) is False


def test_only_expired_rows_are_reclaimed_and_key_can_be_reused(tmp_path):
    now = [1_000.0]
    reservations = store(tmp_path, now=lambda: now[0], cap=1, retention=60)
    assert reservations.reserve_once(KEY)
    now[0] = 1_059.999
    with pytest.raises(DeliveryReservationError, match="capacity_exhausted"):
        reservations.reserve_once("delivery:synthetic:" + "z" * 40)
    now[0] = 1_060.0
    assert reservations.reserve_once("delivery:synthetic:" + "z" * 40)
    now[0] = 1_120.0
    assert reservations.reserve_once(KEY)


def test_secret_mismatch_after_restart_fails_closed(tmp_path):
    store(tmp_path).reserve_once(KEY)
    with pytest.raises(DeliveryReservationError, match="schema_invalid"):
        store(tmp_path, secret=b"a-different-synthetic-secret-32b!")


def test_corrupt_or_incompatible_database_fails_closed(tmp_path):
    path = tmp_path / "private" / "delivery.sqlite3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a sqlite database")
    with pytest.raises(DeliveryReservationError, match="schema_invalid"):
        store(tmp_path)

    path.unlink()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE delivery_reservations(key_digest TEXT PRIMARY KEY)")
    with pytest.raises(DeliveryReservationError, match="schema_invalid"):
        store(tmp_path)


def test_symlink_database_path_is_rejected(tmp_path):
    target = tmp_path / "target.sqlite3"
    target.touch()
    link = tmp_path / "private" / "delivery.sqlite3"
    link.parent.mkdir()
    link.symlink_to(target)
    with pytest.raises(DeliveryReservationError, match="storage_unavailable"):
        store(tmp_path)


def test_hardlinked_database_path_is_rejected(tmp_path):
    target = tmp_path / "target.sqlite3"
    target.touch()
    link = tmp_path / "private" / "delivery.sqlite3"
    link.parent.mkdir()
    os.link(target, link)
    with pytest.raises(DeliveryReservationError, match="storage_unavailable"):
        store(tmp_path)


@pytest.mark.parametrize("key", ["short", "x" * 129, "x" * 31 + "\n"])
def test_invalid_keys_fail_before_database_mutation(tmp_path, key):
    reservations = store(tmp_path)
    with pytest.raises(DeliveryReservationError, match="key_invalid"):
        reservations.reserve_once(key)
    with sqlite3.connect(tmp_path / "private" / "delivery.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM delivery_reservations").fetchone()[0] == 0


@pytest.mark.parametrize("values", [
    {"max_reservations": 0}, {"max_reservations": True},
    {"reservation_retention_seconds": 59},
    {"reservation_retention_seconds": 30 * 24 * 60 * 60 + 1},
    {"outcome_retention_seconds": 59},
    {"outcome_retention_seconds": 365 * 24 * 60 * 60 + 1},
    {"busy_timeout_seconds": 0}, {"busy_timeout_seconds": float("nan")},
])
def test_policy_bounds_are_explicit_and_fail_closed(values):
    with pytest.raises(DeliveryReservationError, match="policy_invalid"):
        DeliveryReservationPolicy(**values)


def test_nonfinite_or_failed_clock_fails_closed(tmp_path):
    for clock in (lambda: float("nan"), lambda: -1, lambda: (_ for _ in ()).throw(RuntimeError())):
        reservations = store(tmp_path, now=clock)
        with pytest.raises(DeliveryReservationError, match="clock_unavailable"):
            reservations.reserve_once(KEY)


def test_store_remains_unwired_from_application():
    source = Path("server.py").read_text(encoding="utf-8")
    assert "SQLiteDeliveryReservationStore" not in source
    assert "delivery_reservations" not in source


def test_accepted_outcome_is_durable_redacted_and_idempotent(tmp_path):
    first = store(tmp_path)
    assert first.reserve_once(KEY)
    accepted = first.record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key=RECONCILIATION,
        provider_reference="provider-private-message-id",
    )
    replay = store(tmp_path).record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key=RECONCILIATION,
        provider_reference="provider-private-message-id",
    )

    assert replay == accepted == {
        "sequence": 1, "status": "accepted", "code": "transport_accepted",
        "recorded_at_utc": "1970-01-01T00:16:40Z", "final": True,
        "provider_reference_present": True, "chain_valid": True,
    }
    document = store(tmp_path).outcome_status(KEY)
    assert document["outcome"] == accepted and document["chain_valid"] is True
    rendered = json.dumps(document, sort_keys=True)
    raw = (tmp_path / "private" / "delivery.sqlite3").read_bytes()
    checkpoint = (tmp_path / "private" / "delivery.sqlite3.checkpoint").read_bytes()
    for private in (KEY, RECONCILIATION, "provider-private-message-id"):
        assert private not in rendered
        assert private.encode() not in raw
        assert private.encode() not in checkpoint


def test_uncertain_outcome_can_be_reconciled_once_to_final(tmp_path):
    clock = [1_000.0]
    ledger = store(tmp_path, now=lambda: clock[0])
    assert ledger.reserve_once(KEY)
    uncertain = ledger.record_outcome(
        KEY, status="uncertain", code="acknowledgement_lost",
        reconciliation_key=RECONCILIATION,
    )
    assert uncertain["sequence"] == 1 and uncertain["final"] is False
    clock[0] = 1_001.0
    final = ledger.record_outcome(
        KEY, status="failed", code="transport_failed",
        reconciliation_key="delivery-outcome:" + "f" * 40,
    )
    assert final["sequence"] == 2 and final["final"] is True
    with pytest.raises(DeliveryReservationError, match="outcome_conflict"):
        ledger.record_outcome(
            KEY, status="accepted", code="transport_accepted",
            reconciliation_key="delivery-outcome:" + "a" * 40,
        )


def test_reconciliation_replay_rejects_changed_payload(tmp_path):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    ledger.record_outcome(
        KEY, status="uncertain", code="timeout",
        reconciliation_key=RECONCILIATION,
    )
    with pytest.raises(DeliveryReservationError, match="outcome_conflict"):
        ledger.record_outcome(
            KEY, status="uncertain", code="acknowledgement_lost",
            reconciliation_key=RECONCILIATION,
        )


@pytest.mark.parametrize("values,error", [
    ({"status": "accepted", "code": "timeout"}, "outcome_invalid"),
    ({"status": "unknown", "code": "transport_accepted"}, "outcome_invalid"),
    ({"reconciliation_key": "short"}, "reconciliation_key_invalid"),
    ({"provider_reference": "bad\nreference"}, "outcome_invalid"),
])
def test_invalid_outcomes_do_not_mutate_ledger(tmp_path, values, error):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    request = dict(status="accepted", code="transport_accepted",
                   reconciliation_key=RECONCILIATION, provider_reference="")
    request.update(values)
    with pytest.raises(DeliveryReservationError, match=error):
        ledger.record_outcome(KEY, **request)
    assert ledger.outcome_status(KEY)["outcome"] is None


def test_missing_and_expired_reservations_reject_outcomes(tmp_path):
    clock = [1_000.0]
    ledger = store(tmp_path, now=lambda: clock[0], retention=60)
    with pytest.raises(DeliveryReservationError, match="reservation_missing"):
        ledger.record_outcome(
            KEY, status="accepted", code="transport_accepted",
            reconciliation_key=RECONCILIATION,
        )
    ledger.reserve_once(KEY)
    clock[0] = 1_060.0
    with pytest.raises(DeliveryReservationError, match="reservation_missing"):
        ledger.record_outcome(
            KEY, status="accepted", code="transport_accepted",
            reconciliation_key=RECONCILIATION,
        )


def test_outcome_retention_blocks_reopen_and_allows_late_final_reconciliation(tmp_path):
    clock = [1_000.0]
    ledger = store(tmp_path, now=lambda: clock[0], retention=60, outcome_retention=300)
    assert ledger.reserve_once(KEY)
    clock[0] = 1_001.0
    ledger.record_outcome(
        KEY, status="uncertain", code="timeout", reconciliation_key=RECONCILIATION,
    )
    clock[0] = 1_061.0
    assert ledger.reserve_once(KEY) is False
    final = ledger.record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key="delivery-outcome:" + "f" * 40,
    )
    assert final["sequence"] == 2 and final["final"] is True
    clock[0] = 1_360.0
    assert ledger.reserve_once(KEY) is False
    clock[0] = 1_361.0
    with pytest.raises(DeliveryReservationError, match="outcome_expired"):
        ledger.outcome_status(KEY)
    assert ledger.reserve_once(KEY) is True
    assert ledger.outcome_status(KEY)["outcome"] is None


def test_retained_outcome_consumes_bounded_capacity_until_expiry(tmp_path):
    clock = [1_000.0]
    ledger = store(
        tmp_path, now=lambda: clock[0], cap=1, retention=60, outcome_retention=300,
    )
    ledger.reserve_once(KEY)
    ledger.record_outcome(
        KEY, status="failed", code="transport_failed",
        reconciliation_key=RECONCILIATION,
    )
    other = "delivery:other:" + "o" * 40
    clock[0] = 1_100.0
    with pytest.raises(DeliveryReservationError, match="capacity_exhausted"):
        ledger.reserve_once(other)
    clock[0] = 1_300.0
    assert ledger.reserve_once(other) is True


def test_shorter_outcome_retention_never_shortens_reservation_idempotency(tmp_path):
    clock = [1_000.0]
    ledger = store(
        tmp_path, now=lambda: clock[0], retention=600, outcome_retention=60,
    )
    assert ledger.reserve_once(KEY)
    ledger.record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key=RECONCILIATION,
    )
    clock[0] = 1_060.0
    with pytest.raises(DeliveryReservationError, match="outcome_expired"):
        ledger.outcome_status(KEY)
    assert ledger.reserve_once(KEY) is False
    clock[0] = 1_599.0
    assert ledger.reserve_once(KEY) is False
    clock[0] = 1_600.0
    assert ledger.reserve_once(KEY) is True


@pytest.mark.parametrize("mutation", [
    "event", "head", "delete", "reservation_time", "nonfinite_event_time",
    "counter", "metadata", "coherent_truncation",
])
def test_outcome_tamper_fails_closed(tmp_path, mutation):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    ledger.record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key=RECONCILIATION,
    )
    path = tmp_path / "private" / "delivery.sqlite3"
    with sqlite3.connect(path) as db:
        if mutation == "event":
            db.execute("UPDATE delivery_outcome_events SET code='transport_rejected'")
        elif mutation == "head":
            db.execute("UPDATE delivery_reservations SET outcome_head=?", (b"0" * 32,))
        elif mutation == "delete":
            db.execute("DELETE FROM delivery_outcome_events")
        elif mutation == "reservation_time":
            db.execute("UPDATE delivery_reservations SET reserved_at=999")
        elif mutation == "nonfinite_event_time":
            db.execute("UPDATE delivery_outcome_events SET recorded_at=?", (float("inf"),))
        elif mutation == "counter":
            db.execute("UPDATE delivery_reservations SET outcome_count=2")
        elif mutation == "metadata":
            db.execute("UPDATE delivery_reservation_meta SET schema_version='tampered'")
        else:
            db.execute("DELETE FROM delivery_outcome_events")
            db.execute(
                """UPDATE delivery_reservations SET outcome_count=0,outcome_head=NULL,
                   outcome_status=NULL,outcome_code=NULL,outcome_updated_at=NULL,
                   provider_reference_present=0,outcome_expires_at=NULL"""
            )
    with pytest.raises(DeliveryReservationError, match="integrity_invalid"):
        ledger.outcome_status(KEY)


def test_v1_database_migrates_without_losing_duplicate_reservation(tmp_path):
    path = tmp_path / "private" / "delivery.sqlite3"
    path.parent.mkdir(parents=True)
    digest = hmac.new(SECRET, KEY.encode("ascii"), hashlib.sha256).digest()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE delivery_reservation_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL, secret_fingerprint TEXT NOT NULL)")
        db.execute("CREATE TABLE delivery_reservations (key_digest BLOB PRIMARY KEY NOT NULL CHECK(length(key_digest)=32), reserved_at REAL NOT NULL, expires_at REAL NOT NULL CHECK(expires_at > reserved_at)) WITHOUT ROWID")
        db.execute("INSERT INTO delivery_reservation_meta VALUES (1,'1',?)",
                   (hashlib.sha256(SECRET).hexdigest(),))
        db.execute("INSERT INTO delivery_reservations VALUES (?,?,?)", (digest, 1_000, 1_600))
    migrated = store(tmp_path)
    assert migrated.reserve_once(KEY) is False
    assert migrated.outcome_status(KEY)["outcome"] is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT schema_version FROM delivery_reservation_meta").fetchone()[0] == "3"


def test_sqlite_snapshot_restore_preserves_verified_outcome_chain(tmp_path):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    expected = ledger.record_outcome(
        KEY, status="uncertain", code="timeout",
        reconciliation_key=RECONCILIATION,
    )
    source = tmp_path / "private" / "delivery.sqlite3"
    restored = tmp_path / "restored" / "delivery.sqlite3"
    restored_checkpoint = tmp_path / "restored" / "delivery.sqlite3.checkpoint"
    restored.parent.mkdir()
    with sqlite3.connect(source) as src, sqlite3.connect(restored) as dst:
        src.backup(dst)
    shutil.copyfile(source.with_name(source.name + ".checkpoint"), restored_checkpoint)
    restored.chmod(0o600)
    copy = SQLiteDeliveryReservationStore(
        restored, key_secret=SECRET,
        policy=DeliveryReservationPolicy(
            reservation_retention_seconds=600, outcome_retention_seconds=3_600,
        ), clock=lambda: 1_000.0,
    )
    assert copy.outcome_status(KEY)["outcome"] == expected


def test_database_only_rollback_is_rejected_by_authenticated_checkpoint(tmp_path):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    ledger.record_outcome(
        KEY, status="uncertain", code="timeout", reconciliation_key=RECONCILIATION,
    )
    source = tmp_path / "private" / "delivery.sqlite3"
    old = tmp_path / "old.sqlite3"
    with sqlite3.connect(source) as src, sqlite3.connect(old) as dst:
        src.backup(dst)
    ledger.record_outcome(
        KEY, status="accepted", code="transport_accepted",
        reconciliation_key="delivery-outcome:" + "f" * 40,
    )
    shutil.copyfile(old, source)
    with pytest.raises(DeliveryReservationError, match="integrity_invalid"):
        ledger.outcome_status(KEY)


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_checkpoint_missing_or_changed_fails_closed(tmp_path, mutation):
    ledger = store(tmp_path)
    ledger.reserve_once(KEY)
    checkpoint = tmp_path / "private" / "delivery.sqlite3.checkpoint"
    if mutation == "missing":
        checkpoint.unlink()
    else:
        checkpoint.write_text('{"format":1,"revision":999}', encoding="ascii")
    with pytest.raises(DeliveryReservationError, match="integrity_invalid"):
        ledger.outcome_status(KEY)


def run_operator(path, command, request, *, secret=SECRET):
    request_read, request_write = os.pipe()
    secret_read, secret_write = os.pipe()
    try:
        os.write(request_write, json.dumps(request).encode())
        os.close(request_write); request_write = -1
        os.write(secret_write, secret + b"\n")
        os.close(secret_write); secret_write = -1
        result = subprocess.run([
            sys.executable, "scripts/delivery_outcome_operator.py", "--db", str(path),
            "--secret-fd", str(secret_read), command, "--request-fd", str(request_read),
        ], cwd=Path(__file__).parents[1], pass_fds=(secret_read, request_read),
            capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout), result.stdout + result.stderr
    finally:
        for descriptor in (request_read, request_write, secret_read, secret_write):
            if descriptor >= 0:
                os.close(descriptor)


def test_offline_operator_records_and_reads_only_redacted_metadata(tmp_path):
    path = tmp_path / "private" / "delivery.sqlite3"
    ledger = SQLiteDeliveryReservationStore(path, key_secret=SECRET)
    ledger.reserve_once(KEY)
    request = {"idempotency_key": KEY, "status": "accepted",
               "code": "transport_accepted", "reconciliation_key": RECONCILIATION,
               "provider_reference": "provider-private-message-id"}
    status, document, rendered = run_operator(path, "record", request)
    assert status == 0 and document["outcome"]["status"] == "accepted"
    status, state, rendered_status = run_operator(
        path, "status", {"idempotency_key": KEY},
    )
    assert status == 0 and state["delivery"]["outcome"] == document["outcome"]
    for private in (KEY, RECONCILIATION, "provider-private-message-id", str(path), SECRET.decode()):
        assert private not in rendered + rendered_status


def test_outcome_ledger_and_operator_remain_unwired_and_network_free():
    source = Path("server.py").read_text(encoding="utf-8")
    operator = Path("scripts/delivery_outcome_operator.py").read_text(encoding="utf-8")
    assert "record_outcome" not in source and "delivery_outcome_operator" not in source
    assert "socket" not in operator and "requests" not in operator and "http" not in operator
