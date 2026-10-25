import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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
            "OPENAI_API_KEY": "present-but-never-printed",
            "OPENAI_MODEL": "explicit-test-model",
            "SLPS_PROMPT_PATH": str(master),
            "SLPS_COOKIE_SECURE": "true",
            "SLPS_ANALYSES_PER_HOUR": "3",
            "SLPS_RATE_DB_PATH": "/var/data/limits.sqlite3",
            "SLPS_CASE_DB_PATH": "/var/data/cases.sqlite3",
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
            checks = {item["id"]: item for item in data["checks"]}
            self.assertEqual(checks["rate_path"]["status"], "pass")
            self.assertEqual(checks["rate_volume"]["status"], "warning")
            self.assertEqual(checks["case_path"]["status"], "pass")
            self.assertEqual(checks["case_volume"]["status"], "warning")
            self.assertEqual(checks["archive_recovery"]["status"], "warning")
            self.assertEqual(checks["provider_verification"]["status"], "warning")
            self.assertEqual(checks["tenant_id"]["status"], "pass")
            self.assertEqual(checks["owner_id"]["status"], "pass")
            serialized = json.dumps(data)
            self.assertNotIn(env["OPENAI_API_KEY"], serialized)
            self.assertNotIn(env["SLPS_PILOT_PASSWORD"], serialized)
            self.assertNotIn(env["SLPS_PILOT_TENANT_ID"], serialized)
            self.assertNotIn(env["SLPS_PILOT_OWNER_ID"], serialized)

    def test_archive_paths_warn_when_missing_and_block_unsafe_locations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = self.configured(root)
            for check_id, variable in (("rate", "SLPS_RATE_DB_PATH"), ("case", "SLPS_CASE_DB_PATH")):
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
