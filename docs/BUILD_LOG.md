# Build Log: What We Actually Made

**21 October 2026.** The original private WhisperShell is being reconstructed and refined from prior working concepts, not presented as a brand-new discovery. Earlier working builds on modest hardware inform the direction but are **not included in this release** unless named below.

## Step 01: Shared Field

Packaged `modules/shared_field.py` and initial directory tree. New implementation uses standard-library SQLite, JSON module blocks keyed by permanent connection code, atomic transactions, a field revision counter, legacy commands/action_map/permissions access, explicit snapshot API, and reader-controlled revision polling. It stores runtime DB beside the Shared Field Python module by default.

## Step 02: Private orchestrator

`WhisperShell.py` provided a Tkinter front panel: module inventory; Resident provider/model choice stored as a block; local Ollama model discovery; Original Builder labels; Script/First Touch text drafts (save-only). No inference or script execution connected.

## Step 03: Template Bridge

`modules/template_bridge.py` now captures every Shared Field block and legacy section in a versioned JSON profile at `templates/<profile>/shared_field.json`. Applying uses `shared_field.apply_snapshot`. Blocks absent from older profiles survive; included blocks are replaced by their captured values. The orchestrator's profile Capture/Apply buttons call the bridge. This is not a live-sync service.

## Step 04: Documented private backup and block creation system

- Added **Block Workshop** tab to `WhisperShell.py` to create, expand, inspect and list blocks by stable connection code.
- Added `tools/block_builder.py` with `create`, `expand`, `set`, `show` and `list`, using the same Shared Field API, not a second block engine.
- Added this documentation, Git ignore protections, Windows launcher, and isolated regression suite.
- The foundation now carries a repeatable, versionable technical explanation of how the expandable blocks are actually coded.

## Tests run for Step 04

`python -m unittest discover -s tests -v`: **9 tests passed** on the package build machine (Python 3.13), covering block registration/growth/identity, separate namespaces, nested mutation, full-field restore plus future-block preservation, legacy values/validation, change polling, 60-thread distinct-module writes, Template Bridge round-trip, and CLI/orchestrator status.

**Not tested:** graphical Windows GUI, model calls, script execution, installed AI modules, customer builder/export, Raspberry Pi, USB transfer, robot control. A UI button's presence is not evidence its downstream module is connected.

## Next software modules (planned, not claimed finished)

Connect and regression-test the original First Sight/First Touch/First Hearing/etc. modules without breaking stable module identities. Implement actual Resident adapters/model inference and the mind's memory subsystems separately. Build customer edition packaging after the full original is operational, then test it against representative customer software under permission.

## Private GitHub archival status

The linked account lists `Dfederale/Whispershell` as **private**. The GitHub connector returned **HTTP 404** when attempting to read the repository metadata and when attempting to create its first `.gitignore` file. Therefore **the remote backup has NOT been completed**. A complete locally committed Git bundle and a clean full source ZIP were prepared instead. GitHub authorization/repository access or local authenticated `git push` is still needed.

## Step 05: Preserve all original schematic knowledge inside the software

- Archived ten original schematics **unchanged** under `docs/schematics/`.
- Translated source diagrams and subsequent design decisions into `architecture/blueprint.json` with component ownership, phase, planned paths and source cross-references.
- Added a **Master Blueprint** tab in the private Orchestrator and `--blueprint` status view. The GUI shows designs separately from genuinely installed source files.
- Added `tools/blueprint_audit.py`: read-only schema/paths/status checker, runs without loading absent modules or touching the Shared Field database.
- Added `docs/MASTER_BLUEPRINT.md` and `docs/BLUEPRINT_ENGINEERING.md`, including historical corrections: **current** Template Bridge snapshots rather than interprets semantics; First Mind is filesystem/spatial resources rather than Resident mind; First Ache is a workload governor; Genesis Conda is optional/superseded by one-folder no-env startup; CD-i/8K and universal DI are research; cloud and MCP are optional adapters.
- No additional sensory, resident, robotic, or execution module is claimed implemented. No first-run Windows test is claimed.
- No private GitHub push attempted in Step 05 because earlier connected GitHub writes returned `404` despite listing the private repository. The archive and Git bundle remain local until authenticated push is possible.
