import io
from pathlib import Path
import signal
import sys
import unittest
from unittest import mock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gemini_web_tunnel_watchdog as watchdog


class WatchdogTest(unittest.TestCase):
    def test_head_uses_loopback_and_bounded_timeout(self):
        opener = mock.MagicMock()
        self.assertTrue(watchdog.reachable(opener, 16970))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:16970/health")
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 5})
        self.assertEqual(request.header_items(), [])

    def test_any_http_response_is_reachable_even_login_or_quota_failure(self):
        for status in (301, 401, 403, 405, 429, 503):
            with self.subTest(status=status):
                body = io.BytesIO(b"")
                opener = mock.Mock()
                opener.open.side_effect = urllib.error.HTTPError(
                    "http://127.0.0.1:16970/health", status, "fixture", {}, body)
                self.assertTrue(watchdog.reachable(opener, 16970))
                self.assertTrue(body.closed)

    def test_network_failure_is_not_reachable(self):
        for error in (TimeoutError(), ConnectionRefusedError(), urllib.error.URLError("fixture")):
            opener = mock.Mock()
            opener.open.side_effect = error
            self.assertFalse(watchdog.reachable(opener, 16970))

    def test_three_consecutive_failures_terminate_only_pinned_parent(self):
        probe = mock.Mock(side_effect=[False, False, True, False, False, False])
        sleep = mock.Mock()
        with mock.patch.object(watchdog, "pidfd_call") as send, \
                mock.patch.object(watchdog, "parent_exited", return_value=False):
            self.assertEqual(watchdog.watch(16970, probe, sleep, parent_fd=17), 75)
            send.assert_called_once_with("signal", 17, signal.SIGTERM)
        self.assertEqual(sleep.call_count, 5)

    def test_unmanaged_command_never_signals_other_sessions(self):
        with mock.patch.object(watchdog, "pidfd_call") as send:
            watchdog.watch(16970, lambda _: False, lambda _: None)
            send.assert_not_called()

    def test_parent_exit_stops_watcher_without_probing_or_signalling(self):
        probe = mock.Mock()
        with mock.patch.object(watchdog, "parent_exited", return_value=True), \
                mock.patch.object(watchdog, "pidfd_call") as send:
            self.assertEqual(watchdog.watch(16970, probe, parent_fd=17), 0)
            probe.assert_not_called()
            send.assert_not_called()

    def test_pinned_parent_exit_detection(self):
        with mock.patch.object(watchdog.select, "select", return_value=([17], [], [])):
            self.assertTrue(watchdog.parent_exited(17))
        with mock.patch.object(watchdog.select, "select", return_value=([], [], [])):
            self.assertFalse(watchdog.parent_exited(17))
        with mock.patch.object(watchdog.select, "select", side_effect=OSError()):
            self.assertTrue(watchdog.parent_exited(17))

    def test_non_sshd_parent_cannot_be_claimed(self):
        with mock.patch.object(watchdog, "ssh_parent_identity", return_value=None), \
                mock.patch.object(watchdog, "pidfd_call") as open_fd:
            self.assertIsNone(watchdog.open_ssh_parent())
            open_fd.assert_not_called()

    def test_pid_reuse_closes_fd_without_signalling(self):
        with mock.patch.object(watchdog.os, "getppid", return_value=123), \
                mock.patch.object(watchdog, "ssh_parent_identity", side_effect=[(123, "a"), (123, "b")]), \
                mock.patch.object(watchdog, "pidfd_call", return_value=17) as call, \
                mock.patch.object(watchdog.os, "close") as close, \
                mock.patch.object(watchdog.os, "kill") as kill:
            self.assertIsNone(watchdog.open_ssh_parent())
            close.assert_called_once_with(17)
            call.assert_called_once_with("open", 123)
            kill.assert_not_called()

    def test_unsupported_pidfd_fails_closed(self):
        with mock.patch.object(watchdog.os, "getppid", return_value=123), \
                mock.patch.object(watchdog, "ssh_parent_identity", return_value=(123, "a")), \
                mock.patch.object(watchdog, "pidfd_call", side_effect=OSError("unsupported")):
            self.assertIsNone(watchdog.open_ssh_parent())

    def test_python38_syscalls_are_pinned_and_never_use_kill(self):
        libc = mock.Mock()
        libc.syscall.return_value = 17
        with mock.patch.object(watchdog.os, "pidfd_open", None, create=True), \
                mock.patch.object(watchdog.signal, "pidfd_send_signal", None, create=True), \
                mock.patch.object(watchdog.ctypes, "CDLL", return_value=libc), \
                mock.patch.object(watchdog.sys, "platform", "linux"), \
                mock.patch.object(watchdog.platform, "machine", return_value="x86_64"):
            self.assertEqual(watchdog.pidfd_call("open", 123), 17)
            self.assertEqual([a.value for a in libc.syscall.call_args.args], [434, 123, 0])
            watchdog.pidfd_call("signal", 17, signal.SIGTERM)
            self.assertEqual([a.value for a in libc.syscall.call_args.args], [424, 17, signal.SIGTERM, 0, 0])

    def test_no_redirects(self):
        self.assertIsNone(watchdog.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.test"))


if __name__ == "__main__":
    unittest.main()
