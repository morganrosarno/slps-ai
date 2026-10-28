import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from accounts import AccountStore
from scripts import preflight


class PreflightTests(unittest.TestCase):
    def configured(self, root: Path) -> dict[str, str]:
        master = root / "master.txt"
        master.write_bytes(b"approved-test-master")
        self.previous_hash = preflight.MASTER_SHA256
        preflight.MASTER_SHA256 = hashlib.sha256(master.read_bytes()).hexdigest()
        return {
            "SLPS_PILOT_PASSWORD": "pilot-password-16-chars",
            "SLPS_SESSION_SECRET": "session-secret-with-at-least-32-characters",
            "SLPS_PRIVATE_GATE_ENABLED": "true",
            "SLPS_PRIVATE_GATE_PASSWORD": "private-gate-test-password-only",
            "SLPS_PROVIDER_REQUESTS_TOTAL": "6",
            "OPENAI_API_KEY": "present-but-never-printed",
            "OPENAI_MODEL": "explicit-test-model",
            "SLPS_PROMPT_PATH": str(master),
            "SLPS_COOKIE_SECURE": "true",
            "SLPS_ANALYSES_PER_HOUR": "3",
            "SLPS_RATE_DB_PATH": "/var/data/limits.sqlite3",
            "SLPS_CASE_DB_PATH": "/var/data/cases.sqlite3",
            "SLPS_HISTORY_ROOT": "/var/data/history-media",
            "SLPS_MAX_HISTORY_BYTES_PER_TENANT": "1073741824",
            "SLPS_PILOT_TENANT_ID": "test-tenant_1",
            "SLPS_PILOT_OWNER_ID": "test-owner.1",
        }

    def tearDown(self):
        if hasattr(self, "previous_hash"):
            preflight.MASTER_SHA256 = self.previous_hash

    def test_complete_configuration_passes_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            env = self.configured(root)
            data = preflight.report(preflight.run_checks(env, root))
            self.assertTrue(data["ready"])
            self.assertGreaterEqual(data["summary"]["warnings"], 1)
            self.assertEqual(data["network_calls"], 0)
            self.assertEqual(data["verification_scope"], "offline_configuration_only")
            self.assertEqual(data["auth_profile"], "pilot")
            checks = {item["id"]: item for item in data["checks"]}
            self.assertEqual(checks["rate_path"]["status"], "pass")
            self.assertEqual(checks["rate_volume"]["status"], "warning")
            self.assertEqual(checks["case_path"]["status"], "pass")
            self.assertEqual(checks["case_volume"]["status"], "warning")
            self.assertEqual(checks["history_path"]["status"], "pass")
            self.assertEqual(checks["history_capacity"]["status"], "pass")
            self.assertEqual(checks["archive_recovery"]["status"], "warning")
            self.assertEqual(checks["provider_verification"]["status"], "warning")
            self.assertEqual(checks["tenant_id"]["status"], "pass")
            self.assertEqual(checks["owner_id"]["status"], "pass")
            serialized = json.dumps(data)
            self.assertNotIn(env["OPENAI_API_KEY"], serialized)
            self.assertNotIn(env["SLPS_PILOT_PASSWORD"], serialized)
            self.assertNotIn(env["SLPS_PILOT_TENANT_ID"], serialized)
            self.assertNotIn(env["SLPS_PILOT_OWNER_ID"], serialized)
            self.assertNotIn(env["SLPS_PRIVATE_GATE_PASSWORD"], serialized)
            self.assertEqual(checks["private_gate"]["status"], "pass")
            self.assertEqual(checks["provider_request_cap"]["status"], "pass")

    def test_private_staging_requires_gate_distinct_password_and_total_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.configured(root)
            for value in (None, "", "false", "yes", "1"):
                with self.subTest(gate=value):
                    if value is None:
                        env.pop("SLPS_PRIVATE_GATE_ENABLED", None)
                    else:
                        env["SLPS_PRIVATE_GATE_ENABLED"] = value
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                    self.assertEqual(checks["private_gate"].status, "blocker")
            env["SLPS_PRIVATE_GATE_ENABLED"] = "true"
            for value in ("", "short", " " * 32, "x" * 257):
                with self.subTest(password_length=len(value)):
                    env["SLPS_PRIVATE_GATE_PASSWORD"] = value
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                    self.assertEqual(checks["private_gate_password"].status, "blocker")
            for variable in ("SLPS_SESSION_SECRET", "SLPS_PILOT_PASSWORD"):
                env["SLPS_PRIVATE_GATE_PASSWORD"] = env[variable]
                checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks["private_gate_secrets_distinct"].status, "blocker")
            env["SLPS_PRIVATE_GATE_PASSWORD"] = "private-gate-test-password-only"
            for value in (None, "", "0", "-1", "10001", "1.5", "unlimited", "+6"):
                with self.subTest(cap=value):
                    if value is None:
                        env.pop("SLPS_PROVIDER_REQUESTS_TOTAL", None)
                    else:
                        env["SLPS_PROVIDER_REQUESTS_TOTAL"] = value
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                    self.assertEqual(checks["provider_request_cap"].status, "blocker")
            for value in ("1", "6", "10000"):
                env["SLPS_PROVIDER_REQUESTS_TOTAL"] = value
                checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks["provider_request_cap"].status, "pass")
                self.assertEqual(checks["provider_request_cap_scope"].status, "warning")

    def test_archive_paths_warn_when_missing_and_block_unsafe_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.configured(root)
            for check_id, variable in (("rate", "SLPS_RATE_DB_PATH"), ("case", "SLPS_CASE_DB_PATH"),
                                       ("history", "SLPS_HISTORY_ROOT")):
                env.pop(variable)
                checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks[f"{check_id}_path"].status, "warning")
                self.assertEqual(checks[f"{check_id}_volume"].status, "warning")
                for path in ("relative.sqlite3", str(root / "archive.sqlite3"), "/tmp/archive.sqlite3",
                             "/var/tmp/archive.sqlite3", "/dev/shm/archive.sqlite3",
                             "/var/data/../../tmp/archive.sqlite3"):
                    with self.subTest(variable=variable, path=path):
                        env[variable] = path
                        checks = {item.id: item for item in preflight.run_checks(env, root)}
                        self.assertEqual(checks[f"{check_id}_path"].status, "blocker")
                        self.assertEqual(checks[f"{check_id}_volume"].status, "warning")
                env[variable] = f"/var/data/{check_id}.sqlite3"
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["master.txt"])

    def test_archive_principals_match_server_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.configured(root)
            for check_id, variable in (("tenant_id", "SLPS_PILOT_TENANT_ID"), ("owner_id", "SLPS_PILOT_OWNER_ID")):
                env.pop(variable)
                checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks[check_id].status, "pass")
                for value in ("a", "AZaz09_.-", "a" * 64):
                    with self.subTest(variable=variable, value=value):
                        env[variable] = value
                        checks = {item.id: item for item in preflight.run_checks(env, root)}
                        self.assertEqual(checks[check_id].status, "pass")
                for value in ("", " ", " owner", "owner ", "owner\n", "tenant/owner", "é", "a" * 65):
                    with self.subTest(variable=variable, value=value):
                        env[variable] = value
                        checks = {item.id: item for item in preflight.run_checks(env, root)}
                        self.assertEqual(checks[check_id].status, "blocker")
                env[variable] = "valid-principal"

    def test_missing_required_values_are_blockers_and_bad_rate_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: invalid\n")
            data = preflight.report(preflight.run_checks({
                "SLPS_ANALYSES_PER_HOUR": "many", "SLPS_COOKIE_SECURE": "false",
            }, root))
            self.assertFalse(data["ready"])
            ids = {item["id"] for item in data["checks"] if item["status"] == "blocker"}
            self.assertTrue({"pilot_password", "session_secret", "api_key", "model", "master",
                             "secure_cookie", "analysis_limit", "start_command"} <= ids)

    def account_configuration(self, root: Path, db_path: Path, *, registration_open="false"):
        env = self.configured(root)
        env.update({
            "SLPS_AUTH_MODE": "accounts",
            "SLPS_ACCOUNT_REGISTRATION_OPEN": registration_open,
            "SLPS_ACCOUNT_DB_PATH": str(db_path),
        })
        env.pop("SLPS_PILOT_PASSWORD")
        env.pop("SLPS_PILOT_TENANT_ID")
        env.pop("SLPS_PILOT_OWNER_ID")
        return env

    @staticmethod
    def eligible_account(db_path: Path):
        store = AccountStore(db_path)
        user = store.register(email="owner@example.test", password="long-account-test-password",
                              company_name="Synthetic Company", company_identifier="CHE123456789",
                              role="Representative", locale="it")
        assert store.consume_token(store.issue_token(user["id"], "email"), "email")
        store.verify_company(user["company_id"], user["id"])

    def test_accounts_mode_does_not_require_pilot_password_and_validates_ready_login(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            db_path = root.parent / (root.name + "-accounts.sqlite3")
            try:
                self.eligible_account(db_path)
                before = hashlib.sha256(db_path.read_bytes()).hexdigest()
                env = self.account_configuration(root, db_path)
                with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
                    data = preflight.report(preflight.run_checks(env, root))
                self.assertEqual(hashlib.sha256(db_path.read_bytes()).hexdigest(), before)
                self.assertTrue(data["ready"])
                self.assertEqual(data["auth_profile"], "accounts")
                checks = {item["id"]: item for item in data["checks"]}
                self.assertNotIn("pilot_password", checks)
                self.assertNotIn("secrets_distinct", checks)
                self.assertNotIn("tenant_id", checks)
                self.assertNotIn("owner_id", checks)
                self.assertEqual(checks["account_db_schema"]["status"], "pass")
                self.assertEqual(checks["account_db_permissions"]["status"], "pass")
                self.assertEqual(checks["account_login_ready"]["status"], "pass")
                self.assertEqual(checks["account_delivery"]["status"], "warning")
                serialized = json.dumps(data)
                self.assertNotIn("owner@example.test", serialized)
                self.assertNotIn(str(db_path), serialized)
            finally:
                db_path.unlink(missing_ok=True)

    def test_account_db_must_not_be_readable_by_group_or_others(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            db_path = root.parent / (root.name + "-permissions.sqlite3")
            try:
                self.eligible_account(db_path)
                db_path.chmod(0o640)
                env = self.account_configuration(root, db_path)
                with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks["account_db_permissions"].status, "blocker")
                self.assertEqual(checks["account_login_ready"].status, "pass")
            finally:
                db_path.unlink(missing_ok=True)

    def test_accounts_mode_reports_registration_delivery_and_login_blockers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            db_path = root.parent / (root.name + "-empty-accounts.sqlite3")
            try:
                AccountStore(db_path)
                env = self.account_configuration(root, db_path, registration_open="true")
                with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks["account_login_ready"].status, "blocker")
                self.assertEqual(checks["account_delivery"].status, "blocker")
                self.assertIn("verifica", checks["account_delivery"].message)
                self.assertIn("recupero", checks["account_delivery"].message)
                self.assertIn("inviti", checks["account_delivery"].message)
                self.assertEqual(checks["account_db_schema"].status, "pass")
            finally:
                db_path.unlink(missing_ok=True)

    def test_accounts_mode_requires_explicit_safe_db_and_strict_boolean(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            env = self.account_configuration(root, root / "accounts.sqlite3", registration_open="yes")
            checks = {item.id: item for item in preflight.run_checks(env, root)}
            self.assertEqual(checks["account_registration_setting"].status, "blocker")
            self.assertEqual(checks["account_db_path"].status, "blocker")
            self.assertEqual(checks["account_login_ready"].status, "blocker")

    def test_existing_account_db_with_wrong_schema_is_a_blocker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            db_path = root.parent / (root.name + "-wrong.sqlite3")
            try:
                db_path.write_text("not sqlite")
                db_path.chmod(0o600)
                env = self.account_configuration(root, db_path)
                with mock.patch.object(preflight, "persistent_path_ok", return_value=True):
                    checks = {item.id: item for item in preflight.run_checks(env, root)}
                self.assertEqual(checks["account_db_schema"].status, "blocker")
                self.assertEqual(checks["account_login_ready"].status, "blocker")
            finally:
                db_path.unlink(missing_ok=True)

    def test_invalid_auth_mode_fails_closed_without_guessing_a_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for value in ("automatic", " accounts", "accounts ", "ACCOUNTS", "Pilot"):
                with self.subTest(value=value):
                    env = self.configured(root)
                    env["SLPS_AUTH_MODE"] = value
                    data = preflight.report(preflight.run_checks(env, root))
                    checks = {item["id"]: item for item in data["checks"]}
                    self.assertFalse(data["ready"])
                    self.assertEqual(data["auth_profile"], "invalid")
                    self.assertEqual(checks["auth_mode"]["status"], "blocker")
                    self.assertNotIn("pilot_password", checks)
                    self.assertNotIn("account_db_path", checks)

    def test_optional_sources_warn_when_absent_and_block_when_invalid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            env = self.configured(root)
            absent = next(item for item in preflight.run_checks(env, root) if item.id == "sources")
            self.assertEqual(absent.status, "warning")
            invalid = root / "sources.json"
            invalid.write_text('[{"id":"duplicate"}]')
            env["SLPS_SOURCES_PATH"] = str(invalid)
            broken = next(item for item in preflight.run_checks(env, root) if item.id == "sources")
            self.assertEqual(broken.status, "blocker")

    def test_valid_source_registry_and_persistence_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            env = self.configured(root)
            sources = root / "sources.json"
            sources.write_text(json.dumps([{
                "id": "source-1", "title": "Official source", "url": "https://example.invalid/source",
                "verified_at": "2026-10-24T00:00:00Z", "excerpt": "Relevant excerpt",
            }]))
            env["SLPS_SOURCES_PATH"] = str(sources)
            env["SLPS_RATE_DB_PATH"] = str(root / "limits.sqlite3")
            checks = {item.id: item for item in preflight.run_checks(env, root)}
            self.assertEqual(checks["sources"].status, "pass")
            self.assertEqual(checks["rate_path"].status, "blocker")
            self.assertEqual(checks["rate_volume"].status, "warning")

    def test_empty_source_registry_warns_instead_of_claiming_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Procfile").write_text("web: " + preflight.EXPECTED_START + "\n")
            env = self.configured(root)
            sources = root / "sources.json"
            sources.write_text("[]")
            env["SLPS_SOURCES_PATH"] = str(sources)
            source_check = next(item for item in preflight.run_checks(env, root) if item.id == "sources")
            self.assertEqual(source_check.status, "warning")

    def test_cli_json_has_nonzero_exit_and_no_environment_secret(self):
        env = dict(os.environ)
        env["OPENAI_API_KEY"] = "never-echo-this-secret"
        result = subprocess.run([sys.executable, "scripts/preflight.py", "--json"], cwd=preflight.ROOT,
                                env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertFalse(data["ready"])
        self.assertNotIn(env["OPENAI_API_KEY"], result.stdout)


if __name__ == "__main__":
    unittest.main()
