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

from delivery_boundary import (AccountDeliveryBoundary, CancellationToken, DeliveryConfig,
                               DEFAULT_ACTION_PATHS, DeliveryTransportResult)
from delivery_reservations import DeliveryReservationPolicy, SQLiteDeliveryReservationStore


class RecordedTransport:
    def __init__(self):
        self.envelopes = []

    def send(self, envelope, *, cancellation):
        self.envelopes.append(envelope)
        return DeliveryTransportResult(True, "synthetic-recorded-id")


def run():
    network_attempts = []

    def blocked(*_args, **_kwargs):
        network_attempts.append(True)
        raise RuntimeError("network forbidden")

    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    transport = RecordedTransport()
    with TemporaryDirectory() as directory:
        database = Path(directory) / "delivery.sqlite3"
        reservations = SQLiteDeliveryReservationStore(
            database, key_secret=b"offline-conformance-secret-32bytes!",
            policy=DeliveryReservationPolicy(retention_seconds=600), clock=lambda: 1_000,
        )
        boundary = AccountDeliveryBoundary(
            config=DeliveryConfig(("accounts.slps.example",)), transport=transport,
            reservations=reservations, cancellation=CancellationToken(), utc_clock=lambda: now,
        )
        with patch.object(socket, "socket", blocked), patch.object(socket, "create_connection", blocked):
            for index, purpose in enumerate(("verify_email", "reset_password", "company_invitation")):
                result = boundary.dispatch(
                    recipient=f"synthetic-{index}@example.test", purpose=purpose, locale="it",
                    action_url=(f"https://accounts.slps.example{dict(DEFAULT_ACTION_PATHS)[purpose]}"
                                f"?token={'x' * 32}"),
                    expires_at_utc=(now + timedelta(hours=1)).isoformat(),
                    idempotency_key=f"delivery:{purpose}:{'i' * 40}",
                )
                assert result == {"status": "accepted", "purpose": purpose}
        restarted = SQLiteDeliveryReservationStore(
            database, key_secret=b"offline-conformance-secret-32bytes!",
            policy=DeliveryReservationPolicy(retention_seconds=600), clock=lambda: 1_000,
        )
        assert restarted.reserve_once(f"delivery:verify_email:{'i' * 40}") is False
    assert len(transport.envelopes) == 3 and not network_attempts
    assert all(item.attempts_allowed == 1 and not item.allow_redirects and item.verify_tls
               for item in transport.envelopes)
    print(json.dumps({
        "offline_conformance": "passed", "purposes": 3, "single_attempts": 3,
        "network_attempts": 0, "provider_sdk": False, "real_messages_sent": 0,
        "application_wired": False, "durable_restart_duplicate_suppressed": True,
    }, sort_keys=True))


if __name__ == "__main__":
    run()
