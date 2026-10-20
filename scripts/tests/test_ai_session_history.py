import importlib.util
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
SOURCE = BASE / "crates/service/src/ai_accounts"
spec = importlib.util.spec_from_file_location("session_history", SOURCE / "session_history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)
SID = "12345678-1234-4321-abcd-123456789abc"


class SessionHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "profiles" / ("a" * 32) / "home"
        self.logs = self.home / ".claude/projects/example"
        self.logs.mkdir(parents=True)
        self.account = {"id": "a" * 32, "provider": "claude"}

    def transcript(self, path=None):
        path = path or self.logs / (SID + ".jsonl")
        path.write_text(json.dumps({"type": "user", "sessionId": SID, "cwd": str(self.root),
                                   "message": {"content": "First prompt"}}) + "\n" +
                        json.dumps({"type": "assistant", "message": {"content": "PRIVATE_RESPONSE"}}))
        return path

    def test_claude_metadata_and_account_pinned_resume(self):
        self.transcript()
        result = history.catalog(self.root, self.account, self.home)
        item = result["items"][0]
        self.assertEqual(item["title"], "First prompt")
        self.assertEqual(item["visibility"], "ready")
        self.assertIn("--resume " + SID, item["resumeCommand"])
        self.assertIn("--account-id " + self.account["id"], item["resumeCommand"])
        self.assertNotIn("PRIVATE_RESPONSE", json.dumps(result))
        self.assertEqual(history.catalog(self.root, self.account, self.home, "no match")["total"], 0)

    def test_symlinks_and_other_accounts_are_excluded(self):
        outside = self.transcript(self.root / "outside.jsonl")
        (self.logs / (SID + ".jsonl")).symlink_to(outside)
        self.assertEqual(history.catalog(self.root, self.account, self.home)["total"], 0)
        (self.logs / (SID + ".jsonl")).unlink()
        self.logs.rmdir()
        self.logs.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(history.catalog(self.root, self.account, self.home)["total"], 0)

    def test_scan_bound_reports_partial(self):
        self.transcript()
        with patch.object(history, "MAX_FILES", 0):
            self.assertTrue(history.catalog(self.root, self.account, self.home)["coverage"]["partial"])

    def test_missing_workspace_and_shell_quoting(self):
        cwd = str(self.root / "missing ' $(touch SHOULD_NOT_EXIST)")
        item = history.entry(self.root, self.account, SID, "", cwd, 0, "test")
        self.assertEqual(item["visibility"], "missing_workspace")
        tokens = shlex.split(item["resumeCommand"])
        self.assertEqual(tokens[:3], ["cd", "--", cwd])
        self.assertIsNone(history.entry(self.root, self.account, "--bad", "", None, 0, "test"))

    def test_antigravity_readonly_index_search_and_native_flag(self):
        self.account["provider"] = "antigravity"
        db = self.home / ".gemini/antigravity-cli/conversation_summaries.db"
        db.parent.mkdir(parents=True)
        with sqlite3.connect(db) as c:
            c.execute("create table conversation_summaries(conversation_id text,title text,workspace_uris text,last_modified_time text)")
            c.execute("insert into conversation_summaries values(?,?,?,?)",
                      (SID, "Agy session", json.dumps([self.root.as_uri()]), "2026-10-20T10:00:00Z"))
        before = db.read_bytes()
        result = history.catalog(self.root, self.account, self.home, "Agy")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["cwd"], str(self.root))
        self.assertIn("--conversation " + SID, result["items"][0]["resumeCommand"])
        self.assertEqual(before, db.read_bytes())
        self.assertEqual(history.catalog(self.root, self.account, self.home, "' OR 1=1")["total"], 0)

    def test_empty_index_is_not_a_fake_session(self):
        self.account["provider"] = "antigravity"
        result = history.catalog(self.root, self.account, self.home)
        self.assertEqual(result["items"], [])
        self.assertTrue(result["continueCommand"].endswith("--continue"))

    def test_invalid_bounds(self):
        for limit in [0, 501, True, "100"]:
            with self.assertRaises(ValueError):
                history.catalog(self.root, self.account, self.home, limit=limit)
        with self.assertRaises(ValueError):
            history.catalog(self.root, self.account, self.home, "x" * 201)

    def test_launcher_pins_nonactive_account_without_switching_default(self):
        # Exercise both actual launcher and actual worker; native CLI is a harmless fixture.
        fake = self.root / "native"
        fake.write_text("#!/usr/bin/env python3\nimport os,sys,json\nprint(json.dumps({'home':os.environ['HOME'],'args':sys.argv[1:]}))\n")
        fake.chmod(0o700)
        (self.root / "worker.py").write_bytes((SOURCE / "worker.py").read_bytes())
        other = {"id": "b" * 32, "provider": "claude"}
        registry = {"accounts": [self.account, other], "active": {"claude": other["id"]}}
        (self.root / "accounts.json").write_text(json.dumps(registry))
        env = {**os.environ, "AIMANAGER_STATE_DIR": str(self.root), "AIMANAGER_CLAUDE_BIN": str(fake)}
        args = [sys.executable, str(BASE / "scripts/aimanager-cli"), "claude", "--account-id", self.account["id"], "--", "--resume", SID]
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=5, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["home"], str(self.home))
        self.assertEqual(data["args"], ["--resume", SID])
        self.assertEqual(json.loads((self.root / "accounts.json").read_text())["active"], registry["active"])
        args[2] = "antigravity"
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different CLI", result.stderr)


if __name__ == "__main__":
    unittest.main()
