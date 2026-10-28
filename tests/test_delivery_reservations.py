from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3

import pytest

from delivery_reservations import (DeliveryReservationError, DeliveryReservationPolicy,
                                   SQLiteDeliveryReservationStore)


SECRET = b"synthetic-test-secret-only-32-bytes!!"
KEY = "delivery:synthetic:" + "k" * 40


def store(tmp_path, *, now=1_000.0, cap=50_000, retention=600, secret=SECRET):
    clock = now if callable(now) else lambda: now
    return SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3", key_secret=secret,
        policy=DeliveryReservationPolicy(max_reservations=cap, retention_seconds=retention),
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
    {"retention_seconds": 59}, {"retention_seconds": 30 * 24 * 60 * 60 + 1},
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
