import io
import json
import unittest

from scripts.preflight import Check, report
from scripts.storage_status import main, public_storage_status


def _report(profile, statuses=None, **extra):
    statuses = statuses or {
        "durable_profile": "pass",
        "durable_layout": "pass",
        "durable_capacity": "pass",
        "real_data_storage": "pass",
    }
    report = {
        "schema_version": 1,
        "storage_profile": profile,
        "checks": [
            {"id": check_id, "status": status, "message": "operator detail"}
            for check_id, status in statuses.items()
        ],
    }
    report.update(extra)
    return report


class StorageStatusTests(unittest.TestCase):
    def test_safe_projection_distinguishes_synthetic_configured_and_blocked(self):
        synthetic = _report("synthetic", {"real_data_storage": "pass"})
        configured = _report("single-instance configured")
        incomplete = _report("single-instance configured", {
            "durable_profile": "pass",
            "durable_layout": "pass",
            "durable_capacity": "warning",
            "real_data_storage": "pass",
        })

        self.assertEqual(public_storage_status(synthetic)["storage_state"], "synthetic")
        self.assertEqual(
            public_storage_status(configured)["storage_state"],
            "single-instance configured",
        )
        self.assertEqual(public_storage_status(incomplete)["storage_state"], "blocked")
        self.assertEqual(public_storage_status({})["storage_state"], "blocked")

    def test_safe_projection_never_forwards_paths_secrets_messages_or_verified_claims(self):
        marker = "DO-NOT-EXPOSE-/private/volume/account.sqlite3"
        report = _report(
            "single-instance configured",
            storage_provider_verified=True,
            durable_root=marker,
            secret=marker,
        )
        report["checks"][0]["message"] = marker

        status = public_storage_status(report)
        rendered = json.dumps(status)

        self.assertNotIn(marker, rendered)
        self.assertEqual(status, {
            "schema_version": 1,
            "storage_state": "single-instance configured",
            "storage_provider_verified": False,
            "verification_scope": "offline_configuration_only",
        })

    def test_preflight_configured_profile_round_trips_to_owner_status(self):
        checks = [
            Check("data_mode", "blocker", "pass", "detail"),
            Check("durable_profile", "blocker", "pass", "detail"),
            Check("durable_layout", "blocker", "pass", "detail"),
            Check("durable_capacity", "blocker", "pass", "detail"),
            Check("real_data_storage", "blocker", "pass", "detail"),
            Check("storage_provider_verification", "blocker", "blocker", "detail"),
        ]

        preflight = report(checks)

        self.assertEqual(preflight["storage_profile"], "single-instance configured")
        self.assertEqual(
            public_storage_status(preflight)["storage_state"],
            "single-instance configured",
        )

    def test_invalid_data_mode_can_never_project_as_synthetic(self):
        checks = [
            Check("data_mode", "blocker", "blocker", "detail"),
            Check("real_data_storage", "blocker", "pass", "detail"),
        ]

        preflight = report(checks)

        self.assertEqual(preflight["storage_profile"], "blocked")
        self.assertEqual(public_storage_status(preflight)["storage_state"], "blocked")

    def test_cli_reads_stdin_and_returns_nonzero_for_blocked_status(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        exit_code = main([], stdin=io.StringIO(json.dumps({})), stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["storage_state"], "blocked")
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_rejects_invalid_json_without_echoing_input(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        exit_code = main([], stdin=io.StringIO("private-secret"), stdout=stdout, stderr=stderr)

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("private-secret", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
