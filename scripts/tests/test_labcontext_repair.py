"""Offline recovery regression coverage; all runtime paths are isolated."""
from __future__ import annotations

import contextlib
import io
import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import labcontext as api
from labcontext_repair import (
    LaunchAgent, RepairFailure, dashboard_ready, private_file, recover, repair_cli,
    repair_lock, validate_local_provider, transport_ports_open,
)


class RepairTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config.toml"
        self.values = {"LABCONTEXT_STATUS_FILE": str(self.root / "launcher.json"),
                       "LABCONTEXT_RECOVERY_LOG_FILE": str(self.root / "recovery.log"),
                       "LABCONTEXT_RECOVERY_STATUS_FILE": str(self.root / "recovery.json"),
                       "LABCONTEXT_ENV_FILE": str(self.root / "launcher.env"),
                       "LABCONTEXT_LAUNCHER_SCRIPT": str(self.root / "labcontext.py")}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        def patch(name, **kwargs):
            return self.stack.enter_context(mock.patch(name, **kwargs))
        patch("labcontext.load_config", return_value=mock.Mock(listen_addr="127.0.0.1:1460"))
        self.status = patch("labcontext.fetch_router_status", return_value={"overall": "ready"})
        self.preflight = patch("labcontext.recovery_preflight", return_value=(0, "diagnostics", True))
        self.stop = patch("labcontext.stop_running_stack")
        self.validate = patch("labcontext_repair.validate_local_provider")
        self.find = patch("labcontext_repair.LaunchAgent.find", return_value=None)
        self.web = patch("labcontext_repair.dashboard_ready", return_value=True)
        self.ports = patch("labcontext_repair.transport_ports_open", return_value=True)
        self.spawn = patch("labcontext_repair.subprocess.Popen", return_value=mock.Mock(pid=42, poll=lambda: 0))
        self.clock = [0.0]
        patch("labcontext_repair.time.monotonic", side_effect=lambda: self.clock[0])
        patch("labcontext_repair.time.sleep", side_effect=lambda seconds: self.clock.__setitem__(0, self.clock[0] + seconds))

    def result(self):
        return json.loads(Path(self.values["LABCONTEXT_RECOVERY_STATUS_FILE"]).read_text())

    def test_ready_is_one_line_and_does_not_restart(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(repair_cli(api, self.config, self.values), 0)
        self.assertEqual(output.getvalue(), "labcontext: 连接成功\n")
        self.status.assert_called_once_with(("127.0.0.1", 1460), force=True, timeout=3.0)
        self.stop.assert_not_called()
        self.spawn.assert_not_called()
        self.assertEqual(self.result()["phase"], "succeeded")

    def test_unavailable_router_never_counts_as_success(self):
        self.status.return_value = {"overall": "unavailable"}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(recover(api, self.config, self.values, timeout=2), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.result()["phase"], "failed")
        self.stop.assert_called_once()  # Historical preflight stack_stopped=True is not trusted.

    def test_concurrent_zero_exit_launcher_still_waits_for_real_ready(self):
        self.status.side_effect = [None, {"overall": "degraded"}, {"overall": "ready"}]
        self.assertEqual(recover(api, self.config, self.values), 0)
        self.assertEqual(self.status.call_count, 3)

    def test_launchd_paused_before_stop_and_restored_before_verification(self):
        events = []
        agent = mock.Mock(paused=False)
        def pause():
            agent.paused = True
            events.append("pause")
        def resume():
            agent.paused = False
            events.append("resume")
        agent.pause.side_effect, agent.resume.side_effect = pause, resume
        self.find.return_value = agent
        self.stop.side_effect = lambda *_: events.append("stop")
        self.preflight.side_effect = lambda *_, **kwargs: (events.append("doctor") or (0, "ok", True))
        self.status.side_effect = [None, {"overall": "ready"}]
        self.assertEqual(recover(api, self.config, self.values), 0)
        self.assertEqual(events, ["pause", "stop", "doctor", "resume"])
        self.preflight.assert_called_once_with(self.config, self.values, stack_stopped=True, quick=True)
        self.spawn.assert_not_called()

    def test_launchd_is_restored_when_preflight_fails(self):
        agent = mock.Mock(paused=False)
        agent.pause.side_effect = lambda: setattr(agent, "paused", True)
        agent.resume.side_effect = lambda: setattr(agent, "paused", False)
        self.find.return_value = agent
        self.status.return_value = None
        self.preflight.return_value = (2, "SSH connection: failed (connection timed out)", True)
        self.assertEqual(recover(api, self.config, self.values), 2)
        agent.resume.assert_called_once()
        self.assertEqual(self.result()["reasonCode"], "ssh_connection_timeout")

    def test_provider_config_failure_is_concrete_and_non_destructive(self):
        self.status.return_value = None
        self.validate.side_effect = RepairFailure("本地 Provider 配置无效：授权目录不存在：/missing", "provider_config_invalid")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(repair_cli(api, self.config, self.values), 2)
        self.assertEqual(output.getvalue(), "labcontext: 连接失败：本地 Provider 配置无效：授权目录不存在：/missing\n")
        self.stop.assert_not_called()
        self.find.assert_not_called()

    def test_dashboard_must_be_reachable_even_if_router_is_ready(self):
        self.web.return_value = False
        self.assertEqual(recover(api, self.config, self.values, timeout=2), 2)
        self.assertEqual(self.result()["reasonCode"], "dashboard_unavailable")

    def test_busy_does_not_clobber_in_progress_status(self):
        original = '{"phase":"verifying","jobId":"other"}'
        Path(self.values["LABCONTEXT_RECOVERY_STATUS_FILE"]).write_text(original)
        output = io.StringIO()
        with repair_lock(self.root / "launcher.repair.lock"), contextlib.redirect_stdout(output):
            self.assertEqual(repair_cli(api, self.config, self.values), 2)
        self.assertIn("另一次修复正在进行", output.getvalue())
        self.assertEqual(Path(self.values["LABCONTEXT_RECOVERY_STATUS_FILE"]).read_text(), original)
        self.status.assert_not_called()

    def test_no_diagnostic_noise_or_credentials_in_default_output(self):
        self.status.return_value = None
        self.preflight.return_value = (2, "Permission denied (publickey)\nprivate-test-credential", False)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(repair_cli(api, self.config, self.values), 2)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertNotIn("private-test-credential", output.getvalue())
        self.assertIn("SSH 身份验证失败", output.getvalue())
        self.assertEqual(stat.S_IMODE((self.root / "recovery.log").stat().st_mode), 0o600)

    def test_stop_refusal_preserves_its_reason(self):
        self.status.return_value = None
        def refused(*_):
            api.fail("refusing to signal PID 123: identity mismatch")
        self.stop.side_effect = refused
        self.assertEqual(recover(api, self.config, self.values), 2)
        self.assertIn("identity mismatch", self.result()["summary"])
        self.spawn.assert_not_called()

    def test_final_diagnostics_override_resolved_earlier_conflict(self):
        self.status.return_value = None
        self.preflight.return_value = (2, "remote port forwarding failed\nAfter managed bridge cleanup:\nconnection timed out", True)
        self.assertEqual(recover(api, self.config, self.values), 2)
        self.assertEqual(self.result()["reasonCode"], "ssh_connection_timeout")

    def test_closed_transport_skips_slow_old_capability_probe(self):
        self.ports.side_effect = [False, False, True]
        self.status.return_value = {"overall": "ready"}
        self.assertEqual(recover(api, self.config, self.values), 0)
        self.status.assert_called_once_with(("127.0.0.1", 1460), force=True, timeout=6.0)
        self.stop.assert_called_once()
        self.assertIn("timingsMs", self.result())

    def test_only_open_ports_never_report_success(self):
        self.status.return_value = None
        self.assertEqual(recover(api, self.config, self.values, timeout=1), 2)
        self.assertEqual(self.result()["phase"], "failed")
        for call in self.status.call_args_list:
            self.assertTrue(call.kwargs["force"])
            self.assertLessEqual(call.kwargs["timeout"], 6)

    def test_new_concurrent_launcher_is_stopped_before_our_start(self):
        self.status.side_effect = [None, {"overall": "ready"}]
        with mock.patch("labcontext.read_runtime_status", return_value={"launcherPid": 42}), \
                mock.patch("labcontext.process_is_alive", return_value=True):
            self.assertEqual(recover(api, self.config, self.values), 0)
        self.assertEqual(self.stop.call_count, 2)


class BoundariesTest(unittest.TestCase):
    def test_short_full_check_timeout_never_falls_back_to_cached_ready(self):
        with mock.patch("labcontext.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            self.assertIsNone(api.fetch_router_status(("127.0.0.1", 1234), force=True, timeout=0.1))
        self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 0.1)

    def test_legacy_fallback_only_for_missing_endpoint(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({"overall": "ready", "router": {"name": "LabContext Router"}}).encode()
        with mock.patch("labcontext.build_opener") as opener:
            opener.return_value.open.side_effect = [HTTPError("url", 404, "missing", {}, None), response]
            result = api.fetch_router_status(("127.0.0.1", 1234), force=True, timeout=1)
        self.assertEqual(result["overall"], "ready")
        self.assertEqual(opener.return_value.open.call_count, 2)

    def test_recovery_doctor_combines_ssh_auth_and_reverse_forwarding(self):
        config = mock.Mock(listen_addr="127.0.0.1:1234", providers=[])
        values = {"LABCONTEXT_ENABLE_SSH": "1", "LABCONTEXT_ENABLE_TUNNEL": "0",
                  "LABCONTEXT_SSH_HOST": "research-host", "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987"}
        with mock.patch("labcontext.load_config", return_value=config), \
                mock.patch("labcontext.local_provider_command", return_value=None), \
                mock.patch("labcontext.require_program"), \
                mock.patch("labcontext.runtime_component", return_value=None), \
                mock.patch("labcontext.ssh_config_forwardings", return_value=(set(), set())), \
                mock.patch("labcontext.probe_ssh_remote_forward", return_value=(True, "ok")) as forward, \
                mock.patch("labcontext.probe_ssh") as ssh, \
                mock.patch("labcontext.fetch_router_status") as status:
            result, _ = api.capture_doctor(Path("/unused"), values, recovery=True)
        self.assertEqual(result, 0)
        forward.assert_called_once()
        ssh.assert_not_called()
        status.assert_not_called()

    def test_stopped_stack_conflict_is_not_probed_twice_before_cleanup(self):
        conflict = "remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.capture_doctor", side_effect=[(2, conflict), (0, "ok")]) as doctor, \
                mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(True, "stopped managed session")) as cleanup, \
                mock.patch("labcontext.stop_running_stack") as stop:
            result, _, stopped = api.recovery_preflight(Path("/unused"), {}, stack_stopped=True, quick=True)
        self.assertEqual(result, 0)
        self.assertTrue(stopped)
        self.assertEqual(doctor.call_count, 2)
        cleanup.assert_called_once()
        stop.assert_not_called()

    def test_transport_gate_checks_ports_but_returns_no_success_result(self):
        from types import SimpleNamespace
        config = SimpleNamespace(listen_addr="127.0.0.1:1234", providers=[
            SimpleNamespace(enabled=True, mcp_url="http://127.0.0.1:1455/mcp")])
        with mock.patch("labcontext.port_is_open", side_effect=[True, False]) as port:
            self.assertFalse(transport_ports_open(api, config))
        self.assertEqual(port.call_count, 2)

    def test_log_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "keep"
            target.write_text("unchanged")
            (root / "link").symlink_to(target)
            with self.assertRaises(OSError):
                private_file(root / "link")
            self.assertEqual(target.read_text(), "unchanged")

    def test_dashboard_only_probes_loopback_without_credentials(self):
        for url in ("https://example.com/", "http://127.0.0.1/?secret=x", "http://user:pass@localhost/"):
            with self.subTest(url=url), self.assertRaises(RepairFailure), mock.patch("labcontext_repair.build_opener") as opener:
                dashboard_ready(api, {"LABCONTEXT_DASHBOARD_URL": url})
            opener.assert_not_called()
        self.assertTrue(dashboard_ready(api, {}))

    def test_provider_validation_uses_its_interpreter_and_does_not_echo_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "labctx"
            executable.write_text("#!/test/venv/bin/python\n")
            command = ["/usr/bin/env", "PRIVATE_TOKEN=never-echo", str(executable), "--config", str(root / "config.toml"), "serve"]
            result = subprocess.CompletedProcess([], 2, '{"error":"授权目录不存在：/missing"}', "secret-stderr")
            with mock.patch("labcontext.local_provider_command", return_value=command), \
                    mock.patch("labcontext_repair.subprocess.run", return_value=result) as run:
                with self.assertRaises(RepairFailure) as error:
                    validate_local_provider(api, {})
            self.assertIn("/missing", str(error.exception))
            self.assertNotIn("secret-stderr", str(error.exception))
            self.assertEqual(run.call_args.args[0][0], "/test/venv/bin/python")
            self.assertNotIn("PRIVATE_TOKEN=never-echo", run.call_args.args[0])

    def test_unrelated_or_tampered_launchagent_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plist = root / "Library/LaunchAgents/com.codexmanager.labcontext.plist"
            plist.parent.mkdir(parents=True)
            env_file = root / "launcher.env"
            config = root / "config.toml"
            script = root / "labcontext.py"
            args = [str(script), "--env-file", str(env_file), "--config", str(config)]
            plist.write_bytes(plistlib.dumps({"Label": "com.codexmanager.labcontext", "ProgramArguments": args}))
            values = {"LABCONTEXT_LAUNCHER_SCRIPT": str(script), "LABCONTEXT_ENV_FILE": str(env_file)}
            live = f"\n path = {plist}\n program = {script}\n arguments = {{\n" + "\n".join(args) + "\n }\n"
            with mock.patch("labcontext_repair.Path.home", return_value=root), \
                    mock.patch("labcontext_repair.sys.platform", "darwin"), \
                    mock.patch.object(LaunchAgent, "call", return_value=subprocess.CompletedProcess([], 0, live)) as call:
                self.assertIsNone(LaunchAgent.find(api, root / "other-config.toml", values))
                call.assert_not_called()
                self.assertIsInstance(LaunchAgent.find(api, config, values), LaunchAgent)
                call.return_value.stdout = live.replace(str(script), "/different/program")
                with self.assertRaises(RepairFailure):
                    LaunchAgent.find(api, config, values)


if __name__ == "__main__":
    unittest.main()
