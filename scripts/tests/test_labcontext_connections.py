from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from labcontext_connections import (ConnectionError, ConnectionStore,
                                    credential_file, health_address, locked, read_json, write_json)
from labcontext_tunnel_control import TunnelControl


class ConnectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ConnectionStore({"LABCONTEXT_ENV_FILE": str(self.root / "launcher.env"),
                                      "LABCONTEXT_STATUS_FILE": str(self.root / "launcher.json"),
                                      "LABCONTEXT_TUNNEL_PROFILE": "existing"})
        self.secret = self.root / "next.env"
        self.secret.write_text("CONTROL_PLANE_API_KEY=test-only-new-key\n")
        self.secret.chmod(0o600)
        self.profile = {"id": "next", "label": "未来账号", "profile": "future", "healthUrl": "http://127.0.0.1:8080",
                        "credentialMode": "file", "secretFile": str(self.secret)}

    def test_read_does_not_create_or_change_config(self) -> None:
        self.assertFalse(self.store.public()["saved"])
        self.assertEqual(self.store.get()["profile"], "existing")
        self.assertFalse(self.store.catalog_path.exists())

    def test_snapshot_is_private_and_contains_references_only(self) -> None:
        self.store.snapshot()
        self.assertEqual(self.store.catalog_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.get()["id"], "current")
        self.assertNotIn("CONTROL_PLANE_API_KEY", self.store.catalog_path.read_text())
        self.assertFalse((self.root / "launcher.env").exists())

    def test_registration_does_not_activate_or_copy_secret(self) -> None:
        self.store.add(self.profile)
        self.assertEqual(self.store.catalog()["activeId"], "current")
        self.assertNotIn("test-only-new-key", self.store.catalog_path.read_text())
        self.assertNotIn(str(self.secret), json.dumps(self.store.public()))
        with self.assertRaises(ConnectionError):
            self.store.add(self.profile)

    def test_dedicated_environment_does_not_reuse_old_key(self) -> None:
        base = {"CONTROL_PLANE_API_KEY": "old-key", "PATH": "/bin"}
        environment = self.store.environment(self.profile, base)
        self.assertEqual(environment["CONTROL_PLANE_API_KEY"], "test-only-new-key")
        self.assertEqual(base["CONTROL_PLANE_API_KEY"], "old-key")
        self.secret.unlink()
        with self.assertRaises(ConnectionError):
            self.store.environment(self.profile, base)

    def test_rejects_broad_permissions_symlinks_and_env_injection(self) -> None:
        self.secret.chmod(0o644)
        with self.assertRaises(ConnectionError):
            credential_file(str(self.secret))
        self.secret.chmod(0o600)
        link = self.root / "link.env"
        link.symlink_to(self.secret)
        with self.assertRaises(ConnectionError):
            credential_file(str(link))
        self.secret.write_text("PATH=/malicious\nCONTROL_PLANE_API_KEY=not-a-real-key\n")
        with self.assertRaises(ConnectionError):
            credential_file(str(self.secret))

    def test_rejects_unsafe_profiles_and_non_loopback_health(self) -> None:
        for url in ("http://example.com", "http://127.0.0.1@evil.test", "https://localhost", "http://127.0.0.1/path", "http://127.0.0.1?secret=value"):
            with self.subTest(url=url), self.assertRaises(ConnectionError):
                health_address(url)
        for profile in ({**self.profile, "profile": "future --evil"}, {**self.profile, "credentialMode": "launcher"},
                        {**self.profile, "apiKey": "forbidden"}):
            with self.assertRaises(ConnectionError):
                self.store.add(profile)

    def test_invalid_catalog_is_not_silently_overwritten(self) -> None:
        self.store.catalog_path.write_text("{broken")
        with self.assertRaises(ConnectionError):
            self.store.snapshot()
        self.assertEqual(self.store.catalog_path.read_text(), "{broken")

    def test_concurrent_requests_are_rejected(self) -> None:
        self.store.request("reconnect", "current", os.getpid())
        with self.assertRaises(ConnectionError):
            self.store.request("reconnect", "current", os.getpid())

    @unittest.skipUnless(os.name == "posix", "supervisor kernel locks use POSIX")
    def test_crashed_writer_does_not_leave_a_permanent_lock(self) -> None:
        path = self.root / "example.lock"
        subprocess.run([sys.executable, "-c", "import os,sys; from pathlib import Path; from labcontext_connections import locked; lock=locked(Path(sys.argv[1])); lock.__enter__(); os._exit(0)", str(path)],
                       env={"PYTHONPATH": str(Path(__file__).resolve().parents[1])}, check=True)
        with locked(path):
            with self.assertRaises(ConnectionError):
                with locked(path):
                    pass
        with locked(path):
            pass

    def test_exited_launcher_record_is_explicit_and_does_not_block_new_requests(self) -> None:
        self.store.request("reconnect", "current", 987654)
        with mock.patch("labcontext_connections.os.kill", side_effect=ProcessLookupError):
            self.assertEqual(self.store.public()["operation"]["reasonCode"], "launcher_exited")
            self.store.request("reconnect", "current", os.getpid())
        self.assertEqual(read_json(self.store.request_path)["launcherPid"], os.getpid())

    def test_corrupt_control_file_does_not_stop_the_stack(self) -> None:
        self.store.request_path.write_text("{broken")
        start, stop = mock.Mock(), mock.Mock()
        TunnelControl(self.store, {}, "client", start, stop).tick()
        start.assert_not_called()
        stop.assert_not_called()
        self.assertEqual(read_json(self.store.operation_path)["reasonCode"], "connection_control_failed")

    def test_preflight_failure_does_not_stop_existing_tunnel(self) -> None:
        self.store.add(self.profile)
        start, stop = mock.Mock(), mock.Mock()
        control = TunnelControl(self.store, {}, "tunnel-client", start, stop)
        self.store.request("switch", "next", os.getpid())
        with mock.patch("labcontext_tunnel_control.subprocess.run", return_value=mock.Mock(returncode=1)) as run:
            control.tick()
        start.assert_not_called()
        stop.assert_not_called()
        self.assertEqual(self.store.catalog()["activeId"], "current")
        self.assertEqual(read_json(self.store.operation_path)["reasonCode"], "tunnel_preflight_failed")
        self.assertEqual(run.call_args.kwargs["env"]["CONTROL_PLANE_API_KEY"], "test-only-new-key")
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)

    def test_success_commits_only_after_readiness_and_stability(self) -> None:
        self.store.add(self.profile)
        child = mock.Mock(pid=1234)
        child.poll.return_value = None
        start, stop = mock.Mock(return_value=child), mock.Mock()
        control = TunnelControl(self.store, {}, "tunnel-client", start, stop)
        self.store.request("switch", "next", os.getpid())
        with mock.patch("labcontext_tunnel_control.subprocess.run", return_value=mock.Mock(returncode=0)), \
                mock.patch("labcontext_tunnel_control.port_open", return_value=False):
            control.tick()
        self.assertEqual(self.store.catalog()["activeId"], "current")
        control.pending["started"] = time.monotonic() - 5
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        with mock.patch.object(control.opener, "open", return_value=response):
            control.tick()
        self.assertEqual(self.store.catalog()["activeId"], "next")
        self.assertEqual(read_json(self.store.operation_path)["phase"], "succeeded")
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(start.call_args.args[0]["id"], "next")

    def test_start_failure_rolls_back_without_activating_target(self) -> None:
        self.store.add(self.profile)
        child = mock.Mock()
        child.poll.return_value = None
        start = mock.Mock(side_effect=[OSError("must not echo secrets"), child])
        stop = mock.Mock()
        control = TunnelControl(self.store, {}, "tunnel-client", start, stop)
        self.store.request("switch", "next", os.getpid())
        with mock.patch("labcontext_tunnel_control.subprocess.run", return_value=mock.Mock(returncode=0)), \
                mock.patch("labcontext_tunnel_control.port_open", return_value=False):
            control.tick()
        self.assertEqual(self.store.catalog()["activeId"], "current")
        self.assertEqual(start.call_args.args[0]["id"], "current")
        self.assertNotIn("must not echo secrets", self.store.operation_path.read_text())

    def test_unrelated_health_listener_is_not_adopted(self) -> None:
        self.store.add(self.profile)
        start, stop = mock.Mock(), mock.Mock()
        control = TunnelControl(self.store, {}, "tunnel-client", start, stop)
        self.store.request("switch", "next", os.getpid())
        with mock.patch("labcontext_tunnel_control.subprocess.run", return_value=mock.Mock(returncode=0)), \
                mock.patch("labcontext_tunnel_control.port_open", return_value=True):
            control.tick()
        self.assertEqual(start.call_args.args[0]["id"], "current")
        self.assertEqual(read_json(self.store.operation_path)["reasonCode"], "tunnel_health_port_in_use")

    def test_old_launcher_request_is_not_executed(self) -> None:
        self.store.request("reconnect", "current", os.getpid() + 1)
        start, stop = mock.Mock(), mock.Mock()
        TunnelControl(self.store, {}, "client", start, stop).tick()
        start.assert_not_called()
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
