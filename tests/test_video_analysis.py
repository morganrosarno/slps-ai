import copy
import io
import sqlite3

from PIL import Image
import pytest

import server
from video_analysis import SyntheticVideoAdapters, VideoAnalysisError, analyze_extracted_video


SOURCE = {"id": "S1", "title": "Synthetic verified source", "url": "https://www.suva.ch/example",
          "verified_at": "2026-10-26T00:00:00Z"}
PASSWORD = "synthetic-video-account-password"


def frame_result(**_kwargs):
    return {"summary": "Synthetic frame observation", "findings": [{
        "id": "f1", "title": "A synthetic hazard", "evidence": "Observed in this sampled frame",
        "certainty": "visible", "risk": "medium", "exposed_people": "Worker",
        "action": "Apply the synthetic test measure", "deadline": "Before continuing",
        "question": "", "critical_unknown": False, "bbox": {"x": .1, "y": .2, "width": .3, "height": .4},
        "references": [{"source_id": "S1"}],
    }], "questions": [], "limitations": ["Synthetic test only"]}


def speech_result(**_kwargs):
    return {"language": "it", "segments": [{"start_seconds": .1, "end_seconds": .8,
                                           "text": "Il lavoratore dice che la macchina è ferma."}]}


def evidence(audio_status="ready_for_transcription"):
    return {"duration_seconds": 4.0,
            "frames": [{"timestamp_seconds": t, "asset_id": f"asset-{i}", "data": b"synthetic-jpeg", "media_type": "image/jpeg"}
                       for i, t in enumerate((1.0, 3.0))],
            "audio": {"status": audio_status, "data": None if audio_status == "absent" else b"synthetic-wav", "media_type": "audio/wav"}}


def test_preserves_timestamps_source_registry_and_spoken_claims_with_durable_subrequest_count(tmp_path):
    store = server.LimitStore(tmp_path / "limits.db")
    seen = []
    def analyze(**kwargs):
        seen.append(kwargs)
        return frame_result()
    result = analyze_extracted_video(evidence(), adapters=SyntheticVideoAdapters(analyze, speech_result),
        reserve_request=lambda: store.reserve_provider_request(3), source_registry=[SOURCE], context="Supplied test context")
    assert store.provider_request_count() == 3 == result["meta"]["subrequests_counted"]
    assert [f["video_evidence"]["timestamp_seconds"] for f in result["findings"]] == [1.0, 3.0]
    assert result["sources"] == [SOURCE] and result["findings"][0]["references"] == [{"source_id": "S1"}]
    assert len({f["id"] for f in result["findings"]}) == 2
    assert result["meta"]["coverage"]["continuous_video_observed"] is False
    assert not result["meta"]["real_ai_analysis_performed"]
    assert seen[0]["spoken_claims"][0]["basis"] == "spoken_claim"
    assert seen[0]["timestamp_seconds"] == 1.0 and 0 < seen[0]["timeout_seconds"] <= 90
    assert "campioni" in " ".join(result["limitations"])


@pytest.mark.parametrize("status", ["absent", "silent"])
def test_absent_or_silent_audio_skips_speech_without_inventing_transcript(status):
    calls = []
    def transcribe(**kwargs):
        pytest.fail("no speech request for absent/silent audio")
    result = analyze_extracted_video(evidence(status), adapters=SyntheticVideoAdapters(frame_result, transcribe),
                                    reserve_request=lambda: calls.append(True) or True, source_registry=[SOURCE])
    assert len(calls) == 2
    assert result["meta"]["transcription"]["reason"] == status
    assert result["meta"]["transcription"]["text"] is None


def test_unintelligible_audio_is_uncertainty_not_silence():
    result = analyze_extracted_video(evidence(), adapters=SyntheticVideoAdapters(frame_result, lambda **_: {"segments": [], "language": None}),
                                    reserve_request=lambda: True, source_registry=[SOURCE])
    assert result["needs_clarification"]
    assert result["meta"]["transcription"]["status"] == "unintelligible"
    assert any(q["id"] == "audio-unintelligible" for q in result["questions"])


@pytest.mark.parametrize("corrupt", ["timestamp", "source", "audio", "frame_count"])
def test_invalid_evidence_or_adapter_data_cannot_confirm_report(corrupt):
    sample = evidence(); analyze = frame_result
    if corrupt == "timestamp": sample["frames"][1]["timestamp_seconds"] = 8
    if corrupt == "audio": sample["audio"]["status"] = "error"
    if corrupt == "frame_count": sample["frames"] *= 6
    if corrupt == "source":
        def analyze(**kwargs):
            result = frame_result(); result["findings"][0]["references"] = [{"source_id": "invented"}]; return result
    with pytest.raises(VideoAnalysisError):
        analyze_extracted_video(sample, adapters=SyntheticVideoAdapters(analyze, speech_result), reserve_request=lambda: True, source_registry=[SOURCE])


def test_transcript_timestamps_are_validated():
    with pytest.raises(VideoAnalysisError):
        analyze_extracted_video(evidence(), adapters=SyntheticVideoAdapters(frame_result, lambda **_: {
            "segments": [{"start_seconds": 0, "end_seconds": 40, "text": "Invalid interval"}], "language": "it"}),
            reserve_request=lambda: True, source_registry=[SOURCE])


@pytest.fixture
def app(tmp_path, monkeypatch):
    # No configured AI service is required or called by the injected test flow.
    monkeypatch.setattr(server, "is_analysis_configured", lambda: False)
    monkeypatch.setattr(server, "analizza_immagine", lambda *_: pytest.fail("live photo/provider adapter used"))
    app = server.create_app({"TESTING": True, "AUTH_MODE": "accounts", "DATA_MODE": "synthetic",
        "SECRET_KEY": "synthetic-video-session-secret-over-32-characters", "SESSION_COOKIE_SECURE": False,
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.db"), "RATE_DB_PATH": str(tmp_path / "limits.db"),
        "CASE_DB_PATH": str(tmp_path / "cases.db"), "HISTORY_ROOT": str(tmp_path / "history"),
        "PILOT_PLAN": "internal", "PROVIDER_REQUESTS_TOTAL": 20, "VIDEO_ANALYSIS_SYNTHETIC_ENABLED": True})
    app.extensions["video_analysis_adapters"] = SyntheticVideoAdapters(frame_result, speech_result)
    app.extensions["video_analysis_sources"] = [SOURCE]
    return app


def add_user(app, *, email="owner@example.test", name="Synthetic Company", identifier="CHE123456789"):
    store = app.extensions["account_store"]
    user = store.register(email=email, password=PASSWORD, company_name=name, company_identifier=identifier, role="Representative", locale="it")
    store.consume_token(store.issue_token(user["id"], "email"), "email")
    store.verify_company(user["company_id"], user["id"])
    return store.get_user(user["id"])


def login(app, email="owner@example.test"):
    client = app.test_client(); csrf = client.get("/api/session").json["csrf"]
    result = client.post("/api/login", json={"email": email, "password": PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert result.status_code == 200
    return client, result.json["csrf"]


def stored_inspection(app, user, audio_status="ready_for_transcription"):
    media = evidence(audio_status)
    jpeg = io.BytesIO(); Image.new("RGB", (32, 24), "blue").save(jpeg, "JPEG")
    assets = [{"role": "original", "filename": "synthetic.mp4", "media_type": "video/mp4", "data": b"synthetic-video-fixture"}]
    for index, frame in enumerate(media["frames"], start=1):
        assets.append({"role": "frame", "filename": f"frame-{index:02d}-{frame['timestamp_seconds']:.3f}s.jpg",
                       "media_type": "image/jpeg", "data": jpeg.getvalue()})
    if audio_status != "absent":
        assets.append({"role": "audio", "filename": "audio-extract.wav", "media_type": "audio/wav", "data": b"synthetic-audio-fixture"})
    case_id, error = app.extensions["case_store"].create(user["company_id"], user["id"], "Synthetic context", {
        "summary": "Technical verification", "findings": [], "meta": {"case_kind": "video_technical_verification",
        "video_inspection": {"validated": True, "duration_seconds": 4, "frames": [{"timestamp_seconds": 1.0}, {"timestamp_seconds": 3.0}],
                             "audio": {"status": audio_status}}}}, None, 100, assets=assets)
    assert not error
    return case_id


def run(client, csrf, case):
    return client.post(f"/api/media/cases/{case}/analyze", json={}, headers={"X-CSRF-Token": csrf})


def assert_released(app, user):
    limits = app.extensions["limit_store"]
    assert limits.trial_status("company:" + user["company_id"], 1) == (0, 1)
    with limits.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0


def test_backend_success_stores_report_and_consumes_one_shared_company_trial(app):
    owner = add_user(app); case = stored_inspection(app, owner)
    client, csrf = login(app)
    response = run(client, csrf, case)
    assert response.status_code == 200
    assert response.json["trial_consumed"] and response.json["real_ai_analysis"] is False
    assert response.json["execution_mode"] == "synthetic_adapters"
    report = app.extensions["case_store"].get(response.json["archive"]["case_id"], owner["company_id"], owner["id"])
    assert report["analysis"]["meta"]["source_case_id"] == case
    assert app.extensions["limit_store"].provider_request_count() == 3
    assert run(client, csrf, case).status_code == 402
    store = app.extensions["account_store"]
    member = store.add_member(owner["company_id"], email="member@example.test", password=PASSWORD, role="Employee", approved=True)
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    member_case = stored_inspection(app, member)
    member_client, member_csrf = login(app, member["email"])
    assert run(member_client, member_csrf, member_case).status_code == 402
    assert app.extensions["limit_store"].provider_request_count() == 3


@pytest.mark.parametrize("audio_status", ["absent", "silent"])
def test_backend_audio_not_applicable_consumes_only_frame_subrequests(app, audio_status):
    owner = add_user(app); case = stored_inspection(app, owner, audio_status)
    client, csrf = login(app); response = run(client, csrf, case)
    assert response.status_code == 200
    assert app.extensions["limit_store"].provider_request_count() == 2
    assert response.json["analysis"]["meta"]["transcription"]["reason"] == audio_status


def test_midway_cap_keeps_durable_attempts_releases_trial_and_all_leases(app):
    app.config["PROVIDER_REQUESTS_TOTAL"] = 2
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    response = run(client, csrf, case)
    assert response.status_code == 503 and response.json["error"]["code"] == "provider_request_cap_reached"
    assert app.extensions["limit_store"].provider_request_count() == 2
    assert server.LimitStore(app.config["RATE_DB_PATH"]).provider_request_count() == 2
    assert_released(app, owner)
    assert len(app.extensions["case_store"].list(owner["company_id"], owner["id"])) == 1
    app.config["PROVIDER_REQUESTS_TOTAL"] = 5
    assert run(client, csrf, case).status_code == 200
    assert app.extensions["limit_store"].provider_request_count() == 5


def test_failed_adapter_counts_attempt_without_consuming_trial_or_retrying(app):
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    def failed(**kwargs): raise RuntimeError("private internal adapter details")
    app.extensions["video_analysis_adapters"] = SyntheticVideoAdapters(failed, speech_result)
    response = run(client, csrf, case)
    assert response.status_code == 502 and response.json["error"]["code"] == "video_adapter_failed"
    assert "private internal" not in response.get_data(as_text=True)
    assert app.extensions["limit_store"].provider_request_count() == 2
    assert_released(app, owner)


@pytest.mark.parametrize("gate", ["flag", "testing", "data_mode", "adapters", "cap"])
def test_backend_has_no_live_or_default_adapter_path(app, gate):
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    if gate == "flag": app.config["VIDEO_ANALYSIS_SYNTHETIC_ENABLED"] = False
    if gate == "testing": app.config["TESTING"] = False
    if gate == "data_mode": app.config["DATA_MODE"] = "real"
    if gate == "adapters": app.extensions.pop("video_analysis_adapters")
    if gate == "cap": app.config["PROVIDER_REQUESTS_TOTAL"] = None
    assert run(client, csrf, case).status_code == 503
    assert app.extensions["limit_store"].provider_request_count() == 0
    assert_released(app, owner)


def test_backend_csrf_cross_company_and_tampered_evidence_stop_before_dispatch(app):
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    assert run(client, "wrong", case).status_code == 403
    other = add_user(app, email="other@example.test", name="Other Synthetic", identifier="CHE987654321")
    other_client, other_csrf = login(app, other["email"])
    assert run(other_client, other_csrf, case).status_code == 404
    saved = app.extensions["case_store"].get(case, owner["company_id"], owner["id"])
    frame = next(asset for asset in saved["assets"] if asset["role"] == "frame")
    private = app.extensions["case_store"].asset(case, frame["id"], owner["company_id"], owner["id"])
    private["path"].write_bytes(b"tampered")
    assert run(client, csrf, case).status_code == 422
    assert app.extensions["limit_store"].provider_request_count() == 0
    assert_released(app, owner)


def test_committed_success_survives_entitlement_refresh_failure(app, monkeypatch):
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    limits = app.extensions["limit_store"]
    real_trial_status = limits.trial_status
    def unavailable_after_commit(scope, limit):
        status = real_trial_status(scope, limit)
        if status[0] > 0:
            raise sqlite3.OperationalError("synthetic status refresh failure")
        return status
    monkeypatch.setattr(limits, "trial_status", unavailable_after_commit)
    response = run(client, csrf, case)
    assert response.status_code == 200
    payload = response.json
    assert payload["trial_consumed"] is True
    assert payload["archive"]["saved"] is True and payload["entitlement"] is None
    assert payload["entitlement_status"]["available"] is False
    assert "prova aziendale utilizzata" in payload["entitlement_status"]["message"]
    assert "nessuna nuova prova consumata" not in response.get_data(as_text=True)
    assert "error" not in payload
    assert real_trial_status("company:" + owner["company_id"], 1) == (1, 0)
    saved = client.get(f"/api/cases/{payload['archive']['case_id']}", headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200
    assert saved.json["case"]["analysis"]["meta"]["source_case_id"] == case
    assert limits.provider_request_count() == 3


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_trial_completion_acknowledgement_failure_reports_unknown_without_losing_saved_case(app, monkeypatch, cleanup_fails):
    owner = add_user(app); case = stored_inspection(app, owner); client, csrf = login(app)
    limits = app.extensions["limit_store"]
    real_complete_trial = limits.complete_trial
    def consumed_then_failed(scope, token):
        assert real_complete_trial(scope, token)
        raise sqlite3.OperationalError("synthetic failure after durable trial completion")
    monkeypatch.setattr(limits, "complete_trial", consumed_then_failed)
    if cleanup_fails:
        def cleanup_unavailable(*_args):
            raise sqlite3.OperationalError("synthetic lease cleanup unavailable")
        monkeypatch.setattr(limits, "release_analysis", cleanup_unavailable)
        monkeypatch.setattr(limits, "release_trial", cleanup_unavailable)
    response = run(client, csrf, case)
    assert response.status_code == 503
    payload = response.json
    assert payload["error"]["code"] == "trial_completion_unknown"
    assert payload["trial_consumed"] is None and payload["archive"]["saved"] is True
    assert "esito quota da verificare" in payload["error"]["message"]
    assert "nessuna nuova prova consumata" not in response.get_data(as_text=True)
    assert limits.trial_status("company:" + owner["company_id"], 1) == (1, 0)
    saved = client.get(f"/api/cases/{payload['archive']['case_id']}", headers={"X-CSRF-Token": csrf})
    assert saved.status_code == 200
    assert saved.json["case"]["analysis"]["meta"]["source_case_id"] == case
    assert limits.provider_request_count() == 3


@pytest.mark.parametrize("closed_gate", ["testing", "data", "flag", "adapters", "cap_missing", "cap_zero", "cap_invalid"])
def test_customer_ui_capability_fails_closed_outside_safe_synthetic_setup(app, closed_gate):
    if closed_gate == "testing": app.config["TESTING"] = False
    elif closed_gate == "data": app.config["DATA_MODE"] = "customer"
    elif closed_gate == "flag": app.config["VIDEO_ANALYSIS_SYNTHETIC_ENABLED"] = False
    elif closed_gate == "adapters": app.extensions.pop("video_analysis_adapters")
    elif closed_gate == "cap_missing": app.config["PROVIDER_REQUESTS_TOTAL"] = None
    elif closed_gate == "cap_zero": app.config["PROVIDER_REQUESTS_TOTAL"] = 0
    elif closed_gate == "cap_invalid": app.config["PROVIDER_REQUESTS_TOTAL"] = True
    state = app.test_client().get("/api/session").json
    assert state["media"]["video_synthetic_analysis_enabled"] is False
    assert state["media"]["video_analysis_enabled"] is False
    assert app.extensions["limit_store"].provider_request_count() == 0


def test_customer_ui_capability_exposes_only_explicit_safe_test_adapter_not_real_ai(app):
    state = app.test_client().get("/api/session").json
    assert state["media"]["video_synthetic_analysis_enabled"] is True
    assert state["media"]["video_analysis_enabled"] is False
    assert state["analysis_configured"] is False
    assert app.extensions["limit_store"].provider_request_count() == 0
