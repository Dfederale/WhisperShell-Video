# DINS WhisperShell ORIGINAL

**PRIVATE DEVELOPMENT SOURCE | 21 October 2026 | Foundation Steps 01–05**

WhisperShell is a portable, modular, local-first environment intended to combine a **body** (sensing/acting software and device modules) and a **mind** (a swappable AI Resident and its own experience/memory mechanisms). The original private edition is our full engineering workshop. Future customer editions will be selected, reduced-capability builds of the same core, **not new incompatible platforms**.

> **Working principle:** Keep the module's identity and connection language even when its available functions are reduced.

## What is in this repository today?

| Piece | Real status | Location |
| --- | --- | --- |
| Expandable Shared Field | Implemented; JSON-namespaced blocks in portable SQLite, revisions, polling, snapshot API | `modules/shared_field.py` |
| Template Bridge | Implemented; full-field capture/restore to JSON, retaining blocks absent from older snapshots | `modules/template_bridge.py` |
| Private WhisperShell orchestrator | Implemented GUI and CLI for status, model **selection**, profile management, script **drafting**, and Block Workshop | `WhisperShell.py` |
| New Block Workshop | Implemented GUI tab **and** CLI: register, list, inspect, expand, set nested values | `WhisperShell.py`, `tools/block_builder.py` |
| Master Blueprint and schematic archive | **Implemented documentation/registry**, not runtime modules. Ten original diagrams, 34 component records, searchable GUI tab, read-only CLI/auditor | `architecture/blueprint.json`, `docs/schematics/`, `docs/MASTER_BLUEPRINT.md` |
| First Touch, orchestrator Resident integration, live robotics, customer packager | **Not integrated in this foundation release** | Planned, not claimed working in this build |

The existence of a dropdown or button does **not** mean its runtime module is installed. In particular, the model picker saves selection but does not call an AI model yet, and scripts can be saved but are not executed until First Touch is wired. The Windows GUI and updated Block Workshop layout were visually confirmed on 22 October 2026. GUI collision registration remains untested.

## Begin

1. Put/extract this entire folder anywhere, including a USB stick. Keep the folders together.
2. Install/use Python 3.10+ with SQLite and Tkinter (standard library on many desktop distributions). No virtual environment is required for the present foundation.
3. Run `python WhisperShell.py` for the GUI or `python WhisperShell.py --status` for headless status. Windows users can run `START_WHISPERSHELL.cmd` if Python is discoverable.
4. Open **Master Blueprint** to see which components are implemented, awaiting original integration, designed, or exploratory, with links to all ten old schematics. The plan is visible on day one, but no planned module is claimed active.
5. Open **Block Workshop** to create and expand a module block. Or use the CLI commands in [the Block Manual](docs/EXPANDABLE_BLOCKS.md).
6. Open **Original Builder** to capture/apply a full profile when needed. Profiles called `default`, `robotics`, `custom` start **empty/not captured**: they are choices, not invented presets.
7. Run foundation tests: `python -m unittest discover -s tests -v`.

## Why the expandable blocks matter

Each module retains its own **stable connection code**. A block starts as JSON `{}` or another small object, grows with new keys/nested maps without an assigned fixed block size, and does not overwrite other module blocks. Shared Field carries live state; Template Bridge only captures/restores the whole field. Future modules can register new namespaced blocks without rewriting the Shared Field Python source.

A connection code is **an address, not an authentication secret**. The prototype currently relies on cooperating local modules; it does not enforce authenticated block ownership. Do not place credentials or confidential customer data in blocks or snapshots.

## Documentation

- [Master Blueprint: ten original schematics reconciled with current code](docs/MASTER_BLUEPRINT.md)
- [Blueprint registry/auditor technical guide](docs/BLUEPRINT_ENGINEERING.md)
- [Original schematic image archive](docs/schematics/)
- [User manual and portable launch](docs/MANUAL.md)
- [Expandable blocks: implementation and Block Workshop](docs/EXPANDABLE_BLOCKS.md)
- [Body/mind architecture and customer builds](docs/ARCHITECTURE.md)
- [Build log and exact test status](docs/BUILD_LOG.md)
- [Compatibility and security contract](docs/COMPATIBILITY_AND_SECURITY.md)
- [Private GitHub backup workflow](docs/PRIVATE_GITHUB.md)

**Private source policy:** Do not copy the original orchestrator, development tools or unpublished mind mechanisms into a public demo. Preserve module identities/Shared Field/Template Bridge across later customer builds; keep the private workshop separate from exports.

## 22 October 2026 - Shared Field foundation checkpoint

We built Shared Field as a local SQLite-backed communication foundation. Modules register expandable JSON blocks under stable connection codes. Revisions and polling let different components observe changes without hardcoding every future module into the core.

Template Bridge was added to capture and restore complete Shared Field snapshots. Older snapshots must not erase newer blocks merely because those blocks did not exist when the snapshot was created.

The private Block Workshop provides creation, inspection and expansion of these blocks. We added a collision registry using persistent birth timestamps: different modules requesting the same number receive distinct identities, while returning modules keep their original identities and data.

Verified on the Windows development laptop: registry self-test passed, including duplicate identities, concurrent claims and snapshot restoration; orchestrator status and Python syntax checks passed; updated Block Workshop GUI opened and was visually confirmed. GUI collision registration is not yet functionally tested.

This milestone is intended for the original private GitHub repository. Git history and commit SHAs provide recoverable source checkpoints without accumulating frozen project folders. Live databases, private memory and machine-specific identity markers remain local.

## Front Window milestone - 22 October 2026

The five-way input picker now supports Onscreen AI, Local AI, API AI, Scripts and Human Input (voice/text), preserving the existing Resident selection.

The resource Monitor provides live RAM readings, a utilization bar, process memory information and a hover popup. Reusable capability ranges and hover hints were added for future module-owned toggles and hardware profiles.

Verified: Python syntax checks passed and the Windows interface was visually inspected. Runtime connections and full integration testing remain pending.


## Checkpoint 004 - First Sight and First Hearing
First Sight ORIGINAL: restored GUI, AI Portal, Shared Field integration and automatic portable dependencies. Tesseract OCR verified READY inside the project folder.
First Hearing ORIGINAL: restored standalone GUI, audio controls, AI Portal and project-local dependencies.
Both modules remain standalone; full orchestrator integration is pending.
Portable OCR binaries and local dependencies remain outside Git through .gitignore.
