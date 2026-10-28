"""Offline delivery activation guards; synthetic fixtures never send messages."""
import hashlib
import json
import os
from pathlib import Path
import socket
from unittest import mock

import pytest

from delivery_boundary import DEFAULT_DELIVERY_TIMEOUT_SECONDS
from delivery_provider_readiness import required_dispatch_marker_retention_seconds
from delivery_reservations import SQLiteDeliveryReservationStore
from scripts import preflight


SECRET = "synthetic-delivery-preflight-secret-unique-42"


def configured(**overrides):
    values = {
        "SLPS_DELIVERY_RESERVATION_SECRET": SECRET,
        "SLPS_SESSION_SECRET": "different-session-test-secret-at-least32characters",
        "SLPS_PRIVATE_GATE_PASSWORD": "different-private-gate-password",
        "SLPS_PILOT_PASSWORD": "different-pilot-test-password",
        "OPENAI_API_KEY": "synthetic-present-not-a-live-provider-credential",
        "SLPS_DELIVERY_DB_PATH": "/var/data/slps/db/delivery.sqlite3",
        "SLPS_DELIVERY_CHECKPOINT_PATH": "/var/data/slps/state/delivery.checkpoint.json",
        "SLPS_ACCOUNT_DB_PATH": "/var/data/slps/db/accounts.sqlite3",
        "SLPS_RATE_DB_PATH": "/var/data/slps/db/limits.sqlite3",
        "SLPS_CASE_DB_PATH": "/var/data/slps/db/cases.sqlite3",
        "SLPS_HISTORY_ROOT": "/var/data/slps/media",
        "SLPS_DELIVERY_TIMEOUT_SECONDS": str(DEFAULT_DELIVERY_TIMEOUT_SECONDS),
        "SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS": str(required_dispatch_marker_retention_seconds(DEFAULT_DELIVERY_TIMEOUT_SECONDS)),
        "SLPS_ACCOUNT_DELIVERY_ADAPTER": "explicit-test-adapter",
    }
    values.update(overrides)
    return values


def checks(env=None, *, root=Path("/opt/slps-test-code"), registration_open=True, adapter=None):
    return {item.id: item for item in preflight.account_delivery_checks(
        env if env is not None else configured(), root, registration_open=registration_open,
        delivery_adapter=adapter,
    )}


class NeverSendAdapter:
    def send(self, *_args, **_kwargs):
        pytest.fail("Offline preflight must not send")


def capability():
    return preflight.ConfiguredAccountDeliveryAdapter("explicit-test-adapter", NeverSendAdapter())


def test_closed_defaults_remain_closed_and_requirements_warn_without_initialization(tmp_path):
    before = list(tmp_path.iterdir())
    found = checks({}, root=tmp_path, registration_open=False)
    assert all(item.status in {"pass", "warning"} for item in found.values())
    assert found["account_delivery_secret"].status == "warning"
    assert found["account_delivery_adapter"].status == "warning"
    assert found["account_delivery_marker_retention"].status == "pass"
    assert list(tmp_path.iterdir()) == before


def test_open_registration_blocks_each_missing_delivery_prerequisite():
    found = checks({})
    for key in ("account_delivery_secret", "account_delivery_db_path", "account_delivery_checkpoint_path",
                "account_delivery_paths_distinct", "account_delivery_secret_stability", "account_delivery_adapter"):
        assert found[key].status == "blocker"
    assert found["account_delivery_provider_verification"].status == "blocker"


@pytest.mark.parametrize("secret", [None, "", "short", " " * 40, "x" * 32, "x" * 257, "line\nbreak-value-of-more-than32characters", "\ud800"*40])
def test_bad_secret_fails_closed_without_echoing_raw_value(secret):
    found = checks(configured(SLPS_DELIVERY_RESERVATION_SECRET=secret))
    assert found["account_delivery_secret"].status == "blocker"
    serialized = json.dumps([vars(item) for item in found.values()])
    if isinstance(secret, str) and secret:
        assert secret not in serialized


@pytest.mark.parametrize("variable", ["SLPS_SESSION_SECRET", "SLPS_PILOT_PASSWORD", "SLPS_PRIVATE_GATE_PASSWORD", "OPENAI_API_KEY"])
def test_delivery_secret_must_be_distinct_from_other_secrets(variable):
    env = configured(); env["SLPS_DELIVERY_RESERVATION_SECRET"] = env[variable]
    assert checks(env)["account_delivery_secret"].status == "blocker"


@pytest.mark.parametrize("variable", ["SLPS_DELIVERY_DB_PATH", "SLPS_DELIVERY_CHECKPOINT_PATH"])
@pytest.mark.parametrize("value", ["", "relative.sqlite3", "/tmp/ledger.sqlite3", "/var/tmp/ledger.sqlite3", "/dev/shm/ledger.sqlite3", "/opt/slps-test-code/ledger.sqlite3", "/var/data/../data/ledger.sqlite3", "/var/data/ledger.sqlite3\n"])
def test_both_state_paths_are_explicit_absolute_non_temporary_and_outside_code(variable, value):
    env = configured(**{variable: value})
    key = "account_delivery_db_path" if variable.endswith("DB_PATH") else "account_delivery_checkpoint_path"
    assert checks(env)[key].status == "blocker"


@pytest.mark.parametrize("variable", ["SLPS_DELIVERY_DB_PATH", "SLPS_DELIVERY_CHECKPOINT_PATH"])
@pytest.mark.parametrize("character", [*(chr(value) for value in range(32)), "\x7f", "\ud800", "\udbff", "\udc80", "\udfff"])
def test_delivery_paths_reject_controls_and_surrogates_before_filesystem_inspection(variable, character):
    value = "/var/data/bad" + character + ".sqlite3"
    with mock.patch.object(preflight, "persistent_path_ok") as inspect_path:
        assert preflight._delivery_file_path(value, Path("/opt/slps-test-code")) is None
        inspect_path.assert_not_called()
    key = "account_delivery_db_path" if variable.endswith("DB_PATH") else "account_delivery_checkpoint_path"
    found = checks(configured(**{variable: value}))
    assert found[key].status == "blocker"
    assert value not in json.dumps([vars(item) for item in found.values()], ensure_ascii=False)


@pytest.mark.parametrize("variable", ["SLPS_DELIVERY_DB_PATH", "SLPS_DELIVERY_CHECKPOINT_PATH"])
def test_delivery_paths_fail_closed_when_filesystem_cannot_encode_them(variable):
    value = "/var/data/not-encodable-\u00e9.sqlite3"
    real_fsencode = os.fsencode

    def reject_path(raw):
        if raw == value:
            raise UnicodeEncodeError("ascii", raw, 0, len(raw), "not encodable")
        return real_fsencode(raw)

    with mock.patch.object(preflight.os, "fsencode", side_effect=reject_path):
        with mock.patch.object(preflight, "persistent_path_ok") as inspect_path:
            assert preflight._delivery_file_path(value, Path("/opt/slps-test-code")) is None
            inspect_path.assert_not_called()
        key = "account_delivery_db_path" if variable.endswith("DB_PATH") else "account_delivery_checkpoint_path"
        assert checks(configured(**{variable: value}))[key].status == "blocker"


@pytest.mark.parametrize("other", ["SLPS_ACCOUNT_DB_PATH", "SLPS_RATE_DB_PATH", "SLPS_CASE_DB_PATH", "SLPS_HISTORY_ROOT", "SLPS_PROMPT_PATH", "SLPS_SOURCES_PATH", "SLPS_DELIVERY_DB_PATH"])
def test_checkpoint_cannot_alias_or_overlap_other_protected_paths(other):
    env = configured(); env[other] = env["SLPS_DELIVERY_CHECKPOINT_PATH"]
    assert checks(env)["account_delivery_paths_distinct"].status == "blocker"
    env = configured(); env["SLPS_DELIVERY_DB_PATH"] = env["SLPS_HISTORY_ROOT"] + "/delivery.sqlite3"
    assert checks(env)["account_delivery_paths_distinct"].status == "blocker"


def test_existing_symlink_ancestor_leaf_hardlink_and_public_permissions_are_rejected(tmp_path):
    private = tmp_path / "private"; private.mkdir()
    db, checkpoint = private / "delivery.db", private / "checkpoint.json"
    db.write_bytes(b"synthetic"); db.chmod(0o600)
    checkpoint.write_bytes(b"synthetic"); checkpoint.chmod(0o600)
    env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
    with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
        assert checks(env)["account_delivery_db_path"].status == "pass"
        link = tmp_path / "linked-parent"; link.symlink_to(private, target_is_directory=True)
        linked_env = {**env, "SLPS_DELIVERY_DB_PATH": str(link / db.name)}
        assert checks(linked_env)["account_delivery_db_path"].status == "blocker"
        leaf = tmp_path / "linked-checkpoint"; leaf.symlink_to(checkpoint)
        assert checks({**env, "SLPS_DELIVERY_CHECKPOINT_PATH": str(leaf)})["account_delivery_checkpoint_path"].status == "blocker"
        hard = tmp_path / "hardlink"; os.link(checkpoint, hard)
        assert checks(env)["account_delivery_checkpoint_path"].status == "blocker"
        hard.unlink(); checkpoint.chmod(0o640)
        assert checks(env)["account_delivery_checkpoint_path"].status == "blocker"


def test_existing_ledger_matches_stable_secret_readonly_and_rotation_is_detected(tmp_path):
    db, checkpoint = tmp_path / "delivery.db", tmp_path / "checkpoint.json"
    SQLiteDeliveryReservationStore(db, checkpoint_path=checkpoint, key_secret=SECRET.encode())
    env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir() if path.is_file()}
    with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
        found = checks(env, adapter=capability())
        assert found["account_delivery_secret_stability"].status == "pass"
        assert found["account_delivery_adapter"].status == "pass"
        assert found["account_delivery_provider_verification"].status == "blocker"
        changed = checks({**env, "SLPS_DELIVERY_RESERVATION_SECRET": "a-different-valid-synthetic-secret-for-restart"})
        assert changed["account_delivery_secret_stability"].status == "blocker"
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir() if path.is_file()}
    assert after == before
    serialized = json.dumps([vars(item) for item in found.values()])
    assert SECRET not in serialized and str(db) not in serialized and str(checkpoint) not in serialized
    assert hashlib.sha256(SECRET.encode()).hexdigest() not in serialized


def test_malformed_fingerprint_is_blocker_not_exception(tmp_path):
    import sqlite3
    db = tmp_path / "malformed.db"; checkpoint = tmp_path / "checkpoint.json"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE delivery_reservation_meta(singleton INTEGER,secret_fingerprint TEXT)")
        connection.execute("INSERT INTO delivery_reservation_meta VALUES (1,?)", ("é"*64,))
    db.chmod(0o600)
    env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
    with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
        assert checks(env)["account_delivery_secret_stability"].status == "blocker"


@pytest.mark.parametrize("timeout", ["8", "8.01", "29.999", "30"])
def test_marker_retention_uses_shared_provider_formula_and_ceil_boundary(timeout):
    required = required_dispatch_marker_retention_seconds(float(timeout))
    env = configured(SLPS_DELIVERY_TIMEOUT_SECONDS=timeout, SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS=str(required))
    assert checks(env)["account_delivery_marker_retention"].status == "pass"
    env["SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS"] = str(required-1)
    assert checks(env)["account_delivery_marker_retention"].status == "blocker"


@pytest.mark.parametrize("timeout,retention", [("nan", "100000"), ("inf", "100000"), ("0", "100000"), ("30.1", "100000"), ("8", "300"), ("8", "invalid"), ("8", "31536001"), ("8", "-1"), ("8", "+100000")])
def test_invalid_delivery_timeout_or_retention_fails_closed(timeout, retention):
    assert checks(configured(SLPS_DELIVERY_TIMEOUT_SECONDS=timeout, SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS=retention))["account_delivery_marker_retention"].status == "blocker"


def test_environment_cannot_auto_attest_an_adapter_and_no_transport_is_invoked(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network forbidden"))
    assert checks(configured())["account_delivery_adapter"].status == "blocker"
    assert checks(configured(SLPS_ACCOUNT_DELIVERY_ADAPTER="true"))["account_delivery_adapter"].status == "blocker"
    assert checks(configured(), adapter=capability())["account_delivery_adapter"].status == "pass"
    wrong = preflight.ConfiguredAccountDeliveryAdapter("another-adapter", NeverSendAdapter())
    assert checks(configured(), adapter=wrong)["account_delivery_adapter"].status == "blocker"


def test_normal_account_preflight_still_blocks_registration_even_with_declarations(tmp_path, monkeypatch):
    env = configured(SLPS_AUTH_MODE="accounts", SLPS_ACCOUNT_REGISTRATION_OPEN="true")
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network forbidden"))
    found = {item.id: item for item in preflight.run_checks(env, tmp_path)}
    assert found["account_delivery_adapter"].status == "blocker"
    assert found["account_delivery"].status == "blocker"
    assert not preflight.report(list(found.values()))["ready"]


def _snapshot_files(directory):
    return {path.name: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns,
                        path.stat().st_ctime_ns)
            for path in directory.iterdir() if path.is_file() and not path.is_symlink()}


def test_immutable_read_of_checkpointed_wal_ledger_does_not_create_sidecars(tmp_path):
    import sqlite3
    db, checkpoint = tmp_path / "delivery.db", tmp_path / "checkpoint.json"
    SQLiteDeliveryReservationStore(db, checkpoint_path=checkpoint, key_secret=SECRET.encode())
    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        writer.close()
    assert db.read_bytes()[18:20] == b"\x02\x02"
    assert not any(Path(str(db)+suffix).exists() for suffix in preflight.SQLITE_SIDECAR_SUFFIXES)
    before = _snapshot_files(tmp_path)
    env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
    real_connect = sqlite3.connect
    uris = []
    def inspect_connect(database, *args, **kwargs):
        uris.append(database)
        assert "mode=ro&immutable=1" in database
        return real_connect(database, *args, **kwargs)
    with mock.patch.object(preflight, "persistent_path_ok", return_value=True), mock.patch.object(preflight.sqlite3, "connect", side_effect=inspect_connect):
        assert checks(env)["account_delivery_secret_stability"].status == "pass"
    assert len(uris) == 1
    assert _snapshot_files(tmp_path) == before
    assert {path.name for path in tmp_path.iterdir()} == set(before)


@pytest.mark.parametrize("checkpointed", [False, True])
def test_wal_sidecar_state_is_not_ignored_or_mutated_by_preflight(tmp_path, checkpointed):
    import sqlite3
    db, checkpoint = tmp_path / "delivery.db", tmp_path / "checkpoint.json"
    checkpoint.write_bytes(b"synthetic checkpoint"); checkpoint.chmod(0o600)
    writer = sqlite3.connect(db)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE delivery_reservation_meta(singleton INTEGER,secret_fingerprint TEXT)")
        writer.execute("INSERT INTO delivery_reservation_meta VALUES(1,?)", (hashlib.sha256(SECRET.encode()).hexdigest(),))
        writer.commit(); db.chmod(0o600)
        if checkpointed:
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        else:
            main_only = sqlite3.connect(db.as_uri()+"?mode=ro&immutable=1", uri=True)
            try:
                with pytest.raises(sqlite3.OperationalError):
                    main_only.execute("SELECT secret_fingerprint FROM delivery_reservation_meta")
            finally:
                main_only.close()
        assert Path(str(db)+"-wal").exists() and Path(str(db)+"-shm").exists()
        before = _snapshot_files(tmp_path)
        env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
        with mock.patch.object(preflight, "persistent_path_ok", return_value=True), mock.patch.object(preflight.sqlite3, "connect", side_effect=AssertionError("No SQLite connection while sidecars exist")):
            assert checks(env)["account_delivery_secret_stability"].status == "blocker"
        assert _snapshot_files(tmp_path) == before
        assert {path.name for path in tmp_path.iterdir()} == set(before)
    finally:
        writer.close()


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_any_existing_delivery_sqlite_sidecar_blocks_fingerprint_without_mutation(tmp_path, suffix):
    db, checkpoint = tmp_path / "delivery.db", tmp_path / "checkpoint.json"
    SQLiteDeliveryReservationStore(db, checkpoint_path=checkpoint, key_secret=SECRET.encode())
    sidecar = Path(str(db)+suffix); sidecar.write_bytes(b"synthetic SQLite sidecar")
    before = _snapshot_files(tmp_path)
    env = configured(SLPS_DELIVERY_DB_PATH=str(db), SLPS_DELIVERY_CHECKPOINT_PATH=str(checkpoint))
    with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
        assert checks(env)["account_delivery_secret_stability"].status == "blocker"
    assert _snapshot_files(tmp_path) == before


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("variable", ["SLPS_DELIVERY_DB_PATH", "SLPS_ACCOUNT_DB_PATH", "SLPS_RATE_DB_PATH", "SLPS_CASE_DB_PATH"])
def test_checkpoint_cannot_use_any_database_reserved_sidecar_name(variable, suffix):
    env = configured()
    env["SLPS_DELIVERY_CHECKPOINT_PATH"] = env[variable]+suffix
    assert checks(env)["account_delivery_paths_distinct"].status == "blocker"


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_delivery_database_cannot_use_checkpoint_reserved_sibling_name(suffix):
    env = configured()
    env["SLPS_DELIVERY_DB_PATH"] = env["SLPS_DELIVERY_CHECKPOINT_PATH"]+suffix
    assert checks(env)["account_delivery_paths_distinct"].status == "blocker"


def test_account_db_inspection_uses_the_same_nonwriting_wal_guard(tmp_path):
    import sqlite3
    from accounts import AccountStore
    db = tmp_path/"accounts.db"
    AccountStore(db)
    writer = sqlite3.connect(db)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
    finally:
        writer.close()
    before = _snapshot_files(tmp_path)
    assert preflight.inspect_account_db(db) == (True, 0)
    assert _snapshot_files(tmp_path) == before
    sidecar = Path(str(db)+"-wal"); sidecar.write_bytes(b"synthetic unapplied WAL")
    before = _snapshot_files(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        preflight.inspect_account_db(db)
    assert _snapshot_files(tmp_path) == before
