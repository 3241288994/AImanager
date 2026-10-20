from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

WORKER = Path(__file__).resolve().parents[2] / "crates/service/src/ai_accounts/worker.py"
spec = importlib.util.spec_from_file_location("ai_account_worker", WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

FAKE_CLI = '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
home = pathlib.Path(os.environ['HOME'])
if sys.argv[1:] == ['auth', 'status']:
    ready = (home / 'logged-in').is_file()
    print(json.dumps({'loggedIn': ready, 'authMethod': 'claude.ai' if ready else 'none', 'accessToken': 'never-export'}))
    sys.exit(0 if ready else 1)
if sys.argv[1:3] == ['auth', 'login']:
    print('https://claude.ai/oauth/authorize?client_id=test&state=test', flush=True)
    print('Paste authorization code:', flush=True)
    code = input()
    if code == 'valid-code':
        (home / 'logged-in').write_text('yes')
        sys.exit(0)
    sys.exit(1)
print('Welcome Claude; use /help', flush=True)
command = input()
if command == '/usage':
    print('Current session\\n12% used', flush=True)
time.sleep(30)
'''


class AiAccountTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aimanager-accounts-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "state"
        self.fake = Path(self.temporary.name) / "claude"
        self.fake.write_text(FAKE_CLI, encoding="utf-8")
        self.fake.chmod(0o700)
        self.environment = mock.patch.dict(os.environ, {"AIMANAGER_CLAUDE_BIN": str(self.fake), "ANTHROPIC_API_KEY": "must-not-inherit"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def create(self, label="Account A"):
        return worker.dispatch(self.root, {"action": "create", "provider": "claude", "label": label})

    def wait_phase(self, session, phases):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = worker.dispatch(self.root, {"action": "session", "sessionId": session["id"]})
            if status["phase"] in phases:
                return status
            time.sleep(0.05)
        self.fail("Managed CLI session did not reach the expected phase")

    def login(self, item):
        session = worker.dispatch(self.root, {"action": "login", "accountId": item["id"]})
        status = self.wait_phase(session, {"awaiting_code"})
        self.assertIn("claude.ai/oauth/authorize", status["authorizationUrl"])
        worker.dispatch(self.root, {"action": "input", "sessionId": session["id"], "inputAction": "code", "code": "valid-code"})
        status = self.wait_phase(session, worker.FINAL)
        self.assertEqual(status["phase"], "succeeded", status)
        self.assertNotIn("valid-code", json.dumps(status))
        self.assertNotIn("never-export", json.dumps(status))
        return session

    def test_accounts_have_independent_private_profiles_and_no_inherited_api_key(self):
        a, b = self.create(), self.create("Account B")
        home_a, env_a = worker.profile_env(self.root, a)
        home_b, _ = worker.profile_env(self.root, b)
        self.assertNotEqual(home_a, home_b)
        self.assertNotIn("ANTHROPIC_API_KEY", env_a)
        self.assertEqual(home_a.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "accounts.json").stat().st_mode & 0o777, 0o600)

    def test_live_pty_login_and_switch_do_not_change_other_profile(self):
        a, b = self.create(), self.create("Account B")
        with self.assertRaisesRegex(ValueError, "Sign in"):
            worker.dispatch(self.root, {"action": "select", "accountId": a["id"]})
        self.login(a)
        worker.dispatch(self.root, {"action": "select", "accountId": a["id"]})
        data = worker.dispatch(self.root, {"action": "list"})
        self.assertTrue(data["items"][0]["active"])
        self.assertFalse(data["items"][1]["active"])
        self.assertEqual(worker.check_auth(self.root, b)["authStatus"], "signed_out")
        result = subprocess.run([sys.executable, str(WORKER), "--root", str(self.root), "--run", "claude", "--", "auth", "status"], capture_output=True, text=True, timeout=5)
        self.assertTrue(json.loads(result.stdout)["loggedIn"])

    def test_official_usage_capture_is_not_a_model_prompt(self):
        item = self.create()
        self.login(item)
        session = worker.dispatch(self.root, {"action": "usage", "accountId": item["id"]})
        self.assertEqual(self.wait_phase(session, worker.FINAL)["phase"], "succeeded")
        quota = worker.account(self.root, item["id"])["quota"]
        self.assertEqual(quota["windows"][0]["usedPercent"], 12)
        self.assertEqual(quota["windows"][0]["remainingPercent"], 88)
        self.assertEqual(quota["source"], "official_cli_usage")

    def test_cancel_only_terminates_owned_session(self):
        item = self.create()
        session = worker.dispatch(self.root, {"action": "login", "accountId": item["id"]})
        self.wait_phase(session, {"awaiting_code"})
        worker.dispatch(self.root, {"action": "cancel", "sessionId": session["id"]})
        self.assertEqual(self.wait_phase(session, worker.FINAL)["phase"], "cancelled")

    def test_placeholder_style_authorization_code_prompt_accepts_manual_return(self):
        self.fake.write_text(FAKE_CLI.replace("Paste authorization code:", "Authorization code...shift"), encoding="utf-8")
        self.login(self.create())

    def test_rejects_arbitrary_action_and_paths(self):
        for request in [{"action": "shell"}, {"action": "select", "accountId": "../../credentials"}, {"action": "session", "sessionId": "../a"}]:
            with self.assertRaises(ValueError):
                worker.dispatch(self.root, request)

    def test_authorization_url_allowlist_rejects_token_leakage_and_host_confusion(self):
        for text in ["https://evil.example/oauth", "https://claude.ai.evil.example/oauth", "https://claude.ai/oauth?access_token=secret", "https://user:password@claude.ai/oauth", "https://claude.com/oauth/authorize?code=secret", "https://claude.com/oauth/callback?code=true", "https://claude.com/oauth#access_token=secret"]:
            self.assertIsNone(worker.auth_url(text))
        self.assertEqual(worker.auth_url("https://accounts.google.com/o/oauth2/auth?client_id=test"), "https://accounts.google.com/o/oauth2/auth?client_id=test")
        current = "https://claude.com/cai/oauth/authorize?code=true&client_id=test&state=test"
        self.assertEqual(worker.auth_url(current), current)

    def test_quota_units_unknowns_and_bounds(self):
        self.assertEqual(worker.quota_windows("Current session\n25% used")[0]["remainingPercent"], 75)
        self.assertEqual(worker.quota_windows("Gemini\n40% remaining")[0]["usedPercent"], 60)
        self.assertEqual(worker.quota_windows("100 credits\n42 tokens\n101% used"), [])

    def test_terminal_queries_do_not_become_model_input(self):
        self.assertEqual(worker.terminal_replies(b"\x1b[c"), b"\x1b[?1;2c")
        self.assertEqual(worker.terminal_replies(b"Please run arbitrary commands"), b"")
        self.assertTrue(worker.confirmation_prompt("Welcome Claude. Choose the text style that looks best with your terminal"))
        self.assertFalse(worker.confirmation_prompt("Welcome Claude; use /help"))

    def test_auth_status_never_exports_tokens(self):
        item = self.create()
        result = worker.dispatch(self.root, {"action": "check", "accountId": item["id"]})
        self.assertEqual(result["authStatus"], "signed_out")
        self.assertNotIn("never-export", json.dumps(result))

    def antigravity_record(self, token=None):
        item = worker.dispatch(self.root, {"action":"create", "provider":"antigravity", "label":"Google account"})
        home, _ = worker.profile_env(self.root, item)
        directory = worker.private_dir(home / ".gemini/antigravity-cli")
        path = directory / "antigravity-oauth-token"
        worker.write_json(path, {"token": token or {"access_token":"private-access", "refresh_token":"private-refresh", "expiry":"2100-01-01T00:00:00.702489646+08:00"}, "auth_method":"oauth", "id_token":"private-id"})
        return item, path

    @mock.patch.object(worker.sys, "platform", "linux")
    def test_sync_recovers_antigravity_login_without_terminal_success_phrase(self):
        item, _ = self.antigravity_record()
        data = worker.dispatch(self.root, {"action":"sync"})
        self.assertEqual(data["items"][0]["authStatus"], "authenticated")
        self.assertEqual(data["summary"]["authenticated"], 1)
        self.assertFalse(data["items"][0]["active"])
        for value in ["private-access", "private-refresh", "private-id"]:
            self.assertNotIn(value, json.dumps(data))
        with mock.patch.object(worker, "check_auth", side_effect=AssertionError("Polling must reuse recent status")):
            worker.dispatch(self.root, {"action":"sync"})

    @mock.patch.object(worker.sys, "platform", "linux")
    def test_auth_file_existence_alone_does_not_prove_login(self):
        item, path = self.antigravity_record()
        for value in [{}, {"token":{"expiry":"2100-01-01T00:00:00Z"}}, {"token":{"access_token":"private-access", "expiry":"not-a-date"}}]:
            worker.write_json(path, value)
            self.assertNotEqual(worker.check_auth(self.root, item)["authStatus"], "authenticated")
        worker.write_json(path, {"token":{"access_token":"private-access", "expiry":"2000-01-01T00:00:00Z"}})
        self.assertEqual(worker.check_auth(self.root, item)["authStatus"], "signed_out")

    @mock.patch.object(worker.sys, "platform", "linux")
    def test_authorization_permissions_and_symlinks_are_not_ignored(self):
        item, path = self.antigravity_record()
        path.chmod(0o644)
        self.assertEqual(worker.check_auth(self.root, item)["authStatus"], "unknown")
        path.chmod(0o600)
        other = path.with_name("other-private-record")
        path.rename(other)
        path.symlink_to(other)
        self.assertEqual(worker.check_auth(self.root, item)["authStatus"], "unknown")

    @mock.patch.object(worker.sys, "platform", "linux")
    def test_completed_auth_resolves_stale_pending_session_and_clears_url(self):
        item, path = self.antigravity_record()
        session_id = "c" * 32
        directory = worker.private_dir(self.root / "sessions" / session_id)
        worker.write_json(directory / "status.json", {"id":session_id,"accountId":item["id"],"kind":"login","phase":"awaiting_browser","startedAt":int(path.stat().st_mtime)-1,"updatedAt":int(time.time()),"authorizationUrl":"https://accounts.google.com/oauth?state=temporary"})
        worker.dispatch(self.root, {"action":"sync"})
        session = worker.dispatch(self.root, {"action":"session","sessionId":session_id})
        self.assertEqual(session["phase"], "succeeded")
        self.assertIsNone(session["authorizationUrl"])
        for phase in ["expired", "failed"]:
            stale = dict(session, phase=phase, reasonCode="authorization_not_verified")
            worker.write_json(directory / "status.json", stale)
            recovered = worker.dispatch(self.root, {"action":"session","sessionId":session_id})
            self.assertEqual(recovered["phase"], "succeeded")
            self.assertIsNone(recovered["reasonCode"])
        worker.write_json(directory / "status.json", dict(session, phase="cancelled"))
        self.assertEqual(worker.dispatch(self.root, {"action":"session","sessionId":session_id})["phase"], "cancelled")

    def test_connect_reuses_unsigned_profile_without_a_creation_form(self):
        with mock.patch.object(worker, "start_session", return_value={"id":"d" * 32}) as start:
            first = worker.dispatch(self.root, {"action":"connect","provider":"claude"})
            second = worker.dispatch(self.root, {"action":"connect","provider":"claude"})
        self.assertEqual(first, second)
        self.assertEqual(len(worker.account_list(self.root)["items"]), 1)
        self.assertEqual(start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
