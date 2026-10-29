"""A passing rehearsal must never imply account delivery was activated."""
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import mock

import pytest

from delivery_provider_readiness import required_dispatch_marker_retention_seconds
from scripts import delivery_activation_rehearsal as rehearsal
from scripts import preflight


@pytest.fixture
def workspace_parent():
    # Intentionally outside /tmp and the source tree; no preflight is bypassed.
    with TemporaryDirectory(prefix="slps-rehearsal-test-", dir=rehearsal.ROOT.parent) as directory:
        yield Path(directory)


def test_shared_preflight_passes_local_prerequisites_but_never_provider_verification(workspace_parent):
    original = preflight.account_delivery_checks
    observations = []

    def observe(settings, root, *, registration_open, delivery_adapter):
        assert settings["SLPS_ACCOUNT_REGISTRATION_OPEN"] == "false"
        assert root == rehearsal.ROOT
        database = Path(settings["SLPS_DELIVERY_DB_PATH"])
        if database.is_absolute():
            assert not preflight._sqlite_sidecar_present(database)
        observations.append((dict(settings), registration_open))
        return original(settings, root, registration_open=registration_open,
                        delivery_adapter=delivery_adapter)

    before_env = dict(os.environ)
    with mock.patch.object(preflight, "account_delivery_checks", side_effect=observe), \
            mock.patch.object(rehearsal.NoSendAdapter, "send", side_effect=AssertionError("must not send")) as send:
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    send.assert_not_called()
    assert result["result"] == "passed"
    assert result["local_prerequisites"] == {"passed": 7, "total": 7}
    assert result["failed_prerequisite_probes"] == {"blocked": 7, "total": 7}
    assert result["provider_verification_blocks_opening"] is True
    assert result["registration_open"] is False
    assert result["application_wired"] is False
    assert result["provider_verified"] is False
    assert result["persistent_storage_verified"] is False
    assert result["state_unchanged_during_checks"] is True
    assert result["quiescent_state"] is True
    assert result["temporary_state_removed"] is True
    assert result["network_attempts"] == result["adapter_send_calls"] == result["real_messages_sent"] == 0
    assert len(observations) == 16  # closed/open baseline, then closed/open for each failure
    settings = observations[0][0]
    assert int(settings["SLPS_DELIVERY_OUTCOME_RETENTION_SECONDS"]) == required_dispatch_marker_retention_seconds(
        float(settings["SLPS_DELIVERY_TIMEOUT_SECONDS"]))
    assert list(workspace_parent.iterdir()) == []
    assert dict(os.environ) == before_env


@pytest.mark.parametrize("check_id", [
    "account_delivery_secret", "account_delivery_db_path", "account_delivery_checkpoint_path",
    "account_delivery_paths_distinct", "account_delivery_secret_stability",
    "account_delivery_marker_retention", "account_delivery_adapter",
])
def test_rehearsal_detects_each_prerequisite_that_incorrectly_passes_a_fault(workspace_parent, check_id):
    original = preflight.account_delivery_checks

    def bypass_failed_prerequisite(*args, **kwargs):
        return [replace(item, status="pass") if item.id == check_id else item
                for item in original(*args, **kwargs)]

    with mock.patch.object(preflight, "account_delivery_checks", side_effect=bypass_failed_prerequisite):
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True
    assert list(workspace_parent.iterdir()) == []


def test_rehearsal_rejects_false_provider_acceptance(workspace_parent):
    original = preflight.account_delivery_checks

    def false_provider_success(*args, **kwargs):
        return [replace(item, status="pass") if item.id == "account_delivery_provider_verification" else item
                for item in original(*args, **kwargs)]

    with mock.patch.object(preflight, "account_delivery_checks", side_effect=false_provider_success):
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True


@pytest.mark.parametrize("operation", ["socket", "create_connection", "getaddrinfo",
                                       "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"])
def test_network_socket_or_dns_attempt_fails_closed_and_cleans_up(workspace_parent, operation):
    def attempt_network(_directory, _adapter, *, guard):
        getattr(socket, operation)("sensitive-never-emitted.example", 443)

    with mock.patch.object(rehearsal, "_exercise", side_effect=attempt_network) as exercise:
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["network_attempts"] == 1
    assert result["real_messages_sent"] == 0
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True
    assert "sensitive-never-emitted" not in json.dumps(result)
    exercise.assert_called_once()  # No fallback or retry.
    assert list(workspace_parent.iterdir()) == []


def test_accidental_adapter_call_fails_without_delivering(workspace_parent):
    def attempt_send(_directory, adapter, *, guard):
        adapter.send("sensitive-not-a-real-recipient")

    with mock.patch.object(rehearsal, "_exercise", side_effect=attempt_send):
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["adapter_send_calls"] == 1
    assert result["real_messages_sent"] == 0
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True


def test_preflight_mutation_is_detected_and_synthetic_files_are_removed(workspace_parent):
    original = preflight.account_delivery_checks
    calls = 0

    def mutate_after_read(settings, *args, **kwargs):
        nonlocal calls
        result = original(settings, *args, **kwargs)
        calls += 1
        if calls == 1:
            Path(settings["SLPS_DELIVERY_CHECKPOINT_PATH"]).write_text("synthetic-corruption")
        return result

    with mock.patch.object(preflight, "account_delivery_checks", side_effect=mutate_after_read):
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["temporary_state_removed"] is True
    assert result["registration_open"] is False
    assert list(workspace_parent.iterdir()) == []


def test_exception_is_sanitized_and_existing_neighbor_file_is_unchanged(workspace_parent):
    neighbor = workspace_parent / "existing-file.txt"
    neighbor.write_bytes(b"pre-existing synthetic sentinel")
    before = neighbor.read_bytes(), neighbor.stat().st_mtime_ns
    with mock.patch.object(rehearsal, "_exercise", side_effect=RuntimeError(
            f"secret fingerprint private-id {workspace_parent}")):
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    assert result["result"] == "failed"
    assert result["error"] == "offline_rehearsal_failed"
    assert result["temporary_state_removed"] is True
    assert (neighbor.read_bytes(), neighbor.stat().st_mtime_ns) == before
    assert list(workspace_parent.iterdir()) == [neighbor]
    serialized = json.dumps(result)
    assert all(value not in serialized for value in ("fingerprint", "secret", "private-id", str(workspace_parent)))


def test_code_or_forbidden_temporary_workspace_cannot_fake_safe_state(workspace_parent):
    # The unchanged preflight must reject a rehearsal inside its own code root.
    before = workspace_parent.stat()
    with mock.patch.object(rehearsal, "ROOT", workspace_parent), \
            mock.patch.object(rehearsal, "TemporaryDirectory") as temporary:
        result = rehearsal.run_rehearsal(workspace_parent=workspace_parent)
    temporary.assert_not_called()
    assert result["result"] == "failed"
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True
    assert list(workspace_parent.iterdir()) == []
    assert workspace_parent.stat().st_mtime_ns == before.st_mtime_ns
    assert workspace_parent.stat().st_ctime_ns == before.st_ctime_ns


@pytest.mark.parametrize("kind", ["code", "temporary", "symlink", "symlink_ancestor",
                                   "group_writable", "world_writable", "not_directory",
                                   "missing", "relative", "noncanonical", "wrong_owner"])
def test_invalid_parent_is_rejected_before_any_creation_or_mutation(workspace_parent, tmp_path, kind):
    target = workspace_parent / "target"
    target.mkdir(mode=0o755)
    parent = target
    if kind == "code":
        parent = rehearsal.ROOT / "scripts"
    elif kind == "temporary":
        parent = tmp_path
    elif kind == "symlink":
        parent = workspace_parent / "link"
        parent.symlink_to(target, target_is_directory=True)
    elif kind == "symlink_ancestor":
        (target / "child").mkdir()
        link = workspace_parent / "link"
        link.symlink_to(target, target_is_directory=True)
        parent = link / "child"
    elif kind == "group_writable":
        parent.chmod(0o770)
    elif kind == "world_writable":
        parent.chmod(0o757)
    elif kind == "not_directory":
        parent = workspace_parent / "file"
        parent.write_bytes(b"unchanged synthetic sentinel")
    elif kind == "missing":
        parent = workspace_parent / "missing"
    elif kind == "relative":
        parent = Path("relative-parent")
    elif kind == "noncanonical":
        parent = str(target) + "/../target"
    watch = (workspace_parent, tmp_path, rehearsal.ROOT / "scripts")
    before = [(item.stat().st_mtime_ns, item.stat().st_ctime_ns,
               sorted(child.name for child in item.iterdir())) for item in watch]
    owner = os.geteuid() + 1 if kind == "wrong_owner" else os.geteuid()
    with mock.patch.object(rehearsal.os, "geteuid", return_value=owner), \
            mock.patch.object(rehearsal, "TemporaryDirectory") as temporary, \
            mock.patch.object(rehearsal, "SQLiteDeliveryReservationStore") as store, \
            mock.patch.object(rehearsal, "_exercise") as exercise:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    temporary.assert_not_called()
    store.assert_not_called()
    exercise.assert_not_called()
    assert result["result"] == "failed" and result["registration_open"] is False
    assert result["temporary_state_removed"] is True
    after = [(item.stat().st_mtime_ns, item.stat().st_ctime_ns,
              sorted(child.name for child in item.iterdir())) for item in watch]
    assert after == before


def test_parent_replacement_cannot_redirect_creation_or_cleanup(workspace_parent):
    parent = workspace_parent / "selected"
    parent.mkdir(mode=0o755)
    moved = workspace_parent / "original"
    original_temporary = TemporaryDirectory

    def replace_before_creation(*args, **kwargs):
        parent.rename(moved)
        parent.mkdir(mode=0o755)
        return original_temporary(*args, **kwargs)

    with mock.patch.object(rehearsal, "TemporaryDirectory", side_effect=replace_before_creation), \
            mock.patch.object(rehearsal, "_exercise") as exercise:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    exercise.assert_not_called()
    assert result["result"] == "failed"
    assert result["registration_open"] is False
    assert result["temporary_state_removed"] is True
    assert list(parent.iterdir()) == []  # Replacement never receives a write.
    assert list(moved.iterdir()) == []  # Pinned original is cleaned up.


@pytest.mark.parametrize("substitute_child", [False, True])
def test_parent_replacement_at_exercise_entry_is_blocked_before_store_write(workspace_parent, substitute_child):
    parent = workspace_parent / "selected"
    parent.mkdir(mode=0o755)
    moved = workspace_parent / "original"
    original_exercise = rehearsal._exercise
    replacement_child = None

    def replace_at_entry(directory, adapter, *, guard):
        nonlocal replacement_child
        parent.rename(moved)
        parent.mkdir(mode=0o755)
        if substitute_child:
            replacement_child = parent / directory.name
            replacement_child.mkdir(mode=0o700)
            (replacement_child / "existing-sentinel").write_bytes(b"unknown replacement remains untouched")
        return original_exercise(directory, adapter, guard=guard)

    with mock.patch.object(rehearsal, "_exercise", side_effect=replace_at_entry), \
            mock.patch.object(rehearsal, "SQLiteDeliveryReservationStore") as store:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    store.assert_not_called()
    assert result["result"] == "failed" and result["registration_open"] is False
    assert result["temporary_state_removed"] is (not substitute_child)
    assert list(moved.iterdir()) == []  # Only the original pinned child was ours.
    if substitute_child:
        assert sorted(item.name for item in replacement_child.iterdir()) == ["existing-sentinel"]
        assert (replacement_child / "existing-sentinel").read_bytes() == b"unknown replacement remains untouched"
    else:
        assert list(parent.iterdir()) == []


def test_cleanup_removes_relocated_original_only_when_identity_matches(workspace_parent):
    parent = workspace_parent / "selected"
    parent.mkdir(mode=0o755)
    moved = workspace_parent / "original"
    original_exercise = rehearsal._exercise

    def relocate_original_at_entry(directory, adapter, *, guard):
        parent.rename(moved)
        parent.mkdir(mode=0o755)
        (moved / directory.name).rename(parent / directory.name)
        return original_exercise(directory, adapter, guard=guard)

    with mock.patch.object(rehearsal, "_exercise", side_effect=relocate_original_at_entry), \
            mock.patch.object(rehearsal, "SQLiteDeliveryReservationStore") as store:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    store.assert_not_called()
    assert result["result"] == "failed" and result["temporary_state_removed"] is True
    assert list(parent.iterdir()) == list(moved.iterdir()) == []


def test_cleanup_never_claims_removed_if_pinned_inode_was_relocated_elsewhere(workspace_parent):
    parent = workspace_parent / "selected"
    parent.mkdir(mode=0o755)
    relocated = workspace_parent / "unknown-location"
    original_exercise = rehearsal._exercise

    def relocate_before_entry(directory, adapter, *, guard):
        directory.rename(relocated)
        return original_exercise(directory, adapter, guard=guard)

    with mock.patch.object(rehearsal, "_exercise", side_effect=relocate_before_entry), \
            mock.patch.object(rehearsal, "SQLiteDeliveryReservationStore") as store:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    store.assert_not_called()
    assert result["result"] == "failed" and result["temporary_state_removed"] is False
    assert relocated.is_dir()


def test_guard_rechecks_before_each_preflight_phase(workspace_parent):
    parent = workspace_parent / "selected"
    parent.mkdir(mode=0o755)
    moved = workspace_parent / "original"
    original_check_map = rehearsal._check_map

    def replace_before_preflight(*args, **kwargs):
        parent.rename(moved)
        parent.mkdir(mode=0o755)
        return original_check_map(*args, **kwargs)

    with mock.patch.object(rehearsal, "_check_map", side_effect=replace_before_preflight), \
            mock.patch.object(preflight, "account_delivery_checks") as preflight_check:
        result = rehearsal.run_rehearsal(workspace_parent=parent)
    preflight_check.assert_not_called()
    assert result["result"] == "failed" and result["temporary_state_removed"] is True
    assert list(parent.iterdir()) == list(moved.iterdir()) == []


@pytest.mark.parametrize("stage", ["write", "flush"])
def test_main_stdout_failure_is_silent_nonzero_and_never_retried(stage):
    class FailingOutput:
        def __init__(self):
            self.writes = self.flushes = 0

        def write(self, _payload):
            self.writes += 1
            if stage == "write":
                raise OSError("sensitive-secret-private-path-provider-id")

        def flush(self):
            self.flushes += 1
            raise OSError("sensitive-secret-private-path-provider-id")

    output, errors = FailingOutput(), io.StringIO()
    with mock.patch.object(rehearsal, "run_rehearsal", return_value={"result": "passed"}) as run, \
            mock.patch.object(sys, "stdout", output), mock.patch.object(sys, "stderr", errors):
        status = rehearsal.main()
        assert sys.stdout is not output  # Prevent interpreter-shutdown retry.
        sys.stdout.flush()
    assert status == 2 and errors.getvalue() == ""
    assert output.writes == 1
    assert output.flushes == (0 if stage == "write" else 1)
    run.assert_called_once()


def test_json_output_ignores_real_environment_and_contains_no_material_or_paths(tmp_path):
    forbidden_destination = tmp_path / "must-not-be-created"
    env = {**os.environ, "SLPS_ACCOUNT_REGISTRATION_OPEN": "true",
           "SLPS_DELIVERY_RESERVATION_SECRET": "sensitive-real-env-canary-never-use-me",
           "SLPS_DELIVERY_DB_PATH": str(forbidden_destination),
           "SLPS_DELIVERY_CHECKPOINT_PATH": str(forbidden_destination) + ".checkpoint",
           "SLPS_ACCOUNT_DELIVERY_ADAPTER": "sensitive-real-adapter-id"}
    command = subprocess.run([sys.executable, str(rehearsal.ROOT / "scripts/delivery_activation_rehearsal.py")],
                             cwd=rehearsal.ROOT, env=env, capture_output=True, text=True, timeout=15)
    assert command.returncode == 0 and command.stderr == ""
    result = json.loads(command.stdout)
    assert result["result"] == "passed" and result["registration_open"] is False
    assert len(command.stdout.encode("utf-8")) < 2048
    assert set(result) == {
        "result", "scope", "registration_open", "application_wired", "provider_verified",
        "persistent_storage_verified", "temporary_state_removed", "network_attempts",
        "adapter_send_calls", "real_messages_sent", "local_prerequisites",
        "failed_prerequisite_probes", "provider_verification_blocks_opening",
        "quiescent_state", "state_unchanged_during_checks",
    }
    synthetic_secret = "synthetic-activation-rehearsal-reservation-key-only-42"
    for forbidden in (str(rehearsal.ROOT.parent), str(forbidden_destination), "sensitive-real-env-canary",
                      "sensitive-real-adapter-id", synthetic_secret,
                      hashlib.sha256(synthetic_secret.encode()).hexdigest(), "synthetic-never-send"):
        assert forbidden not in command.stdout
    assert not forbidden_destination.exists()
    assert list(tmp_path.iterdir()) == []
