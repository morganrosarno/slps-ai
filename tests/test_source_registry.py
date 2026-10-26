import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import slps_ai
from scripts.preflight import source_registry
from source_registry import RegistryError, read_registry, validate_registry


def registry():
    return {"schema_version": 1, "registry_version": "test-1", "jurisdiction": "CH", "sources": [{
        "id": "SUVA-TEST", "title": "Synthetic source fixture", "url": "https://www.suva.ch/it-ch",
        "verified_at": "2026-10-26", "excerpt": "Software fixture, not legal evidence.",
        "classification": "recommendation", "source_kind": "technical_guidance", "publisher": "Suva",
        "locator": "Fixture section", "scope": "Synthetic tests only", "document_version": "fixture",
        "limitations": ["Not suitable for a real assessment"], "verification_scope": "fixture only",
    }]}


def test_versioned_metadata_survives_but_excerpt_is_server_only(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry()))
    monkeypatch.setenv("SLPS_SOURCES_PATH", str(path))
    sources = slps_ai.load_sources()
    assert source_registry(path) == (True, 1)
    assert sources[0]["registry_version"] == "test-1"
    response = slps_ai.validate_analysis({"summary": "Test", "findings": [], "questions": [], "limitations": []}, sources)
    assert response["sources"][0]["classification"] == "recommendation"
    assert response["sources"][0]["scope"] == "Synthetic tests only"
    assert "excerpt" not in response["sources"][0]


@pytest.mark.parametrize("field,value", [
    ("url", "https://suva.ch.attacker.invalid/"), ("url", "http://www.suva.ch/"),
    ("url", "https://secret@www.suva.ch/"), ("url", "https://www.suva.ch:8443/"),
    ("url", "https://www.suva.ch:bad/"), ("url", "https://www.suva.ch/a b"),
    ("classification", "law"), ("source_kind", "unknown"), ("locator", ""),
    ("scope", ""), ("document_version", ""), ("verification_scope", ""),
    ("limitations", []), ("limitations", [""]), ("verified_at", "not-a-date"),
    ("verified_at", (date.today() + timedelta(days=1)).isoformat()), ("id", "spaces are not ids"),
])
def test_invalid_versioned_sources_rejected(field, value):
    data = registry(); data["sources"][0][field] = value
    with pytest.raises(RegistryError):
        validate_registry(data)


def test_recommendation_cannot_silently_become_obligation():
    data = registry(); data["sources"][0]["classification"] = "obligation"
    with pytest.raises(RegistryError):
        validate_registry(data)


def test_hypothesis_requires_explicit_application_inference_kind():
    data = registry(); data["sources"][0]["classification"] = "hypothesis"
    with pytest.raises(RegistryError):
        validate_registry(data)
    data["sources"][0]["source_kind"] = "application_hypothesis"
    assert validate_registry(data)[0]["classification"] == "hypothesis"


def test_legacy_extra_classification_is_not_trusted():
    source = registry()["sources"][0]
    result = validate_registry([source])
    assert "classification" not in result[0]
    assert "registry_version" not in result[0]


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(schema_version=True), lambda d: d.update(schema_version=2),
    lambda d: d.update(jurisdiction="IT"), lambda d: d.update(unexpected="value"),
    lambda d: d["sources"].append(copy.deepcopy(d["sources"][0])),
    lambda d: d["sources"][0].update(unexpected="value"),
])
def test_invalid_envelope_duplicates_and_unknown_fields(mutation):
    data = registry(); mutation(data)
    with pytest.raises(RegistryError):
        validate_registry(data)


def test_parser_limits_and_non_utf8(tmp_path):
    path = tmp_path / "registry.json"
    for raw in (b"x" * 200001, b"\xff", b"null", b"[null]"):
        path.write_bytes(raw)
        with pytest.raises(RegistryError):
            read_registry(path)


def test_normalization_is_defensive():
    data = registry(); result = validate_registry(data)
    result[0]["limitations"].append("Changed")
    assert len(data["sources"][0]["limitations"]) == 1


def test_video_provenance_preserves_classification_and_rejects_partial_metadata():
    from video_analysis import _sources, VideoAnalysisError
    source = validate_registry(registry())[0]
    result = _sources([source])
    assert result[0]["classification"] == "recommendation"
    assert result[0]["registry_version"] == "test-1"
    assert "excerpt" not in result[0]
    del source["scope"]
    with pytest.raises(VideoAnalysisError):
        _sources([source])


def test_checked_in_registry_is_valid_and_scoped():
    path = Path(__file__).resolve().parents[1] / "data" / "sources.ch.v1.json"
    data = read_registry(path)
    assert len(data) >= 4
    assert all(item["scope"] and item["limitations"] and item["registry_version"] for item in data)
    assert {item["classification"] for item in data} >= {"obligation", "recommendation"}
