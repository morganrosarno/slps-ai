"""Bounded orchestration of extracted video evidence with synthetic adapters.

There is deliberately no provider SDK, default adapter, retry or live dispatch.
An adapter must honour timeout_seconds; the orchestrator also checks its shared
wall-clock budget before and after every callback. It does not spawn workers.
"""
from dataclasses import dataclass
from datetime import datetime
import copy
import math
import time
from urllib.parse import urlsplit
from source_registry import BASE_KEYS, DETAIL_KEYS, public_source, validate_registry


class VideoAnalysisError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class SyntheticVideoAdapters:
    analyze_frame: object
    transcribe_speech: object = None


LIMITATION = "I fotogrammi analizzati sono campioni temporali: non è stato osservato ogni istante del video."


def _fail(message="Le evidenze o le risposte sintetiche del video non sono valide."):
    raise VideoAnalysisError("video_evidence_invalid", message)


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _text(value, maximum=4000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        _fail()
    return value


def _sources(registry):
    if not isinstance(registry, (list, tuple)) or len(registry) > 30:
        _fail()
    clean, seen = [], set()
    for item in registry:
        if not isinstance(item, dict):
            _fail()
        source = {key: _text(item.get(key), 2000) for key in ("id", "title", "url", "verified_at")}
        url = urlsplit(source["url"])
        if source["id"] in seen or url.scheme != "https" or not url.hostname or url.username or url.password:
            _fail()
        try:
            datetime.fromisoformat(source["verified_at"].replace("Z", "+00:00"))
        except ValueError:
            _fail()
        if any(key in item for key in DETAIL_KEYS | {"registry_version"}):
            try:
                # Validate the same provenance contract as the photo pipeline.
                # Excerpts are not sent through the video/report public boundary.
                entry = {key: item.get(key) for key in BASE_KEYS | DETAIL_KEYS}
                entry["excerpt"] = item.get("excerpt", "Provenance metadata only")
                normalized = validate_registry({"schema_version": 1,
                    "registry_version": item.get("registry_version"), "jurisdiction": "CH", "sources": [entry]})
                source = public_source(normalized[0])
            except (ValueError, TypeError):
                _fail()
        seen.add(source["id"])
        clean.append(source)
    return clean


def _transcript(value, duration):
    if not isinstance(value, dict) or not isinstance(value.get("segments"), list) or len(value["segments"]) > 200:
        _fail()
    language = value.get("language")
    if language not in {None, "it", "de", "fr", "en"}:
        _fail()
    segments, text_bytes, previous = [], 0, -1
    for item in value["segments"]:
        if not isinstance(item, dict):
            _fail()
        start, end = item.get("start_seconds"), item.get("end_seconds")
        if not _number(start) or not _number(end) or not 0 <= start <= end <= duration + .05 or start < previous:
            _fail()
        text = _text(item.get("text"), 4000)
        text_bytes += len(text.encode("utf-8"))
        if text_bytes > 32000:
            _fail()
        segments.append({"start_seconds": start, "end_seconds": end, "text": text, "basis": "spoken_claim"})
        previous = start
    text = " ".join(item["text"] for item in segments)
    # An inaudible result is an explicit uncertainty, not an audio failure or silence.
    available = bool(text and text.casefold() not in {"[inaudible]", "[unintelligible]", "[non comprensibile]"})
    return {"status": "available" if available else "unintelligible", "language": language,
            "segments": segments if available else [], "text": text if available else None,
            "basis": "spoken_claim", "ambient_sound_analysis_performed": False}


def _frame_response(value, known_sources, index, timestamp, asset_id):
    if not isinstance(value, dict):
        _fail()
    summary = _text(value.get("summary"), 8000, empty=True)
    findings, questions, limitations = value.get("findings"), value.get("questions"), value.get("limitations")
    if (not isinstance(findings, list) or len(findings) > 30 or not isinstance(questions, list)
            or len(questions) > 20 or not isinstance(limitations, list) or len(limitations) > 30):
        _fail()
    clean_findings, seen = [], set()
    for finding in findings:
        if not isinstance(finding, dict):
            _fail()
        fid = _text(finding.get("id"), 64)
        if fid in seen:
            _fail()
        seen.add(fid)
        clean = {key: _text(finding.get(key), 4000) for key in ("title", "evidence", "action", "deadline")}
        for key in ("exposed_people", "question"):
            clean[key] = _text(finding.get(key, ""), 4000, empty=True)
        certainty, risk = finding.get("certainty"), finding.get("risk")
        if certainty not in {"visible", "reported", "verify"} or risk not in {"high", "medium", "low", "undetermined"} or type(finding.get("critical_unknown")) is not bool:
            _fail()
        if finding["critical_unknown"] and not clean["question"].strip():
            _fail()
        box = finding.get("bbox")
        if box is not None:
            if (not isinstance(box, dict) or set(box) != {"x", "y", "width", "height"}
                    or not all(_number(v) for v in box.values()) or not 0 <= box["x"] < 1
                    or not 0 <= box["y"] < 1 or not 0 < box["width"] <= 1 or not 0 < box["height"] <= 1
                    or box["x"] + box["width"] > 1.000001 or box["y"] + box["height"] > 1.000001):
                _fail()
        refs = finding.get("references")
        if not isinstance(refs, list) or len(refs) > 30:
            _fail()
        if any(not isinstance(ref, dict) or ref.get("source_id") not in known_sources for ref in refs):
            # The orchestrator never accepts a provider-created normative URL/ID.
            _fail("La risposta contiene una fonte non presente nel registro fornito.")
        clean.update(id=f"frame-{index}:{fid}", certainty=certainty, risk=risk,
                     critical_unknown=finding["critical_unknown"], bbox=copy.deepcopy(box),
                     references=[{"source_id": ref["source_id"]} for ref in refs],
                     video_evidence={"timestamp_seconds": timestamp, "asset_id": asset_id,
                                     "basis": "sampled_frame" if certainty == "visible" else certainty})
        clean_findings.append(clean)
    clean_questions, seen = [], set()
    for question in questions:
        if not isinstance(question, dict) or type(question.get("critical")) is not bool:
            _fail()
        qid = _text(question.get("id"), 64)
        if qid in seen:
            _fail()
        seen.add(qid)
        clean_questions.append({"id": f"frame-{index}:{qid}", "text": _text(question.get("text")),
                                "why": _text(question.get("why")), "critical": question["critical"],
                                "timestamp_seconds": timestamp})
    return summary, clean_findings, clean_questions, [_text(item) for item in limitations]


def analyze_extracted_video(evidence, *, adapters, reserve_request, context="", source_registry=(), max_seconds=30, max_elapsed_seconds=90):
    """Analyze private extracted artifacts, counting every subrequest before it.

    reserve_request is a mandatory callback to the application's atomic durable
    counter. False/exception prevents dispatch. Counted failed/uncertain calls
    are never refunded; a trial is intentionally managed by the caller only.
    """
    if not isinstance(adapters, SyntheticVideoAdapters) or not callable(adapters.analyze_frame) or not callable(reserve_request):
        raise VideoAnalysisError("video_adapter_unavailable", "Gli adattatori sintetici video non sono configurati.", 503)
    _text(context, 8000, empty=True)
    if not isinstance(evidence, dict):
        _fail()
    duration, frames, audio = evidence.get("duration_seconds"), evidence.get("frames"), evidence.get("audio")
    if not _number(duration) or not _number(max_seconds) or not 0 < duration <= max_seconds + .05 or not 0 < max_seconds <= 3600:
        _fail()
    if not _number(max_elapsed_seconds) or not 0 < max_elapsed_seconds <= 90:
        _fail()
    if not isinstance(frames, list) or not 1 <= len(frames) <= 10 or not isinstance(audio, dict):
        _fail()
    if audio.get("status") not in {"absent", "silent", "low_level", "ready_for_transcription"}:
        raise VideoAnalysisError("video_audio_unavailable", "La traccia audio non è verificata: nessuna analisi complessiva confermata.", 422)
    last, frame_evidence = -1, []
    for frame in frames:
        if not isinstance(frame, dict):
            _fail()
        stamp, raw = frame.get("timestamp_seconds"), frame.get("data")
        if (not _number(stamp) or not last < stamp <= duration or stamp < 0
                or not isinstance(raw, bytes) or not 0 < len(raw) <= 2_000_000 or frame.get("media_type") != "image/jpeg"):
            _fail()
        asset_id = _text(frame.get("asset_id"), 64)
        frame_evidence.append({"timestamp_seconds": stamp, "asset_id": asset_id})
        last = stamp
    if audio["status"] == "absent" and audio.get("data") is not None:
        _fail("Lo stato audio assente contraddice le evidenze disponibili.")
    speech_needed = audio["status"] in {"low_level", "ready_for_transcription"}
    if speech_needed and (not callable(adapters.transcribe_speech) or not isinstance(audio.get("data"), bytes)
                          or not 0 < len(audio["data"]) <= 2_500_000 or audio.get("media_type") != "audio/wav"):
        raise VideoAnalysisError("video_adapter_unavailable", "La trascrizione sintetica richiesta non è disponibile.", 503)
    registry = _sources(source_registry)
    source_ids = {source["id"] for source in registry}
    deadline, dispatches = time.monotonic() + max_elapsed_seconds, []

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise VideoAnalysisError("video_analysis_timeout", "L’analisi sintetica ha superato il tempo consentito.", 504)
        return value

    def dispatch(kind, callback, **kwargs):
        timeout = remaining()
        try:
            permitted = reserve_request()
        except Exception:
            raise VideoAnalysisError("provider_accounting_unavailable", "Il conteggio delle richieste non è disponibile. Nessuna nuova richiesta inviata.", 503) from None
        if permitted is not True:
            raise VideoAnalysisError("provider_request_cap_reached", "Limite totale delle richieste raggiunto. Nessuna nuova richiesta inviata.", 503)
        remaining()
        dispatches.append({"kind": kind, "timestamp_seconds": kwargs.get("timestamp_seconds")})
        try:
            result = callback(timeout_seconds=min(timeout, remaining()), **kwargs)
        except VideoAnalysisError:
            raise
        except Exception:
            raise VideoAnalysisError("video_adapter_failed", "Un adattatore sintetico non ha completato l’elaborazione. Nessuna analisi complessiva confermata.", 502) from None
        remaining()
        return result

    if speech_needed:
        transcript = _transcript(dispatch("speech", adapters.transcribe_speech,
                                         audio_bytes=audio["data"], mime_type=audio["media_type"], duration_seconds=duration), duration)
    else:
        transcript = {"status": "not_applicable", "reason": audio["status"], "segments": [],
                      "text": None, "language": None, "basis": "spoken_claim",
                      "ambient_sound_analysis_performed": False}
    findings, questions, limitations, summaries = [], [], [LIMITATION], []
    for index, frame in enumerate(frames, start=1):
        response = dispatch("frame", adapters.analyze_frame, image_bytes=frame["data"],
                            mime_type=frame["media_type"], context=context,
                            timestamp_seconds=frame["timestamp_seconds"],
                            spoken_claims=copy.deepcopy(transcript["segments"]), sources=copy.deepcopy(registry))
        summary, frame_findings, frame_questions, frame_limits = _frame_response(
            response, source_ids, index, frame["timestamp_seconds"], frame["asset_id"])
        findings.extend(frame_findings); questions.extend(frame_questions); limitations.extend(frame_limits)
        summaries.append({"timestamp_seconds": frame["timestamp_seconds"], "summary": summary})
        if len(findings) > 100 or len(questions) > 100:
            raise VideoAnalysisError("video_response_limit", "Il risultato supera i limiti del rapporto sintetico.", 422)
    if transcript["status"] == "unintelligible":
        questions.append({"id": "audio-unintelligible", "text": "Quali informazioni vengono pronunciate nell’audio?",
                          "why": "Il parlato non è stato compreso e potrebbe cambiare la valutazione.", "critical": True})
        limitations.append("La traccia contiene audio, ma il parlato non è stato compreso.")
    limitations.append("Il parlato è informazione dichiarata, non prova visiva; i rumori ambientali e i livelli acustici non sono stati analizzati.")
    if not registry:
        limitations.append("Nessuna fonte normativa verificata è stata fornita a questa elaborazione sintetica.")
    return {
        "summary": f"Analisi sintetica di {len(frames)} fotogrammi campionati; risultato di prova, non analisi AI reale.",
        "findings": findings, "questions": questions, "limitations": list(dict.fromkeys(limitations)),
        "sources": registry,
        "needs_clarification": not findings or any(f["critical_unknown"] or f["risk"] == "undetermined" for f in findings) or any(q["critical"] for q in questions),
        "meta": {"case_kind": "video_synthetic_analysis", "execution_mode": "synthetic_adapters",
                 "real_ai_analysis_performed": False, "transcription": transcript,
                 "coverage": {"duration_seconds": duration, "sampling_method": "archived_timestamp_samples",
                              "frame_count": len(frames), "frames": frame_evidence, "continuous_video_observed": False,
                              "audio_status": audio["status"], "ambient_sound_analysis_performed": False},
                 "frame_summaries": summaries, "subrequests_counted": len(dispatches), "subrequests": dispatches},
    }
