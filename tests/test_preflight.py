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
            checks = {item["id"]: item for item in data["checks"]}
            self.assertEqual(checks["rate_path"]["status"], "pass")
            self.assertEqual(checks["rate_volume"]["status"], "warning")
            serialized = json.dumps(data)
            self.assertNotIn(env["OPENAI_API_KEY"], serialized)
            self.assertNotIn(env["SLPS_PILOT_PASSWORD"], serialized)

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
