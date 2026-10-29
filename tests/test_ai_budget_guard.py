from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from ai_budget_guard import (
    AIBudgetGuard,
    BudgetGuardError,
    BudgetProfile,
    RateCard,
    Reservation,
    SubrequestPlan,
    Usage,
)


RATES = RateCard(
    input_per_million=2_000_000,
    output_per_million=10_000_000,
    image_per_million=2_000_000,
    audio_per_minute=4_500,
    fixed_per_request=100,
)
PROFILE = BudgetProfile("synthetic-small", ceiling=50_000, max_subrequests=4, max_vision=3, max_transcription=1)


def digest(value="a"):
    return (value * 64)[:64]


def plan(kind="vision", ordinal=1, binding="a", usage=None):
    return SubrequestPlan(kind, ordinal, digest(binding), usage or Usage(input_units=1000, output_units=100, image_units=500))


def guard(tmp_path, profile=PROFILE, rates=RATES):
    return AIBudgetGuard(tmp_path / "private" / "budget.sqlite3", rates=rates, profile=profile, clock=lambda: 1000)


def test_integer_cost_components_round_up_without_float_drift():
    rates = RateCard(1, 1, 1, 1, 0)
    assert Usage(input_units=1, output_units=1, image_units=1, audio_milliseconds=1).cost(rates) == 4
    assert Usage().cost(rates) == 0


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan"), 10**13])
def test_usage_rejects_non_integer_unbounded_values(value):
    with pytest.raises(BudgetGuardError) as error:
        Usage(input_units=value)
    assert error.value.code == "budget_configuration_invalid"


def test_stable_subrequest_id_binds_job_kind_ordinal_and_request_digest():
    item = plan()
    assert item.stable_id("job-1") == item.stable_id("job-1")
    assert item.stable_id("job-1") != replace(item, ordinal=2).stable_id("job-1")
    assert item.stable_id("job-1") != replace(item, binding_digest=digest("b")).stable_id("job-1")
    assert item.stable_id("job-1") != item.stable_id("job-2")


def test_reservation_precedes_dispatch_and_holds_full_maximum(tmp_path):
    ledger = guard(tmp_path); before = ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan())
    assert before.liability == 0
    assert ledger.subrequest_state(reservation.subrequest_id) == "reserved"
    assert ledger.snapshot("photo-job").liability == reservation.reserved_cost
    ledger.begin_dispatch(reservation)
    assert ledger.subrequest_state(reservation.subrequest_id) == "dispatched"


def test_settlement_reconciles_actual_usage_and_releases_difference(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan())
    maximum = reservation.reserved_cost
    ledger.begin_dispatch(reservation)
    actual = Usage(input_units=100, output_units=10, image_units=50)
    receipt = ledger.settle(reservation, "receipt-photo-1", actual)
    snapshot = ledger.snapshot("photo-job")
    assert snapshot.liability == actual.cost(RATES) < maximum
    assert snapshot.unresolved == 0
    assert ledger.subrequest_state(reservation.subrequest_id) == "settled"
    assert receipt == ledger.receipt(reservation.subrequest_id)


def test_identical_receipt_replay_after_restart_returns_persisted_outcome(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan()); ledger.begin_dispatch(reservation)
    usage = Usage(input_units=100, output_units=10, image_units=50)
    first = ledger.settle(reservation, "stable-receipt-1", usage)
    with sqlite3.connect(ledger.path) as connection:
        first_updated = connection.execute(
            "SELECT updated_at FROM budget_subrequests WHERE subrequest_id=?",
            (reservation.subrequest_id,),
        ).fetchone()[0]

    reopened = AIBudgetGuard(ledger.path, rates=RATES, profile=PROFILE, clock=lambda: 2000)
    replay = reopened.settle(reservation, "stable-receipt-1", usage)
    with sqlite3.connect(ledger.path) as connection:
        replay_updated = connection.execute(
            "SELECT updated_at FROM budget_subrequests WHERE subrequest_id=?",
            (reservation.subrequest_id,),
        ).fetchone()[0]
    assert replay == first == reopened.receipt(reservation.subrequest_id)
    assert replay_updated == first_updated


@pytest.mark.parametrize(
    ("receipt_id", "usage"),
    [
        ("stable-receipt-1", Usage(input_units=101, output_units=10, image_units=50)),
        ("different-receipt-2", Usage(input_units=100, output_units=10, image_units=50)),
    ],
)
def test_different_receipt_replay_fails_without_mutation(tmp_path, receipt_id, usage):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan()); ledger.begin_dispatch(reservation)
    accepted = ledger.settle(
        reservation, "stable-receipt-1", Usage(input_units=100, output_units=10, image_units=50)
    )
    before = ledger.snapshot("photo-job")
    with pytest.raises(BudgetGuardError) as error:
        ledger.settle(reservation, receipt_id, usage)
    assert error.value.code == "budget_receipt_conflict"
    assert ledger.receipt(reservation.subrequest_id) == accepted
    assert ledger.snapshot("photo-job") == before


def test_public_receipt_and_snapshot_expose_only_sanitized_metadata(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan()); ledger.begin_dispatch(reservation)
    raw_receipt_id = "private-adapter-receipt-1"
    metadata = ledger.settle(reservation, raw_receipt_id, Usage(input_units=1))
    assert raw_receipt_id not in repr(metadata)
    assert reservation.capability not in repr(metadata)
    assert set(metadata.__dict__) == {
        "subrequest_id", "state", "receipt_id_digest", "receipt_digest", "actual_cost"
    }
    assert set(ledger.snapshot("photo-job").__dict__) == {
        "job_id", "status", "ceiling", "liability", "remaining", "subrequests",
        "vision", "transcription", "unresolved",
    }
    assert raw_receipt_id.encode() not in ledger.path.read_bytes()


def test_timeout_is_potential_charge_until_usage_receipt_reconciles(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("video-job")
    reservation = ledger.reserve("video-job", plan())
    ledger.begin_dispatch(reservation); ledger.mark_uncertain(reservation, "timeout")
    uncertain = ledger.snapshot("video-job")
    assert uncertain.liability == reservation.reserved_cost and uncertain.unresolved == 1
    with pytest.raises(BudgetGuardError) as error:
        ledger.reserve("video-job", plan())
    assert error.value.code == "budget_subrequest_already_recorded"
    ledger.reconcile_uncertain(
        reservation, "receipt-video-1", Usage(input_units=100, output_units=10, image_units=50)
    )
    assert ledger.snapshot("video-job").unresolved == 0


def test_retry_requires_new_attempt_id_and_new_reservation(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("video-job")
    first = ledger.reserve("video-job", plan())
    ledger.begin_dispatch(first); ledger.mark_uncertain(first, "transport_error")
    second = ledger.reserve("video-job", plan(ordinal=2))
    assert second.subrequest_id != first.subrequest_id
    assert ledger.snapshot("video-job").liability == first.reserved_cost + second.reserved_cost


def test_release_is_only_possible_before_dispatch_and_does_not_refund_attempt_slot(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan())
    ledger.release_before_dispatch(reservation, "cancelled_before_dispatch")
    snapshot = ledger.snapshot("photo-job")
    assert snapshot.liability == 0 and snapshot.subrequests == 1
    with pytest.raises(BudgetGuardError) as error:
        ledger.begin_dispatch(reservation)
    assert error.value.code == "budget_state_conflict"


@pytest.mark.parametrize("operation", ["settle", "uncertain", "release"])
def test_capability_and_state_machine_block_forged_or_replayed_actions(tmp_path, operation):
    ledger = guard(tmp_path); ledger.start_job("job-1")
    reservation = ledger.reserve("job-1", plan())
    forged = replace(reservation, capability="forged")
    with pytest.raises(BudgetGuardError) as error:
        if operation == "settle": ledger.settle(forged, "receipt-1", Usage(input_units=1))
        if operation == "uncertain": ledger.mark_uncertain(forged, "timeout")
        if operation == "release": ledger.release_before_dispatch(forged, "cancelled_before_dispatch")
    assert error.value.code == "budget_capability_invalid"


def test_malformed_capability_fails_with_sanitized_guard_error(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("job-1")
    reservation = ledger.reserve("job-1", plan())
    malformed = replace(reservation, capability=None)
    with pytest.raises(BudgetGuardError) as error:
        ledger.begin_dispatch(malformed)
    assert error.value.code == "budget_capability_invalid"


def test_usage_over_reservation_is_durably_recorded_and_blocks_job(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("photo-job")
    reservation = ledger.reserve("photo-job", plan(usage=Usage(input_units=10)))
    ledger.begin_dispatch(reservation)
    receipt = ledger.settle(reservation, "receipt-overage-1", Usage(input_units=11))
    assert receipt.state == "overage"
    assert ledger.subrequest_state(reservation.subrequest_id) == "overage"
    assert ledger.snapshot("photo-job").status == "blocked"
    with pytest.raises(BudgetGuardError) as blocked:
        ledger.reserve("photo-job", plan(ordinal=2, binding="b"))
    assert blocked.value.code == "budget_job_blocked"

    reopened = AIBudgetGuard(ledger.path, rates=RATES, profile=PROFILE)
    replay = reopened.settle(reservation, "receipt-overage-1", Usage(input_units=11))
    assert replay == receipt == reopened.receipt(reservation.subrequest_id)


def test_budget_and_kind_call_limits_fail_before_dispatch(tmp_path):
    one = BudgetProfile("one-vision", ceiling=50_000, max_subrequests=1, max_vision=1, max_transcription=0)
    ledger = guard(tmp_path, profile=one); ledger.start_job("job-1")
    first = ledger.reserve("job-1", plan())
    ledger.release_before_dispatch(first, "cancelled_before_dispatch")
    with pytest.raises(BudgetGuardError) as error:
        ledger.reserve("job-1", plan(ordinal=2, binding="b"))
    assert error.value.code == "budget_call_limit_reached"

    small = BudgetProfile("small", ceiling=500, max_subrequests=2, max_vision=2, max_transcription=0)
    other = guard(tmp_path / "other", profile=small); other.start_job("job-2")
    with pytest.raises(BudgetGuardError) as ceiling:
        other.reserve("job-2", plan())
    assert ceiling.value.code == "budget_ceiling_exceeded"


def test_photo_and_video_profiles_enforce_distinct_subrequest_shapes(tmp_path):
    video = BudgetProfile("video-30s", ceiling=100_000, max_subrequests=9, max_vision=8, max_transcription=1)
    ledger = guard(tmp_path); ledger.start_job("video-job", profile=video)
    for ordinal in range(1, 9):
        ledger.reserve("video-job", plan(ordinal=ordinal, binding=hex(ordinal)[2:]))
    ledger.reserve("video-job", plan("transcription", 1, "f", Usage(audio_milliseconds=30_000)))
    assert ledger.snapshot("video-job").subrequests == 9
    with pytest.raises(BudgetGuardError) as error:
        ledger.reserve("video-job", plan("vision", 9, "e"))
    assert error.value.code == "budget_call_limit_reached"


def test_concurrent_reservations_cannot_oversubscribe_same_ordinal(tmp_path):
    path = tmp_path / "private" / "budget.sqlite3"
    first = AIBudgetGuard(path, rates=RATES, profile=PROFILE)
    second = AIBudgetGuard(path, rates=RATES, profile=PROFILE)
    first.start_job("job-1")

    def reserve(instance):
        try:
            return instance.reserve("job-1", plan()).subrequest_id
        except BudgetGuardError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, (first, second)))
    assert sum(value.startswith("srq_") for value in results) == 1
    assert set(results) & {"budget_subrequest_already_recorded", "budget_ordinal_conflict"}
    assert first.snapshot("job-1").subrequests == 1


def test_reopen_preserves_dispatch_liability_and_configuration_binding(tmp_path):
    path = tmp_path / "private" / "budget.sqlite3"
    ledger = AIBudgetGuard(path, rates=RATES, profile=PROFILE); ledger.start_job("job-1")
    reservation = ledger.reserve("job-1", plan()); ledger.begin_dispatch(reservation)
    reopened = AIBudgetGuard(path, rates=RATES, profile=PROFILE)
    assert reopened.snapshot("job-1").liability == reservation.reserved_cost
    with pytest.raises(BudgetGuardError) as rate_error:
        AIBudgetGuard(path, rates=replace(RATES, input_per_million=1), profile=PROFILE)
    assert rate_error.value.code == "budget_configuration_conflict"
    changed = AIBudgetGuard(path, rates=RATES, profile=replace(PROFILE, ceiling=49_999))
    with pytest.raises(BudgetGuardError) as profile_error:
        changed.start_job("job-1")
    assert profile_error.value.code == "budget_profile_conflict"


def test_one_ledger_supports_distinct_photo_and_video_job_ceilings(tmp_path):
    video = BudgetProfile("video-30s", ceiling=100_000, max_subrequests=9, max_vision=8, max_transcription=1)
    ledger = guard(tmp_path)
    photo = ledger.start_job("photo-job")
    movie = ledger.start_job("video-job", profile=video)
    assert photo.ceiling == PROFILE.ceiling and movie.ceiling == video.ceiling
    reopened = AIBudgetGuard(ledger.path, rates=RATES, profile=PROFILE)
    assert reopened.start_job("video-job", profile=video).ceiling == video.ceiling


def test_database_contains_digests_not_capability_or_payload(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("job-1")
    reservation = ledger.reserve("job-1", plan())
    raw = ledger.path.read_bytes()
    assert reservation.capability.encode() not in raw
    assert digest().encode() in raw  # caller-provided digest is public-safe metadata, never the payload


def test_invalid_reason_and_post_dispatch_release_fail_closed(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("job-1")
    reservation = ledger.reserve("job-1", plan()); ledger.begin_dispatch(reservation)
    with pytest.raises(BudgetGuardError) as invalid:
        ledger.mark_uncertain(reservation, "provider_said_free")
    assert invalid.value.code == "budget_reason_invalid"
    with pytest.raises(BudgetGuardError) as release:
        ledger.release_before_dispatch(reservation, "cancelled_before_dispatch")
    assert release.value.code == "budget_state_conflict"


def test_storage_is_created_with_private_directory_and_file_modes(tmp_path):
    ledger = guard(tmp_path)
    assert stat_mode(ledger.path.parent) == 0o700
    assert stat_mode(ledger.path) == 0o600
    assert ledger.path.stat().st_nlink == 1


def stat_mode(path):
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize("kind", ["leaf_symlink", "ancestor_symlink", "hardlink"])
def test_symlink_and_hardlink_storage_are_rejected_with_sanitized_error(tmp_path, kind):
    private = tmp_path / "private"
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    path = private / "budget.sqlite3"
    if kind == "ancestor_symlink":
        private.symlink_to(external, target_is_directory=True)
    else:
        private.mkdir(mode=0o700)
        target = external / "target.sqlite3"
        target.touch(mode=0o600)
        if kind == "leaf_symlink":
            path.symlink_to(target)
        else:
            os.link(target, path)
    with pytest.raises(BudgetGuardError) as error:
        AIBudgetGuard(path, rates=RATES, profile=PROFILE)
    assert error.value.code == "budget_storage_unavailable"
    assert str(error.value) == "Registro budget non disponibile."


def test_unsafe_existing_or_changed_permissions_fail_closed(tmp_path):
    private = tmp_path / "public-parent"
    private.mkdir(mode=0o755)
    with pytest.raises(BudgetGuardError) as parent_error:
        AIBudgetGuard(private / "budget.sqlite3", rates=RATES, profile=PROFILE)
    assert parent_error.value.code == "budget_storage_unavailable"

    ledger = guard(tmp_path / "changed-file"); ledger.start_job("job-1")
    ledger.path.chmod(0o640)
    with pytest.raises(BudgetGuardError) as file_error:
        ledger.snapshot("job-1")
    assert file_error.value.code == "budget_storage_unavailable"

    other = guard(tmp_path / "changed-parent"); other.start_job("job-2")
    other.path.parent.chmod(0o750)
    with pytest.raises(BudgetGuardError) as changed_parent:
        other.snapshot("job-2")
    assert changed_parent.value.code == "budget_storage_unavailable"


def test_database_file_replacement_is_detected_before_next_connection(tmp_path):
    ledger = guard(tmp_path); ledger.start_job("job-1")
    replacement = tmp_path / "replacement.sqlite3"
    shutil.copy2(ledger.path, replacement)
    replacement.chmod(0o600)
    os.replace(replacement, ledger.path)
    with pytest.raises(BudgetGuardError) as error:
        ledger.snapshot("job-1")
    assert error.value.code == "budget_storage_unavailable"
