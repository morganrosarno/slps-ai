import copy
from dataclasses import replace
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from provider_boundary import (CancellationToken, ProviderBoundaryError, ProviderConfig,
    RealVideoAdapterBoundary, SCHEMAS, TransportResponse)
from video_analysis import SyntheticVideoAdapters, VideoAnalysisError, analyze_extracted_video

FIXTURES = Path(__file__).parent / "fixtures/provider_boundary"


def config(task="vision", **overrides):
    args = dict(task=task, model_id=f"recorded-{task}-v1", endpoint=f"https://recorded.provider.example/v1/{task}",
        allowed_hosts=("recorded.provider.example",), locale="it", response_schema=SCHEMAS[task] if isinstance(task, str) and task in SCHEMAS else SCHEMAS["vision"],
        timeout_seconds=5, max_request_bytes=100000, max_response_bytes=10000)
    args.update(overrides)
    return ProviderConfig(**args)


def recorded(task):
    return TransportResponse(200, (FIXTURES / f"{task}.json").read_bytes())


class Transport:
    def __init__(self, response=None, action=None):
        self.response = response or recorded("vision")
        self.action = action
        self.calls = []
    def send(self, request, *, cancellation):
        self.calls.append(request)
        if self.action: self.action()
        return self.response


def boundary(transport=None, token=None, clock=None, **configs):
    return RealVideoAdapterBoundary(vision=configs.get("vision", config()), speech=configs.get("speech", config("speech")),
        transport=transport or Transport(), cancellation=token or CancellationToken(),
        **({"clock": clock} if clock else {}))


def vision_kwargs(**overrides):
    result = dict(image_bytes=b"recorded-sanitized-image", mime_type="image/jpeg", context="Synthetic context",
        timestamp_seconds=.5, spoken_claims=[], sources=[], timeout_seconds=5)
    result.update(overrides)
    return result


def audio_kwargs(**overrides):
    result = dict(audio_bytes=b"recorded-sanitized-audio", mime_type="audio/wav", duration_seconds=1, timeout_seconds=5)
    result.update(overrides)
    return result


def test_recorded_vision_mapping_preserves_timestamp_and_single_attempt_contract(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("network called"))
    transport = Transport(); adapter = boundary(transport)
    result = adapter.analyze_frame(**vision_kwargs())
    assert result == json.loads(recorded("vision").body)["output"]
    assert len(transport.calls) == 1
    request = transport.calls[0]; payload = json.loads(request.body)
    assert payload["model"] == "recorded-vision-v1" and payload["input"]["timestamp_seconds"] == .5
    assert request.attempts_allowed == 1 and not request.allow_redirects and request.verify_tls
    assert request.timeout_seconds == 5 and request.max_response_bytes == 10000
    assert "recorded-sanitized-image" not in repr(request)


def test_recorded_speech_mapping_compatible_with_orchestrator_invariants():
    transport = Transport(recorded("speech")); adapter = boundary(transport)
    result = adapter.transcribe_speech(**audio_kwargs())
    assert result == {"language": "it", "segments": [{"start_seconds": .1, "end_seconds": .8,
        "text": "Informazione pronunciata nel caso sintetico."}]}
    assert json.loads(transport.calls[0].body)["schema"] == "slps.video.speech.request.v1"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("locale", ["it", "de", "fr", "en"])
def test_supported_locale_is_explicit_without_fallback(locale):
    assert config(locale=locale).locale == locale


@pytest.mark.parametrize("overrides", [
    {"locale": "rm"}, {"response_schema": "unknown"}, {"model_id": ""}, {"timeout_seconds": float("nan")},
    {"timeout_seconds": float("inf")}, {"timeout_seconds": True}, {"max_response_bytes": 0},
    {"max_request_bytes": 9_000_000}, {"allowed_hosts": ()}, {"task": []},
])
def test_config_rejects_unsupported_or_unbounded_settings(overrides):
    with pytest.raises(ProviderBoundaryError) as error: config(**overrides)
    assert error.value.code == "provider_configuration_invalid"


@pytest.mark.parametrize("endpoint", [
    "http://recorded.provider.example/v1", "https://user:secret@recorded.provider.example/v1",
    "https://@recorded.provider.example/v1", "https://127.0.0.1/v1", "https://localhost/v1",
    "https://other.provider.example/v1", "https://recorded.provider.example/v1?credential=fixture",
    "https://recorded.provider.example/v1#fragment", "https://recorded.provider.example:8443/v1",
    "https://recorded.provider.example/../v1", "https://recorded.provider.example/%2e%2e/v1",
    "https://recorded.provider.example/v1\n", "https://recorded.provider.example./v1",
])
def test_endpoint_validation_never_dispatches(endpoint):
    with pytest.raises(ProviderBoundaryError): config(endpoint=endpoint)


@pytest.mark.parametrize("body", [b"{", b"\xff", b'{"schema":NaN}', b'{"schema":1,"schema":2}', b"["*30+b"0"+b"]"*30])
def test_malformed_truncated_nonfinite_duplicate_and_deep_json_are_rejected(body):
    transport = Transport(TransportResponse(200, body))
    with pytest.raises(ProviderBoundaryError) as error: boundary(transport).analyze_frame(**vision_kwargs())
    assert error.value.code == "provider_response_invalid" and len(transport.calls) == 1


@pytest.mark.parametrize("kind", ["truncated", "oversize", "content_type", "status"])
def test_transport_response_limits_and_failures_have_one_attempt(kind):
    if kind == "truncated": response = replace(recorded("vision"), truncated=True)
    if kind == "oversize": response = TransportResponse(200, b" " * 10001)
    if kind == "content_type": response = replace(recorded("vision"), content_type="text/html")
    if kind == "status": response = replace(recorded("vision"), status_code=429)
    transport = Transport(response)
    with pytest.raises(ProviderBoundaryError): boundary(transport).analyze_frame(**vision_kwargs())
    assert len(transport.calls) == 1


@pytest.mark.parametrize("mutator", [
    lambda value: value.update(schema="unknown"),
    lambda value: value.update(model="other-model"),
    lambda value: value.update(locale="xx"),
    lambda value: value["output"].update(extra="not permitted"),
    lambda value: value["output"]["findings"][0].update(bbox={"x": 0, "y": 0, "width": 2, "height": 1}),
    lambda value: value["output"]["findings"][0].update(references=[{"source_id": "invented"}]),
])
def test_schema_model_locale_and_vision_semantics_are_strict(mutator):
    value = json.loads(recorded("vision").body); mutator(value)
    transport = Transport(TransportResponse(200, json.dumps(value).encode()))
    with pytest.raises(ProviderBoundaryError) as error: boundary(transport).analyze_frame(**vision_kwargs())
    assert error.value.code == "provider_response_invalid" and len(transport.calls) == 1


@pytest.mark.parametrize("segments,language", [
    ([{"start": 0, "end": 4, "text": "outside duration"}], "it"),
    ([{"start": 0, "end": .5, "text": "ok", "extra": True}], "it"),
    ([{"start": 0, "end": .5, "text": "ok"}], "xx"),
])
def test_speech_timestamps_language_and_fields_are_strict(segments, language):
    value = json.loads(recorded("speech").body); value["output"] = {"language": language, "segments": segments}
    transport = Transport(TransportResponse(200, json.dumps(value).encode()))
    with pytest.raises(ProviderBoundaryError): boundary(transport).transcribe_speech(**audio_kwargs())
    assert len(transport.calls) == 1


def test_request_byte_cap_stops_before_dispatch_but_large_media_is_not_arbitrarily_truncated():
    transport = Transport(); adapter = boundary(transport, vision=config(max_request_bytes=1024))
    with pytest.raises(ProviderBoundaryError) as error: adapter.analyze_frame(**vision_kwargs(image_bytes=b"x"*2000))
    assert error.value.code == "provider_payload_too_large" and transport.calls == []
    full = Transport(); boundary(full).analyze_frame(**vision_kwargs(image_bytes=b"x"*40000))
    import base64
    assert len(base64.b64decode(json.loads(full.calls[0].body)["input"]["image"]["data"])) == 40000


@pytest.mark.parametrize("when", ["before", "after"])
def test_cancellation_before_and_after_dispatch_never_retries_or_returns_result(when):
    token = CancellationToken()
    if when == "before": token.cancel()
    transport = Transport(action=token.cancel if when == "after" else None)
    with pytest.raises(ProviderBoundaryError) as error: boundary(transport, token).analyze_frame(**vision_kwargs())
    assert error.value.code == "provider_cancelled" and len(transport.calls) == (0 if when == "before" else 1)


@pytest.mark.parametrize("kind", ["raised", "elapsed"])
def test_timeout_requires_no_fallback_or_second_attempt(kind):
    def timeout(): raise TimeoutError("SENSITIVE_DETAILS")
    transport = Transport(action=timeout if kind == "raised" else None)
    moments = iter((0, 6))
    adapter = boundary(transport, clock=(lambda: next(moments)) if kind == "elapsed" else None)
    with pytest.raises(ProviderBoundaryError) as error: adapter.analyze_frame(**vision_kwargs())
    assert error.value.code == "provider_timeout" and len(transport.calls) == 1
    assert "SENSITIVE_DETAILS" not in str(error.value)


def test_transport_exception_is_sanitized_and_no_fallback_exists():
    def failed(): raise RuntimeError("SENSITIVE_DETAILS")
    transport = Transport(action=failed)
    with pytest.raises(ProviderBoundaryError) as error: boundary(transport).analyze_frame(**vision_kwargs())
    assert error.value.code == "provider_transport_failed" and len(transport.calls) == 1
    assert "SENSITIVE_DETAILS" not in str(error.value) and error.value.__suppress_context__


def test_real_boundary_is_rejected_by_unchanged_synthetic_orchestrator_gate():
    transport = Transport(); adapter = boundary(transport)
    assert not isinstance(adapter, SyntheticVideoAdapters)
    with pytest.raises(VideoAnalysisError): analyze_extracted_video({}, adapters=adapter, reserve_request=lambda: pytest.fail("reservation happened"))
    assert transport.calls == []


def test_existing_customer_synthetic_route_never_accepts_real_boundary(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "is_analysis_configured", lambda: False)
    app = server.create_app({"TESTING": True, "DATA_MODE": "synthetic", "VIDEO_ANALYSIS_SYNTHETIC_ENABLED": True,
        "SECRET_KEY": "provider-gate-test-secret-at-least32characters", "PILOT_PASSWORD": "provider-gate-test-password",
        "SESSION_COOKIE_SECURE": False, "RATE_DB_PATH": str(tmp_path/"limits.db"), "CASE_DB_PATH": str(tmp_path/"cases.db"),
        "PROVIDER_REQUESTS_TOTAL": 3})
    transport = Transport(); app.extensions["video_analysis_adapters"] = boundary(transport)
    client = app.test_client(); csrf = client.get("/api/session").json["csrf"]
    csrf = client.post("/api/login", json={"password": "provider-gate-test-password"}, headers={"X-CSRF-Token": csrf}).json["csrf"]
    response = client.post("/api/media/cases/nonexistent/analyze", json={}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 503 and response.json["error"]["code"] == "video_synthetic_analysis_disabled"
    assert not transport.calls and app.extensions["limit_store"].provider_request_count() == 0


def test_zero_network_conformance_command():
    result = subprocess.run([sys.executable, "scripts/provider_conformance.py"], cwd=Path(__file__).parents[1],
        check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert output["offline_conformance"] == "passed" and output["network_attempts"] == 0
    assert output["single_attempts"] == 2 and output["real_provider_tested"] is False
