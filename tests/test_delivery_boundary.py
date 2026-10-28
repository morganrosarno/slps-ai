from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from delivery_boundary import (AccountDeliveryBoundary, CancellationToken, DeliveryBoundaryError,
    DeliveryConfig, DeliveryTransportResult, LOCALES, PURPOSES)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
TOKEN = "sensitiveRawTokenValue_1234567890"
KEY = "delivery:synthetic:" + "k" * 40


class Reservations:
    def __init__(self, result=True, action=None):
        self.result, self.action, self.keys = result, action, []

    def reserve_once(self, key):
        self.keys.append(key)
        if self.action:
            self.action()
        return self.result


class Transport:
    def __init__(self, result=None, action=None):
        self.result = result or DeliveryTransportResult(True, "synthetic-message-id")
        self.action, self.calls = action, []

    def send(self, envelope, *, cancellation):
        self.calls.append(envelope)
        if self.action:
            self.action()
        return self.result


def boundary(transport=None, reservations=None, token=None, times=None, **config):
    moments = iter(times or (0, 0.1))
    return AccountDeliveryBoundary(
        config=DeliveryConfig(("accounts.slps.example",), **config),
        transport=transport or Transport(), reservations=reservations or Reservations(),
        cancellation=token or CancellationToken(), monotonic_clock=lambda: next(moments), utc_clock=lambda: NOW,
    )


def kwargs(**overrides):
    value = dict(recipient="Person.Synthetic@example.test", purpose="verify_email", locale="it",
        action_url=f"https://accounts.slps.example/verify?token={TOKEN}",
        expires_at_utc=(NOW + timedelta(hours=1)).isoformat(), idempotency_key=KEY)
    value.update(overrides)
    return value


def test_all_purposes_and_locales_dispatch_once_with_safe_result_and_repr():
    for purpose in PURPOSES:
        for locale in LOCALES:
            transport = Transport()
            result = boundary(transport).dispatch(**kwargs(purpose=purpose, locale=locale,
                idempotency_key=f"delivery:{purpose}:{locale}:" + "x" * 32))
            assert result == {"status": "accepted", "purpose": purpose}
            assert len(transport.calls) == 1
            envelope = transport.calls[0]
            assert envelope.recipient == "person.synthetic@example.test"
            assert envelope.attempts_allowed == 1 and not envelope.allow_redirects and envelope.verify_tls
            assert TOKEN not in repr(envelope) and envelope.recipient not in repr(envelope)
            assert "synthetic-message-id" not in json.dumps(result)


@pytest.mark.parametrize("recipient", ["", " person@example.test", "a@localhost", "a@127.0.0.1", "a..b@example.test", "a@example", "a\n@example.test", "ü@example.test"])
def test_invalid_recipient_fails_before_reservation_and_dispatch(recipient):
    transport, reservations = Transport(), Reservations()
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations).dispatch(**kwargs(recipient=recipient))
    assert error.value.code == "delivery_recipient_invalid"
    assert not transport.calls and not reservations.keys


@pytest.mark.parametrize("url", [
    f"http://accounts.slps.example/verify?token={TOKEN}",
    f"https://user:secret@accounts.slps.example/verify?token={TOKEN}",
    f"https://other.example/verify?token={TOKEN}",
    f"https://127.0.0.1/verify?token={TOKEN}",
    f"https://accounts.slps.example:8443/verify?token={TOKEN}",
    f"https://accounts.slps.example/../verify?token={TOKEN}",
    f"https://accounts.slps.example/verify?token={TOKEN}&next=x",
    "https://accounts.slps.example/verify?token=short",
    f"https://accounts.slps.example/verify?token={TOKEN}#fragment",
])
def test_action_url_is_strict_and_never_leaks_token(url):
    transport, reservations = Transport(), Reservations()
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations).dispatch(**kwargs(action_url=url))
    assert error.value.code == "delivery_action_invalid"
    assert TOKEN not in str(error.value) and not transport.calls and not reservations.keys


@pytest.mark.parametrize("overrides", [
    {"purpose": "unknown"}, {"locale": "rm"}, {"idempotency_key": "short"},
    {"expires_at_utc": (NOW - timedelta(seconds=1)).isoformat()},
    {"expires_at_utc": (NOW + timedelta(days=2)).isoformat()}, {"expires_at_utc": "not-a-date"},
])
def test_invalid_policy_values_fail_closed_before_reservation(overrides):
    transport, reservations = Transport(), Reservations()
    with pytest.raises(DeliveryBoundaryError):
        boundary(transport, reservations).dispatch(**kwargs(**overrides))
    assert not transport.calls and not reservations.keys


@pytest.mark.parametrize("overrides", [
    {"allowed_action_hosts": ()}, {"allowed_action_hosts": ("localhost",)},
    {"allowed_action_hosts": ("127.0.0.1",)}, {"timeout_seconds": 0},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": True}, {"max_action_url_bytes": 10},
])
def test_configuration_rejects_local_unbounded_or_nonfinite_values(overrides):
    args = dict(allowed_action_hosts=("accounts.slps.example",), timeout_seconds=8, max_action_url_bytes=2048)
    args.update(overrides)
    with pytest.raises(DeliveryBoundaryError) as error:
        DeliveryConfig(**args)
    assert error.value.code == "delivery_configuration_invalid"


def test_duplicate_is_durably_suppressed_without_transport_attempt():
    transport, reservations = Transport(), Reservations(False)
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations).dispatch(**kwargs())
    assert error.value.code == "delivery_duplicate"
    assert reservations.keys == [KEY] and not transport.calls


@pytest.mark.parametrize("kind", ["raised", "elapsed"])
def test_timeout_consumes_reservation_and_never_retries(kind):
    def timeout():
        raise TimeoutError("SENSITIVE_PROVIDER_DETAILS")
    transport, reservations = Transport(action=timeout if kind == "raised" else None), Reservations()
    times = (0, 9) if kind == "elapsed" else (0, 0)
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations, times=times).dispatch(**kwargs())
    assert error.value.code == "delivery_timeout" and len(transport.calls) == 1
    assert reservations.keys == [KEY] and "SENSITIVE_PROVIDER_DETAILS" not in str(error.value)


def test_transport_failure_is_sanitized_and_never_retried():
    def fail():
        raise RuntimeError(f"provider error {TOKEN}")
    transport, reservations = Transport(action=fail), Reservations()
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations).dispatch(**kwargs())
    assert error.value.code == "delivery_transport_failed" and len(transport.calls) == 1
    assert TOKEN not in str(error.value) and reservations.keys == [KEY]


@pytest.mark.parametrize("when", ["before", "after"])
def test_cancellation_before_or_after_dispatch_never_returns_success(when):
    token = CancellationToken()
    if when == "before":
        token.cancel()
    transport = Transport(action=token.cancel if when == "after" else None)
    reservations = Reservations()
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, reservations, token).dispatch(**kwargs())
    assert error.value.code == "delivery_cancelled"
    assert len(transport.calls) == (0 if when == "before" else 1)
    assert reservations.keys == ([] if when == "before" else [KEY])


@pytest.mark.parametrize("result", [
    object(), DeliveryTransportResult(False, "rejected"), DeliveryTransportResult(True, "x\nsecret"),
    replace(DeliveryTransportResult(True), accepted=1),
])
def test_transport_response_is_strict_and_sanitized(result):
    with pytest.raises(DeliveryBoundaryError):
        boundary(Transport(result=result)).dispatch(**kwargs())


def test_reservation_exception_is_sanitized_and_stops_before_transport():
    def fail():
        raise RuntimeError(TOKEN)
    transport = Transport()
    with pytest.raises(DeliveryBoundaryError) as error:
        boundary(transport, Reservations(action=fail)).dispatch(**kwargs())
    assert error.value.code == "delivery_reservation_failed" and TOKEN not in str(error.value)
    assert not transport.calls


def test_application_remains_unwired():
    import server
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "AccountDeliveryBoundary" not in source and "delivery_boundary" not in source


def test_zero_network_conformance_command():
    result = subprocess.run([sys.executable, "scripts/delivery_conformance.py"], cwd=Path(__file__).parents[1],
        check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert output["offline_conformance"] == "passed" and output["network_attempts"] == 0
    assert output["single_attempts"] == 3 and output["real_messages_sent"] == 0
