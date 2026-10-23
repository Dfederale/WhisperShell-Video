"""WhisperShell private block creation console.

Use the EXISTING Shared Field APIs; this is a front end, not another database,
module router, Template Bridge, or authorization layer.

Run from any working directory: python tools/block_builder.py list
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))
import shared_field as field  # noqa: E402


def object_argument(raw: str) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("Block JSON must be an object, for example '{\"enabled\":true}'")
    return obj


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register/expand/view namespaced WhisperShell Shared Field blocks"
    )
    parser.add_argument("--db", metavar="FILE", help="Optional explicit Shared Field database for testing")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List connection codes currently present")
    create = sub.add_parser("create", help="Register a new block without overwriting an existing one")
    create.add_argument("code", help="Stable permanent connection code of the owning module")
    create.add_argument("--json", default="{}", help="Initial block JSON object")
    extend = sub.add_parser("expand", help="Recursively merge JSON into one block")
    extend.add_argument("code")
    extend.add_argument("--json", required=True, help="JSON object of added or changed fields")
    show = sub.add_parser("show", help="Read a single block")
    show.add_argument("code")
    set_value = sub.add_parser("set", help="Write one nested key under a block")
    set_value.add_argument("code")
    set_value.add_argument("keys", help="Dot-separated nested key path, e.g. capabilities.ocr.enabled")
    set_value.add_argument("value", help="JSON value, e.g. true or '128' or '\"word\"'")
    args = parser.parse_args(argv)
    opts = {"path": args.db}
    try:
        if args.command == "list":
            state = field.load_field(args.db)
            print(f"Shared Field revision {state['revision']}")
            for code in sorted(state["blocks"]):
                print(code)
        elif args.command == "create":
            existing = field.get_block(args.code, default=None, **opts)
            if existing is not None:
                print("Already registered; existing content was NOT modified.", file=sys.stderr)
                return 2
            result = field.register_block(args.code, object_argument(args.json), **opts)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "expand":
            result = field.update_block(args.code, object_argument(args.json), **opts)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "show":
            result = field.get_block(args.code, default=None, **opts)
            if result is None:
                print("No such connection code.", file=sys.stderr)
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            keys = args.keys.split(".")
            result = field.set_block_value(args.code, keys, json.loads(args.value), **opts)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"Block Builder: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
