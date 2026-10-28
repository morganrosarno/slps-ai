from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import re
import sqlite3

from accounts import AccountStore
from scripts import company_verification_operator as operator_cli
from scripts.company_verification_operator import main


PASSWORD = "a-long-local-test-passphrase"
SECRET_TEXT = "synthetic-operator-secret-32-bytes!"
SECRET = SECRET_TEXT.encode("ascii")
OPERATOR_REF = "synthetic-operator@example.test"
IDEMPOTENCY_KEY = "verification:operator-tool:" + "i" * 48


def setup_review(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    accounts = AccountStore(path, verification_operator_secret=SECRET)
    user = accounts.register(
        email="private-owner@example.test",
        password=PASSWORD,
        company_name="Private Synthetic Company",
        company_identifier="CHE123456789",
        role="Representative",
        locale="it",
    )
    review = accounts.list_verification_reviews(authorization=SECRET)[0]
    return path, accounts, user, review


def run_tool(path, *args, env=None):
    output = io.StringIO()
    values = {
        "SLPS_ACCOUNT_DB_PATH": str(path),
        "SLPS_VERIFICATION_OPERATOR_SECRET": SECRET_TEXT,
    }
    if env:
        values.update(env)
    status = main(list(args), env=values, stdout=output)
    return status, json.loads(output.getvalue()), output.getvalue()


def decision_env(**overrides):
    values = {
        "SLPS_VERIFICATION_OPERATOR_REF": OPERATOR_REF,
        "SLPS_VERIFICATION_IDEMPOTENCY_KEY": IDEMPOTENCY_KEY,
    }
    values.update(overrides)
    return values


def verification_snapshot(path, user_id, review_id):
    with sqlite3.connect(path) as db:
        user = db.execute(
            """SELECT c.verified,u.membership_verified
               FROM account_users u JOIN account_companies c ON c.id=u.company_id
               WHERE u.id=?""",
            (user_id,),
        ).fetchone()
        review = db.execute(
            """SELECT status,decision_code,version,
                      (SELECT COUNT(*) FROM account_verification_audit WHERE review_id=?)
               FROM account_verification_reviews WHERE id=?""",
            (review_id, review_id),
        ).fetchone()
    return user, review


def assert_binding_failure_before_store(
        monkeypatch, path, user_id, review_id, *, expected_status, expected_code,
        secret=SECRET_TEXT):
    database_before = path.read_bytes()
    state_before = verification_snapshot(path, user_id, review_id)
    constructions = []

    def forbidden_store(*args, **kwargs):
        constructions.append((args, kwargs))
        raise AssertionError("AccountStore must not be constructed")

    monkeypatch.setattr(operator_cli, "AccountStore", forbidden_store)
    commands = [
        (("list",), {}),
        (("audit", review_id), {}),
        (("approve", review_id, "--reason", "identity_and_authority_confirmed"),
         decision_env()),
        (("reject", review_id, "--reason", "insufficient_evidence"),
         decision_env()),
    ]
    for args, extra_env in commands:
        output = io.StringIO()
        environment = {
            "SLPS_ACCOUNT_DB_PATH": str(path),
            "SLPS_VERIFICATION_OPERATOR_SECRET": secret,
            **extra_env,
        }
        status = main(list(args), env=environment, stdout=output)
        assert status == expected_status
        assert json.loads(output.getvalue()) == {
            "ok": False, "error": {"code": expected_code},
        }
        assert path.read_bytes() == database_before
        assert verification_snapshot(path, user_id, review_id) == state_before
    assert constructions == []


def setup_unbound_server_review(tmp_path):
    path = tmp_path / "unbound-server-accounts.sqlite3"
    accounts = AccountStore(path)
    user = accounts.register(
        email="unbound-owner@example.test",
        password=PASSWORD,
        company_name="Unbound Synthetic Company",
        company_identifier="CHE987654321",
        role="Representative",
        locale="it",
    )
    with sqlite3.connect(path) as db:
        review_id = db.execute(
            "SELECT id FROM account_verification_reviews WHERE subject_user_id=?",
            (user["id"],),
        ).fetchone()[0]
    return path, user, review_id


def test_list_is_pending_only_and_strictly_redacted(tmp_path):
    path, _accounts, user, review = setup_review(tmp_path)

    status, document, rendered = run_tool(path, "list")

    assert status == 0
    assert document == {
        "ok": True,
        "operation": "list",
        "count": 1,
        "reviews": [{
            "review_id": review["id"],
            "kind": "company_representative",
            "status": "pending",
            "decision_code": None,
            "created_at_utc": review["created_at_utc"],
            "updated_at_utc": review["updated_at_utc"],
            "decided_at_utc": None,
            "version": 1,
        }],
    }
    for private_value in (
        "private-owner", "example.test", "Private Synthetic Company",
        "CHE123456789", user["company_id"], user["id"], SECRET_TEXT,
    ):
        assert private_value not in rendered
    assert not re.search(r"\b[a-f0-9]{64}\b", rendered)


def test_approve_and_audit_are_redacted_and_replay_is_idempotent(tmp_path):
    path, accounts, user, review = setup_review(tmp_path)
    args = (
        "approve", review["id"], "--reason", "identity_and_authority_confirmed",
    )

    first = run_tool(path, *args, env=decision_env())
    replay = run_tool(path, *args, env=decision_env())
    audit_status, audit, rendered = run_tool(path, "audit", review["id"])

    assert first[0] == replay[0] == audit_status == 0
    assert first[1] == replay[1]
    assert first[1]["review"]["status"] == "approved"
    assert audit["chain_valid"] is True
    assert [event["event"] for event in audit["events"]] == ["submitted", "approved"]
    assert accounts.get_user(user["id"])["company_verified"]
    assert accounts.get_user(user["id"])["membership_verified"]
    with accounts.connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM account_verification_audit WHERE review_id=?",
            (review["id"],),
        ).fetchone()[0]
    assert count == 2
    for private_value in (OPERATOR_REF, IDEMPOTENCY_KEY, SECRET_TEXT, "example.test"):
        assert private_value not in first[2] + rendered
    assert "operator_digest" not in rendered
    assert "event_hash" not in rendered
    assert "previous_hash" not in rendered
    assert not re.search(r"\b[a-f0-9]{64}\b", first[2] + rendered)


def test_missing_invalid_and_mismatched_capability_fail_closed_with_same_error(tmp_path):
    path, accounts, user, _review = setup_review(tmp_path)
    database_before = path.read_bytes()
    variants = ({}, {
        "SLPS_VERIFICATION_OPERATOR_SECRET": "short",
    }, {
        "SLPS_VERIFICATION_OPERATOR_SECRET": "different-operator-secret-32bytes!",
    })

    results = []
    for environment in variants:
        output = io.StringIO()
        status = main(
            ["--db", str(path), "list"], env=environment, stdout=output,
        )
        results.append((status, json.loads(output.getvalue())))

    assert results == [(3, {
        "ok": False, "error": {"code": "authorization_failed"},
    })] * 3
    assert path.read_bytes() == database_before
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_normal_server_database_without_secret_binding_rejects_every_command_before_store(
        tmp_path, monkeypatch):
    path, user, review_id = setup_unbound_server_review(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM account_verification_operator_meta"
        ).fetchone()[0] == 0

    assert_binding_failure_before_store(
        monkeypatch, path, user["id"], review_id,
        expected_status=3, expected_code="authorization_failed",
    )


def test_missing_capability_table_rejects_every_command_before_store(tmp_path, monkeypatch):
    path, _accounts, user, review = setup_review(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE account_verification_operator_meta")

    assert_binding_failure_before_store(
        monkeypatch, path, user["id"], review["id"],
        expected_status=3, expected_code="authorization_failed",
    )


def test_deleted_capability_singleton_rejects_every_command_before_store(tmp_path, monkeypatch):
    path, _accounts, user, review = setup_review(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM account_verification_operator_meta WHERE singleton=1")

    assert_binding_failure_before_store(
        monkeypatch, path, user["id"], review["id"],
        expected_status=3, expected_code="authorization_failed",
    )


def test_malformed_capability_fingerprint_rejects_every_command_before_store(
        tmp_path, monkeypatch):
    path, _accounts, user, review = setup_review(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE account_verification_operator_meta SET secret_fingerprint=? WHERE singleton=1",
            ("malformed-fingerprint",),
        )

    assert_binding_failure_before_store(
        monkeypatch, path, user["id"], review["id"],
        expected_status=4, expected_code="database_unavailable",
    )


def test_mismatched_capability_rejects_every_command_before_store(tmp_path, monkeypatch):
    path, _accounts, user, review = setup_review(tmp_path)

    assert_binding_failure_before_store(
        monkeypatch, path, user["id"], review["id"],
        expected_status=3, expected_code="authorization_failed",
        secret="different-operator-secret-32bytes!",
    )


def test_reason_and_decision_inputs_fail_closed_without_mutation(tmp_path):
    path, accounts, user, review = setup_review(tmp_path)

    wrong_reason = run_tool(
        path, "approve", review["id"], "--reason", "insufficient_evidence",
        env=decision_env(),
    )
    missing_input = run_tool(
        path, "reject", review["id"], "--reason", "insufficient_evidence",
    )

    assert wrong_reason[:2] == (2, {"ok": False, "error": {"code": "invalid_input"}})
    assert missing_input[:2] == (2, {"ok": False, "error": {"code": "invalid_input"}})
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]
    assert accounts.list_verification_reviews(authorization=SECRET)[0]["status"] == "pending"


def test_corrupt_audit_blocks_queue_audit_and_decision(tmp_path):
    path, accounts, user, review = setup_review(tmp_path)
    with accounts.connect() as db:
        db.execute(
            "UPDATE account_verification_reviews SET audit_head=? WHERE id=?",
            ("0" * 64, review["id"]),
        )

    listed = run_tool(path, "list")
    audited = run_tool(path, "audit", review["id"])
    decided = run_tool(
        path, "approve", review["id"], "--reason", "identity_and_authority_confirmed",
        env=decision_env(),
    )

    for result in (listed, audited, decided):
        assert result[:2] == (4, {"ok": False, "error": {"code": "audit_invalid"}})
    current = accounts.get_user(user["id"])
    assert not current["company_verified"] and not current["membership_verified"]


def test_secret_and_decision_material_can_be_read_from_file_descriptors(tmp_path):
    path, _accounts, _user, review = setup_review(tmp_path)
    secret_read, secret_write = os.pipe()
    decision_read, decision_write = os.pipe()
    try:
        os.write(secret_write, SECRET + b"\n")
        os.close(secret_write)
        secret_write = -1
        os.write(decision_write, json.dumps({
            "operator_ref": OPERATOR_REF,
            "idempotency_key": IDEMPOTENCY_KEY,
        }).encode("utf-8"))
        os.close(decision_write)
        decision_write = -1
        output = io.StringIO()
        status = main([
            "--db", str(path), "--secret-fd", str(secret_read),
            "reject", review["id"], "--reason", "insufficient_evidence",
            "--decision-fd", str(decision_read),
        ], env={}, stdout=output)
    finally:
        os.close(secret_read)
        os.close(decision_read)
        if secret_write >= 0:
            os.close(secret_write)
        if decision_write >= 0:
            os.close(decision_write)

    assert status == 0
    assert json.loads(output.getvalue())["review"]["status"] == "rejected"
    assert OPERATOR_REF not in output.getvalue()
    assert IDEMPOTENCY_KEY not in output.getvalue()


def test_concurrent_same_command_has_one_atomic_audit_decision(tmp_path):
    path, accounts, _user, review = setup_review(tmp_path)
    args = (
        "approve", review["id"], "--reason", "identity_and_authority_confirmed",
    )

    def approve_once(_index):
        return run_tool(path, *args, env=decision_env())[:2]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(approve_once, range(6)))

    assert all(status == 0 and body["review"]["status"] == "approved"
               for status, body in results)
    audit = accounts.verification_review_audit(review["id"], authorization=SECRET)
    assert [event["event"] for event in audit] == ["submitted", "approved"]


def test_non_database_and_overpermissive_database_are_rejected_without_path_echo(tmp_path):
    missing = tmp_path / "private-missing.sqlite3"
    output = io.StringIO()
    status = main(
        ["--db", str(missing), "list"],
        env={"SLPS_VERIFICATION_OPERATOR_SECRET": SECRET_TEXT}, stdout=output,
    )
    assert status == 4
    assert json.loads(output.getvalue())["error"]["code"] == "database_unavailable"
    assert str(missing) not in output.getvalue()

    path, _accounts, _user, _review = setup_review(tmp_path)
    alias = tmp_path / "private-alias.sqlite3"
    alias.symlink_to(path)
    status, document, rendered = run_tool(alias, "list")
    assert status == 4 and document["error"]["code"] == "database_unavailable"
    assert str(alias) not in rendered

    path.chmod(0o644)
    status, document, rendered = run_tool(path, "list")
    assert status == 4 and document["error"]["code"] == "database_unavailable"
    assert str(path) not in rendered
