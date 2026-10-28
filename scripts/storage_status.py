#!/usr/bin/env python3
"""Render a redacted storage status from the offline preflight report.

The detailed preflight report is useful to an operator but can contain messages
that should not be copied into an owner-facing status.  This projection emits
only a fixed vocabulary and never forwards paths, environment values or check
messages.  Provider durability remains unverified: only a restart and restore
drill in the target environment can supply that evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, TextIO


SAFE_STATES = {"synthetic", "single-instance configured", "blocked"}
DURABLE_CHECKS = {
    "durable_profile",
    "durable_layout",
    "durable_capacity",
    "real_data_storage",
}


def _passed_checks(report: dict[str, Any]) -> set[str]:
    checks = report.get("checks")
    if not isinstance(checks, list):
        return set()
    passed: set[str] = set()
    for item in checks:
        if (isinstance(item, dict) and isinstance(item.get("id"), str)
                and item.get("status") == "pass"):
            passed.add(item["id"])
    return passed


def public_storage_status(report: Any) -> dict[str, Any]:
    """Return the small, non-sensitive status safe for owner/admin display."""
    state = "blocked"
    if isinstance(report, dict):
        profile = report.get("storage_profile")
        passed = _passed_checks(report)
        if profile == "synthetic" and "real_data_storage" in passed:
            state = "synthetic"
        elif profile == "single-instance configured" and DURABLE_CHECKS <= passed:
            state = "single-instance configured"
    return {
        "schema_version": 1,
        "storage_state": state,
        "storage_provider_verified": False,
        "verification_scope": "offline_configuration_only",
    }


def _read_report(path: str | None, stream: TextIO) -> Any:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(stream)


def main(argv: list[str] | None = None, *, stdin: TextIO = sys.stdin,
         stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    parser = argparse.ArgumentParser(
        description="Riduce il preflight allo stato storage depurato per proprietario/amministratore."
    )
    parser.add_argument(
        "--input", metavar="FILE",
        help="Report JSON del preflight; se omesso viene letto da standard input.",
    )
    args = parser.parse_args(argv)
    try:
        report = _read_report(args.input, stdin)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"storage_status: report non leggibile ({type(exc).__name__})", file=stderr)
        return 2
    status = public_storage_status(report)
    json.dump(status, stdout, ensure_ascii=False, indent=2)
    stdout.write("\n")
    return 0 if status["storage_state"] in SAFE_STATES - {"blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
