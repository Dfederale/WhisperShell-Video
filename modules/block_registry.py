

"""WhisperShell block identity registry."""
import argparse
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import shared_field as field

REGISTRY_BLOCK = "DINS.WHISPERSHELL.BLOCK_REGISTRY"
PREFIX = "DINS.WHISPERSHELL.BLOCK."


def normalize_birth(value):
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("Missing timezone")
        return t.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    except (AttributeError, ValueError) as exc:
        raise ValueError("Use a fixed ISO birth timestamp with timezone") from exc


def birth_marker(file):
    file = Path(file)
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        stamp = normalize_birth(datetime.now(timezone.utc).isoformat())
        try:
            with file.open("x", encoding="utf-8") as stream:
                json.dump({"born_utc": stamp}, stream)
        except FileExistsError:
            pass
    return normalize_birth(
        json.loads(file.read_text(encoding="utf-8"))["born_utc"]
    )


def _connect(db):
    conn = field._connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whispershell_block_claims ("
        "requested TEXT NOT NULL, born_utc TEXT NOT NULL, "
        "assigned TEXT NOT NULL UNIQUE, "
        "connection_code TEXT NOT NULL UNIQUE, "
        "PRIMARY KEY(requested,born_utc))"
    )
    return conn


def _mirror(conn):
    claims = [
        {
            "requested_number": r[0],
            "born_utc": r[1],
            "assigned_number": r[2],
            "connection_code": r[3],
        }
        for r in conn.execute(
            "SELECT requested,born_utc,assigned,connection_code "
            "FROM whispershell_block_claims ORDER BY requested,assigned"
        )
    ]
    payload = field._json({"schema": 1, "claims": claims})
    row = conn.execute(
        "SELECT payload FROM field_blocks WHERE connection_code=?",
        (REGISTRY_BLOCK,),
    ).fetchone()
    if row is None or json.loads(row[0]) != json.loads(payload):
        conn.execute(
            "INSERT INTO field_blocks VALUES(?,?) "
            "ON CONFLICT(connection_code) "
            "DO UPDATE SET payload=excluded.payload",
            (REGISTRY_BLOCK, payload),
        )
        return True
    return False


def claim(number, born_utc, initial=None, *, db=None):
    if not isinstance(number, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", number
    ):
        raise ValueError("Invalid block number")

    born = normalize_birth(born_utc)
    if initial is None:
        initial = {}
    if not isinstance(initial, dict):
        raise TypeError("Initial block content must be an object")

    encoded = field._json(initial)
    conn = _connect(db)

    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT payload FROM field_blocks WHERE connection_code=?",
            (REGISTRY_BLOCK,),
        ).fetchone()

        if row:
            mirror = json.loads(row[0])
            if mirror.get("schema") != 1:
                raise ValueError("Incompatible registry mirror")

            for saved in mirror.get("claims", []):
                req = saved["requested_number"]
                birth = saved["born_utc"]
                assigned = saved["assigned_number"]
                code = PREFIX + assigned

                if saved["connection_code"] != code:
                    raise ValueError("Inconsistent snapshot claim")

                current = conn.execute(
                    "SELECT 1 FROM whispershell_block_claims "
                    "WHERE requested=? AND born_utc=?",
                    (req, birth),
                ).fetchone()
                taken = conn.execute(
                    "SELECT 1 FROM whispershell_block_claims "
                    "WHERE assigned=? OR connection_code=?",
                    (assigned, code),
                ).fetchone()

                if not current and not taken:
                    conn.execute(
                        "INSERT INTO whispershell_block_claims "
                        "VALUES(?,?,?,?)",
                        (req, birth, assigned, code),
                    )

        existing = conn.execute(
            "SELECT assigned,connection_code "
            "FROM whispershell_block_claims "
            "WHERE requested=? AND born_utc=?",
            (number, born),
        ).fetchone()

        is_new = existing is None

        if existing:
            assigned, code = existing
        else:
            index = 0
            while True:
                assigned = number if index == 0 else f"{number}-{index}"
                code = PREFIX + assigned

                busy = conn.execute(
                    "SELECT 1 FROM whispershell_block_claims "
                    "WHERE assigned=? OR connection_code=?",
                    (assigned, code),
                ).fetchone()
                occupied = conn.execute(
                    "SELECT 1 FROM field_blocks "
                    "WHERE connection_code=?",
                    (code,),
                ).fetchone()

                if not busy and not occupied:
                    break
                index += 1

            conn.execute(
                "INSERT INTO whispershell_block_claims VALUES(?,?,?,?)",
                (number, born, assigned, code),
            )

        old = conn.execute(
            "SELECT payload FROM field_blocks WHERE connection_code=?",
            (code,),
        ).fetchone()

        if old is None:
            conn.execute(
                "INSERT INTO field_blocks VALUES(?,?)",
                (code, encoded),
            )

        mirror_changed = _mirror(conn)
        if is_new or old is None or mirror_changed:
            field._tick(conn)

        conn.execute("COMMIT")

        return {
            "requested_number": number,
            "born_utc": born,
            "assigned_number": assigned,
            "connection_code": code,
            "new_identity": is_new,
            "block": json.loads(old[0]) if old else initial,
        }

    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def self_test():
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "field.sqlite3"
        births = [
            f"2026-10-22T10:00:00.{i:06d}Z"
            for i in range(1, 21)
        ]

        first = claim("007", births[0], {"original": True}, db=db)

        assert claim(
            "007", births[0], {"original": False}, db=db
        )["assigned_number"] == "007"

        with ThreadPoolExecutor(max_workers=8) as pool:
            found = list(
                pool.map(lambda b: claim("007", b, db=db), births[1:])
            )

        assert set(x["assigned_number"] for x in found) == {
            f"007-{i}" for i in range(1, 20)
        }

        assert field.get_block(
            first["connection_code"], path=db
        ) == {"original": True}

        assert len(
            field.get_block(REGISTRY_BLOCK, path=db)["claims"]
        ) == 20

        new_db = Path(temp) / "restored.sqlite3"
        field.apply_snapshot(field.load_field(db), path=new_db)

        assert claim(
            "007", births[1], db=new_db
        )["assigned_number"] == found[0]["assigned_number"]

    print(
        "PASS: 007 retained, duplicates separated, "
        "restored, concurrent claims unique"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
    else:
        parser.print_help()
