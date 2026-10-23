"""Read-only ORIGINAL architecture blueprint auditor (no network or side effects).

Run: python tools/blueprint_audit.py
The JSON blueprint stores plans and maturity, NOT executable capabilities.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = ROOT / "architecture" / "blueprint.json"
ALLOWED_PHASES = {"implemented_tested", "partial_tested", "planned_integration", "designed", "research_only"}
ALLOWED_REGIONS = {"body", "mind", "support", "adapter", "tooling"}


def audit() -> tuple[list[str], dict]:
    problems: list[str] = []
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("format") != "DINS.WhisperShell.Original.Blueprint" or plan.get("schema_version") != 1:
        problems.append("Unknown format/schema version")
    diagrams = {str(row["number"]).zfill(2) for row in plan["diagram_index"]}
    for diagram in plan["diagram_index"]:
        p = ROOT / diagram["file"]
        if not p.is_file():
            problems.append(f"Missing source diagram: {diagram['file']}")
    ids, codes = set(), set()
    for entry in plan["components"]:
        identifier = entry["id"]
        if identifier in ids:
            problems.append(f"Duplicate component id: {identifier}")
        ids.add(identifier)
        if entry["phase"] not in ALLOWED_PHASES:
            problems.append(f"Unknown phase for {identifier}")
        if entry["region"] not in ALLOWED_REGIONS:
            problems.append(f"Unknown region for {identifier}")
        if not set(entry.get("sources", [])).issubset(diagrams):
            problems.append(f"Unknown source-diagram reference for {identifier}")
        code = entry.get("connection_code")
        if code is not None:
            if code in codes:
                problems.append(f"Duplicate assigned module connection code: {code}")
            codes.add(code)
        # Blueprint paths must be relative to ROOT and never permit traversal.
        p = Path(entry["path"])
        if p.is_absolute() or ".." in p.parts:
            problems.append(f"Unsafe path for {identifier}: {p}")
            continue
        if entry["phase"] in ("implemented_tested", "partial_tested") and not (ROOT / p).is_file():
            problems.append(f"Claimed implemented file missing: {entry['path']}")
        if entry["phase"] in ("designed", "research_only", "planned_integration") and (ROOT / p).exists():
            # Not an error: files can be installed before status is formally upgraded.
            pass
    return problems, {"components": len(plan["components"]), "diagrams": len(diagrams),
                      "implemented_or_partial": sum(1 for e in plan["components"] if e["phase"] in ("implemented_tested", "partial_tested")),
                      "unimplemented_or_unintegrated": sum(1 for e in plan["components"] if e["phase"] not in ("implemented_tested", "partial_tested")),
                      "issues": len(problems)}


def main():
    try:
        errors, summary = audit()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Architecture audit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for error in errors:
        print("ISSUE: " + error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
