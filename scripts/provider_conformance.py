"""Zero-network conformance of sanitized synthetic recorded wire fixtures."""
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from provider_boundary import (CancellationToken, ProviderConfig, RealVideoAdapterBoundary,
                               SCHEMAS, TransportResponse)


def run():
    network_attempts = []
    def blocked(*_args, **_kwargs):
        network_attempts.append(True)
        raise RuntimeError("Network forbidden in offline conformance")
    class RecordedTransport:
        def __init__(self): self.requests = []
        def send(self, request, *, cancellation):
            self.requests.append(request)
            task = "vision" if request.endpoint.endswith("/vision") else "speech"
            return TransportResponse(200, (ROOT / "tests/fixtures/provider_boundary" / f"{task}.json").read_bytes())
    def config(task):
        return ProviderConfig(task=task, model_id=f"recorded-{task}-v1",
            endpoint=f"https://recorded.provider.example/v1/{task}", allowed_hosts=("recorded.provider.example",),
            locale="it", response_schema=SCHEMAS[task], timeout_seconds=5,
            max_request_bytes=100000, max_response_bytes=10000)
    transport, token = RecordedTransport(), CancellationToken()
    with patch.object(socket, "socket", blocked), patch.object(socket, "create_connection", blocked):
        adapter = RealVideoAdapterBoundary(vision=config("vision"), speech=config("speech"), transport=transport, cancellation=token)
        speech = adapter.transcribe_speech(audio_bytes=b"recorded-audio-fixture", mime_type="audio/wav", duration_seconds=1, timeout_seconds=5)
        frame = adapter.analyze_frame(image_bytes=b"recorded-image-fixture", mime_type="image/jpeg", context="Synthetic context",
            timestamp_seconds=.5, spoken_claims=[{**speech["segments"][0], "basis": "spoken_claim"}], sources=[], timeout_seconds=5)
    assert len(transport.requests) == 2 and not network_attempts
    assert frame["findings"][0]["id"] == "f1" and speech["segments"][0]["start_seconds"] == .1
    print(json.dumps({"offline_conformance": "passed", "fixture_kind": "synthetic_recorded_wire",
        "vision_mapping": "passed", "speech_mapping": "passed", "single_attempts": 2,
        "network_attempts": 0, "real_provider_tested": False}, sort_keys=True))


if __name__ == "__main__":
    run()
