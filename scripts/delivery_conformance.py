"""Offline conformance for the intentionally unwired account-delivery boundary."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from delivery_boundary import (AccountDeliveryBoundary, CancellationToken, DeliveryConfig,
                               DeliveryTransportResult)


class Reservations:
    def __init__(self):
        self.keys = set()

    def reserve_once(self, key):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


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
    transport, reservations = RecordedTransport(), Reservations()
    boundary = AccountDeliveryBoundary(
        config=DeliveryConfig(("accounts.slps.example",)), transport=transport,
        reservations=reservations, cancellation=CancellationToken(), utc_clock=lambda: now,
    )
    with patch.object(socket, "socket", blocked), patch.object(socket, "create_connection", blocked):
        for index, purpose in enumerate(("verify_email", "reset_password", "company_invitation")):
            result = boundary.dispatch(
                recipient=f"synthetic-{index}@example.test", purpose=purpose, locale="it",
                action_url=f"https://accounts.slps.example/{purpose}?token={'x' * 32}",
                expires_at_utc=(now + timedelta(hours=1)).isoformat(),
                idempotency_key=f"delivery:{purpose}:{'i' * 40}",
            )
            assert result == {"status": "accepted", "purpose": purpose}
    assert len(transport.envelopes) == 3 and not network_attempts
    assert all(item.attempts_allowed == 1 and not item.allow_redirects and item.verify_tls
               for item in transport.envelopes)
    print(json.dumps({
        "offline_conformance": "passed", "purposes": 3, "single_attempts": 3,
        "network_attempts": 0, "provider_sdk": False, "real_messages_sent": 0,
        "application_wired": False,
    }, sort_keys=True))


if __name__ == "__main__":
    run()
