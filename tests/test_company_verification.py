from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from accounts import (
    AccountStore, VerificationAuthorizationError, VerificationReviewConflict,
)


PASSWORD = "a-long-local-test-passphrase"
SECRET = b"synthetic-operator-secret-32-bytes!"
OTHER_SECRET = b"different-operator-secret-32bytes!"


def store(tmp_path, secret=SECRET):
    return AccountStore(
        tmp_path / "accounts.sqlite3",
        verification_operator_secret=secret,
    )


def register(accounts, *, email="owner@example.test", identifier="CHE123456789"):
    return accounts.register(
        email=email, password=PASSWORD, company_name="Synthetic Company",
        company_identifier=identifier, role="Representative", locale="it",
    )


def key(value):
    return "verification:synthetic:" + value * 40


def test_registration_creates_pending_redacted_review_and_never_auto_approves(tmp_path):
    accounts = store(tmp_path)
    user = register(accounts)
    reviews = accounts.list_verification_reviews(authorization=SECRET)
    assert len(reviews) == 1
    review = reviews[0]
    assert review["kind"] == "company_representative"
    assert review["company_id"] == user["company_id"]
    assert review["subject_user_id"] == user["id"]
    assert review["status"] == "pending" and review["decision_code"] is None
    assert "email" not in review and "company_name" not in review
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_operator_capability_is_required_and_secret_mismatch_fails_closed(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    unconfigured = AccountStore(path)
    register(unconfigured)
    with pytest.raises(VerificationAuthorizationError, match="unauthorized"):
        unconfigured.list_verification_reviews(authorization=SECRET)

    configured = AccountStore(path, verification_operator_secret=SECRET)
    assert configured.list_verification_reviews(authorization=SECRET)
    with pytest.raises(VerificationAuthorizationError, match="unauthorized"):
        configured.list_verification_reviews(authorization=OTHER_SECRET)
    with pytest.raises(VerificationAuthorizationError, match="secret_mismatch"):
        AccountStore(path, verification_operator_secret=OTHER_SECRET)


def test_legacy_unverified_company_backfills_representative_and_member_reviews(tmp_path):
    path = tmp_path / "legacy-accounts.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE account_companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, identifier TEXT NOT NULL,
            identity_key TEXT NOT NULL UNIQUE, verified INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL);
        CREATE TABLE account_users (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL, locale TEXT NOT NULL,
            email_verified INTEGER NOT NULL DEFAULT 0,
            membership_verified INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1,
            created REAL NOT NULL);
        CREATE TABLE consultation_requests (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, user_id TEXT NOT NULL,
            case_id TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
            period_started REAL NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
            used_at REAL, cancelled_at REAL);
        INSERT INTO account_companies
            VALUES ('c1','Synthetic Legacy AG','CHE1','id:CHE1',0,1);
        INSERT INTO account_users VALUES
            ('u1','c1','owner@example.test','hash','Owner','it',1,0,1,1,2),
            ('u2','c1','member@example.test','hash','Member','it',1,0,1,1,3);
    """)
    db.commit()
    db.close()

    accounts = AccountStore(path, verification_operator_secret=SECRET)
    reviews = accounts.list_verification_reviews(authorization=SECRET)
    assert {(item["kind"], item["subject_user_id"]) for item in reviews} == {
        ("company_representative", "u1"), ("membership", "u2"),
    }
    company_review = next(item for item in reviews if item["kind"] == "company_representative")
    member_review = next(item for item in reviews if item["kind"] == "membership")
    accounts.decide_verification_review(
        company_review["id"], decision="approve",
        decision_code="identity_and_authority_confirmed",
        operator_ref="operator-1", idempotency_key=key("l"),
        authorization=SECRET,
    )
    assert accounts.get_user("u1")["company_verified"]
    assert accounts.get_user("u1")["membership_verified"]
    assert not accounts.get_user("u2")["membership_verified"]
    accounts.decide_verification_review(
        member_review["id"], decision="approve",
        decision_code="membership_confirmed",
        operator_ref="operator-1", idempotency_key=key("n"),
        authorization=SECRET,
    )
    assert accounts.get_user("u2")["membership_verified"]


def test_legacy_fixture_approval_is_disabled_outside_testing(tmp_path):
    accounts = store(tmp_path)
    user = register(accounts)
    with pytest.raises(VerificationAuthorizationError, match="fixture_verification_disabled"):
        accounts.verify_company(user["company_id"], user["id"])
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_company_and_authority_approval_is_atomic_audited_and_redacted(tmp_path):
    accounts = store(tmp_path)
    user = register(accounts)
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    result = accounts.decide_verification_review(
        review["id"], decision="approve",
        decision_code="identity_and_authority_confirmed",
        operator_ref="synthetic-operator@example.test", idempotency_key=key("a"),
        authorization=SECRET, now=1_800_000_000,
    )
    assert result["status"] == "approved" and result["version"] == 2
    current = accounts.get_user(user["id"])
    assert current["company_verified"] and current["membership_verified"]
    audit = accounts.verification_review_audit(review["id"], authorization=SECRET)
    assert [item["event"] for item in audit] == ["submitted", "approved"]
    assert audit[1]["decision_code"] == "identity_and_authority_confirmed"
    assert len(audit[1]["operator_digest"]) == 64
    raw = (tmp_path / "accounts.sqlite3").read_bytes()
    assert b"synthetic-operator@example.test" not in raw
    assert key("a").encode() not in raw
    assert SECRET not in raw


def test_rejection_keeps_company_and_membership_blocked(tmp_path):
    accounts = store(tmp_path)
    user = register(accounts)
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    result = accounts.decide_verification_review(
        review["id"], decision="reject", decision_code="insufficient_evidence",
        operator_ref="operator-1", idempotency_key=key("r"),
        authorization=SECRET, now=1_800_000_000,
    )
    assert result["status"] == "rejected"
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_membership_review_requires_verified_company_then_unlocks_only_member(tmp_path):
    accounts = store(tmp_path)
    owner = register(accounts)
    member = accounts.add_member(
        owner["company_id"], email="member@example.test", password=PASSWORD,
        role="Employee",
    )
    reviews = accounts.list_verification_reviews(authorization=SECRET)
    company_review = next(item for item in reviews if item["kind"] == "company_representative")
    member_review = next(item for item in reviews if item["kind"] == "membership")
    with pytest.raises(VerificationReviewConflict, match="company_not_verified"):
        accounts.decide_verification_review(
            member_review["id"], decision="approve", decision_code="membership_confirmed",
            operator_ref="operator-1", idempotency_key=key("m"),
            authorization=SECRET,
        )
    accounts.decide_verification_review(
        company_review["id"], decision="approve",
        decision_code="identity_and_authority_confirmed",
        operator_ref="operator-1", idempotency_key=key("c"),
        authorization=SECRET,
    )
    assert not accounts.get_user(member["id"])["membership_verified"]
    accounts.decide_verification_review(
        member_review["id"], decision="approve", decision_code="membership_confirmed",
        operator_ref="operator-1", idempotency_key=key("m2"),
        authorization=SECRET,
    )
    assert accounts.get_user(member["id"])["membership_verified"]


def test_same_decision_is_idempotent_across_concurrent_instances(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    first = AccountStore(path, verification_operator_secret=SECRET)
    register(first)
    review = first.list_verification_reviews(authorization=SECRET)[0]
    instances = [
        AccountStore(path, verification_operator_secret=SECRET) for _ in range(8)
    ]

    def decide(accounts):
        return accounts.decide_verification_review(
            review["id"], decision="approve",
            decision_code="identity_and_authority_confirmed",
            operator_ref="operator-1", idempotency_key=key("i"),
            authorization=SECRET,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(decide, instances))
    assert all(item["status"] == "approved" for item in results)
    audit = first.verification_review_audit(review["id"], authorization=SECRET)
    assert [item["event"] for item in audit] == ["submitted", "approved"]


def test_reused_idempotency_key_with_different_decision_fails_closed(tmp_path):
    accounts = store(tmp_path)
    register(accounts)
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    accounts.decide_verification_review(
        review["id"], decision="reject", decision_code="insufficient_evidence",
        operator_ref="operator-1", idempotency_key=key("x"),
        authorization=SECRET,
    )
    with pytest.raises(VerificationReviewConflict, match="idempotency_conflict"):
        accounts.decide_verification_review(
            review["id"], decision="approve",
            decision_code="identity_and_authority_confirmed",
            operator_ref="operator-1", idempotency_key=key("x"),
            authorization=SECRET,
        )


def test_audit_rows_are_append_only_and_tamper_detection_fails_closed(tmp_path):
    accounts = store(tmp_path)
    register(accounts)
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    with accounts.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            db.execute(
                "UPDATE account_verification_audit SET event='rejected' WHERE review_id=?",
                (review["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            db.execute(
                "DELETE FROM account_verification_audit WHERE review_id=?", (review["id"],)
            )
        db.execute(
            "UPDATE account_verification_reviews SET audit_head=? WHERE id=?",
            ("0" * 64, review["id"]),
        )
    with pytest.raises(VerificationReviewConflict, match="audit_invalid"):
        accounts.verification_review_audit(review["id"], authorization=SECRET)
    with pytest.raises(VerificationReviewConflict, match="audit_invalid"):
        accounts.list_verification_reviews(authorization=SECRET)
    with pytest.raises(VerificationReviewConflict, match="audit_invalid"):
        accounts.decide_verification_review(
            review["id"], decision="approve",
            decision_code="identity_and_authority_confirmed",
            operator_ref="operator-1", idempotency_key=key("t"),
            authorization=SECRET,
        )


@pytest.mark.parametrize("decision,code", [
    ("approve", "insufficient_evidence"),
    ("reject", "identity_and_authority_confirmed"),
])
def test_decision_code_must_match_decision(tmp_path, decision, code):
    accounts = store(tmp_path)
    register(accounts)
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    with pytest.raises(ValueError, match="decision_code"):
        accounts.decide_verification_review(
            review["id"], decision=decision, decision_code=code,
            operator_ref="operator-1", idempotency_key=key("v"),
            authorization=SECRET,
        )


def test_public_server_has_no_operator_review_route_or_operator_secret(tmp_path):
    source = open("server.py", encoding="utf-8").read()
    assert "decide_verification_review" not in source
    assert "list_verification_reviews" not in source
    assert "verification_operator_secret" not in source
    assert "SLPS_VERIFICATION_OPERATOR" not in source
