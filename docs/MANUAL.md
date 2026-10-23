# Operator Manual: WhisperShell ORIGINAL (Foundation)

## Start on Windows or a USB stick

Extract the ZIP into a single folder such as `D:\DINS-WhisperShell-ORIGINAL` or `E:\WhisperShell`. Paths inside Python are relative to `WhisperShell.py` or the module file, so the drive letter is not fixed. No `venv` or environment installation is used in this stage. Python **3.10+** must currently be available on the PC. For GUI mode, its Tkinter and SQLite modules must be present.

Launch `START_WHISPERSHELL.cmd` or use a terminal in the folder:

```powershell
python WhisperShell.py
```

The launcher looks for an optional **future** bundled `runtime/python/python.exe`, then uses Windows `py` launcher or `python` on PATH. **Python is not bundled in this archive.** Offline portability across machines is a target, not guaranteed until a runtime is bundled and tested.

For quick health checks:

```powershell
python WhisperShell.py --status
python WhisperShell.py --templates
python -m unittest discover -s tests -v
```

## What each GUI tab does TODAY

**Home / Body:** shows the modules whose source files are present and the active Shared Field revision. `FILE PRESENT` is not proof the module is running.

**Resident / Mind:** select a provider (None, local Ollama, OpenAI API, Nebius API, Custom API) and a model string, stored in the orchestrator's own Shared Field block. Optionally discover models via local Ollama at `127.0.0.1:11434`. No actual inference connection exists yet. Never enter API secrets into this interface.

**Original Builder:** choose Default, Robotics or Custom (or another created profile). Save the profile choice, **Capture complete profile**, or **Apply saved profile**. A profile is not available until it has actually been captured. Apply replaces captured blocks while retaining blocks absent from the snapshot. The customer build export control is intentionally disabled.

**Script / First Touch:** draft text scripts in Python, PowerShell or CMD and save them under `tools/scripts/`. Execution is disabled until First Touch's action/approval interface is implemented. Do not treat drafts as sandboxed code.

**Block Workshop:** create new connection-code blocks, expand their JSON dictionaries, inspect one or list all blocks. An existing code is not overwritten by Create. Expand recursively merges only the selected block. Detailed examples: [Expandable Blocks](EXPANDABLE_BLOCKS.md).

## Template Bridge without the GUI

```powershell
python modules/template_bridge.py --list
python modules/template_bridge.py --save default
python modules/template_bridge.py --apply default
```

These create/read `templates/default/shared_field.json` (or another profile name). Local profile snapshots are ignored by Git because they may contain private runtime state. Store your own encrypted/offline backups if preservation of live data is important. GitHub source backups do **not** back up your runtime memory or databases by default.

## Make a new module capable of joining Shared Field

1. Give the module a stable `connection_code` that won't be reused by unrelated modules.
2. On startup call `register_block(code, {...})`; subsequent boots preserve the block.
3. Read latest settings using `get_block(code)` and publish owned updates with `update_block(code, changes)` or `set_block_value(...)`.
4. For live synchronization, compare `revision()` values or use `wait_for_change()` from your module's own loop. No central service is required in this foundation.
5. During customization, use Template Bridge to capture the **whole field** and restore it later. Do not use it as the live message router.
6. Preserve module identity and recognized fields in any trimmed customer version.

## Folder meanings

- `modules/`: body and Shared Field/Template Bridge libraries.
- `mind/`: future Resident, memory layers, Jumpcore.
- `templates/`: optional whole-field snapshots. Runtime snapshot JSON ignored by Git.
- `data/`: future runtime state and logs. Excluded from Git.
- `tools/`: private developer tools; `block_builder.py` is current.
- `tests/`: isolated standard-library regression tests.
- `builds/`: future customer export output. Excluded from Git.
- `docs/`: engineering explanations and decision history.

## Troubleshooting

**`python` not found:** install Python on the machine or wait for the planned bundled runtime. There is no hidden/automatic install.

**Blank preset profile:** expected; the three labels are not prepared snapshots. Capture one before applying.

**Something updated but a second module doesn't see it:** legacy import globals are static copies. Use `get_block`, `load_field` or `wait_for_change` to refresh. The current mechanism uses polling.

**Existing block not changed by Create:** expected. Use Expand for new keys; Create intentionally preserves an existing block.

**A customer module doesn't understand a field:** expandable storage does not translate semantics automatically. The module must know how to use that field or gracefully ignore it.

**SQLite database copied while in use:** close running applications or use SQLite's backup API to create a consistent backup; don't assume copying a hot `.sqlite3` file alone captures all committed data.

## Current verification boundary

Core code and CLI are regression-tested on the build machine. GUI display, Windows path behavior, packaged standalone Python, actual Resident inference, First Touch execution, full First Sight/Touch/Hearing integration, and physical robotics remain unverified/not yet integrated in **this foundation package**.

## Master Blueprint / archival diagrams (Step 05)

Open **Master Blueprint** in the private GUI to review body, mind, support, adapter and tooling modules. Use its region filter or search to find a capability. Each row shows engineering **phase** and whether its source file is present, separately. The Blueprint is a tracked plan, not a feature launcher. All ten archival schematics are in `docs/schematics/` and are explained in `docs/MASTER_BLUEPRINT.md`.

For a quick check without a GUI run `python tools/blueprint_audit.py` (read-only). To see the machine-readable inventory run `python WhisperShell.py --blueprint`. No new virtual environment or installation process is required.
