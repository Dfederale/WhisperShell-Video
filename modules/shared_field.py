"""WhisperShell Shared Field | common language for all builds.

LIVE: modules publish and read shared state through this one module.
PRESERVE: Template Bridge captures/restores snapshots through this module.

Blocks have stable connection codes (namespaces), no predetermined size, and
may grow by adding new keys or nested dictionaries. A module updates only its
own block. A connection code is an address, NOT an authentication secret.

Portable standard-library SQLite stores live state beside this .py. It allows
multiple Python processes to update different blocks atomically, without
rewriting executable code. No LLM, external server, or extra dependency needed.

Legacy vocabulary (commands, action_map, permissions) remains for the old
WhisperShell modules. New modules should use blocks to avoid keyword collisions.
Old modules that import these globals get a point-in-time COPY; they must call
load_field()/get_block() or wait_for_change() for ongoing synchronization.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping

FIELD_PATH = Path(__file__).resolve()
DEFAULT_DB = FIELD_PATH.with_name("shared_field.sqlite3")
LEGACY_KEYS = ("commands", "action_map", "permissions")


def _database(path: str | Path | None = None) -> Path:
    if path is None:
        target = Path(os.environ.get("WHISPERSHELL_FIELD_DB", str(DEFAULT_DB)))
    else:
        target = Path(path)
    if target.suffix.lower() == ".py":
        raise ValueError("Shared Field never overwrites a .py file. Use the shared database.")
    return target.expanduser().resolve()


def _json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise TypeError("Shared Field values must be JSON-compatible") from exc


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = _database(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=15.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS field_meta (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS field_legacy (
            key TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS field_blocks (
            connection_code TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
        conn.execute("INSERT OR IGNORE INTO field_meta VALUES ('revision', '0')")
        for key, initial in (("commands", []), ("action_map", {}), ("permissions", {})):
            conn.execute("INSERT OR IGNORE INTO field_legacy VALUES (?, ?)",
                         (key, _json(initial)))
    except BaseException:
        conn.close()
        raise
    return conn


def _tick(conn: sqlite3.Connection) -> int:
    conn.execute("UPDATE field_meta SET value = CAST(value AS INTEGER) + 1 "
                 "WHERE key = 'revision'")
    return int(conn.execute("SELECT value FROM field_meta WHERE key='revision'").fetchone()[0])


def _read(conn: sqlite3.Connection) -> dict[str, Any]:
    base = {key: json.loads(payload)
            for key, payload in conn.execute("SELECT key, payload FROM field_legacy")}
    blocks = {code: json.loads(payload)
              for code, payload in conn.execute("SELECT connection_code, payload FROM field_blocks")}
    revision = int(conn.execute("SELECT value FROM field_meta WHERE key='revision'").fetchone()[0])
    return {"commands": base.get("commands", []),
            "action_map": base.get("action_map", {}),
            "permissions": base.get("permissions", {}),
            "blocks": blocks, "revision": revision}


def load_field(path: str | Path | None = None) -> dict[str, Any]:
    """Read one consistent view of the complete live field from disk."""
    conn = _connect(path)
    try:
        conn.execute("BEGIN")
        result = _read(conn)
        conn.execute("COMMIT")
        return result
    finally:
        conn.close()


def snapshot() -> dict[str, Any]:
    """Detached, JSON-compatible full-state snapshot for Template Bridge."""
    return load_field()


def revision(path: str | Path | None = None) -> int:
    """Monotonic local change counter; NOT a cryptographic SHA."""
    conn = _connect(path)
    try:
        return int(conn.execute("SELECT value FROM field_meta WHERE key='revision'").fetchone()[0])
    finally:
        conn.close()


def _code(connection_code: str) -> str:
    if not isinstance(connection_code, str):
        raise TypeError("connection_code must be a string")
    code = connection_code.strip()
    if not code or len(code) > 200 or any(c in code for c in "\r\n\x00"):
        raise ValueError("connection_code must be a stable nonempty module identifier")
    return code


def _merge(old: dict[str, Any], new: Mapping[str, Any]) -> None:
    """Merge dictionaries recursively; preserve unrelated keys, replace list values."""
    for key, val in new.items():
        if not isinstance(key, str):
            raise TypeError("Block keys must be strings")
        if isinstance(val, dict) and isinstance(old.get(key), dict):
            _merge(old[key], val)
        else:
            old[key] = copy.deepcopy(val)


def register_block(connection_code: str, initial: Mapping[str, Any] | None = None,
                   *, path: str | Path | None = None) -> dict[str, Any]:
    """Make a block if absent; NEVER overwrite a previously registered block."""
    code = _code(connection_code)
    payload = dict(initial or {})
    _json(payload)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM field_blocks WHERE connection_code=?", (code,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO field_blocks VALUES (?, ?)", (code, _json(payload)))
            _tick(conn)
            result = payload
        else:
            result = json.loads(row[0])
        conn.execute("COMMIT")
        return copy.deepcopy(result)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_block(connection_code: str, *, path: str | Path | None = None,
              default: Any = None) -> Any:
    """Read the latest state of one module, or default when not registered."""
    conn = _connect(path)
    try:
        row = conn.execute("SELECT payload FROM field_blocks WHERE connection_code=?",
                           (_code(connection_code),)).fetchone()
        return json.loads(row[0]) if row else copy.deepcopy(default)
    finally:
        conn.close()


def update_block(connection_code: str, changes: Mapping[str, Any], *,
                 path: str | Path | None = None, replace: bool = False) -> dict[str, Any]:
    """Create/expand a module block atomically, touching no other module block.

    replace=False recursively extends existing dictionaries (default).
    replace=True deliberately replaces ONLY this block, e.g. snapshot restoration.
    """
    code = _code(connection_code)
    if not isinstance(changes, Mapping):
        raise TypeError("A block update must be a mapping")
    updates = dict(changes)
    _json(updates)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM field_blocks WHERE connection_code=?", (code,)).fetchone()
        result = {} if replace or row is None else json.loads(row[0])
        if replace:
            result = copy.deepcopy(updates)
        else:
            _merge(result, updates)
        conn.execute("INSERT INTO field_blocks VALUES (?, ?) ON CONFLICT(connection_code) "
                     "DO UPDATE SET payload=excluded.payload", (code, _json(result)))
        _tick(conn)
        conn.execute("COMMIT")
        return copy.deepcopy(result)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def set_block_value(connection_code: str, keys: str | list[str] | tuple[str, ...],
                    value: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    """Update one nested key atomically, without changing adjacent keys."""
    code = _code(connection_code)
    parts = [keys] if isinstance(keys, str) else list(keys)
    if not parts or any(not isinstance(k, str) or not k for k in parts):
        raise ValueError("keys must be nonempty strings")
    _json(value)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM field_blocks WHERE connection_code=?", (code,)).fetchone()
        block = json.loads(row[0]) if row else {}
        node = block
        for key in parts[:-1]:
            if key not in node:
                node[key] = {}
            if not isinstance(node[key], dict):
                raise TypeError("Cannot descend into non-dictionary block value: " + key)
            node = node[key]
        node[parts[-1]] = copy.deepcopy(value)
        conn.execute("INSERT INTO field_blocks VALUES (?, ?) ON CONFLICT(connection_code) "
                     "DO UPDATE SET payload=excluded.payload", (code, _json(block)))
        _tick(conn)
        conn.execute("COMMIT")
        return copy.deepcopy(block)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def write_field(path: str | Path | None = None, *,
                new_commands: list[list[str]] | None = None,
                new_action_map: dict[str, dict[str, Any]] | None = None,
                new_permissions: dict[str, dict[str, Any]] | None = None) -> Path:
    """Legacy bridge for the original three sections. Unspecified data is retained.

    Does NOT rewrite shared_field.py (doing so would erase all these methods).
    """
    changes = {key: value for key, value in (
        ("commands", new_commands), ("action_map", new_action_map),
        ("permissions", new_permissions)) if value is not None}
    if not changes:
        return _database(path)
    for key, value in changes.items():
        if key == "commands" and not isinstance(value, list):
            raise TypeError("commands must be a list")
        if key != "commands" and not isinstance(value, dict):
            raise TypeError(key + " must be a dictionary")
        _json(value)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in changes.items():
            conn.execute("INSERT INTO field_legacy VALUES (?, ?) ON CONFLICT(key) "
                         "DO UPDATE SET payload=excluded.payload", (key, _json(value)))
        _tick(conn)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    if path is None:
        refresh_legacy_globals()
    return _database(path)


def replace_field(*, new_commands: list[list[str]] | None = None,
                  new_action_map: dict[str, dict[str, Any]] | None = None,
                  new_permissions: dict[str, dict[str, Any]] | None = None) -> None:
    """Backward-compatible name for updating only supplied legacy sections."""
    write_field(new_commands=new_commands, new_action_map=new_action_map,
                new_permissions=new_permissions)


def apply_snapshot(state: Mapping[str, Any], *, path: str | Path | None = None) -> int:
    """Apply a captured/default state as one transaction (for Template Bridge).

    Sections ABSENT from the input are untouched. Each included block is
    replaced with its captured value; blocks absent from the template are
    retained, so a contest template cannot erase unrelated/new modules.
    """
    if not isinstance(state, Mapping):
        raise TypeError("state must be a mapping")
    legacy = {key: state[key] for key in LEGACY_KEYS if key in state}
    blocks = state.get("blocks", {})
    if not isinstance(blocks, Mapping) or any(not isinstance(x, Mapping) for x in blocks.values()):
        raise TypeError("snapshot blocks must map connection codes to dictionaries")
    for code in blocks:
        _code(code)
    for v in legacy.values():
        _json(v)
    for v in blocks.values():
        _json(dict(v))
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in legacy.items():
            conn.execute("INSERT INTO field_legacy VALUES (?, ?) ON CONFLICT(key) "
                         "DO UPDATE SET payload=excluded.payload", (key, _json(value)))
        for code, value in blocks.items():
            conn.execute("INSERT INTO field_blocks VALUES (?, ?) ON CONFLICT(connection_code) "
                         "DO UPDATE SET payload=excluded.payload", (code, _json(dict(value))))
        new_revision = _tick(conn) if (legacy or blocks) else int(
            conn.execute("SELECT value FROM field_meta WHERE key='revision'").fetchone()[0])
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    if path is None:
        refresh_legacy_globals()
    return new_revision


def wait_for_change(after_revision: int, *, timeout: float = 1.0,
                    interval: float = 0.05, path: str | Path | None = None
                    ) -> dict[str, Any] | None:
    """Poll for a newer live state; gives modules a simple cross-process sync hook.

    This is NOT a background service. Each module decides when to poll.
    Returns None when no update occurs within timeout seconds.
    """
    end = time.monotonic() + max(0.0, timeout)
    while True:
        if revision(path) > after_revision:
            return load_field(path)
        if time.monotonic() >= end:
            return None
        time.sleep(max(0.0, min(max(0.005, interval), end - time.monotonic())))


def refresh_legacy_globals() -> None:
    """Refresh module-level exports for old import-based consumers in this process."""
    global commands, action_map, permissions
    state = load_field()
    commands = state["commands"]
    action_map = state["action_map"]
    permissions = state["permissions"]


# Compatibility with existing code that imports shared_field.commands at startup.
commands: list[list[str]] = []
action_map: dict[str, dict[str, Any]] = {}
permissions: dict[str, dict[str, Any]] = {}
# Lazy DB access for new calls; old imports should not require a writable disk.
try:
    refresh_legacy_globals()
except (sqlite3.Error, OSError):
    pass
