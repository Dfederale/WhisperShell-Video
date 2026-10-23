# Expandable Shared Field Blocks: Engineering Manual

**Implementation:** `modules/shared_field.py` (foundation Step 01). **New block creation tools:** `tools/block_builder.py` and the **Block Workshop** tab in `WhisperShell.py` (Step 04).

## 1. The original problem

Legacy WhisperShell's common field used three top-level concepts: `commands`, `action_map`, `permissions`. They helped early modules communicate, but a single flat naming scheme invites collisions: `forward` could mean moving robot wheels, a media player seeking, or navigating a desktop. Rewriting a Python source file just to update shared values also risks losing helpers and introduces races.

We kept the legacy vocabulary as a compatibility section, but introduced **namespace blocks** for new modules. Blocks are not hardware slots and have **no allocated byte size**. They are independently addressed JSON dictionaries in one database.

## 2. The actual storage code

The Shared Field uses Python's **standard-library `sqlite3`**, not a new database engine or a network server. The database is created on first access at `modules/shared_field.sqlite3` by default, right beside `shared_field.py`. `WHISPERSHELL_FIELD_DB` can override its location; most of our runtime stays within one relocatable parent folder.

The essential schema in `_connect()` is:

```sql
CREATE TABLE IF NOT EXISTS field_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_legacy (
    key TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_blocks (
    connection_code TEXT PRIMARY KEY, payload TEXT NOT NULL
);
```

`field_meta` holds a monotonically incremented **revision number**; `field_legacy` keeps the original three sections; `field_blocks` maps each module's unique connection code to a JSON payload. Every module can expand its own JSON structure independently. There is **no fixed list of supported modules or a fixed number of block fields**. Practical SQLite/storage/RAM limitations still exist, of course.

Our permanent module identity is the `connection_code` string. Example codes in this manual are illustrative, **not official IDs already assigned to unfinished modules**.

```json
{
  "connection_code": "DINS.EXAMPLE.FIRST_SIGHT",
  "payload": {
    "capabilities": {"ocr": true},
    "buttons": [],
    "settings": {"confidence": 0.8}
  }
}
```

Each code lives in a different row. One module updating `buttons` cannot overwrite the unrelated `DINS.EXAMPLE.FIRST_TOUCH` row.

## 3. How a block is created

In `shared_field.py`, `register_block(connection_code, initial)` validates the code and JSON, opens a SQLite `BEGIN IMMEDIATE` transaction, checks for an existing row, and **inserts only when absent**. It increments `revision` only when it inserts. If the code already exists, registration returns the existing content without overwriting it. This allows a module to register itself each startup and retain its data.

```python
from modules import shared_field

IDENTITY = "DINS.EXAMPLE.FIRST_SIGHT"  # pick once, keep stable
shared_field.register_block(IDENTITY, {
    "capabilities": {"ocr": False},
    "buttons": [],
})
```

This imports fine when the project root is on `sys.path`. Modules run directly from `modules/` may use `import shared_field` instead. Connection codes are **addresses, not passwords**.

## 4. How a block expands

`update_block(code, changes)` uses a recursive dictionary merge (`_merge`). Existing keys not mentioned in `changes` survive. New keys are added, including arbitrarily nested dictionaries. Lists/scalars are replaced as whole values. The update and revision increment happen in **one SQLite write transaction**.

```python
shared_field.update_block(IDENTITY, {
    "capabilities": {"ocr": True, "screen_regions": True},
    "buttons": [{"label": "Open", "x": 531, "y": 395}],
})
```

A later version can introduce `capabilities.screen_regions` without touching `settings`, unrelated modules, or `shared_field.py` source.

For a single nested path, use `set_block_value()`:

```python
shared_field.set_block_value(
    IDENTITY, ["capabilities", "tracking", "enabled"], True
)
```

`update_block()` can also implicitly create a missing row. The private Block Workshop **requires Create first** when the human presses Expand, to avoid accidental identities. `update_block(code, changes, replace=True)` explicitly replaces only that module's block. It does not replace the whole field.

## 5. New block creation system, from the GUI

1. Launch `python WhisperShell.py` and select **Block Workshop**.
2. Set a **permanent module connection code** (example: `DINS.MODULE.ROBOT_ARM_V1`). Establish a naming registry before shipping customer modules, since renaming after distribution requires migration.
3. Enter a JSON **object**, for example `{"capabilities":{"grip":false},"settings":{}}`.
4. Click **Create new block**. An existing code is not overwritten.
5. When a module gains features, enter only the new or updated nested values and click **Expand existing**. This recursively merges with the old block.
6. Use **Inspect** or **List all** to see actual current state. No Template Bridge action is required for live updates.
7. In **Original Builder**, click **Capture complete profile** when you want to preserve the current entire Shared Field. A profile is a snapshot, not the live communication channel.

Block Workshop is a **private maintenance interface**, not a customer feature and not an authenticator. The UI has not yet been smoke-tested on a Windows display.

## 6. New block creation system, from the console

All commands resolve the actual Shared Field Python module relative to the project directory. There is no duplicate block store.

```powershell
python tools/block_builder.py list
python tools/block_builder.py create DINS.MODULE.ROBOT_ARM_V1 --json '{"capabilities":{"grip":false}}'
python tools/block_builder.py show DINS.MODULE.ROBOT_ARM_V1
python tools/block_builder.py expand DINS.MODULE.ROBOT_ARM_V1 --json '{"capabilities":{"grip":true,"rotate":true}}'
python tools/block_builder.py set DINS.MODULE.ROBOT_ARM_V1 settings.speed 0.25
```

The quoted examples work in modern PowerShell, though shell quoting can vary in other terminals. The `set` command's final value is **JSON**, so plain words must be quoted as JSON strings. Use `--db <file>` before the subcommand to operate on an isolated test database, not the live one.

## 7. How live information reaches modules

Shared Field publishes committed values to the **same on-disk database**. `revision()` returns the current change number. `wait_for_change(previous_revision, timeout=..., interval=...)` polls for an increased revision, then returns a fresh complete state. A module can also call `get_block(code)` whenever it needs fresh values.

**Important technical distinction:** This is **polling**, not automatic OS push notifications. Legacy globals `commands`, `action_map`, and `permissions` are **point-in-time copies** when imported; old consumers must refresh or read the live field to see subsequent updates. The architecture supports independent processes because each uses SQLite, not shared Python globals.

Every module should update **its own block** only. The current library does not cryptographically verify ownership; this is a coding convention today and a security feature to design for untrusted customer plugins later.

## 8. How Template Bridge relates to the blocks

`modules/template_bridge.py` saves `templates/<profile>/shared_field.json`, containing **all** legacy sections and **all** blocks known at capture time, even if their owner module is disconnected.

On `apply_profile()`, each captured block's contents are restored atomically through `shared_field.apply_snapshot()`; **blocks created after the snapshot remain present**. This is a deliberate merge-preserving policy for unknown future modules. Keys added later *inside a block that is included in the old snapshot* are removed because that included block is replaced with its captured contents. This distinction matters: the bridge is not an automatic version migrator.

Sample commands:

```powershell
python -m modules.template_bridge --list
python -m modules.template_bridge --save robotics
python -m modules.template_bridge --apply robotics
```

From the main folder, `python modules/template_bridge.py --save robotics` also works. Profiles do not directly control modules or translate screen mappings; **Shared Field is responsible for shared live state**.

## 9. What expandable does and does not guarantee

**It does:** add modules, expand nested configuration/state, keep separate module namespaces, allow older blocks to survive alongside new ones, retain disconnected module blocks, offer a stable module discovery address, and avoid rewriting Shared Field code for new fields.

**It does not automatically:** understand new semantics; translate old API commands; guarantee future Python/OS binary compatibility; stop unauthorized local processes changing a block; validate arbitrary user-defined block schemas; detect payload conflicts inside one owner's block; or synchronize devices over the internet. Those are separate engineering concerns.

## 10. Repeatable regression check

Run `python -m unittest discover -s tests -v`. The tests exercise namespaced identity, growth, atomic write behavior under parallel activity, nested writes, snapshot restore that retains absent new blocks, revision polling, legacy compatibility and the CLI. A passed test verifies these specific behaviors, **not** unbuilt AI/robotics capabilities.
