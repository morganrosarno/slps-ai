from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import re
import sqlite3

import pytest

from accounts import AccountStore
from scripts.company_verification_capability import main
from scripts.company_verification_operator import main as operator_main


PASSWORD = "a-long-local-test-passphrase"
FIRST = "synthetic-first-capability-32-bytes!"
SECOND = "synthetic-second-capability-32bytes!"
THIRD = "synthetic-third-capability-32-bytes!"


def setup_unbound(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    store = AccountStore(path)
    store.register(
        email="owner@example.test", password=PASSWORD,
        company_name="Synthetic Company", company_identifier="CHE123456789",
        role="Representative", locale="it",
    )
    path.chmod(0o600)
    backup_dir = tmp_path / "private-backups"
    backup_dir.mkdir(mode=0o700)
    return path, backup_dir


def pipe_bytes(value):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, value if isinstance(value, bytes) else value.encode("utf-8"))
    os.close(write_fd)
    return read_fd


def run_lifecycle(path, backup, command, *, change_id, expected_generation,
                  current=None, new=None, source=None):
    intent_fd = pipe_bytes(json.dumps({
        "operation": command,
        "change_id": change_id,
        "expected_generation": expected_generation,
    }))
    opened = [intent_fd]
    argv = [
        "--db", str(path), "--intent-fd", str(intent_fd),
        "--rollback-db", str(backup),
    ]
    if current is not None:
        current_fd = pipe_bytes(current)
        opened.append(current_fd)
        argv += ["--current-secret-fd", str(current_fd)]
    if new is not None:
        new_fd = pipe_bytes(new)
        opened.append(new_fd)
        argv += ["--new-secret-fd", str(new_fd)]
    argv.append(command)
    if source is not None:
        argv += ["--source-backup", str(source)]
    output = io.StringIO()
    try:
        status = main(argv, env={}, stdout=output)
    finally:
        for descriptor in opened:
            os.close(descriptor)
    return status, json.loads(output.getvalue()), output.getvalue()


def operator_list(path, secret):
    output = io.StringIO()
    status = operator_main(
        ["--db", str(path), "list"],
        env={"SLPS_VERIFICATION_OPERATOR_SECRET": secret}, stdout=output,
    )
    return status, json.loads(output.getvalue()), output.getvalue()


def state(path):
    with sqlite3.connect(path) as db:
        binding = db.execute(
            "SELECT secret_fingerprint FROM account_verification_operator_meta WHERE singleton=1"
        ).fetchone()
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_verification_operator_lifecycle'"
        ).fetchone()
        lifecycle = None if not table else db.execute(
            "SELECT database_id,generation,last_change_hash FROM account_verification_operator_lifecycle WHERE singleton=1"
        ).fetchone()
    return binding, lifecycle


def provision(path, backup_dir, *, secret=FIRST, suffix="initial"):
    rollback = backup_dir / f"{suffix}.sqlite3"
    result = run_lifecycle(
        path, rollback, "provision", change_id=f"provision:{suffix}:0001",
        expected_generation=0, new=secret,
    )
    return result, rollback


def test_provision_is_explicit_redacted_and_leaves_verified_unbound_rollback(tmp_path):
    path, backups = setup_unbound(tmp_path)
    before = path.read_bytes()

    (status, document, rendered), rollback = provision(path, backups)

    assert status == 0
    assert document == {
        "ok": True, "operation": "provision", "generation": 1,
        "binding_verified": True, "rollback_created": True,
        "rollback_verified": True, "rollback_binding": "unbound",
    }
    binding, lifecycle = state(path)
    assert len(binding[0]) == 64 and len(lifecycle[0]) == 32 and lifecycle[1] == 1
    assert FIRST not in rendered and str(path) not in rendered and str(rollback) not in rendered
    assert not re.search(r"\b[0-9a-f]{64}\b", rendered)
    assert rollback.read_bytes() != before  # SQLite backup is coherent, not a live-file copy.
    manifest = rollback.with_name(rollback.name + ".capability.json")
    assert rollback.stat().st_mode & 0o777 == 0o600
    assert manifest.stat().st_mode & 0o777 == 0o600
    saved = json.loads(manifest.read_text())
    assert saved["binding"] == "unbound" and saved["generation"] == 0
    assert operator_list(path, FIRST)[0] == 0


def test_provision_requires_exact_intent_and_never_rebinds(tmp_path):
    path, backups = setup_unbound(tmp_path)
    before = path.read_bytes()
    bad = run_lifecycle(
        path, backups / "bad.sqlite3", "provision",
        change_id="rotate:wrong-operation:0001", expected_generation=1, new=FIRST,
    )
    assert bad[:2] == (3, {"ok": False, "error": {"code": "generation_conflict"}})
    assert path.read_bytes() == before and not (backups / "bad.sqlite3").exists()

    first, _rollback = provision(path, backups)
    second = run_lifecycle(
        path, backups / "second.sqlite3", "provision",
        change_id="provision:duplicate:0002", expected_generation=0, new=SECOND,
    )
    assert first[0] == 0
    assert second[:2] == (3, {"ok": False, "error": {"code": "already_provisioned"}})
    assert not (backups / "second.sqlite3").exists()
    assert operator_list(path, FIRST)[0] == 0 and operator_list(path, SECOND)[0] == 3


def test_rotation_is_atomic_and_rollback_copy_recovers_prior_capability(tmp_path):
    path, backups = setup_unbound(tmp_path)
    provision(path, backups)
    rotation_backup = backups / "before-rotation.sqlite3"

    rotated = run_lifecycle(
        path, rotation_backup, "rotate", change_id="rotate:scheduled:0001",
        expected_generation=1, current=FIRST, new=SECOND,
    )

    assert rotated[0] == 0 and rotated[1]["generation"] == 2
    assert rotated[1]["rollback_binding"] == "bound"
    assert operator_list(path, FIRST)[0] == 3
    assert operator_list(path, SECOND)[0] == 0
    assert FIRST not in rotation_backup.read_bytes().decode("latin1")
    assert SECOND not in path.read_bytes().decode("latin1")

    recovery_backup = backups / "before-recovery.sqlite3"
    recovered = run_lifecycle(
        path, recovery_backup, "recover", change_id="recover:lost-current:0001",
        expected_generation=2, new=FIRST, source=rotation_backup,
    )
    assert recovered[0] == 0 and recovered[1]["generation"] == 3
    assert operator_list(path, FIRST)[0] == 0
    assert operator_list(path, SECOND)[0] == 3
    assert state(path)[1][1] == 3  # Generation never rewinds during recovery.


def test_first_rotation_adopts_legacy_binding_in_the_rollback_before_mutation(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    AccountStore(path, verification_operator_secret=FIRST.encode("ascii"))
    path.chmod(0o600)
    backups = tmp_path / "legacy-backups"
    backups.mkdir(mode=0o700)
    assert state(path)[0] is not None and state(path)[1] is None

    source = backups / "before-first-rotation.sqlite3"
    rotated = run_lifecycle(
        path, source, "rotate", change_id="rotate:legacy-adoption:0001",
        expected_generation=1, current=FIRST, new=SECOND,
    )
    assert rotated[0] == 0 and rotated[1]["generation"] == 2
    with sqlite3.connect(source) as rollback:
        adopted = rollback.execute(
            "SELECT database_id,generation FROM account_verification_operator_lifecycle"
        ).fetchone()
    assert len(adopted[0]) == 32 and adopted[1] == 1
    assert state(path)[1][0] == adopted[0]

    recovered = run_lifecycle(
        path, backups / "before-legacy-recovery.sqlite3", "recover",
        change_id="recover:legacy-adoption:0001", expected_generation=2,
        new=FIRST, source=source,
    )
    assert recovered[0] == 0 and recovered[1]["generation"] == 3
    assert operator_list(path, FIRST)[0] == 0


def test_wrong_current_secret_and_stale_generation_fail_before_backup(tmp_path):
    path, backups = setup_unbound(tmp_path)
    provision(path, backups)
    before = path.read_bytes()
    wrong_path = backups / "wrong.sqlite3"
    wrong = run_lifecycle(
        path, wrong_path, "rotate", change_id="rotate:wrong-secret:0001",
        expected_generation=1, current=SECOND, new=THIRD,
    )
    stale_path = backups / "stale.sqlite3"
    stale = run_lifecycle(
        path, stale_path, "rotate", change_id="rotate:stale-generation:0001",
        expected_generation=9, current=FIRST, new=SECOND,
    )
    assert wrong[:2] == (3, {"ok": False, "error": {"code": "authorization_failed"}})
    assert stale[:2] == (3, {"ok": False, "error": {"code": "generation_conflict"}})
    assert path.read_bytes() == before
    assert not wrong_path.exists() and not stale_path.exists()


def test_recovery_rejects_tampered_or_foreign_backup_without_mutating_target(tmp_path):
    path, backups = setup_unbound(tmp_path)
    provision(path, backups)
    source = backups / "old.sqlite3"
    assert run_lifecycle(
        path, source, "rotate", change_id="rotate:for-recovery:0001",
        expected_generation=1, current=FIRST, new=SECOND,
    )[0] == 0
    before = path.read_bytes()
    manifest = source.with_name(source.name + ".capability.json")
    saved = json.loads(manifest.read_text())
    saved["database_sha256"] = "0" * 64
    manifest.write_text(json.dumps(saved))
    manifest.chmod(0o600)
    target = backups / "recovery-rollback.sqlite3"
    tampered = run_lifecycle(
        path, target, "recover", change_id="recover:tampered:0001",
        expected_generation=2, new=FIRST, source=source,
    )
    assert tampered[:2] == (4, {"ok": False, "error": {"code": "storage_unavailable"}})
    assert path.read_bytes() == before and not target.exists()

    other_root = tmp_path / "other"
    other_root.mkdir(mode=0o700)
    other, other_backups = setup_unbound(other_root)
    provision(other, other_backups, suffix="other")
    foreign_source = other_backups / "foreign.sqlite3"
    run_lifecycle(
        other, foreign_source, "rotate", change_id="rotate:foreign:0001",
        expected_generation=1, current=FIRST, new=THIRD,
    )
    foreign_target = backups / "foreign-recovery.sqlite3"
    foreign = run_lifecycle(
        path, foreign_target, "recover", change_id="recover:foreign:0001",
        expected_generation=2, new=FIRST, source=foreign_source,
    )
    assert foreign[:2] == (3, {"ok": False, "error": {"code": "rollback_mismatch"}})
    assert path.read_bytes() == before and not foreign_target.exists()


def test_concurrent_rotation_has_one_winner_and_one_verified_backup_per_attempt(tmp_path):
    path, backups = setup_unbound(tmp_path)
    provision(path, backups)

    def rotate(index):
        return run_lifecycle(
            path, backups / f"concurrent-{index}.sqlite3", "rotate",
            change_id=f"rotate:concurrent:{index:04d}", expected_generation=1,
            current=FIRST, new=SECOND if index == 1 else THIRD,
        )[:2]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, (1, 2)))
    assert sum(status == 0 for status, _body in results) == 1
    assert sum(status == 3 for status, _body in results) == 1
    binding, lifecycle = state(path)
    assert lifecycle[1] == 2 and len(binding[0]) == 64
    assert operator_list(path, FIRST)[0] == 3
    assert sum(operator_list(path, candidate)[0] == 0 for candidate in (SECOND, THIRD)) == 1


def test_secret_sources_are_not_cli_values_and_errors_are_redacted(tmp_path):
    source = Path("scripts/company_verification_capability.py").read_text()
    assert "add_argument(\"--current-secret\"" not in source
    assert "add_argument(\"--new-secret\"" not in source
    path, backups = setup_unbound(tmp_path)
    output = io.StringIO()
    status = main(
        ["--db", str(path), "--rollback-db", str(backups / "missing.sqlite3"),
         "provision"], env={}, stdout=output,
    )
    assert status == 2
    assert json.loads(output.getvalue()) == {
        "ok": False, "error": {"code": "invalid_input"},
    }
    assert str(path) not in output.getvalue() and FIRST not in output.getvalue()


def test_symlinked_or_overpermissive_storage_paths_fail_before_mutation(tmp_path):
    path, backups = setup_unbound(tmp_path)
    before = path.read_bytes()
    external = tmp_path / "external-private"
    external.mkdir(mode=0o700)
    linked = tmp_path / "linked-private"
    linked.symlink_to(external, target_is_directory=True)
    through_link = run_lifecycle(
        path, linked / "rollback.sqlite3", "provision",
        change_id="provision:symlink-parent:0001", expected_generation=0,
        new=FIRST,
    )
    assert through_link[:2] == (2, {
        "ok": False, "error": {"code": "invalid_input"},
    })
    assert path.read_bytes() == before and not (external / "rollback.sqlite3").exists()

    backups.chmod(0o755)
    permissive = run_lifecycle(
        path, backups / "permissive.sqlite3", "provision",
        change_id="provision:permissive-dir:0001", expected_generation=0,
        new=FIRST,
    )
    assert permissive[:2] == (2, {
        "ok": False, "error": {"code": "invalid_input"},
    })
    assert path.read_bytes() == before


@pytest.mark.parametrize("directory_mode", [0o755, 0o777])
def test_private_database_file_is_rejected_under_replaceable_parent(
        tmp_path, directory_mode):
    public_parent = tmp_path / f"public-{directory_mode:o}"
    public_parent.mkdir(mode=0o700)
    path = public_parent / "accounts.sqlite3"
    AccountStore(path)
    path.chmod(0o600)
    public_parent.chmod(directory_mode)
    backup_parent = tmp_path / f"private-backup-{directory_mode:o}"
    backup_parent.mkdir(mode=0o700)
    before = path.read_bytes()

    result = run_lifecycle(
        path, backup_parent / "rollback.sqlite3", "provision",
        change_id=f"provision:public-parent:{directory_mode:o}",
        expected_generation=0, new=FIRST,
    )

    assert result[:2] == (4, {
        "ok": False, "error": {"code": "storage_unavailable"},
    })
    assert path.read_bytes() == before
    assert not (backup_parent / "rollback.sqlite3").exists()


@pytest.mark.parametrize("directory_mode", [0o755, 0o777])
def test_recovery_source_is_rejected_under_replaceable_parent(
        tmp_path, directory_mode):
    path, backups = setup_unbound(tmp_path)
    provision(path, backups)
    source = backups / "old.sqlite3"
    assert run_lifecycle(
        path, source, "rotate", change_id="rotate:public-source:0001",
        expected_generation=1, current=FIRST, new=SECOND,
    )[0] == 0
    before = path.read_bytes()
    backups.chmod(directory_mode)
    recovery_backups = tmp_path / f"private-recovery-{directory_mode:o}"
    recovery_backups.mkdir(mode=0o700)
    target = recovery_backups / "before-recovery.sqlite3"

    result = run_lifecycle(
        path, target, "recover",
        change_id=f"recover:public-source:{directory_mode:o}",
        expected_generation=2, new=FIRST, source=source,
    )

    assert result[:2] == (4, {
        "ok": False, "error": {"code": "storage_unavailable"},
    })
    assert path.read_bytes() == before and not target.exists()


def test_database_is_rejected_beneath_nonsticky_world_writable_ancestor(tmp_path):
    replaceable = tmp_path / "replaceable-db-ancestor"
    replaceable.mkdir(mode=0o700)
    private_parent = replaceable / "private-db"
    private_parent.mkdir(mode=0o700)
    path = private_parent / "accounts.sqlite3"
    AccountStore(path)
    path.chmod(0o600)
    replaceable.chmod(0o777)
    backups = tmp_path / "private-db-ancestor-backups"
    backups.mkdir(mode=0o700)
    target = backups / "rollback.sqlite3"
    before = path.read_bytes()

    result = run_lifecycle(
        path, target, "provision", change_id="provision:writable-ancestor:0001",
        expected_generation=0, new=FIRST,
    )

    assert result[:2] == (4, {
        "ok": False, "error": {"code": "storage_unavailable"},
    })
    assert path.read_bytes() == before and not target.exists()


def test_recovery_source_is_rejected_beneath_nonsticky_world_writable_ancestor(
        tmp_path):
    path, _ordinary_backups = setup_unbound(tmp_path)
    source_ancestor = tmp_path / "replaceable-source-ancestor"
    source_ancestor.mkdir(mode=0o700)
    source_parent = source_ancestor / "private-source"
    source_parent.mkdir(mode=0o700)
    provision_backup = source_parent / "initial.sqlite3"
    assert run_lifecycle(
        path, provision_backup, "provision",
        change_id="provision:writable-source:0001", expected_generation=0,
        new=FIRST,
    )[0] == 0
    source = source_parent / "before-rotation.sqlite3"
    assert run_lifecycle(
        path, source, "rotate", change_id="rotate:writable-source:0001",
        expected_generation=1, current=FIRST, new=SECOND,
    )[0] == 0
    source_ancestor.chmod(0o777)
    target_parent = tmp_path / "private-recovery-target"
    target_parent.mkdir(mode=0o700)
    target = target_parent / "before-recovery.sqlite3"
    before = path.read_bytes()

    result = run_lifecycle(
        path, target, "recover",
        change_id="recover:writable-source:0001", expected_generation=2,
        new=FIRST, source=source,
    )

    assert result[:2] == (4, {
        "ok": False, "error": {"code": "storage_unavailable"},
    })
    assert path.read_bytes() == before and not target.exists()
