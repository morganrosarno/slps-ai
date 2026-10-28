"""Provider-neutral account-message boundary, intentionally not wired.

The application does not instantiate this boundary.  A future approved
integration must inject a transport and a durable, atomic idempotency
reservation.  This module contains no provider SDK, credentials, network
client, retry, fallback or background worker.

Raw recipients, action URLs and provider identifiers are hidden from repr and
are never returned by the boundary.  A reserved idempotency key is consumed
even when dispatch is uncertain: callers must create a new operation instead
of retrying an ambiguous send.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import math
import re
import time
from typing import Callable, Protocol
from urllib.parse import parse_qsl, unquote, urlsplit


PURPOSES = frozenset({"verify_email", "reset_password", "company_invitation"})
LOCALES = frozenset({"it", "de", "fr", "en"})


class DeliveryBoundaryError(ValueError):
    """Sanitized error; messages never copy transport or input details."""

    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code, self.status = code, status


def _configuration_error():
    raise DeliveryBoundaryError(
        "delivery_configuration_invalid",
        "Configurazione del confine di consegna non valida.",
        503,
    )


def _host(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 253 or value != value.lower()
            or value.endswith(".") or "." not in value
            or value.endswith((".localhost", ".local", ".internal"))):
        _configuration_error()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        _configuration_error()
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
           for label in value.split(".")):
        _configuration_error()
    return value


def _finite(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


@dataclass(frozen=True)
class DeliveryConfig:
    """Public policy only; provider endpoints and credentials do not belong here."""

    allowed_action_hosts: tuple[str, ...]
    timeout_seconds: float = 8.0
    max_action_url_bytes: int = 2048

    def __post_init__(self):
        if (not isinstance(self.allowed_action_hosts, tuple)
                or not 1 <= len(self.allowed_action_hosts) <= 8
                or len(set(self.allowed_action_hosts)) != len(self.allowed_action_hosts)):
            _configuration_error()
        for host in self.allowed_action_hosts:
            _host(host)
        if not _finite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30:
            _configuration_error()
        if type(self.max_action_url_bytes) is not int or not 256 <= self.max_action_url_bytes <= 4096:
            _configuration_error()


class CancellationSignal(Protocol):
    def is_cancelled(self) -> bool: ...


class CancellationToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


@dataclass(frozen=True)
class DeliveryEnvelope:
    """Minimal transport contract. Sensitive fields are deliberately non-repr."""

    recipient: str = field(repr=False)
    purpose: str
    locale: str
    action_url: str = field(repr=False)
    expires_at_utc: str
    idempotency_key: str = field(repr=False)
    timeout_seconds: float
    attempts_allowed: int = 1
    allow_redirects: bool = False
    verify_tls: bool = True


@dataclass(frozen=True)
class DeliveryTransportResult:
    accepted: bool
    provider_message_id: str = field(default="", repr=False)


class SingleAttemptDeliveryTransport(Protocol):
    def send(self, envelope: DeliveryEnvelope, *, cancellation: CancellationSignal) -> DeliveryTransportResult:
        """Exactly one attempt, with no redirect, retry or fallback."""
        ...


class AtomicIdempotencyReservation(Protocol):
    def reserve_once(self, key: str) -> bool:
        """Atomically return True only for the first durable reservation."""
        ...


def _normalize_recipient(value: object) -> str:
    if (not isinstance(value, str) or value != value.strip() or len(value) > 254
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise DeliveryBoundaryError("delivery_recipient_invalid", "Destinatario non valido.", 422)
    lowered = value.lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", lowered):
        raise DeliveryBoundaryError("delivery_recipient_invalid", "Destinatario non valido.", 422)
    local, domain = lowered.rsplit("@", 1)
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise DeliveryBoundaryError("delivery_recipient_invalid", "Destinatario non valido.", 422)
    if (".." in local or ".." in domain or "." not in domain or domain.endswith(".")
            or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   for label in domain.split("."))):
        raise DeliveryBoundaryError("delivery_recipient_invalid", "Destinatario non valido.", 422)
    return lowered


def _action_url(value: object, config: DeliveryConfig) -> str:
    if (not isinstance(value, str) or len(value.encode("utf-8", "ignore")) > config.max_action_url_bytes
            or any(c.isspace() or ord(c) < 32 for c in value)):
        raise DeliveryBoundaryError("delivery_action_invalid", "Collegamento di azione non valido.", 422)
    try:
        parts = urlsplit(value)
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        if (parts.scheme != "https" or "@" in parts.netloc or parts.username or parts.password
                or parts.port not in {None, 443} or parts.hostname not in config.allowed_action_hosts
                or parts.fragment or not parts.path.startswith("/") or "\\" in value
                or any(segment in {".", ".."} for segment in unquote(parts.path).split("/"))
                or len(pairs) != 1 or pairs[0][0] != "token"
                or not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", pairs[0][1])):
            raise ValueError
    except (TypeError, ValueError, UnicodeError):
        raise DeliveryBoundaryError("delivery_action_invalid", "Collegamento di azione non valido.", 422) from None
    return value


def _expires(value: object, now_utc: datetime) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise DeliveryBoundaryError("delivery_expiry_invalid", "Scadenza del collegamento non valida.", 422)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DeliveryBoundaryError("delivery_expiry_invalid", "Scadenza del collegamento non valida.", 422) from None
    if parsed.tzinfo is None:
        raise DeliveryBoundaryError("delivery_expiry_invalid", "Scadenza del collegamento non valida.", 422)
    parsed = parsed.astimezone(timezone.utc)
    seconds = (parsed - now_utc).total_seconds()
    if not 0 < seconds <= 86400:
        raise DeliveryBoundaryError("delivery_expiry_invalid", "Scadenza del collegamento non valida.", 422)
    return parsed.isoformat().replace("+00:00", "Z")


class AccountDeliveryBoundary:
    """Unwired boundary for verification, reset and invitation messages."""

    def __init__(self, *, config: DeliveryConfig, transport: SingleAttemptDeliveryTransport,
                 reservations: AtomicIdempotencyReservation, cancellation: CancellationSignal,
                 monotonic_clock: Callable[[], float] = time.monotonic,
                 utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if (not isinstance(config, DeliveryConfig)
                or not callable(getattr(transport, "send", None))
                or not callable(getattr(reservations, "reserve_once", None))
                or not callable(getattr(cancellation, "is_cancelled", None))
                or not callable(monotonic_clock) or not callable(utc_clock)):
            _configuration_error()
        self.config = config
        self._transport, self._reservations, self._cancellation = transport, reservations, cancellation
        self._monotonic, self._utc = monotonic_clock, utc_clock

    def _cancelled(self):
        try:
            result = self._cancellation.is_cancelled()
        except Exception:
            raise DeliveryBoundaryError("delivery_cancellation_unavailable", "Stato di annullamento non disponibile.") from None
        if type(result) is not bool:
            _configuration_error()
        if result:
            raise DeliveryBoundaryError("delivery_cancelled", "Consegna annullata; nessun invio confermato.", 499)

    def dispatch(self, *, recipient: str, purpose: str, locale: str, action_url: str,
                 expires_at_utc: str, idempotency_key: str) -> dict[str, str]:
        """Reserve then perform at most one injected transport attempt."""
        if purpose not in PURPOSES or locale not in LOCALES:
            raise DeliveryBoundaryError("delivery_request_invalid", "Richiesta di consegna non valida.", 422)
        normalized = _normalize_recipient(recipient)
        action = _action_url(action_url, self.config)
        try:
            now = self._utc()
            if not isinstance(now, datetime) or now.tzinfo is None:
                _configuration_error()
            now = now.astimezone(timezone.utc)
        except DeliveryBoundaryError:
            raise
        except Exception:
            _configuration_error()
        expiry = _expires(expires_at_utc, now)
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{31,127}", idempotency_key):
            raise DeliveryBoundaryError("delivery_request_invalid", "Richiesta di consegna non valida.", 422)
        self._cancelled()
        try:
            reserved = self._reservations.reserve_once(idempotency_key)
        except Exception:
            raise DeliveryBoundaryError("delivery_reservation_failed", "Prenotazione della consegna non disponibile.") from None
        if type(reserved) is not bool:
            _configuration_error()
        if not reserved:
            raise DeliveryBoundaryError("delivery_duplicate", "Consegna già prenotata; nessun nuovo tentativo.", 409)
        envelope = DeliveryEnvelope(normalized, purpose, locale, action, expiry, idempotency_key,
                                    self.config.timeout_seconds)
        self._cancelled()
        try:
            started = self._monotonic()
            if not _finite(started):
                _configuration_error()
            result = self._transport.send(envelope, cancellation=self._cancellation)
            ended = self._monotonic()
            if not _finite(ended) or ended < started:
                _configuration_error()
        except DeliveryBoundaryError:
            raise
        except TimeoutError:
            self._cancelled()
            raise DeliveryBoundaryError("delivery_timeout", "Il trasporto non ha risposto nel tempo consentito.", 504) from None
        except Exception:
            self._cancelled()
            raise DeliveryBoundaryError("delivery_transport_failed", "Il trasporto non ha completato l’unico tentativo.") from None
        self._cancelled()
        if ended - started > self.config.timeout_seconds:
            raise DeliveryBoundaryError("delivery_timeout", "Il trasporto non ha risposto nel tempo consentito.", 504)
        if (not isinstance(result, DeliveryTransportResult) or type(result.accepted) is not bool
                or not isinstance(result.provider_message_id, str)
                or len(result.provider_message_id) > 256 or any(ord(c) < 32 for c in result.provider_message_id)):
            raise DeliveryBoundaryError("delivery_response_invalid", "Risposta del trasporto non valida.")
        if not result.accepted:
            raise DeliveryBoundaryError("delivery_not_accepted", "Il trasporto non ha confermato la consegna.")
        return {"status": "accepted", "purpose": purpose}
