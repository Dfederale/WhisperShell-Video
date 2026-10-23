"""Standard-library smoke/regression tests for WhisperShell Steps 01-04.

Run: python -m unittest discover -s tests -v
Creates isolated temporary DB/profile directories. Does not touch real user state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))
import shared_field as field  # noqa: E402
import template_bridge as bridge  # noqa: E402


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "shared_field.sqlite3"

    def test_blocks_create_expand_nesting_and_stable_identity(self):
        self.assertEqual(field.register_block("DINS.TEST.FIRST_SIGHT", {
            "capabilities": {"ocr": True}, "owner": "first_sight", "buttons": []}, path=self.db)["owner"],
            "first_sight")
        before = field.revision(self.db)
        field.register_block("DINS.TEST.FIRST_SIGHT", {"wrong": True}, path=self.db)
        self.assertEqual(before, field.revision(self.db))
        field.update_block("DINS.TEST.FIRST_SIGHT", {"capabilities": {"markers": True}}, path=self.db)
        block = field.get_block("DINS.TEST.FIRST_SIGHT", path=self.db)
        self.assertTrue(block["capabilities"]["ocr"])
        self.assertTrue(block["capabilities"]["markers"])
        self.assertNotIn("wrong", block)
        self.assertEqual(block["owner"], "first_sight")

    def test_module_blocks_do_not_collide(self):
        field.update_block("DINS.TEST.ROBOT", {"forward": "wheels"}, path=self.db)
        field.update_block("DINS.TEST.DESKTOP", {"forward": "scroll"}, path=self.db)
        self.assertEqual(field.get_block("DINS.TEST.ROBOT", path=self.db)["forward"], "wheels")
        self.assertEqual(field.get_block("DINS.TEST.DESKTOP", path=self.db)["forward"], "scroll")

    def test_nested_value_and_replace_affect_only_owner(self):
        field.register_block("DINS.TEST.A", {"a": 1}, path=self.db)
        field.register_block("DINS.TEST.B", {"keep": True}, path=self.db)
        field.set_block_value("DINS.TEST.A", ["capabilities", "ocr", "enabled"], True, path=self.db)
        field.update_block("DINS.TEST.A", {"new": 2}, path=self.db, replace=True)
        self.assertEqual(field.get_block("DINS.TEST.A", path=self.db), {"new": 2})
        self.assertEqual(field.get_block("DINS.TEST.B", path=self.db), {"keep": True})

    def test_snapshot_restores_old_and_preserves_future_blocks(self):
        field.register_block("DINS.TEST.OLD", {"v": 1}, path=self.db)
        snapshot = field.load_field(self.db)
        field.update_block("DINS.TEST.OLD", {"v": 99}, path=self.db)
        field.update_block("DINS.TEST.NEW", {"n": "future"}, path=self.db)
        changed_rev = field.revision(self.db)
        applied = field.apply_snapshot(snapshot, path=self.db)
        self.assertGreater(applied, changed_rev)
        self.assertEqual(field.get_block("DINS.TEST.OLD", path=self.db)["v"], 1)
        self.assertEqual(field.get_block("DINS.TEST.NEW", path=self.db)["n"], "future")

    def test_legacy_state_and_validation(self):
        field.write_field(path=self.db, new_commands=[["first_sight"]], new_action_map={"click": "touch"})
        self.assertEqual(field.load_field(self.db)["commands"], [["first_sight"]])
        with self.assertRaises((TypeError, ValueError)):
            field.update_block("DINS.TEST.INVALID", {"not_json": {4}}, path=self.db)
        with self.assertRaises(ValueError):
            field.register_block("bad\ncode", {}, path=self.db)

    def test_revision_watcher(self):
        rev = field.revision(self.db)
        self.assertIsNone(field.wait_for_change(rev, path=self.db, timeout=0.01))
        field.register_block("DINS.TEST.NEW", {}, path=self.db)
        update = field.wait_for_change(rev, path=self.db, timeout=0.1)
        self.assertIn("DINS.TEST.NEW", update["blocks"])

    def test_parallel_distinct_modules(self):
        errors = []
        def worker(n):
            try:
                field.register_block(f"DINS.TEST.{n}", {"value": n}, path=self.db)
                field.update_block(f"DINS.TEST.{n}", {"nested": {"n": n}}, path=self.db)
            except Exception as exc:
                errors.append(str(exc))
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(60)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors, errors)
        self.assertEqual(len(field.load_field(self.db)["blocks"]), 60)

    def test_template_bridge_captures_all_blocks(self):
        field.register_block("DINS.TEST.OLD", {"setting": 1}, path=self.db)
        with patch.object(bridge, "TEMPLATES", self.root / "templates"):
            with patch.dict(os.environ, {"WHISPERSHELL_FIELD_DB": str(self.db)}):
                name = bridge.save_profile("robotics")
                self.assertTrue(name.is_file())
                self.assertEqual(bridge.read_profile("robotics")["field"]["blocks"]["DINS.TEST.OLD"], {"setting": 1})
                field.update_block("DINS.TEST.OLD", {"setting": 3}, path=self.db)
                field.update_block("DINS.TEST.FUTURE", {"setting": 4}, path=self.db)
                bridge.apply_profile("robotics")
                self.assertEqual(field.get_block("DINS.TEST.OLD", path=self.db)["setting"], 1)
                self.assertEqual(field.get_block("DINS.TEST.FUTURE", path=self.db)["setting"], 4)

    def test_master_blueprint_archive_and_provenance(self):
        plan_path = ROOT / "architecture" / "blueprint.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(len(plan["diagram_index"]), 10)
        self.assertGreaterEqual(len(plan["components"]), 30)
        for row in plan["diagram_index"]:
            self.assertTrue((ROOT / row["file"]).is_file(), row["file"])
        modules = {row["id"]: row for row in plan["components"]}
        self.assertEqual(modules["first_mind"]["region"], "support")
        self.assertEqual(modules["sha_thread"]["region"], "mind")
        self.assertEqual(modules["first_ache"]["phase"], "designed")
        self.assertIsNone(modules["first_sight"]["connection_code"])
        self.assertEqual(modules["orchestrator"]["connection_code"],
                         "DINS.WHISPERSHELL.ORCHESTRATOR")

    def test_blueprint_audit_and_headless_status(self):
        env = dict(os.environ, WHISPERSHELL_FIELD_DB=str(self.db))
        audit = subprocess.run([sys.executable, str(ROOT / "tools" / "blueprint_audit.py")],
                               env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(audit.returncode, 0, audit.stderr)
        self.assertEqual(json.loads(audit.stdout)["issues"], 0)
        info = subprocess.run([sys.executable, str(ROOT / "WhisperShell.py"), "--blueprint"],
                              env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(info.returncode, 0, info.stderr)
        inventory = json.loads(info.stdout)
        self.assertEqual(inventory["diagrams_archived"], 10)
        by_id = {row["id"]: row for row in inventory["components"]}
        self.assertTrue(by_id["shared_field"]["source_file_present"])
        self.assertFalse(by_id["first_sight"]["source_file_present"])

    def test_blueprint_is_read_only_and_does_not_activate_modules(self):
        env = dict(os.environ, WHISPERSHELL_FIELD_DB=str(self.db))
        run = subprocess.run([sys.executable, str(ROOT / "tools" / "blueprint_audit.py")],
                             env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(self.db.exists(), "Read-only audit must not initialize Shared Field")

    def test_cli_block_builder_and_orchestrator_status(self):
        env = dict(os.environ, WHISPERSHELL_FIELD_DB=str(self.db))
        tool = ROOT / "tools" / "block_builder.py"
        def cli(*args):
            return subprocess.run([sys.executable, str(tool), *args], env=env,
                                  capture_output=True, text=True, timeout=10)
        self.assertEqual(cli("create", "DINS.TEST.CLI", "--json", '{"capabilities":{}}').returncode, 0)
        self.assertEqual(cli("create", "DINS.TEST.CLI").returncode, 2)
        self.assertEqual(cli("expand", "DINS.TEST.CLI", "--json", '{"capabilities":{"ping":true}}').returncode, 0)
        self.assertEqual(cli("set", "DINS.TEST.CLI", "capabilities.depth", "7").returncode, 0)
        self.assertIn("DINS.TEST.CLI", cli("list").stdout)
        self.assertEqual(field.get_block("DINS.TEST.CLI", path=self.db)["capabilities"]["depth"], 7)
        status = subprocess.run([sys.executable, str(ROOT / "WhisperShell.py"), "--status"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("orchestrator", json.loads(status.stdout))


if __name__ == "__main__":
    unittest.main()
