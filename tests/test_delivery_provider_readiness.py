from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event

import pytest

from delivery_boundary import (
    CancellationToken, DeliveryBoundaryError, DeliveryConfig,
    DeliveryTransportResult, MAX_ACTION_TTL_SECONDS,
)
from delivery_provider_readiness import ProviderNeutralDeliveryCoordinator
from delivery_reservations import (
    DeliveryReservationError, DeliveryReservationPolicy,
    SQLiteDeliveryReservationStore,
)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
KEY = "delivery:provider-readiness:" + "k" * 40
TOKEN = "sensitiveSyntheticToken_123456789"
SECRET = b"synthetic-provider-readiness-key!!"
REQUIRED_MARKER_RETENTION = MAX_ACTION_TTL_SECONDS + 8 + 60


class Adapter:
    def __init__(self, result=None, action=None):
        self.result = result if result is not None else DeliveryTransportResult(
            True, "private-provider-message-id",
        )
        self.action = action
        self.calls = []

    def send(self, envelope, *, cancellation):
        self.calls.append(envelope)
        if self.action:
            self.action()
        return self.result


def store(tmp_path):
    return SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3",
        key_secret=SECRET,
        policy=DeliveryReservationPolicy(
            reservation_retention_seconds=600,
            outcome_retention_seconds=REQUIRED_MARKER_RETENTION,
        ),
        clock=lambda: 1_000.0,
    )


def coordinator(ledger, adapter=None, cancellation=None, times=None, utc_clock=None):
    moments = iter(times or (0.0, 0.1))
    return ProviderNeutralDeliveryCoordinator(
        config=DeliveryConfig(("accounts.slps.example",)),
        adapter=adapter or Adapter(), ledger=ledger,
        cancellation=cancellation or CancellationToken(),
        monotonic_clock=lambda: next(moments), utc_clock=utc_clock or (lambda: NOW),
    )


def request(**overrides):
    values = {
        "recipient": "synthetic.person@example.test",
        "purpose": "verify_email",
        "locale": "it",
        "action_url": (
            "https://accounts.slps.example/account/verify-email?token=" + TOKEN
        ),
        "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
        "idempotency_key": KEY,
    }
    values.update(overrides)
    return values


def test_acceptance_is_recorded_once_and_duplicate_never_reinvokes_adapter(tmp_path):
    ledger, marker_seen = store(tmp_path), []

    def inspect_marker_before_adapter():
        marker_seen.append(ledger.outcome_status(KEY)["outcome"])

    adapter = Adapter(action=inspect_marker_before_adapter)
    first = coordinator(ledger, adapter).dispatch(**request())
    replay = coordinator(store(tmp_path), adapter).dispatch(**request())

    assert replay == first == {
        "status": "accepted", "code": "transport_accepted",
        "purpose": "verify_email", "final": True,
        "provider_reference_present": True, "chain_valid": True,
    }
    assert len(adapter.calls) == 1
    assert marker_seen[0]["code"] == "dispatch_started"
    assert marker_seen[0]["sequence"] == 1 and marker_seen[0]["final"] is False
    assert ledger.outcome_status(KEY)["outcome"]["sequence"] == 2
    assert TOKEN not in json.dumps(first)
    assert "private-provider-message-id" not in json.dumps(first)
    raw = (tmp_path / "private" / "delivery.sqlite3").read_bytes()
    assert KEY.encode() not in raw
    assert b"private-provider-message-id" not in raw


@pytest.mark.parametrize("changed", [
    {"recipient": "different.person@example.test"},
    {
        "purpose": "reset_password",
        "action_url": (
            "https://accounts.slps.example/account/reset-password?token=" + TOKEN
        ),
    },
    {
        "action_url": (
            "https://accounts.slps.example/account/verify-email?token="
            "differentSyntheticToken_123456789"
        ),
    },
    {"locale": "de"},
    {"expires_at_utc": (NOW + timedelta(hours=2)).isoformat()},
])
def test_same_key_bound_to_different_valid_request_fails_closed(tmp_path, changed):
    ledger, adapter = store(tmp_path), Adapter()
    accepted = coordinator(ledger, adapter).dispatch(**request())
    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(store(tmp_path), adapter).dispatch(**request(**changed))
    assert error.value.code == "delivery_outcome_conflict"
    assert str(error.value) == "Chiave di consegna già associata a una richiesta diversa."
    assert len(adapter.calls) == 1
    assert accepted["purpose"] == "verify_email"
    assert ledger.outcome_status(KEY)["outcome"]["sequence"] == 2


def test_same_key_with_invalid_action_path_fails_before_ledger_or_adapter(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()
    coordinator(ledger, adapter).dispatch(**request())
    changed = request(action_url=(
        "https://accounts.slps.example/account/reset-password?token=" + TOKEN
    ))
    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(store(tmp_path), adapter).dispatch(**changed)
    assert error.value.code == "delivery_action_invalid"
    assert len(adapter.calls) == 1
    assert ledger.outcome_status(KEY)["outcome"]["sequence"] == 2


def test_canonical_recipient_and_expiry_replay_same_bound_request(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()
    first = coordinator(ledger, adapter).dispatch(**request())
    equivalent_expiry = (NOW + timedelta(hours=1)).astimezone(
        timezone(timedelta(hours=1)),
    ).isoformat()
    replay = coordinator(store(tmp_path), adapter).dispatch(**request(
        recipient="  SYNTHETIC.PERSON@EXAMPLE.TEST  ",
        expires_at_utc=equivalent_expiry,
    ))
    assert replay == first
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("equivalent_url", [
    "https://ACCOUNTS.SLPS.EXAMPLE/account/verify-email?token=A" + TOKEN,
    "https://accounts.slps.example:443/account/verify-email?token=A" + TOKEN,
    "https://accounts.slps.example/account/verify-email?token=%41" + TOKEN,
])
def test_equivalent_action_url_replays_same_bound_request(tmp_path, equivalent_url):
    ledger, adapter = store(tmp_path), Adapter()
    canonical_url = (
        "https://accounts.slps.example/account/verify-email?token=A" + TOKEN
    )
    first = coordinator(ledger, adapter).dispatch(**request(action_url=canonical_url))
    replay = coordinator(store(tmp_path), adapter).dispatch(**request(
        action_url=equivalent_url,
    ))
    assert replay == first
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("result,expected", [
    (DeliveryTransportResult(False, "private-rejection-id"),
     ("failed", "transport_rejected", True)),
    (object(), ("uncertain", "dispatch_started", False)),
    (DeliveryTransportResult(True, "bad\nprivate-id"),
     ("uncertain", "dispatch_started", False)),
])
def test_provider_rejection_or_invalid_response_is_durable(
        tmp_path, result, expected):
    ledger, adapter = store(tmp_path), Adapter(result=result)
    document = coordinator(ledger, adapter).dispatch(**request())
    assert (document["status"], document["code"], document["final"]) == expected
    assert ledger.outcome_status(KEY)["outcome"]["status"] == expected[0]
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("kind", ["timeout", "exception", "elapsed"])
def test_ambiguous_provider_failures_keep_dispatch_marker_and_never_retry(
        tmp_path, kind):
    def failure():
        if kind == "timeout":
            raise TimeoutError("private timeout details")
        if kind == "exception":
            raise RuntimeError("private provider details")

    adapter = Adapter(action=failure if kind != "elapsed" else None)
    times = (0.0, 9.0) if kind == "elapsed" else (0.0, 0.1)
    document = coordinator(store(tmp_path), adapter, times=times).dispatch(**request())
    replay = coordinator(store(tmp_path), adapter).dispatch(**request())
    assert replay == document
    assert document["status"] == "uncertain"
    assert document["code"] == "dispatch_started" and document["final"] is False
    assert len(adapter.calls) == 1
    assert "private" not in json.dumps(document)


def test_cancellation_after_adapter_is_uncertain(tmp_path):
    token = CancellationToken()
    adapter = Adapter(action=token.cancel)
    document = coordinator(store(tmp_path), adapter, token).dispatch(**request())
    assert document["status"] == "uncertain"
    assert document["code"] == "dispatch_started"
    assert document["provider_reference_present"] is False
    assert len(adapter.calls) == 1


def test_cancellation_before_reservation_does_not_create_an_outcome(tmp_path):
    token, ledger, adapter = CancellationToken(), store(tmp_path), Adapter()
    token.cancel()
    with pytest.raises(DeliveryBoundaryError, match="nessun invio confermato") as error:
        coordinator(ledger, adapter, token).dispatch(**request())
    assert error.value.code == "delivery_cancelled" and adapter.calls == []
    with pytest.raises(DeliveryReservationError, match="reservation_missing"):
        ledger.outcome_status(KEY)


def test_cancellation_after_reservation_before_adapter_is_final(tmp_path):
    token, ledger, adapter = CancellationToken(), store(tmp_path), Adapter()

    class CancelAfterReserve:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            result = ledger.reserve_dispatch_started_once(
                key, reconciliation_key=reconciliation_key,
            )
            token.cancel()
            return result

        def record_outcome(self, *args, **kwargs):
            return ledger.record_outcome(*args, **kwargs)

        def outcome_status(self, key):
            return ledger.outcome_status(key)

    document = coordinator(CancelAfterReserve(), adapter, token).dispatch(**request())
    assert document["status"] == "failed"
    assert document["code"] == "cancelled_before_dispatch"
    assert document["final"] is True and adapter.calls == []


def test_legacy_unbound_reservation_fails_closed_without_adapter_invocation(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()
    assert ledger.reserve_once(KEY) is True  # simulated stop after reservation
    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(ledger, adapter).dispatch(**request())
    assert error.value.code == "delivery_outcome_conflict"
    assert adapter.calls == []
    state = ledger.outcome_status(KEY)
    assert state["outcome"] is None and state["chain_valid"] is True


def test_concurrent_duplicate_never_sends_twice_and_final_reconciles(tmp_path):
    entered, release = Event(), Event()
    ledger = store(tmp_path)

    def hold_first_attempt():
        entered.set()
        assert release.wait(timeout=5)

    adapter = Adapter(action=hold_first_attempt)
    first = coordinator(ledger, adapter)
    duplicate = coordinator(store(tmp_path), adapter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(first.dispatch, **request())
        assert entered.wait(timeout=5)
        replay = pool.submit(duplicate.dispatch, **request()).result(timeout=5)
        in_flight = ledger.outcome_status(KEY)["outcome"]
        assert in_flight["sequence"] == 1
        assert in_flight["code"] == "dispatch_started"
        release.set()
        accepted = winner.result(timeout=5)
    assert replay["status"] == "uncertain"
    assert replay["code"] == "dispatch_started"
    assert accepted["status"] == "accepted"
    assert len(adapter.calls) == 1
    final = ledger.outcome_status(KEY)["outcome"]
    assert final["status"] == "accepted" and final["sequence"] == 2


def test_lost_final_write_keeps_pre_dispatch_marker_and_blocks_retry(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()

    class FailFirstRecord:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def __init__(self):
            self.calls = 0

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return ledger.reserve_dispatch_started_once(
                key, reconciliation_key=reconciliation_key,
            )

        def outcome_status(self, key):
            return ledger.outcome_status(key)

        def record_outcome(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("private storage detail")
            return ledger.record_outcome(*args, **kwargs)

    wrapped = FailFirstRecord()
    first = coordinator(wrapped, adapter).dispatch(**request())
    recovered = coordinator(wrapped, adapter).dispatch(**request())
    assert recovered == first
    assert recovered["status"] == "uncertain"
    assert recovered["code"] == "dispatch_started"
    assert len(adapter.calls) == 1 and wrapped.calls == 1


def test_external_acceptance_crash_cannot_resend_after_reservation_expiry(tmp_path):
    clock = [1_000.0]
    ledger = SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3", key_secret=SECRET,
        policy=DeliveryReservationPolicy(
            reservation_retention_seconds=60,
            outcome_retention_seconds=REQUIRED_MARKER_RETENTION,
        ),
        clock=lambda: clock[0],
    )
    adapter = Adapter()

    class LoseFinalWrite:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return ledger.reserve_dispatch_started_once(
                key, reconciliation_key=reconciliation_key,
            )

        def outcome_status(self, key):
            return ledger.outcome_status(key)

        def record_outcome(self, *args, **kwargs):
            raise RuntimeError("simulated stop before final outcome commit")

    first = coordinator(LoseFinalWrite(), adapter).dispatch(**request())
    assert first["code"] == "dispatch_started" and len(adapter.calls) == 1
    clock[0] = 1_301.0  # exceeds the rejected short policy; marker is retained
    replay = coordinator(ledger, adapter).dispatch(**request())
    assert replay == first and len(adapter.calls) == 1
    marker = ledger.outcome_status(KEY)["outcome"]
    assert marker["sequence"] == 1 and marker["code"] == "dispatch_started"


def test_short_marker_retention_is_rejected_before_reservation_or_adapter(tmp_path):
    ledger = SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3", key_secret=SECRET,
        policy=DeliveryReservationPolicy(
            reservation_retention_seconds=60, outcome_retention_seconds=300,
        ),
        clock=lambda: 1_000.0,
    )
    adapter = Adapter()
    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(ledger, adapter)
    assert error.value.code == "delivery_configuration_invalid"
    assert adapter.calls == []
    with pytest.raises(DeliveryReservationError, match="reservation_missing"):
        ledger.outcome_status(KEY)


def test_maximum_valid_action_link_never_outlives_dispatch_marker(tmp_path):
    elapsed = [0.0]
    ledger_clock = [1_000.0]
    ledger = SQLiteDeliveryReservationStore(
        tmp_path / "private" / "delivery.sqlite3", key_secret=SECRET,
        policy=DeliveryReservationPolicy(
            reservation_retention_seconds=60,
            outcome_retention_seconds=REQUIRED_MARKER_RETENTION,
        ),
        clock=lambda: ledger_clock[0],
    )
    adapter = Adapter()

    class LoseFinalWrite:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return ledger.reserve_dispatch_started_once(
                key, reconciliation_key=reconciliation_key,
            )

        def outcome_status(self, key):
            return ledger.outcome_status(key)

        def record_outcome(self, *args, **kwargs):
            raise RuntimeError("simulated final write loss")

    maximum_link = request(
        expires_at_utc=(NOW + timedelta(seconds=MAX_ACTION_TTL_SECONDS)).isoformat(),
    )
    utc_clock = lambda: NOW + timedelta(seconds=elapsed[0])
    first = coordinator(LoseFinalWrite(), adapter, utc_clock=utc_clock).dispatch(
        **maximum_link,
    )
    assert first["code"] == "dispatch_started" and len(adapter.calls) == 1

    elapsed[0] = MAX_ACTION_TTL_SECONDS - 1
    ledger_clock[0] += MAX_ACTION_TTL_SECONDS - 1
    replay = coordinator(ledger, adapter, utc_clock=utc_clock).dispatch(**maximum_link)
    assert replay == first and len(adapter.calls) == 1
    assert ledger.outcome_status(KEY)["outcome"]["code"] == "dispatch_started"

    elapsed[0] = MAX_ACTION_TTL_SECONDS + 1
    ledger_clock[0] += 2
    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(ledger, adapter, utc_clock=utc_clock).dispatch(**maximum_link)
    assert error.value.code == "delivery_expiry_invalid"
    assert len(adapter.calls) == 1


def test_lost_ack_after_outcome_commit_is_recovered_without_second_write(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()

    class CommitThenLoseAck:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def __init__(self):
            self.calls = 0

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return ledger.reserve_dispatch_started_once(
                key, reconciliation_key=reconciliation_key,
            )

        def outcome_status(self, key):
            return ledger.outcome_status(key)

        def record_outcome(self, *args, **kwargs):
            self.calls += 1
            ledger.record_outcome(*args, **kwargs)
            raise RuntimeError("private lost acknowledgement")

    wrapped = CommitThenLoseAck()
    document = coordinator(wrapped, adapter).dispatch(**request())
    assert document["status"] == "accepted"
    assert wrapped.calls == 1 and len(adapter.calls) == 1


def test_invalid_ledger_document_fails_closed(tmp_path):
    ledger, adapter = store(tmp_path), Adapter()

    class InvalidStatus:
        dispatch_marker_retention_seconds = ledger.dispatch_marker_retention_seconds

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return False

        def outcome_status(self, key):
            return {"chain_valid": True, "outcome": {"status": "accepted"}}

        record_outcome = ledger.record_outcome

    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(InvalidStatus(), adapter).dispatch(**request())
    assert error.value.code == "delivery_outcome_invalid"
    assert adapter.calls == []


@pytest.mark.parametrize("event", [
    {"status": "accepted", "code": "transport_accepted", "final": False,
     "provider_reference_present": True, "chain_valid": True},
    {"status": "uncertain", "code": "dispatch_started", "final": True,
     "provider_reference_present": False, "chain_valid": True},
])
def test_public_projection_rejects_status_finality_mismatch(event):
    class ForgedLedger:
        dispatch_marker_retention_seconds = REQUIRED_MARKER_RETENTION

        def reserve_dispatch_started_once(self, key, *, reconciliation_key):
            return False

        def outcome_status(self, key):
            return {"chain_valid": True, "outcome": event}

        def record_outcome(self, *args, **kwargs):
            raise AssertionError("must not record")

    with pytest.raises(DeliveryBoundaryError) as error:
        coordinator(ForgedLedger()).dispatch(**request())
    assert error.value.code == "delivery_outcome_invalid"


def test_coordinator_remains_unwired_and_has_no_network_or_provider_sdk():
    server_source = Path("server.py").read_text(encoding="utf-8")
    source = Path("delivery_provider_readiness.py").read_text(encoding="utf-8")
    assert "ProviderNeutralDeliveryCoordinator" not in server_source
    for forbidden in ("import socket", "import requests", "urllib.request", "boto", "sendgrid"):
        assert forbidden not in source.lower()
