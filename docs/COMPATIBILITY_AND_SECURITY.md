# Compatibility and Security Contract

## Non-negotiable architecture

1. Connection code is stable per independently owned module block. A trimmed First Sight must remain First Sight with its original identity, not an unrelated replacement.
2. Every edition shares the same core Shared Field and Template Bridge language/files from the compatible release. Custom builds may omit capabilities, not silently mutate the contract.
3. Blocks can add fields and subobjects without fixed size; readers must ignore unknown fields gracefully.
4. Never assume a missing/disconnected module's state may be deleted. Snapshot restores keep blocks absent from the saved snapshot.
5. Block data and Template Bridge templates belong to body/muscle-memory functionality. Provenance, associative/sequential memory, SHA thread, ping/observation and Jumpcore belong to mind workstreams and must not be quietly grafted into Shared Field.
6. Default paths are portable. Avoid absolute drive letters/user folders in core code.

## Precisely what code guarantees today

- `register_block` does not overwrite an existing code.
- `update_block` recursively merges maps and replaces scalar/list values; an explicit `replace=True` replaces one entire block.
- `set_block_value` changes a nested path atomically.
- SQLite transactions serialize writes and increment a revision counter.
- Reader-controlled `wait_for_change` polls for new revisions; it does not push callbacks.
- Snapshot application changes captured blocks but preserves uncaptured blocks; captured block contents are replaced exactly.
- There is no automatic ownership/authentication check; a process with DB access can update any block.

## Security and operational boundaries

- **Private repo only** for original source. Do not mirror or fork into public repositories.
- Never commit `*.sqlite3*`, live snapshot JSON, API keys, user-specific scripts, memory data, logs, compiled caches or customer software unless explicitly reviewed and scrubbed.
- Connection codes are names, **not access control tokens**. Credential management and trusted plugin interfaces remain future work.
- Shell/Python execution under First Touch must have explicit approval and scoped permissions when connected. The current UI saves drafts only.
- In future robotics integration, use independent safety mechanisms, tested actuator constraints and user-observable emergency-stop behavior.
- GitHub source history is not a backup of persistent live Resident experience or Shared Field SQLite runtime state. Back those up separately.

## Future compatibility still requires care

A self-describing storage format reduces the need to redesign a field when a new module is attached. It does **not** guarantee old code will run unchanged on new OS/Python/hardware, nor that future modules interpret old fields correctly. Compatibility tests and stable protocols are part of preserving the legacy.
