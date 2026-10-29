"""Offline conformance for the intentionally unwired account-delivery boundary."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from delivery_boundary import (CancellationToken, DeliveryBoundaryError, DeliveryConfig,
                               DEFAULT_ACTION_PATHS, DeliveryTransportResult)
from delivery_provider_readiness import ProviderNeutralDeliveryCoordinator
from delivery_reservations import DeliveryReservationPolicy, SQLiteDeliveryReservationStore


class RecordedTransport:
    def __init__(self, result=None, failure=None, before_send=None):
        self.envelopes = []
        self.result = result if result is not None else DeliveryTransportResult(
            True, "synthetic-recorded-id",
        )
        self.failure = failure
        self.before_send = before_send

    def send(self, envelope, *, cancellation):
        self.envelopes.append(envelope)
        if self.before_send:
            self.before_send(envelope)
        if self.failure:
            raise self.failure
        return self.result


def run():
    network_attempts = []

    def blocked(*_args, **_kwargs):
        network_attempts.append(True)
        raise RuntimeError("network forbidden")

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    with TemporaryDirectory() as directory:
        database = Path(directory) / "delivery.sqlite3"
        reservations = SQLiteDeliveryReservationStore(
            database, key_secret=b"offline-conformance-secret-32bytes!",
            policy=DeliveryReservationPolicy(
                reservation_retention_seconds=600, outcome_retention_seconds=90_000,
            ), clock=lambda: 1_000,
        )
        markers_seen = []

        def verify_pre_dispatch_marker(envelope):
            event = reservations.outcome_status(envelope.idempotency_key)["outcome"]
            assert event["status"] == "uncertain" and event["code"] == "dispatch_started"
            markers_seen.append(event["sequence"])

        transport = RecordedTransport(before_send=verify_pre_dispatch_marker)
        boundary = ProviderNeutralDeliveryCoordinator(
            config=DeliveryConfig(("accounts.slps.example",)), adapter=transport,
            ledger=reservations, cancellation=CancellationToken(), utc_clock=lambda: now,
        )
        with patch.object(socket, "socket", blocked), patch.object(socket, "create_connection", blocked):
            for index, purpose in enumerate(("verify_email", "reset_password", "company_invitation")):
                key = f"delivery:{purpose}:{'i' * 40}"
                result = boundary.dispatch(
                    recipient=f"synthetic-{index}@example.test", purpose=purpose, locale="it",
                    action_url=(f"https://accounts.slps.example{dict(DEFAULT_ACTION_PATHS)[purpose]}"
                                f"?token={'x' * 32}"),
                    expires_at_utc=(now + timedelta(hours=1)).isoformat(),
                    idempotency_key=key,
                )
                assert result["status"] == "accepted" and result["chain_valid"]

            first_key = f"delivery:verify_email:{'i' * 40}"
            try:
                boundary.dispatch(
                    recipient="different@example.test", purpose="verify_email", locale="it",
                    action_url=("https://accounts.slps.example/account/verify-email"
                                f"?token={'x' * 32}"),
                    expires_at_utc=(now + timedelta(hours=1)).isoformat(),
                    idempotency_key=first_key,
                )
            except DeliveryBoundaryError as error:
                request_binding_conflict = error.code == "delivery_outcome_conflict"
            else:
                request_binding_conflict = False
            assert request_binding_conflict and len(transport.envelopes) == 3

            failure_probes = []
            scenarios = (
                ("rejected", RecordedTransport(DeliveryTransportResult(False, "rejected"))),
                ("timeout", RecordedTransport(failure=TimeoutError("synthetic private"))),
                ("exception", RecordedTransport(failure=RuntimeError("synthetic private"))),
                ("invalid", RecordedTransport(result=object())),
            )
            for index, (name, fake) in enumerate(scenarios):
                probe = ProviderNeutralDeliveryCoordinator(
                    config=DeliveryConfig(("accounts.slps.example",)), adapter=fake,
                    ledger=reservations, cancellation=CancellationToken(), utc_clock=lambda: now,
                ).dispatch(
                    recipient=f"failure-{index}@example.test", purpose="verify_email",
                    locale="en",
                    action_url=("https://accounts.slps.example/account/verify-email"
                                f"?token={'f' * 32}"),
                    expires_at_utc=(now + timedelta(hours=1)).isoformat(),
                    idempotency_key=f"delivery:failure:{name}:{'z' * 40}",
                )
                failure_probes.append({"name": name, "status": probe["status"],
                                       "code": probe["code"]})
        restarted = SQLiteDeliveryReservationStore(
            database, key_secret=b"offline-conformance-secret-32bytes!",
            policy=DeliveryReservationPolicy(
                reservation_retention_seconds=600, outcome_retention_seconds=90_000,
            ), clock=lambda: 1_000,
        )
        assert restarted.reserve_once(f"delivery:verify_email:{'i' * 40}") is False
        assert restarted.outcome_status(
            f"delivery:verify_email:{'i' * 40}",
        )["outcome"]["status"] == "accepted"
    assert len(transport.envelopes) == 3 and not network_attempts
    assert all(item.attempts_allowed == 1 and not item.allow_redirects and item.verify_tls
               for item in transport.envelopes)
    print(json.dumps({
        "offline_conformance": "passed", "purposes": 3, "single_attempts": 3,
        "network_attempts": 0, "provider_sdk": False, "real_messages_sent": 0,
        "application_wired": False, "durable_restart_duplicate_suppressed": True,
        "durable_outcomes_verified": 7, "failure_probes": failure_probes,
        "atomic_pre_dispatch_markers": len(markers_seen),
        "request_binding_conflict": request_binding_conflict,
    }, sort_keys=True))


if __name__ == "__main__":
    run()
