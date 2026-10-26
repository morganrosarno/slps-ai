"""Provider-neutral ASR/vision boundary; no network implementation or credentials.

A future approved integration must supply a transport that authenticates out of
band, applies TLS/host/stream limits and performs exactly one non-redirected
attempt. This module supplies neither transport, fallback, SDK nor live route.
Its fixed wire envelopes are an application contract, not a vendor API claim.
"""
from dataclasses import dataclass, field
import base64
import copy
import ipaddress
import json
import math
import re
import time
from typing import Callable, Protocol
from urllib.parse import unquote, urlsplit

from video_analysis import VideoAnalysisError, _frame_response, _sources, _transcript

LOCALES = frozenset({"it", "de", "fr", "en"})
SCHEMAS = {"vision": "slps.video.vision.response.v1", "speech": "slps.video.speech.response.v1"}


class ProviderBoundaryError(ValueError):
    """Safe errors never include endpoint, credential, payload or provider body."""
    def __init__(self, code, message, status=502):
        super().__init__(message)
        self.code, self.status = code, status


def _bad_config():
    raise ProviderBoundaryError("provider_configuration_invalid", "Configurazione del confine provider non valida.", 503)


def _finite(value):
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def _host(value):
    if (not isinstance(value, str) or len(value) > 253 or value != value.lower()
            or value.endswith(".") or "." not in value or value.endswith((".localhost", ".local", ".internal"))):
        _bad_config()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        _bad_config()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", value.split(".")[-1]):
        _bad_config()
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split(".")):
        _bad_config()
    return value


@dataclass(frozen=True)
class ProviderConfig:
    task: str
    model_id: str = field(repr=False)
    endpoint: str = field(repr=False)
    allowed_hosts: tuple[str, ...] = field(repr=False)
    locale: str
    response_schema: str
    timeout_seconds: float
    max_request_bytes: int
    max_response_bytes: int

    def __post_init__(self):
        if (not isinstance(self.task, str) or not isinstance(self.locale, str) or self.task not in SCHEMAS
                or self.locale not in LOCALES or self.response_schema != SCHEMAS[self.task]):
            _bad_config()
        if not isinstance(self.model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", self.model_id):
            _bad_config()
        if not _finite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 90:
            _bad_config()
        if type(self.max_request_bytes) is not int or not 1024 <= self.max_request_bytes <= 8_000_000:
            _bad_config()
        if type(self.max_response_bytes) is not int or not 256 <= self.max_response_bytes <= 2_000_000:
            _bad_config()
        if not isinstance(self.allowed_hosts, tuple) or not 1 <= len(self.allowed_hosts) <= 8:
            _bad_config()
        hosts = {_host(host) for host in self.allowed_hosts}
        if not isinstance(self.endpoint, str) or len(self.endpoint) > 2048 or any(c.isspace() or ord(c) < 32 for c in self.endpoint):
            _bad_config()
        try:
            parts = urlsplit(self.endpoint)
            if (parts.scheme != "https" or "@" in parts.netloc or parts.username or parts.password or parts.port not in {None, 443}
                    or parts.query or parts.fragment or parts.hostname not in hosts
                    or not parts.path.startswith("/") or not re.fullmatch(r"[A-Za-z0-9/_.:-]+", parts.path) or "\\" in self.endpoint
                    or any(segment in {".", ".."} for segment in unquote(parts.path).split("/"))):
                _bad_config()
            _host(parts.hostname)
        except (TypeError, ValueError):
            _bad_config()


class CancellationSignal(Protocol):
    def is_cancelled(self) -> bool: ...


class CancellationToken:
    def __init__(self):
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled


@dataclass(frozen=True)
class TransportRequest:
    endpoint: str = field(repr=False)
    body: bytes = field(repr=False)
    timeout_seconds: float
    max_response_bytes: int
    method: str = "POST"
    content_type: str = "application/json"
    attempts_allowed: int = 1
    allow_redirects: bool = False
    verify_tls: bool = True


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes = field(repr=False)
    content_type: str = "application/json"
    truncated: bool = False


class SingleAttemptTransport(Protocol):
    def send(self, request: TransportRequest, *, cancellation: CancellationSignal) -> TransportResponse:
        """Exactly one attempt; no redirect/retry/fallback; streaming cap enforced."""
        ...


def _shape(value, depth=0, max_string=32000):
    if depth > 16:
        raise ValueError("depth")
    if value is None or type(value) is bool:
        return
    if isinstance(value, str):
        if len(value) > max_string or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("text")
        return
    if type(value) in {int, float}:
        if not math.isfinite(value):
            raise ValueError("finite")
        return
    if isinstance(value, list):
        if len(value) > 300:
            raise ValueError("array")
        for item in value:
            _shape(item, depth + 1, max_string)
        return
    if isinstance(value, dict):
        if len(value) > 40 or any(not isinstance(k, str) or len(k) > 128 for k in value):
            raise ValueError("object")
        for item in value.values():
            _shape(item, depth + 1, max_string)
        return
    raise ValueError("type")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-finite")


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("schema")


def _validate_vision(output, source_ids, stamp):
    _keys(output, {"summary", "findings", "questions", "limitations"})
    if not isinstance(output["findings"], list) or not isinstance(output["questions"], list):
        raise ValueError("schema")
    for finding in output["findings"]:
        _keys(finding, {"id", "title", "evidence", "certainty", "risk", "exposed_people", "action", "deadline",
                        "question", "critical_unknown", "bbox", "references"})
        if not isinstance(finding["references"], list):
            raise ValueError("schema")
        for ref in finding["references"]:
            _keys(ref, {"source_id"})
    for question in output["questions"]:
        _keys(question, {"id", "text", "why", "critical"})
    # Reuse the orchestrator's semantic, source, ID, bounding-box and size rules.
    _frame_response(copy.deepcopy(output), source_ids, 1, stamp, "provider-boundary")
    return output


class RealVideoAdapterBoundary:
    """Unwired real-adapter boundary, intentionally NOT SyntheticVideoAdapters.

    The caller must durably reserve each subrequest before invoking a method.
    Each invocation issues at most one transport.send, including on failure.
    Cancellation and timeout do not refund an uncertain dispatch attempt.
    """
    def __init__(self, *, vision: ProviderConfig, speech: ProviderConfig,
                 transport: SingleAttemptTransport, cancellation: CancellationSignal,
                 clock: Callable[[], float] = time.monotonic):
        if (not isinstance(vision, ProviderConfig) or vision.task != "vision" or not isinstance(speech, ProviderConfig)
                or speech.task != "speech" or not callable(getattr(transport, "send", None))
                or not callable(getattr(cancellation, "is_cancelled", None)) or not callable(clock)):
            _bad_config()
        self.vision, self.speech = vision, speech
        self._transport, self._cancellation, self._clock = transport, cancellation, clock

    def _cancelled(self):
        try:
            result = self._cancellation.is_cancelled()
            if type(result) is not bool:
                _bad_config()
        except ProviderBoundaryError:
            raise
        except Exception:
            raise ProviderBoundaryError("provider_cancellation_unavailable", "Stato di annullamento non disponibile.", 503) from None
        if result:
            raise ProviderBoundaryError("provider_cancelled", "Richiesta annullata; nessuna risposta confermata.", 499)

    def _dispatch(self, config, payload, timeout_seconds):
        if not _finite(timeout_seconds) or not 0 < timeout_seconds <= 90:
            _bad_config()
        self._cancelled()
        try:
            _shape(payload, max_string=8_000_000)
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            raise ProviderBoundaryError("provider_payload_invalid", "Dati della richiesta non validi.", 422) from None
        if len(body) > config.max_request_bytes:
            raise ProviderBoundaryError("provider_payload_too_large", "Dati della richiesta oltre il limite configurato.", 413)
        effective_timeout = min(config.timeout_seconds, timeout_seconds)
        request = TransportRequest(config.endpoint, body, effective_timeout, config.max_response_bytes)
        started = self._clock()
        if not _finite(started):
            _bad_config()
        self._cancelled()
        try:
            response = self._transport.send(request, cancellation=self._cancellation)
        except TimeoutError:
            self._cancelled()
            raise ProviderBoundaryError("provider_timeout", "Il trasporto non ha risposto nel tempo consentito.", 504) from None
        except Exception:
            self._cancelled()
            raise ProviderBoundaryError("provider_transport_failed", "Il trasporto non ha completato l’unico tentativo previsto.", 503) from None
        self._cancelled()
        finished = self._clock()
        if not _finite(finished) or finished < started:
            _bad_config()
        if finished - started >= effective_timeout:
            raise ProviderBoundaryError("provider_timeout", "La risposta è arrivata oltre il tempo consentito.", 504)
        if (not isinstance(response, TransportResponse) or type(response.status_code) is not int
                or type(response.truncated) is not bool or not isinstance(response.body, bytes)):
            raise ProviderBoundaryError("provider_response_invalid", "Risposta del trasporto non valida.")
        if response.status_code != 200:
            raise ProviderBoundaryError("provider_rejected", "Il provider non ha restituito una risposta utilizzabile.")
        if response.truncated:
            raise ProviderBoundaryError("provider_response_truncated", "La risposta è incompleta e non viene confermata.")
        if len(response.body) > config.max_response_bytes:
            raise ProviderBoundaryError("provider_response_too_large", "La risposta supera il limite configurato.")
        if not isinstance(response.content_type, str) or response.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise ProviderBoundaryError("provider_response_invalid", "Formato della risposta non supportato.")
        try:
            parsed = json.loads(response.body.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_pairs)
            _shape(parsed)
            _keys(parsed, {"schema", "model", "locale", "output"})
            if parsed["schema"] != config.response_schema or parsed["model"] != config.model_id or parsed["locale"] != config.locale:
                raise ValueError("schema")
            return parsed["output"]
        except (ValueError, TypeError, RecursionError, UnicodeError, OverflowError):
            raise ProviderBoundaryError("provider_response_invalid", "La risposta non rispetta il contratto configurato.") from None

    def analyze_frame(self, *, image_bytes, mime_type, context, timestamp_seconds, spoken_claims, sources, timeout_seconds):
        try:
            if (not isinstance(image_bytes, bytes) or not 0 < len(image_bytes) <= 2_000_000 or mime_type != "image/jpeg"
                    or not isinstance(context, str) or len(context) > 8000 or not _finite(timestamp_seconds)
                    or not 0 <= timestamp_seconds <= 3600 or not isinstance(spoken_claims, list) or len(spoken_claims) > 200):
                raise ValueError("payload")
            registry = _sources(sources)
            for claim in spoken_claims:
                _keys(claim, {"start_seconds", "end_seconds", "text", "basis"})
                if claim["basis"] != "spoken_claim":
                    raise ValueError("basis")
            _transcript({"language": None, "segments": [{key: item[key] for key in ("start_seconds", "end_seconds", "text")} for item in spoken_claims]}, 3600)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ProviderBoundaryError("provider_payload_invalid", "Evidenze visive o informazioni dichiarate non valide.", 422) from None
        payload = {"schema": "slps.video.vision.request.v1", "model": self.vision.model_id, "locale": self.vision.locale,
                   "input": {"image": {"media_type": mime_type, "encoding": "base64", "data": base64.b64encode(image_bytes).decode("ascii")},
                             "timestamp_seconds": timestamp_seconds, "context": context,
                             "spoken_claims": copy.deepcopy(spoken_claims), "sources": registry}}
        output = self._dispatch(self.vision, payload, timeout_seconds)
        try:
            return _validate_vision(output, {source["id"] for source in registry}, timestamp_seconds)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ProviderBoundaryError("provider_response_invalid", "La risposta visiva non rispetta il contratto della valutazione.") from None

    def transcribe_speech(self, *, audio_bytes, mime_type, duration_seconds, timeout_seconds):
        if (not isinstance(audio_bytes, bytes) or not 0 < len(audio_bytes) <= 2_500_000 or mime_type != "audio/wav"
                or not _finite(duration_seconds) or not 0 < duration_seconds <= 3600):
            raise ProviderBoundaryError("provider_payload_invalid", "Evidenza audio non valida.", 422)
        payload = {"schema": "slps.video.speech.request.v1", "model": self.speech.model_id, "locale": self.speech.locale,
                   "input": {"audio": {"media_type": mime_type, "encoding": "base64", "data": base64.b64encode(audio_bytes).decode("ascii")},
                             "duration_seconds": duration_seconds}}
        output = self._dispatch(self.speech, payload, timeout_seconds)
        try:
            _keys(output, {"language", "segments"})
            if not isinstance(output["segments"], list):
                raise ValueError("segments")
            mapped = []
            for item in output["segments"]:
                _keys(item, {"start", "end", "text"})
                mapped.append({"start_seconds": item["start"], "end_seconds": item["end"], "text": item["text"]})
            canonical = {"language": output["language"], "segments": mapped}
            _transcript(canonical, duration_seconds)
            return canonical
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ProviderBoundaryError("provider_response_invalid", "La risposta del parlato non rispetta il contratto della trascrizione.") from None
