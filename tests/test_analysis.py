import base64
import hashlib
import io
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
import slps_ai

def sample():
    return {"summary": "Un passaggio richiede verifica.", "findings": [{
        "id": "F1", "title": "Libera il passaggio", "evidence": "Un cavo attraversa il passaggio.",
        "certainty": "visible", "risk": "medium", "exposed_people": "Persone che attraversano il passaggio.",
        "action": "Instrada il cavo fuori dal percorso.", "deadline": "Prima del prossimo passaggio",
        "question": "", "critical_unknown": False,
        "bbox": {"x": 0.1, "y": 0.6, "width": 0.6, "height": 0.2}, "references": []
    }], "questions": [], "limitations": []}

@pytest.fixture
def configured(monkeypatch, tmp_path):
    raw = ("METODO DI PROVA: fonte solo per test software.\n"
           "37. REGOLA FINALE\nNon inventare.\n"
           "APPENDICE — CHANGELOG DELLA REVISIONE 1.1\nCronologia da escludere.").encode()
    path = tmp_path / "master.txt"
    path.write_bytes(raw)
    monkeypatch.setattr(slps_ai, "MASTER_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("SLPS_PROMPT_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-no-network")
    monkeypatch.setenv("OPENAI_MODEL", "unit-test-model")
    monkeypatch.delenv("SLPS_SOURCES_PATH", raising=False)
    return path

def mock_client(data=None, **response_args):
    response = SimpleNamespace(status="completed", output=[], output_text=json.dumps(data or sample()), usage=SimpleNamespace(input_tokens=100, output_tokens=50))
    for key, value in response_args.items():
        setattr(response, key, value)
    client = Mock()
    client.responses.create.return_value = response
    return client

def test_actual_photo_and_context_transmitted_with_approved_method(configured):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(output, "PNG")
    raw = output.getvalue()
    client = mock_client()
    result = slps_ai.analizza_immagine(raw, "image/png", "Macchina ferma.", client=client)
    call = client.responses.create.call_args.kwargs
    parts = call["input"][0]["content"]
    assert "Macchina ferma." in parts[0]["text"]
    assert parts[1]["type"] == "input_image"
    assert base64.b64decode(parts[1]["image_url"].split(",", 1)[1]) == raw
    assert "37. REGOLA FINALE" in call["instructions"]
    assert "Cronologia da escludere." not in call["instructions"]
    assert call["store"] is False
    assert call["text"]["format"]["strict"] is True
    assert result["meta"]["method_version"] == "1.8"
    assert result["meta"]["image_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["sources"] == []
    assert "non ha fonti" in result["limitations"][-1]

@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_missing_configuration_no_provider_call(configured, monkeypatch, missing):
    monkeypatch.delenv(missing)
    client = mock_client()
    with pytest.raises(slps_ai.AnalysisError) as e:
        slps_ai.analizza_immagine(b"photo", "image/jpeg", client=client)
    assert e.value.status == 503
    client.responses.create.assert_not_called()

def test_modified_master_rejected_before_provider(configured):
    configured.write_text("Unapproved method")
    client = mock_client()
    with pytest.raises(slps_ai.AnalysisError, match="non corrisponde"):
        slps_ai.analizza_immagine(b"photo", "image/jpeg", client=client)
    client.responses.create.assert_not_called()

def test_missing_master_startup_and_failure_are_controlled(configured):
    configured.unlink()
    assert slps_ai.is_analysis_configured() is False
    with pytest.raises(slps_ai.AnalysisError) as e:
        slps_ai.load_master()
    assert e.value.code == "prompt_missing"

@pytest.mark.parametrize("result", [{"summary": "all safe"}, {"findings": []}, None, [], "safe"])
def test_invalid_provider_result_not_shown_as_assessment(result):
    with pytest.raises(slps_ai.AnalysisError):
        slps_ai.validate_analysis(result, [])

def test_unknown_citation_removed_and_limitation_added():
    data = sample()
    data["findings"][0]["references"] = [{"source_id": "invented-law"}]
    result = slps_ai.validate_analysis(data, [])
    assert result["findings"][0]["references"] == []
    assert any("esclusi" in x for x in result["limitations"])

def test_critical_unknown_never_marked_complete():
    data = sample()
    data["findings"][0].update(risk="low", critical_unknown=True, question="Il mezzo è in movimento?")
    result = slps_ai.validate_analysis(data, [])
    assert result["needs_clarification"] is True

def test_undetermined_risk_never_marked_complete():
    data = sample()
    data["findings"][0]["risk"] = "undetermined"
    assert slps_ai.validate_analysis(data, [])["needs_clarification"] is True

def test_invalid_crop_not_displayed():
    data = sample()
    data["findings"][0]["bbox"].update(x=0.8, width=0.5)
    assert slps_ai.validate_analysis(data, [])["findings"][0]["bbox"] is None

def test_blank_urgent_question_rejected():
    data = sample()
    data["findings"][0]["critical_unknown"] = True
    with pytest.raises(slps_ai.AnalysisError):
        slps_ai.validate_analysis(data, [])

def test_duplicate_observation_ids_rejected():
    data = sample()
    data["findings"].append(deepcopy(data["findings"][0]))
    with pytest.raises(slps_ai.AnalysisError):
        slps_ai.validate_analysis(data, [])

@pytest.mark.parametrize("kwargs,code", [
    ({"status": "incomplete"}, "incomplete_response"),
    ({"output_text": "<h1>safe</h1>"}, "invalid_response"),
    ({"output": [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]}, "refused"),
])
def test_incomplete_refused_or_nonjson_output(configured, kwargs, code):
    with pytest.raises(slps_ai.AnalysisError) as e:
        slps_ai.analizza_immagine(b"photo", "image/jpeg", client=mock_client(**kwargs))
    assert e.value.code == code

def test_quota_error_no_retry_no_provider_details(configured, monkeypatch):
    class FakeQuota(Exception):
        pass
    monkeypatch.setattr(slps_ai, "RateLimitError", FakeQuota)
    client = mock_client()
    client.responses.create.side_effect = FakeQuota("secret internal account detail")
    with pytest.raises(slps_ai.AnalysisError) as e:
        slps_ai.analizza_immagine(b"photo", "image/jpeg", client=client)
    assert e.value.code == "quota_exceeded" and e.value.status == 429
    assert "secret" not in str(e.value)
    assert client.responses.create.call_count == 1

def test_sources_from_owner_registry_only(configured, monkeypatch, tmp_path):
    sources = [{"id": "S1", "title": "Fonte di prova", "url": "https://www.suva.ch/it-ch", "verified_at": "2026-10-23", "excerpt": "Testo esclusivamente per verifica software."}]
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(sources))
    monkeypatch.setenv("SLPS_SOURCES_PATH", str(path))
    data = sample()
    data["findings"][0]["references"] = [{"source_id": "S1"}]
    result = slps_ai.analizza_immagine(b"photo", "image/jpeg", client=mock_client(data))
    assert result["findings"][0]["references"] == [{"source_id": "S1"}]
    assert "excerpt" not in result["sources"][0]
    assert result["meta"]["reference_mode"] == "owner_verified_registry"

