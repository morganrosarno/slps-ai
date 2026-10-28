"""Offline provider-neutral coordination for account-message delivery.

This module is deliberately not imported by the web application.  It binds the
existing strict account-message boundary to the durable reservation/outcome
ledger while keeping the actual transport injected.  It contains no provider
SDK, credentials, endpoint, network client, retry, fallback or worker.

One durable reservation permits at most one adapter invocation.  A duplicate
reservation reads the durable outcome instead of invoking the adapter again. If
a previous process stopped after reservation but before recording an outcome,
the replay records a conservative uncertain outcome and still does not send.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Protocol

from delivery_boundary import (
    AccountDeliveryBoundary, CancellationSignal, DeliveryBoundaryError,
    canonical_delivery_envelope, DeliveryConfig, DeliveryEnvelope, DeliveryTransportResult,
    MAX_ACTION_TTL_SECONDS, SingleAttemptDeliveryTransport,
)


DELIVERY_CLOCK_MARGIN_SECONDS = 60


def required_dispatch_marker_retention_seconds(timeout_seconds: float) -> int:
    """Shared offline/runtime lower bound for retaining a dispatch marker."""
    if (type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
        raise DeliveryBoundaryError(
            "delivery_configuration_invalid", "Configurazione del confine di consegna non valida.",
        )
    return MAX_ACTION_TTL_SECONDS + math.ceil(timeout_seconds) + DELIVERY_CLOCK_MARGIN_SECONDS


class DurableDeliveryLedger(Protocol):
    @property
    def dispatch_marker_retention_seconds(self) -> int: ...

    def reserve_dispatch_started_once(self, key: str, *,
                                      reconciliation_key: str) -> bool: ...

    def record_outcome(self, key: str, *, status: str, code: str,
                       reconciliation_key: str,
                       provider_reference: str = "") -> dict[str, object]: ...

    def outcome_status(self, key: str) -> dict[str, object]: ...


class _CapturingTransport:
    """Record only safe attempt metadata around one injected adapter."""

    def __init__(self, adapter: SingleAttemptDeliveryTransport):
        self._adapter = adapter
        self.invoked = False
        self.provider_reference = ""

    def send(self, envelope: DeliveryEnvelope, *,
             cancellation: CancellationSignal) -> DeliveryTransportResult:
        if self.invoked:
            raise RuntimeError("single adapter invocation exceeded")
        self.invoked = True
        result = self._adapter.send(envelope, cancellation=cancellation)
        if (isinstance(result, DeliveryTransportResult)
                and isinstance(result.provider_message_id, str)
                and len(result.provider_message_id) <= 256
                and not any(ord(character) < 32 for character in result.provider_message_id)):
            self.provider_reference = result.provider_message_id
        return result


class _DispatchStartedReservation:
    """Expose the atomic pre-dispatch ledger operation to the strict boundary."""

    def __init__(self, ledger: DurableDeliveryLedger, reconciliation_key: str):
        self._ledger = ledger
        self._reconciliation_key = reconciliation_key

    def reserve_once(self, key: str) -> bool:
        try:
            return self._ledger.reserve_dispatch_started_once(
                key, reconciliation_key=self._reconciliation_key,
            )
        except Exception as error:
            if getattr(error, "args", ()) == ("delivery_outcome_conflict",):
                raise DeliveryBoundaryError(
                    "delivery_outcome_conflict",
                    "Chiave di consegna già associata a una richiesta diversa.",
                    409,
                ) from None
            raise


class ProviderNeutralDeliveryCoordinator:
    """Coordinate one injected adapter attempt with one durable outcome.

    Transport failures are represented as redacted durable outcomes. Request,
    configuration, reservation and ledger failures remain sanitized exceptions.
    The returned document never contains recipient, action URL, idempotency key,
    reconciliation key or provider reference.
    """

    _MAPPED = {
        "delivery_timeout": ("uncertain", "timeout"),
        "delivery_transport_failed": ("uncertain", "acknowledgement_lost"),
        "delivery_not_accepted": ("failed", "transport_rejected"),
        # A malformed acknowledgement cannot prove that the provider rejected
        # the operation, so preserve the attempt as uncertain.
        "delivery_response_invalid": ("uncertain", "acknowledgement_lost"),
    }
    _CODES = {
        "accepted": frozenset({"transport_accepted"}),
        "failed": frozenset({
            "transport_rejected", "transport_failed", "invalid_response",
            "expired", "cancelled_before_dispatch",
        }),
        "uncertain": frozenset({
            "dispatch_started", "timeout", "acknowledgement_lost",
            "cancelled_after_dispatch",
        }),
    }
    CLOCK_MARGIN_SECONDS = DELIVERY_CLOCK_MARGIN_SECONDS

    def __init__(self, *, config: DeliveryConfig,
                 adapter: SingleAttemptDeliveryTransport,
                 ledger: DurableDeliveryLedger,
                 cancellation: CancellationSignal,
                 monotonic_clock=None, utc_clock=None):
        if (not isinstance(config, DeliveryConfig)
                or not callable(getattr(adapter, "send", None))
                or not callable(getattr(ledger, "reserve_dispatch_started_once", None))
                or not callable(getattr(ledger, "record_outcome", None))
                or not callable(getattr(ledger, "outcome_status", None))):
            raise DeliveryBoundaryError(
                "delivery_configuration_invalid",
                "Configurazione del confine di consegna non valida.",
            )
        try:
            marker_retention = ledger.dispatch_marker_retention_seconds
            required_retention = required_dispatch_marker_retention_seconds(config.timeout_seconds)
        except Exception:
            marker_retention = None
            required_retention = None
        if (type(marker_retention) is not int or type(required_retention) is not int
                or marker_retention < required_retention):
            raise DeliveryBoundaryError(
                "delivery_configuration_invalid",
                "Configurazione del confine di consegna non valida.",
            )
        self._ledger = ledger
        self._adapter = adapter
        self._config = config
        self._cancellation = cancellation
        self._monotonic = monotonic_clock
        self._utc = utc_clock

    @staticmethod
    def _reconciliation_key(idempotency_key: str, status: str, code: str,
                            provider_reference: str) -> str:
        digest = hashlib.sha256(
            b"slps.delivery.provider-readiness.v1\0"
            + idempotency_key.encode("utf-8") + b"\0"
            + status.encode("ascii") + b"\0" + code.encode("ascii") + b"\0"
            + provider_reference.encode("utf-8")
        ).hexdigest()
        return "delivery-provider-readiness:" + digest

    @staticmethod
    def _request_binding_key(envelope: DeliveryEnvelope) -> str:
        digest = hashlib.sha256(b"slps.delivery.request-binding.v1\0")
        # Length framing makes the tuple unambiguous without persisting any
        # recipient or action token.  The ledger HMACs this derived value again.
        for value in (
                envelope.idempotency_key, envelope.recipient, envelope.purpose,
                envelope.locale, envelope.action_url, envelope.expires_at_utc):
            payload = value.encode("utf-8")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
        return "delivery-request-binding:" + digest.hexdigest()

    @staticmethod
    def _public(purpose: str, event: object) -> dict[str, object]:
        if not isinstance(event, dict):
            raise DeliveryBoundaryError(
                "delivery_outcome_invalid", "Esito della consegna non valido."
            )
        status, code = event.get("status"), event.get("code")
        final = event.get("final")
        reference_present = event.get("provider_reference_present")
        chain_valid = event.get("chain_valid")
        if (status not in ProviderNeutralDeliveryCoordinator._CODES
                or code not in ProviderNeutralDeliveryCoordinator._CODES.get(status, ())
                or type(final) is not bool or type(reference_present) is not bool
                or final is not (status in {"accepted", "failed"})
                or chain_valid is not True):
            raise DeliveryBoundaryError(
                "delivery_outcome_invalid", "Esito della consegna non valido."
            )
        return {
            "status": status, "code": code, "purpose": purpose,
            "final": final, "provider_reference_present": reference_present,
            "chain_valid": True,
        }

    def _existing_event(self, key: str) -> object:
        try:
            state = self._ledger.outcome_status(key)
        except Exception:
            raise DeliveryBoundaryError(
                "delivery_outcome_unavailable",
                "Stato della consegna non disponibile.",
            ) from None
        if not isinstance(state, dict) or state.get("chain_valid") is not True:
            raise DeliveryBoundaryError(
                "delivery_outcome_invalid", "Esito della consegna non valido."
            )
        return state.get("outcome")

    def _persist(self, *, key: str, purpose: str, status: str, code: str,
                 provider_reference: str = "", accept_any_existing: bool = False) -> dict[str, object]:
        reconciliation = self._reconciliation_key(
            key, status, code, provider_reference,
        )
        try:
            event = self._ledger.record_outcome(
                key, status=status, code=code,
                reconciliation_key=reconciliation,
                provider_reference=provider_reference,
            )
        except Exception:
            # A commit may have succeeded while its acknowledgement was lost.
            event = self._existing_event(key)
            if event is None:
                raise DeliveryBoundaryError(
                    "delivery_outcome_unavailable",
                    "Registrazione dell’esito non disponibile; nessun nuovo tentativo consentito.",
                ) from None
            if (isinstance(event, dict) and event.get("status") == "uncertain"
                    and event.get("code") == "dispatch_started"):
                return self._public(purpose, event)
            if (not accept_any_existing
                    and (not isinstance(event, dict)
                         or event.get("status") != status or event.get("code") != code)):
                raise DeliveryBoundaryError(
                    "delivery_outcome_conflict", "Esito della consegna in conflitto."
                ) from None
        document = self._public(purpose, event)
        if (not accept_any_existing
                and (document["status"] != status or document["code"] != code)):
            raise DeliveryBoundaryError(
                "delivery_outcome_conflict", "Esito della consegna in conflitto."
            )
        return document

    def _duplicate(self, *, key: str, purpose: str) -> dict[str, object]:
        event = self._existing_event(key)
        if event is not None:
            return self._public(purpose, event)
        # The only safe interpretation of a durable reservation with no outcome
        # is an interrupted/unknown prior attempt. Never invoke the adapter again.
        return self._persist(
            key=key, purpose=purpose, status="uncertain",
            code="acknowledgement_lost", accept_any_existing=True,
        )

    def dispatch(self, *, recipient: str, purpose: str, locale: str,
                 action_url: str, expires_at_utc: str,
                 idempotency_key: str) -> dict[str, object]:
        try:
            now = self._utc() if self._utc is not None else datetime.now(timezone.utc)
            canonical = canonical_delivery_envelope(
                config=self._config, recipient=recipient, purpose=purpose,
                locale=locale, action_url=action_url,
                expires_at_utc=expires_at_utc,
                idempotency_key=idempotency_key, now_utc=now,
            )
        except DeliveryBoundaryError:
            raise
        except Exception:
            raise DeliveryBoundaryError(
                "delivery_configuration_invalid",
                "Configurazione del confine di consegna non valida.",
            ) from None
        capture = _CapturingTransport(self._adapter)
        marker_key = self._request_binding_key(canonical)
        arguments = {
            "config": self._config, "transport": capture,
            "reservations": _DispatchStartedReservation(self._ledger, marker_key),
            "cancellation": self._cancellation,
        }
        if self._monotonic is not None:
            arguments["monotonic_clock"] = self._monotonic
        arguments["utc_clock"] = lambda: now
        boundary = AccountDeliveryBoundary(**arguments)
        try:
            boundary.dispatch(
                recipient=recipient, purpose=purpose, locale=locale,
                action_url=action_url, expires_at_utc=expires_at_utc,
                idempotency_key=idempotency_key,
            )
        except DeliveryBoundaryError as error:
            if error.code == "delivery_duplicate":
                return self._duplicate(key=idempotency_key, purpose=purpose)
            if error.code == "delivery_cancelled":
                if capture.invoked:
                    event = self._existing_event(idempotency_key)
                    return self._public(purpose, event)
                try:
                    existing = self._existing_event(idempotency_key)
                except DeliveryBoundaryError:
                    raise error
                if (isinstance(existing, dict)
                        and existing.get("status") == "uncertain"
                        and existing.get("code") == "dispatch_started"):
                    return self._persist(
                        key=idempotency_key, purpose=purpose, status="failed",
                        code="cancelled_before_dispatch",
                    )
                if existing is not None:
                    return self._public(purpose, existing)
                raise error
            mapped = self._MAPPED.get(error.code)
            if mapped is None:
                raise
            status, code = mapped
            if status == "uncertain":
                event = self._existing_event(idempotency_key)
                return self._public(purpose, event)
            return self._persist(
                key=idempotency_key, purpose=purpose, status=status, code=code,
                provider_reference=capture.provider_reference,
            )
        return self._persist(
            key=idempotency_key, purpose=purpose, status="accepted",
            code="transport_accepted", provider_reference=capture.provider_reference,
        )
