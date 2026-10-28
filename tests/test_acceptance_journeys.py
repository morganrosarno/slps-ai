"""Integrated local customer journeys; AI responses and operator checks are synthetic.

Routes, sessions, SQLite migrations, media processing and file storage are real.
These checks are deliberately separate from real-provider and browser acceptance.
"""
import io
from pathlib import Path
import shutil
import sqlite3
import subprocess

from PIL import Image
import pytest

import server
import slps_ai
from account_delivery_runtime import synthetic_registration_capability


PASSWORD = "synthetic-acceptance-password-only"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    calls = []
    outcome = {"fail": False}

    def synthetic_analysis(image, mime, context):
        calls.append({"mime": mime, "context": context})
        if outcome["fail"]:
            raise server.AnalysisError("provider_unavailable", "Synthetic outage", 503)
        return {
            "summary": "Synthetic acceptance report; no safety assessment performed",
            "findings": [], "questions": [],
            "limitations": ["Deterministic test response, not AI analysis"],
        }

    def forbidden_provider(*_args, **_kwargs):
        pytest.fail("Local acceptance must never instantiate the real AI client")

    monkeypatch.setattr(slps_ai, "OpenAI", forbidden_provider)
    monkeypatch.setattr(server, "is_analysis_configured", lambda: True)
    monkeypatch.setattr(server, "analizza_immagine", synthetic_analysis)
    config = {
        "TESTING": True, "DATA_MODE": "synthetic", "AUTH_MODE": "accounts",
        "ACCOUNT_REGISTRATION_OPEN": True, "BILLING_SANDBOX_ENABLED": True,
        "ACCOUNT_REGISTRATION_TEST_CAPABILITY": synthetic_registration_capability(),
        "SECRET_KEY": "synthetic-acceptance-session-secret-over-32-characters",
        "SESSION_COOKIE_SECURE": False,
        "ACCOUNT_DB_PATH": str(tmp_path / "accounts.sqlite3"),
        "CASE_DB_PATH": str(tmp_path / "cases.sqlite3"),
        "RATE_DB_PATH": str(tmp_path / "limits.sqlite3"),
        "HISTORY_ROOT": str(tmp_path / "media"),
        "ANALYSES_PER_HOUR": 10,
    }
    return server.create_app(config), config, calls, outcome


def headers(client, **extra):
    return {"X-CSRF-Token": client.get("/api/session").json["csrf"], **extra}


def post(client, path, payload, **extra):
    return client.post(path, json=payload, headers=headers(client, **extra))


def login(client, email):
    response = post(client, "/api/login", {"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.json


def register_and_verify(app, client, email="journey@example.test", company="Synthetic A"):
    """Exercise registration/email HTTP routes; operator company check is explicit."""
    response = post(client, "/api/accounts/register", {
        "email": email, "password": PASSWORD, "company_name": company,
        "company_identifier": "", "role": "Representative", "locale": "it",
    })
    assert response.status_code == 202
    assert response.json["delivery_configured"] is False
    pending = login(client, email)
    assert pending["verification_required"] and not pending["configured"]
    assert client.get("/app/").location == "/account"
    assert upload_photo(client).status_code == 403
    store = app.extensions["account_store"]
    user_id = pending["account"]["id"]
    # The fixture stands in for delivery; no token is exposed by a public route.
    token = store.issue_token(user_id, "email")
    assert post(client, "/api/accounts/verify-email", {"token": token}).status_code == 200
    assert upload_photo(client).status_code == 403  # email alone is insufficient
    user = store.get_user(user_id)
    store.verify_company(user["company_id"], user_id)  # trusted synthetic operator
    assert client.get("/api/session").json["account"]["eligible_for_analysis"]
    assert client.get("/app/").status_code == 200
    return store.get_user(user_id)


def photo(color="blue"):
    data = io.BytesIO()
    Image.new("RGB", (48, 32), color).save(data, "PNG")
    return data.getvalue()


def upload_photo(client, *, color="blue", **fields):
    return client.post("/analizza", data={
        "file": (io.BytesIO(photo(color)), "synthetic.png", "image/png"),
        "context": "Synthetic fixture only", **fields,
    }, headers=headers(client))


def case(client, case_id):
    response = client.get(f"/api/cases/{case_id}", headers=headers(client))
    assert response.status_code == 200
    return response.json["case"]


def test_photo_trial_to_history_survives_reopen_and_cannot_be_reused(environment):
    app, config, calls, outcome = environment
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/register").status_code == 200
    user = register_and_verify(app, client)
    assert calls == []

    outcome["fail"] = True
    assert upload_photo(client).status_code == 503
    assert client.get("/api/session").json["entitlement"]["analyses_remaining"] == 1
    assert client.get("/api/cases", headers=headers(client)).json["cases"] == []
    outcome["fail"] = False
    initial = upload_photo(client)
    assert initial.status_code == 200 and initial.json["archive"]["saved"]
    case_id = initial.json["archive"]["case_id"]
    entitlement = initial.json["entitlement"]
    assert entitlement["analyses_remaining"] == 0 and not entitlement["export_allowed"]
    assert upload_photo(client, color="red").status_code == 402
    assert len(calls) == 2  # failed provider attempt plus the successful one

    # A different photograph cannot be smuggled through the included clarification.
    rejected = upload_photo(client, color="red", request_kind="clarification", case_id=case_id)
    assert rejected.status_code == 400
    assert rejected.json["error"]["code"] == "clarification_image_mismatch"
    assert len(calls) == 2
    clarified = upload_photo(client, request_kind="clarification", case_id=case_id,
                             context="Synthetic additional context")
    assert clarified.status_code == 200
    assert clarified.json["entitlement"]["clarifications_remaining"] == 0
    assert calls[-1]["context"] == "Synthetic additional context"
    assert upload_photo(client, request_kind="clarification", case_id=case_id).status_code == 402
    assert len(calls) == 3

    # Reconstruct all adapters against the same files: counters and media must persist.
    reopened = server.create_app(config)
    returning = reopened.test_client()
    assert login(returning, user["email"])["entitlement"]["analyses_remaining"] == 0
    saved = case(returning, case_id)
    original = next(asset for asset in saved["assets"] if asset["role"] == "original")
    assert returning.get(original["download_url"]).data == photo()
    assert app.test_client().get(original["download_url"]).status_code == 401
    outsider = reopened.test_client()
    register_and_verify(reopened, outsider, "outsider@example.test", "Synthetic B")
    assert outsider.get(f"/api/cases/{case_id}", headers=headers(outsider)).status_code == 404
    assert outsider.get(original["download_url"]).status_code == 404

    member = reopened.extensions["account_store"].add_member(
        user["company_id"], email="colleague@example.test", password=PASSWORD,
        role="Employee", approved=True,
    )
    store = reopened.extensions["account_store"]
    store.consume_token(store.issue_token(member["id"], "email"), "email")
    colleague = reopened.test_client()
    assert login(colleague, member["email"])["entitlement"]["analyses_remaining"] == 0
    assert upload_photo(colleague).status_code == 402
    assert len(calls) == 3
    assert returning.delete(f"/api/cases/{case_id}", headers=headers(returning)).json == {"deleted": True}
    assert returning.get(original["download_url"]).status_code == 404
    assert upload_photo(returning).status_code == 402  # deletion never restores a trial
    assert len(calls) == 3


def test_video_audio_intake_archive_and_delete_do_not_spend_photo_trial(environment, tmp_path):
    app, config, calls, _outcome = environment
    client = app.test_client()
    user = register_and_verify(app, client)
    clip = tmp_path / "synthetic-with-audio.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=160x90:d=0.8", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=0.8", "-shortest", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
    ], check=True, timeout=15)
    raw = clip.read_bytes()
    response = client.post("/api/media/inspect", data={
        "file": (io.BytesIO(raw), "synthetic.mp4", "video/mp4"),
        "context": "Synthetic colour and tone; no workplace material",
    }, headers=headers(client))
    assert response.status_code == 200
    body = response.json
    assert body["analysis_available"] is False and body["trial_consumed"] is False
    assert body["media"]["validated"]
    assert body["media"]["audio"]["status"] == "ready_for_transcription"
    assert body["media"]["transcription"]["status"] == "not_performed"
    assert body["media"]["frames"] and calls == []
    case_id = body["archive"]["case_id"]
    returning = server.create_app(config).test_client()
    assert login(returning, user["email"])["entitlement"]["analyses_remaining"] == 1
    saved = case(returning, case_id)
    assets = saved["assets"]
    assert {"original", "frame", "audio"}.issubset({asset["role"] for asset in assets})
    for asset in assets:
        result = returning.get(asset["download_url"])
        assert result.status_code == 200
        if asset["role"] == "original":
            assert result.data == raw
        elif asset["role"] == "audio":
            assert result.data.startswith(b"RIFF")
    assert returning.delete(f"/api/cases/{case_id}", headers=headers(returning)).status_code == 200
    assert all(returning.get(asset["download_url"]).status_code == 404 for asset in assets)
    assert returning.get("/api/session").json["entitlement"]["analyses_remaining"] == 1
    assert calls == []


def test_exhausted_trial_consultation_and_checkout_remain_separate_after_reopen(environment):
    app, config, calls, _outcome = environment
    client = app.test_client()
    user = register_and_verify(app, client)
    case_id = upload_photo(client).json["archive"]["case_id"]
    app.extensions["account_store"].assign_consultation_policy(
        user["company_id"], included=1, period_months=12,
    )  # explicit fixture policy; no commercial package is being approved
    consultation = post(client, "/api/consultations", {"case_id": case_id, "channel": "phone"},
                        **{"Idempotency-Key": "acceptance-consultation-001"})
    assert consultation.status_code == 201
    assert consultation.json["recorded"] and not consultation.json["contacted"]
    assert consultation.json["charged"] is False
    request_id = consultation.json["consultation"]["request_id"]
    checkout = post(client, "/api/sandbox/billing/checkout-simulations", {
        "plan_code": "tier_team_v1", "billing_cycle": "annual",
    }, **{"Idempotency-Key": "acceptance-checkout-001"})
    assert checkout.status_code == 201
    checkout_id = checkout.json["checkout"]["checkout_id"]
    confirmed = post(client, f"/api/sandbox/billing/checkout-simulations/{checkout_id}/confirm", {})
    assert confirmed.status_code == 200
    assert confirmed.json["checkout"]["status"] == "confirmed_simulation"
    assert not confirmed.json["checkout"]["charged"]
    assert not confirmed.json["checkout"]["subscription_active"]

    returning = server.create_app(config).test_client()
    login(returning, user["email"])
    assert returning.get("/api/consultations").json["consultation"]["balance"] == 0
    replay = post(returning, "/api/consultations", {"case_id": case_id, "channel": "phone"},
                  **{"Idempotency-Key": "acceptance-consultation-001"})
    assert replay.status_code == 200 and replay.json["consultation"]["request_id"] == request_id
    saved = returning.get(f"/api/sandbox/billing/checkout-simulations/{checkout_id}").json["checkout"]
    assert saved["status"] == "confirmed_simulation" and saved["subscription_active"] is False
    assert saved["selection"]["price"]["amount_chf"] is None
    cancelled = post(returning, f"/api/consultations/{request_id}/cancel", {})
    assert cancelled.status_code == 200 and cancelled.json["credited"] is False
    assert cancelled.json["consultation"]["balance"] == 0
    assert upload_photo(returning).status_code == 402
    assert len(calls) == 1


def test_quiescent_synthetic_backup_restore_preserves_case_media_and_company_trial(environment, tmp_path):
    """Offline rehearsal only: no requests/writes run during the snapshot.

    SQLite's backup API is used, not a copy of a possibly live database file.
    Production still needs its destination-specific backup/restore validation.
    """
    app, config, calls, _outcome = environment
    client = app.test_client()
    user = register_and_verify(app, client)
    case_id = upload_photo(client).json["archive"]["case_id"]
    app.extensions["account_store"].assign_consultation_policy(
        user["company_id"], included=1, period_months=12,
    )
    assert post(client, "/api/consultations", {"case_id": case_id, "channel": "phone"},
                **{"Idempotency-Key": "snapshot-consultation-001"}).status_code == 201

    snapshot = tmp_path / "offline-backup"
    snapshot.mkdir()
    for key in ("ACCOUNT_DB_PATH", "CASE_DB_PATH", "RATE_DB_PATH"):
        with sqlite3.connect(config[key]) as source, sqlite3.connect(snapshot / key) as target:
            source.backup(target)
    shutil.copytree(config["HISTORY_ROOT"], snapshot / "media")

    # Prove recovery comes from the snapshot rather than the old running store.
    assert client.delete(f"/api/cases/{case_id}", headers=headers(client)).status_code == 200
    restore_root = tmp_path / "restored"
    restore_root.mkdir()
    restored_config = dict(config)
    for key in ("ACCOUNT_DB_PATH", "CASE_DB_PATH", "RATE_DB_PATH"):
        restored_config[key] = str(restore_root / Path(config[key]).name)
        with sqlite3.connect(snapshot / key) as source, sqlite3.connect(restored_config[key]) as target:
            source.backup(target)
    restored_config["HISTORY_ROOT"] = str(restore_root / "media")
    shutil.copytree(snapshot / "media", restored_config["HISTORY_ROOT"])

    restored_app = server.create_app(restored_config)
    recovered = restored_app.test_client()
    assert login(recovered, user["email"])["entitlement"]["analyses_remaining"] == 0
    original = next(asset for asset in case(recovered, case_id)["assets"] if asset["role"] == "original")
    assert recovered.get(original["download_url"]).data == photo()
    ledger = recovered.get("/api/consultations").json["consultation"]
    assert ledger["reserved"] == 1 and ledger["balance"] == 0
    assert upload_photo(recovered).status_code == 402
    assert len(calls) == 1
    assert restored_app.extensions["limit_store"].provider_request_count() == 1
