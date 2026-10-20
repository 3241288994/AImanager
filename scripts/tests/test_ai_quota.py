"""Quota discovery must preserve provenance and never fabricate availability."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("worker_quota", Path(__file__).resolve().parents[2] / "crates/service/src/ai_accounts/worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class QuotaTest(unittest.TestCase):
    def test_null_invalid_and_boolean_values_are_not_zero(self):
        self.assertEqual(worker.claude_quota_windows({"five_hour": None, "seven_day": {"utilization": True}, "seven_day_opus": {"utilization": -1}}), [])
        self.assertEqual(worker.claude_quota_windows({"five_hour": {"utilization": float('nan')}}), [])

    def test_official_window_and_reset_are_preserved(self):
        items = worker.claude_quota_windows({"five_hour": {"utilization": 0}, "seven_day": {"utilization": 12.5, "resets_at": "2026-10-26T21:00:00Z"}})
        self.assertEqual([i['remainingPercent'] for i in items], [100, 87.5])
        self.assertEqual(items[1]['resetsAt'], '2026-10-26T21:00:00Z')

    def test_terminal_column_movement_preserves_word_boundaries(self):
        self.assertTrue(worker.confirmation_prompt(worker.strip_terminal('Choose\x1b[9Gthe\x1b[13Gtext\x1b[18Gstyle')))

    def test_failed_refresh_preserves_last_success_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = worker.dispatch(root, {"action": "create", "provider": "claude", "label": "Test"})
            home, _ = worker.profile_env(root, item)
            credentials = home / '.claude/.credentials.json'
            credentials.parent.mkdir(exist_ok=True)
            credentials.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'never-export'}}))
            credentials.chmod(0o600)
            old = {"state": "available", "checkedAt": 123, "windows": [{"remainingPercent": 80}]}
            worker.update_account(root, item['id'], quota=old)
            status = {"id": "test", "accountId": item['id']}
            session = root/'test-session'; session.mkdir()
            opener = mock.Mock()
            opener.open.side_effect = HTTPError('https://api.anthropic.com/api/oauth/usage',401,'private-response',{},None)
            with mock.patch('urllib.request.build_opener', return_value=opener):
                self.assertTrue(worker.refresh_claude_quota(root,item,session,status))
            saved = worker.account(root,item['id'])['quota']
            self.assertEqual(saved['checkedAt'],123)
            self.assertEqual(saved['windows'],old['windows'])
            self.assertEqual(saved['reasonCode'],'authorization_required')
            self.assertNotIn('never-export',json.dumps(saved)+json.dumps(status))

    def test_cached_disabled_models_are_not_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            item=worker.dispatch(root,{"action":"create","provider":"claude","label":"Test"})
            home,_=worker.profile_env(root,item)
            p=home/'.claude/.claude.json';p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps({'additionalModelOptionsCache':[{'value':'claude-enabled','label':'Enabled'},{'value':'disabled-model','disabled':True}]}))
            models=worker.refresh_models(root,item)
            self.assertEqual([m['id'] for m in models['items']],['claude-enabled'])
            self.assertEqual(models['source'],'official_cli_cache')

    def test_proxy_environment_is_shared_but_api_credentials_are_not(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'HTTPS_PROXY':'http://127.0.0.1:17987','ANTHROPIC_API_KEY':'private','GOOGLE_API_KEY':'private'}):
            _,env=worker.profile_env(Path(directory),{'id':'a'*32,'provider':'claude'})
            self.assertEqual(env['HTTPS_PROXY'],'http://127.0.0.1:17987')
            self.assertNotIn('ANTHROPIC_API_KEY',env)
            self.assertNotIn('GOOGLE_API_KEY',env)

if __name__ == '__main__':
    unittest.main()
