"""WhisperShell Template Bridge | snapshots of the WHOLE Shared Field.

The Shared Field coordinates live modules; Template Bridge only saves and
restores whole-field profiles. It does not synchronize modules, interpret
module-specific keys, rewrite Python files, or contain the mind's memories.

Profile files are portable UTF-8 JSON at:
    <WhisperShell root>/templates/<profile>/shared_field.json

Snapshots include all current legacy values and ALL registered connection
blocks, including disconnected modules. Restoring calls Shared Field's atomic
apply_snapshot; blocks absent from an older profile are intentionally retained
for forward compatibility, while blocks included in the profile are replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
TEMPLATES = ROOT / "templates"
SNAPSHOT_NAME = "shared_field.json"
FORMAT = "DINS.WhisperShell.TemplateBridge"
FORMAT_VERSION = 1


def _field():
    if str(MODULES) not in sys.path:
        sys.path.insert(0, str(MODULES))
    import shared_field
    return shared_field


def profile_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Profile names may contain letters, digits, _ and - (max 64).")
    return name.lower()


def profile_path(name: str) -> Path:
    """Path restricted to the portable templates folder."""
    return TEMPLATES / profile_name(name) / SNAPSHOT_NAME


def list_profiles() -> list[dict[str, Any]]:
    """List prepared profile names; mark which ones contain a saved snapshot."""
    found = {"default", "robotics", "custom"}
    if TEMPLATES.is_dir():
        found.update(p.name for p in TEMPLATES.iterdir()
                     if p.is_dir() and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", p.name))
    return [{"name": name, "saved": profile_path(name).is_file()}
            for name in sorted(found)]


def save_profile(name: str) -> Path:
    """Capture every Shared Field block and legacy section; no filtering."""
    dest = profile_path(name)
    state = _field().load_field()
    payload = {"format": FORMAT, "format_version": FORMAT_VERSION,
               "profile": profile_name(name),
               "captured_at_utc": datetime.now(timezone.utc).isoformat(),
               "field": state}
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=dest.parent, prefix=".snapshot-",
                                         suffix=".tmp", delete=False) as file:
            temp_path = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, dest)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return dest


def read_profile(name: str) -> dict[str, Any]:
    dest = profile_path(name)
    if not dest.is_file():
        raise FileNotFoundError(f"Profile '{profile_name(name)}' has not been saved yet. "
                                "Capture it first; there is no preset configuration to invent.")
    with dest.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or payload.get("format") != FORMAT or \
       payload.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"Not a compatible WhisperShell Template Bridge snapshot: {dest}")
    state = payload.get("field")
    if not isinstance(state, dict) or not all(k in state for k in
                                              ("commands", "action_map", "permissions", "blocks")):
        raise ValueError("Snapshot does not contain the complete Shared Field")
    if not isinstance(state["commands"], list) or \
       not isinstance(state["action_map"], dict) or \
       not isinstance(state["permissions"], dict) or \
       not isinstance(state["blocks"], dict):
        raise ValueError("Snapshot sections have invalid types")
    return payload


def apply_profile(name: str) -> int:
    """Restore all captured sections atomically through the live Shared Field.

    Does not remove additional blocks that appeared after the snapshot.
    Connected modules observe the new field revision on their next read/poll.
    """
    payload = read_profile(name)
    return _field().apply_snapshot(payload["field"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WhisperShell complete Shared Field profile bridge")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="Show available and saved profiles")
    actions.add_argument("--save", metavar="NAME", help="Capture all current blocks into NAME")
    actions.add_argument("--apply", metavar="NAME", help="Restore saved NAME into live field")
    args = parser.parse_args(argv)
    try:
        if args.list:
            for row in list_profiles():
                print(f"{row['name']}: {'SAVED' if row['saved'] else 'not captured'}")
        elif args.save:
            print(f"Snapshot saved: {save_profile(args.save)}")
        else:
            print(f"Profile applied; new Shared Field revision: {apply_profile(args.apply)}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"Template Bridge: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
