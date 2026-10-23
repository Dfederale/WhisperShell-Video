# Blueprint Data Contract and Implementation Notes

The original schematics in `docs/schematics/` are first-class **source artifacts**. `architecture/blueprint.json` is their structured crosswalk to the actual software. The private GUI's **Master Blueprint** tab reads this JSON, and `python WhisperShell.py --blueprint` prints source file existence and implementation claims separately.

## Editing a module in the blueprint

Each `components[]` item has an `id`, `name`, `region`, `path`, `phase`, `description`, `connection_code`, `sources`, and `tags`. Valid phase values: `implemented_tested`, `partial_tested`, `planned_integration`, `designed`, `research_only`.

**Do not set a phase to `implemented_tested` until its source has been built and a specific relevant test has passed.** A source file's existence does not prove the process runs on the user's Windows or Raspberry Pi. A schematic's existence does not prove the code exists.

**Do not invent permanent connection codes from naming conventions.** The only confirmed new code in this release is the orchestrator's. When the original First Sight is recovered, record its authentic connection code and owner schema after inspecting the source. Next record schema version, event envelopes and nonbreaking migration rules; that structure is planned, not currently enforced.

## Block creation, no magic transport

`shared_field.register_block(code, {})` creates a stable, extensible namespace. `update_block` recursively merges keys, allowing runtime state and settings to grow. `set_block_value` updates nested values atomically. Current `wait_for_change` uses revision polling to observe new updates. Template Bridge's `save_profile` and `apply_profile` capture/restore the entire live field on demand. **None of these functions translates raw screenshots into semantic actions; that's the job for First Sight and the semantic adapters.** The original template features are just stored states, not online instruction pipelines.

## Original-to-consumer contract

Reduced modules retain their existing connection IDs, base interfaces and settings namespaces. Avoid distributing the full original Orchestrator/Block Workshop with customer packages. Current code does not enforce signed plugins, runtime access control, code sandboxing, or a trustworthy capability-handshake protocol. Those are required future protections, especially for the CMD/PowerShell/Python tools and robotics.

## Inspection commands

```text
python WhisperShell.py --status
python WhisperShell.py --blueprint
python tools/blueprint_audit.py
python -m unittest discover -s tests -v
```

The audit only reads `architecture/blueprint.json` and checks source names, diagram files, valid statuses and path safety. It does not execute absent modules or modify runtime data. The `--status` command is allowed to initialize an empty local Shared Field database when none exists, while the audit is read-only.
