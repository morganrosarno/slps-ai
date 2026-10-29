#!/usr/bin/env python3
"""Offline snapshot/restore for a quiesced single-instance profile."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from durable_storage import create_snapshot, profile_from_mapping, restore_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup/ripristino storage SLPS single-instance")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--confirm-quiesced", action="store_true",
                        help="Conferma che servizio e writer sono arrestati")
    restore = commands.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("target_root", type=Path)
    restore.add_argument("--min-free-bytes", type=int)
    args = parser.parse_args()
    if args.command == "backup":
        manifest = create_snapshot(profile_from_mapping(os.environ), args.destination,
                                   quiesced=args.confirm_quiesced)
        print(json.dumps({"status": "ok", "format": manifest["format"],
                          "files": len(manifest["files"])}, sort_keys=True))
    else:
        profile = restore_snapshot(args.backup, args.target_root,
                                   min_free_bytes=args.min_free_bytes)
        print(json.dumps({"status": "ok", "profile": profile.name}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
