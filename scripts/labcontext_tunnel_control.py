"""Tunnel-only supervisor operations. Never signal Provider, Router or SSH PIDs."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable, Mapping
from urllib.request import ProxyHandler, build_opener

from labcontext_connections import ConnectionError, ConnectionStore, port_open, read_json, timestamp, tunnel_preflight_command, write_json


class TunnelControl:
    def __init__(self, store: ConnectionStore, environment: Mapping[str, str], client: str,
                 start: Callable[..., Any], stop: Callable[[], None]):
        self.store, self.environment, self.client = store, dict(environment), client
        self.start, self.stop = start, stop
        self.pending: dict[str, Any] | None = None
        self.opener = build_opener(ProxyHandler({}))
        self.disabled = False

    def _write(self, operation: dict[str, Any], **updates: Any) -> None:
        operation.update(updates, updatedAt=timestamp())
        write_json(self.store.operation_path, operation)

    def _fail(self, operation: dict[str, Any], code: str, message: str, rollback: bool = False) -> None:
        self.pending = None
        if rollback:
            self.stop()
            try:
                self.start(self.store.get())
                message += " 已尝试重新启动原接入，请检查 Tunnel 状态；工作区和 SSH 未改动。"
            except (OSError, ConnectionError):
                message += " 原接入也无法启动，请检查其凭据文件后重试；工作区和 SSH 未改动。"
        self._write(operation, phase="failed", reasonCode=code, summary=message)

    def tick(self) -> None:
        if self.disabled:
            return
        try:
            self._tick()
        except (ConnectionError, OSError):
            # A damaged control file must never escape into run()'s finally
            # block and consequently stop Provider, SSH and Router.
            operation = self.pending["operation"] if self.pending else {"launcherPid": os.getpid()}
            was_pending = self.pending is not None
            self.pending = None
            if was_pending:
                try:
                    self.stop()
                    self.start(self.store.get())
                except (OSError, ConnectionError):
                    pass
            try:
                self.store.request_path.unlink(missing_ok=True)
                self._write(operation, phase="failed", reasonCode="connection_control_failed",
                            summary="接入管理文件无法读取或保存；请检查本机文件权限。Provider、SSH 和 Router 未重启。")
            except OSError:
                self.disabled = True

    def _tick(self) -> None:
        if self.pending:
            self._verify()
            return
        request = read_json(self.store.request_path)
        if not request:
            return
        self.store.request_path.unlink(missing_ok=True)
        if request.get("launcherPid") != os.getpid():
            self._fail(request, "launcher_changed", "启动器已变化，未执行旧任务；请重新发起。")
            return
        self._write(request, phase="checking", summary="检查目标配置与凭据；现有 Tunnel 仍在运行")
        try:
            target = self.store.get(str(request.get("connectionId", "")))
            environment = self.store.environment(target, self.environment)
            # Silent diagnostics: provider output may contain secret-bearing URLs.
            result = subprocess.run(tunnel_preflight_command(self.client, target["profile"]),
                                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=12, check=False)
            if result.returncode:
                self._fail(request, "tunnel_preflight_failed", "目标 Tunnel 诊断未通过，原连接未停止。请在本机检查 profile、运行凭据和工作区权限。")
                return
        except ConnectionError as exc:
            self._fail(request, "connection_config_invalid", str(exc))
            return
        except (OSError, subprocess.TimeoutExpired):
            self._fail(request, "tunnel_preflight_failed", "目标 Tunnel 诊断无法完成，原连接未停止。请检查 tunnel-client 和网络。")
            return
        self.stop()
        # An unrelated listener must never be mistaken for the new client.
        if port_open(target["healthUrl"]):
            self._fail(request, "tunnel_health_port_in_use", "健康端口仍被占用；未接管其他进程。", rollback=True)
            return
        try:
            process = self.start(target)
        except (OSError, ConnectionError):
            self._fail(request, "tunnel_start_failed", "目标 Tunnel 无法启动。", rollback=True)
            return
        self.pending = {"operation": request, "profile": target, "process": process,
                        "deadline": time.monotonic() + 35, "started": time.monotonic()}
        self._write(request, phase="verifying", summary="正在验证新 Tunnel；Provider、SSH 和 Router 保持运行")

    def _verify(self) -> None:
        assert self.pending is not None
        pending = self.pending
        operation, profile, process = pending["operation"], pending["profile"], pending["process"]
        if process.poll() is not None:
            self._fail(operation, "tunnel_exited", "目标 Tunnel 已退出。", rollback=True)
            return
        ready = False
        try:
            with self.opener.open(profile["healthUrl"].rstrip("/") + "/readyz", timeout=0.5) as response:
                ready = response.status == 200
        except OSError:
            pass
        if ready and time.monotonic() - pending["started"] >= 3:
            try:
                self.store.activate(profile["id"])
            except (ConnectionError, OSError):
                self._fail(operation, "connection_commit_failed", "新接入已启动，但无法保存选择。", rollback=True)
                return
            self._write(operation, phase="succeeded", summary="Tunnel 已就绪；请在目标 ChatGPT 账号中完成插件调用验证")
            self.pending = None
        elif time.monotonic() >= pending["deadline"]:
            self._fail(operation, "tunnel_not_ready", "目标 Tunnel 未在限定时间内就绪，接入选择未更改。", rollback=True)
