#!/usr/bin/env python3
"""Run as the remote command of a dedicated, non-multiplexed SSH tunnel.

Only transport liveness is checked. No cookies, API keys, quota requests or
generation calls are needed. A stopped/login-required pool is not auto-started.
"""
import argparse
import ctypes
import os
from pathlib import Path
import platform
import select
import signal
import sys
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def reachable(opener, port):
    request = urllib.request.Request(
        "http://127.0.0.1:{}/health".format(port), method="HEAD"
    )
    try:
        with opener.open(request, timeout=5):
            return True
    except urllib.error.HTTPError as response:
        # 405 (HEAD unsupported), 401, or 503 still prove that the forwarding
        # path responds. Do not mistake authentication/quota for a dead tunnel.
        response.close()
        return True
    except (OSError, urllib.error.URLError):
        return False


def ssh_parent_identity(pid):
    """Only a direct, same-user Linux sshd parent can be signalled."""
    try:
        status = dict(line.split(":", 1) for line in
                      Path("/proc/{}/status".format(pid)).read_text().splitlines())
        if status.get("Name", "").strip() not in ("sshd", "sshd-session"):
            return None
        if any(int(uid) != os.getuid() for uid in status["Uid"].split()):
            return None
        fields = Path("/proc/{}/stat".format(pid)).read_text().rsplit(")", 1)[1].split()
        return pid, fields[19]  # starttime; guards PID reuse before pidfd_open
    except (OSError, KeyError, ValueError, IndexError):
        return None


def pidfd_call(name, *args):
    """Python 3.8 compatibility for the deployed Linux x86_64 host.

    Linux x86_64 UAPI: __NR_pidfd_open=434, __NR_pidfd_send_signal=424.
    Unsupported OS/architecture/kernel fails closed, without a kill(PID) fallback.
    """
    if name == "open" and callable(getattr(os, "pidfd_open", None)):
        return os.pidfd_open(*args)
    if name == "signal" and callable(getattr(signal, "pidfd_send_signal", None)):
        return signal.pidfd_send_signal(*args)
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise OSError("pidfd unavailable")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    if name == "open":
        arguments = (434, args[0], 0)
    elif name == "signal":
        arguments = (424, args[0], args[1], 0, 0)
    else:
        raise ValueError("unknown pidfd operation")
    result = libc.syscall(*(ctypes.c_long(arg) for arg in arguments))
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def open_ssh_parent():
    # A pidfd pins the exact process, not a PID that could later be reused.
    pid = os.getppid()
    identity = ssh_parent_identity(pid)
    if identity is None:
        return None
    try:
        fd = pidfd_call("open", pid)
    except OSError:
        return None
    if os.getppid() != pid or ssh_parent_identity(pid) != identity:
        os.close(fd)
        return None
    return fd


def parent_exited(fd):
    try:
        return bool(select.select([fd], [], [], 0)[0])
    except (OSError, ValueError):
        return True  # Invalid handle: stop watching, never guess another parent.


def watch(port, probe, sleep=time.sleep, parent_fd=None):
    failures = 0
    while True:
        if parent_fd is not None and parent_exited(parent_fd):
            return 0  # Do not leave an orphan watcher after a normal SSH restart.
        if probe(port):
            failures = 0
        else:
            failures += 1
            if failures >= 3:
                print("gemini-web-tunnel: transport unresponsive; closing dedicated session",
                      file=sys.stderr, flush=True)
                if parent_fd is not None:
                    try:
                        pidfd_call("signal", parent_fd, signal.SIGTERM)
                    except OSError:
                        pass  # Parent already gone: never target another process.
                return 75
        sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=16969)
    parser.add_argument("--managed-ssh", action="store_true",
                        help="Only for a dedicated SSH connection with no other forwards")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    parent_fd = open_ssh_parent() if args.managed_ssh else None
    try:
        return watch(args.port, lambda port: reachable(opener, port), parent_fd=parent_fd)
    except KeyboardInterrupt:
        return 0
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


if __name__ == "__main__":
    sys.exit(main())
