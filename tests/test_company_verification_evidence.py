import hashlib
import io
import json
import os
import re
import sqlite3

import pytest

from accounts import AccountStore, VerificationReviewConflict
from scripts.company_verification_operator import main


SECRET_TEXT = "synthetic-operator-secret-32-bytes!"
SECRET = SECRET_TEXT.encode("ascii")
PASSWORD = "a-long-local-test-passphrase"
NOW = 1_800_000_000
EXPIRES = 2_000_000_000


def setup_company(tmp_path, *, suffix="one"):
    path = tmp_path / f"accounts-{suffix}.sqlite3"
    store = AccountStore(path, verification_operator_secret=SECRET)
    user = store.register(
        email=f"owner-{suffix}@example.test", password=PASSWORD,
        company_name=f"Synthetic Company {suffix}",
        company_identifier=f"CHE12345678{len(suffix)}", role="Representative", locale="it",
    )
    review = store.list_verification_reviews(authorization=SECRET)[0]
    return path, store, user, review


def record(store, review, category, *, token, expires=EXPIRES, content=None):
    content = content or f"synthetic:{category}:{token}".encode()
    return store.record_verification_evidence(
        review["id"], category=category,
        content_sha256=hashlib.sha256(content).hexdigest(),
        observed_at=1_700_000_000, verified_at=1_750_000_000,
        expires_at=expires, verifier_ref="operator-code",
        idempotency_key="verification:evidence:" + hashlib.sha256(token.encode()).hexdigest(),
        authorization=SECRET, now=NOW,
    )


def company_packet(store, review, *, prefix="p"):
    return [
        record(store, review, "commercial_register_extract", token=prefix + "r")["id"],
        record(store, review, "representative_authority_record", token=prefix + "a")["id"],
    ]


def decide(store, review, receipt_ids, *, key="d"):
    return store.decide_verification_review(
        review["id"], decision="approve",
        decision_code="identity_and_authority_confirmed",
        operator_ref="operator-code",
        idempotency_key="verification:decision:" + key * 40,
        evidence_receipt_ids=receipt_ids, authorization=SECRET, now=NOW,
    )


def pipe(value):
    read_fd, write_fd = os.pipe()
    os.write(write_fd, value)
    os.close(write_fd)
    return read_fd


def test_decision_requires_complete_verified_packet_and_leaves_flags_unchanged(tmp_path):
    _path, store, user, review = setup_company(tmp_path)
    register_only = record(
        store, review, "commercial_register_extract", token="missing-authority",
    )
    with pytest.raises(VerificationReviewConflict, match="evidence_incomplete"):
        decide(store, review, [register_only["id"]])
    with pytest.raises(ValueError, match="evidence_receipts"):
        decide(store, review, [])
    current = store.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_categories_are_scoped_to_review_kind(tmp_path):
    _path, store, _user, review = setup_company(tmp_path)
    with pytest.raises(ValueError, match="evidence_category"):
        record(store, review, "membership_authority_record", token="wrong-kind")


def test_verified_packet_is_bound_into_audit_without_raw_material(tmp_path):
    path, store, user, review = setup_company(tmp_path)
    raw_evidence = b"synthetic offline evidence bytes without personal data"
    first = record(
        store, review, "commercial_register_extract", token="bind-register",
        content=raw_evidence,
    )
    second = record(
        store, review, "representative_authority_record", token="bind-authority",
    )
    result = decide(store, review, [first["id"], second["id"]])
    assert result["status"] == "approved"
    audit = store.verification_review_audit(review["id"], authorization=SECRET)
    assert audit[-1]["evidence_bound"] is True
    assert store.get_user(user["id"])["company_verified"]
    database = path.read_bytes()
    assert raw_evidence not in database
    assert b"operator-code" not in database
    assert b"verification:evidence:" not in database


def test_expired_foreign_or_tampered_receipts_fail_closed(tmp_path):
    path, store, user, review = setup_company(tmp_path)
    expired = record(
        store, review, "commercial_register_extract", token="expired",
        expires=1_800_000_001,
    )
    authority = record(
        store, review, "representative_authority_record", token="authority",
    )
    with pytest.raises(VerificationReviewConflict, match="evidence_invalid"):
        store.decide_verification_review(
            review["id"], decision="approve",
            decision_code="identity_and_authority_confirmed",
            operator_ref="operator-code", idempotency_key="verification:decision:expired-0001",
            evidence_receipt_ids=[expired["id"], authority["id"]],
            authorization=SECRET, now=1_800_000_002,
        )

    other_user = store.add_member(
        user["company_id"], email="member@example.test", password=PASSWORD,
        role="Employee",
    )
    member_review = next(
        item for item in store.list_verification_reviews(authorization=SECRET)
        if item["subject_user_id"] == other_user["id"]
    )
    member_receipt = record(
        store, member_review, "membership_authority_record", token="foreign",
    )
    with pytest.raises(VerificationReviewConflict, match="evidence_invalid"):
        decide(store, review, [member_receipt["id"], authority["id"]])

    register = record(
        store, review, "commercial_register_extract", token="tampered",
    )
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            db.execute(
                "UPDATE account_verification_evidence_receipts SET content_sha256=? WHERE id=?",
                ("0" * 64, register["id"]),
            )
        db.execute("DROP TRIGGER account_verification_evidence_receipts_no_update")
        db.execute(
            "UPDATE account_verification_evidence_receipts SET content_sha256=? WHERE id=?",
            ("0" * 64, register["id"]),
        )
    with pytest.raises(VerificationReviewConflict, match="evidence_invalid"):
        decide(store, review, [register["id"], authority["id"]])


def test_receipt_idempotency_replays_exactly_and_rejects_changed_payload(tmp_path):
    _path, store, _user, review = setup_company(tmp_path)
    first = record(store, review, "commercial_register_extract", token="same")
    replay = record(store, review, "commercial_register_extract", token="same")
    assert first == replay
    with pytest.raises(VerificationReviewConflict, match="idempotency_conflict"):
        record(
            store, review, "commercial_register_extract", token="same",
            content=b"different synthetic content",
        )


def test_pending_dossier_marks_valid_receipts_unbound_without_identity_fields(tmp_path):
    path, store, user, review = setup_company(tmp_path)
    receipt = record(
        store, review, "commercial_register_extract", token="pending-dossier",
    )

    dossier = store.verification_decision_dossier(
        review["id"], authorization=SECRET,
    )

    assert dossier == {
        "review_id": review["id"],
        "kind": "company_representative",
        "status": "pending",
        "decision_code": None,
        "created_at_utc": review["created_at_utc"],
        "updated_at_utc": review["updated_at_utc"],
        "decided_at_utc": None,
        "chain_valid": True,
        "evidence": [{
            "category": "commercial_register_extract",
            "observed_at_utc": receipt["observed_at_utc"],
            "verified_at_utc": receipt["verified_at_utc"],
            "expires_at_utc": receipt["expires_at_utc"],
            "bound_to_decision": False,
        }],
    }
    rendered = json.dumps(dossier, sort_keys=True)
    for forbidden in (
        user["company_id"], user["id"], "owner-one", "example.test",
        "operator-code", str(path),
    ):
        assert forbidden not in rendered
    assert not re.search(r"\b[a-f0-9]{64}\b", rendered)


def test_dossier_fails_closed_on_pending_receipt_tamper(tmp_path):
    path, store, _user, review = setup_company(tmp_path)
    receipt = record(
        store, review, "commercial_register_extract", token="dossier-tamper",
    )
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER account_verification_evidence_receipts_no_update")
        db.execute(
            "UPDATE account_verification_evidence_receipts SET content_sha256=? WHERE id=?",
            ("0" * 64, receipt["id"]),
        )

    with pytest.raises(VerificationReviewConflict, match="evidence_invalid"):
        store.verification_decision_dossier(review["id"], authorization=SECRET)


def test_post_decision_evidence_link_tamper_invalidates_audit(tmp_path):
    path, store, _user, review = setup_company(tmp_path)
    receipt_ids = company_packet(store, review, prefix="audit")
    decide(store, review, receipt_ids)
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            db.execute(
                "DELETE FROM account_verification_decision_evidence WHERE review_id=?",
                (review["id"],),
            )
        db.execute("DROP TRIGGER account_verification_decision_evidence_no_delete")
        db.execute(
            "DELETE FROM account_verification_decision_evidence WHERE receipt_id=?",
            (receipt_ids[0],),
        )
    with pytest.raises(VerificationReviewConflict, match="audit_invalid"):
        store.verification_review_audit(review["id"], authorization=SECRET)
    with pytest.raises(VerificationReviewConflict, match="audit_invalid"):
        store.verification_decision_dossier(review["id"], authorization=SECRET)


def test_cli_hashes_evidence_from_fd_and_redacts_receipt_output(tmp_path):
    path, _store, _user, review = setup_company(tmp_path)
    evidence_bytes = b"synthetic register extract fixture"
    metadata = json.dumps({
        "verifier_ref": "operator-private-code",
        "idempotency_key": "verification:receipt:cli-register-0001",
        "observed_at_utc": "2023-11-14T22:13:20Z",
        "verified_at_utc": "2025-06-15T15:06:40Z",
        "expires_at_utc": "2033-05-18T03:33:20Z",
    }).encode()
    evidence_fd, metadata_fd = pipe(evidence_bytes), pipe(metadata)
    output = io.StringIO()
    try:
        status = main([
            "--db", str(path), "evidence", review["id"],
            "--category", "commercial_register_extract",
            "--evidence-fd", str(evidence_fd), "--receipt-fd", str(metadata_fd),
        ], env={"SLPS_VERIFICATION_OPERATOR_SECRET": SECRET_TEXT}, stdout=output)
    finally:
        os.close(evidence_fd)
        os.close(metadata_fd)
    document = json.loads(output.getvalue())
    assert status == 0 and document["receipt"]["integrity_verified"] is True
    assert document["receipt"]["category"] == "commercial_register_extract"
    rendered = output.getvalue()
    assert evidence_bytes.decode() not in rendered
    assert "operator-private-code" not in rendered
    assert "cli-register" not in rendered
    assert not re.search(r"\b[a-f0-9]{64}\b", rendered)


def test_public_server_has_no_evidence_operator_route(tmp_path):
    source = open("server.py", encoding="utf-8").read()
    assert "record_verification_evidence" not in source
    assert "evidence_receipt_ids" not in source
    assert "verification_decision_dossier" not in source
