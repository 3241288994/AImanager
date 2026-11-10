"""Offline OS-boundary regressions; live process identity also runs on macOS."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_collab import native, processes, providers
from ai_collab.config import CollabError, defaults


class MacCompatibilityTest(unittest.TestCase):
    def test_process_birth_identity_is_real_and_disappears_after_exit(self):
        identity = processes.process_identity(os.getpid())
        self.assertIsInstance(identity, str)
        self.assertEqual(processes.process_identity(os.getpid()), identity)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            self.assertIsInstance(processes.process_identity(child.pid), str)
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertIsNone(processes.process_identity(child.pid))

    def test_darwin_requires_complete_pidinfo_and_checks_identity_and_zombies(self):
        self.assertEqual(ctypes.sizeof(processes.BsdInfo), 136)
        info = processes.BsdInfo(pid=123, status=2, start_seconds=100, start_microseconds=456)
        def probe(pid, flavor, argument, target, size):
            self.assertEqual((pid, flavor, size), (123, 3, 136))
            ctypes.memmove(target, ctypes.byref(info), size)
            return size
        with mock.patch.object(processes.sys, 'platform', 'darwin'), \
                mock.patch.object(processes, 'darwin_pidinfo', return_value=probe):
            self.assertEqual(processes.process_identity(123), 'darwin:100:456')
            info.status = 5
            self.assertIsNone(processes.process_identity(123))
            info.status, info.pid = 2, 124
            self.assertIsNone(processes.process_identity(123))
        with mock.patch.object(processes.sys, 'platform', 'darwin'), \
                mock.patch.object(processes, 'darwin_pidinfo', return_value=lambda *_: 0):
            self.assertIsNone(processes.process_identity(123))

    def test_invalid_pids_are_never_treated_as_live(self):
        for pid in (None, True, -1, 0, '123'):
            self.assertIsNone(processes.process_identity(pid))

    def test_mac_exec_uses_seatbelt_without_linux_dependencies_or_escape_hatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = mock.Mock()
            module.profile_env.return_value = (root, {'HOME': str(root), 'PATH': '/usr/bin:/bin'})
            with mock.patch.object(providers.sys, 'platform', 'darwin'), \
                    mock.patch.object(providers, 'claude_version', return_value='2.1.308'), \
                    mock.patch.object(providers, 'claude_account', return_value=(root, module, {'id': 'a' * 32})), \
                    mock.patch.object(providers.Path, 'is_file', return_value=True), \
                    mock.patch.object(providers.shutil, 'which', return_value=None):
                command, _, _ = providers.claude_command(defaults(), {'model': 'fixture'}, 'a' * 32,
                                                       [{'path': str(root)}], 'exec')
            import json
            sandbox = json.loads(command[command.index('--settings') + 1])['sandbox']
            self.assertTrue(sandbox['enabled'])
            self.assertTrue(sandbox['failIfUnavailable'])
            self.assertFalse(sandbox['allowUnsandboxedCommands'])
            self.assertNotIn('--dangerously-skip-permissions', command)
            self.assertEqual(sandbox['network']['allowedDomains'], [])

    def test_mac_endpoint_override_does_not_rewrite_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'client.env'
            contents = 'GEMINI_WEB_BASE_URL=http://127.0.0.1:16969/v1\nGEMINI_WEB_API_KEY=fixture-only\n'
            path.write_text(contents)
            config = defaults()
            config['geminiWeb'] = {'envFile': str(path), 'baseUrl': 'http://127.0.0.1:6969/v1'}
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(providers.gemini_settings(config), ('http://127.0.0.1:6969/v1', 'fixture-only'))
                config['geminiWeb']['resolvedBaseUrl'] = 'http://127.0.0.1:1234/v1'
                self.assertEqual(providers.gemini_settings(config)[0], 'http://127.0.0.1:1234/v1')
            self.assertEqual(path.read_text(), contents)

    def test_codex_mac_sdk_read_access_preserves_workspace_and_network_boundaries(self):
        for access in ('read', 'exec'):
            with self.subTest(access=access), \
                    mock.patch.object(native.sys, 'platform', 'darwin'), \
                    mock.patch.object(native, 'codex_identity', return_value=(Path('/profile'), 'fixture', 'test')), \
                    mock.patch.object(native, 'binary', return_value='/opt/codex/bin/codex'), \
                    mock.patch.object(native.Path, 'is_dir', return_value=True):
                command, _, _ = native.codex_command(defaults(), {'model': 'fixture'}, 'fixture', access,
                                                     [{'path': '/prepared-project'}])
            profile = next(arg for arg in command if arg.startswith('permissions.ai_collab.filesystem='))
            self.assertIn('"/Library/Developer/CommandLineTools"="read"', profile)
            self.assertIn('"/Applications/Xcode.app/Contents/Developer"="read"', profile)
            self.assertIn('":workspace_roots"="' + ('write' if access == 'exec' else 'read') + '"', profile)
            self.assertIn('permissions.ai_collab.network.enabled=false', command)

    def test_codex_linux_does_not_gain_mac_developer_paths(self):
        with mock.patch.object(native.sys, 'platform', 'linux'), \
                mock.patch.object(native, 'codex_identity', return_value=(Path('/profile'), 'fixture', 'test')), \
                mock.patch.object(native, 'binary', return_value='/opt/codex/bin/codex'), \
                mock.patch.object(native.Path, 'is_dir', return_value=True):
            command, _, _ = native.codex_command(defaults(), {'model': 'fixture'}, 'fixture', 'exec',
                                                 [{'path': '/prepared-project'}])
        self.assertFalse(any('CommandLineTools' in arg or 'Xcode.app' in arg for arg in command))


if __name__ == '__main__':
    unittest.main()
