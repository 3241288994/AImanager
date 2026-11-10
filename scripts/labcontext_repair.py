"""Bounded, quiet recovery shared by the CLI and the Router recovery worker."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import plistlib
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


INITIAL_CHECK_SECONDS = 3.0
VERIFY_CHECK_SECONDS = 6.0


class RepairFailure(RuntimeError):
    def __init__(self, summary: str, code: str = "repair_failed", detail: str = ""):
        super().__init__(summary)
        self.code, self.detail = code, detail


def private_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(fd)
        raise RepairFailure("修复日志不是当前用户拥有的普通文件", "unsafe_recovery_file")
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8", buffering=1)


@contextlib.contextmanager
def repair_lock(path: Path):
    with private_file(path) as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RepairFailure("另一次修复正在进行，请稍后再试", "repair_in_progress") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate_local_provider(api, values: dict[str, str]) -> None:
    """Use labctx's own interpreter/config loader; never relax allowed roots."""
    command = api.local_provider_command(values)
    if not command:
        return
    if Path(command[0]).name == "env":
        command = command[1:]
        while command and "=" in command[0]:
            command = command[1:]
    if not command or Path(command[0]).name != "labctx" or "--config" not in command:
        return  # Custom Provider commands remain externally validated.
    index = command.index("--config") + 1
    if index >= len(command):
        raise RepairFailure("本地 Provider 缺少配置文件参数", "provider_config_invalid")
    with Path(command[0]).open(encoding="utf-8") as handle:
        shebang = handle.readline(4096).strip()
    interpreter = shlex.split(shebang[2:]) if shebang.startswith("#!") else []
    if len(interpreter) != 1 or not Path(interpreter[0]).is_absolute():
        return
    script = '''import json, sys, tomllib
from pathlib import Path
from labcontext.config import load_config
try:
    path = Path(sys.argv[1]).expanduser()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for root in data.get("registry", {}).get("allowed_roots", []):
        if not Path(root).expanduser().is_dir():
            print(json.dumps({"error": "授权目录不存在：" + str(root)}, ensure_ascii=False))
            sys.exit(2)
    load_config(path)
except (OSError, ValueError) as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
    sys.exit(2)
'''
    try:
        result = subprocess.run([interpreter[0], "-c", script, command[index]],
                                capture_output=True, text=True, timeout=10,
                                env=api.process_environment(values))
    except subprocess.TimeoutExpired:
        raise RepairFailure("本地 Provider 配置检查超时", "provider_config_timeout") from None
    if result.returncode:
        try:
            detail = json.loads(result.stdout).get("error", "配置解析失败")
        except (ValueError, AttributeError):
            detail = "配置检查程序无法运行，请检查 Provider 安装"
        raise RepairFailure("本地 Provider 配置无效：" + str(detail)[:500], "provider_config_invalid")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def dashboard_ready(api, values: dict[str, str]) -> bool:
    # Local-only configurations do not implicitly depend on the remote Web UI.
    url = values.get("LABCONTEXT_DASHBOARD_URL")
    if url is None and api.parse_bool(values.get("LABCONTEXT_ENABLE_SSH")):
        port = values.get("LABCONTEXT_SERVER_WEB_LOCAL_PORT", "48761")
        url = f"http://127.0.0.1:{port}/labcontext/"
    if not url:
        return True
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise RepairFailure("连接中心地址必须是无凭据的本机 HTTP(S) 地址", "dashboard_url_invalid")
        request = Request(url, headers={"Accept": "text/html"})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
            return 200 <= response.status < 400
    except HTTPError as exc:
        return exc.code in {301, 302, 303, 307, 308, 401, 403}
    except (URLError, OSError, ValueError):
        return False


class LaunchAgent:
    """Pause only the installed, same-config LabContext job, never arbitrary SSH."""
    def __init__(self, path: Path, label: str):
        self.path, self.label = path, label
        self.domain = f"gui/{os.getuid()}"
        self.paused = False

    @classmethod
    def find(cls, api, config_path: Path, values: dict[str, str]):
        if sys.platform != "darwin":
            return None
        path = Path.home() / "Library/LaunchAgents/com.codexmanager.labcontext.plist"
        if not path.exists():
            return None
        info = path.stat()
        if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RepairFailure("LabContext 后台任务配置权限不安全，未停止任何任务", "launchagent_unverified")
        with path.open("rb") as handle:
            data = plistlib.load(handle)
        args = data.get("ProgramArguments", [])
        if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
            raise RepairFailure("LabContext 后台任务启动参数无效，未停止任何任务", "launchagent_unverified")
        if data.get("Program") and Path(data["Program"]).resolve() != Path(args[0]).resolve():
            raise RepairFailure("LabContext 后台任务程序与参数不匹配，未停止任何任务", "launchagent_unverified")
        script = Path(values.get("LABCONTEXT_LAUNCHER_SCRIPT", str(api.SCRIPT_DIR / "labcontext.py"))).resolve()
        script_index = next((i for i in range(min(2, len(args))) if Path(args[i]).expanduser().resolve() == script), None)
        if script_index is None or data.get("Label") != "com.codexmanager.labcontext":
            return None
        options = args[script_index + 1:]
        if len(options) % 2 or any(options[i] not in {"--config", "--env-file"} for i in range(0, len(options), 2)):
            return None
        def option(name, default):
            return Path(options[options.index(name) + 1] if name in options else default).expanduser().resolve()
        # A custom config must not stop the user's default background stack.
        env_path = option("--env-file", api.DEFAULT_ENV_PATH)
        if env_path != Path(values.get("LABCONTEXT_ENV_FILE", str(api.DEFAULT_ENV_PATH))).expanduser().resolve():
            return None
        job_values = api.load_env(env_path)
        job_config = option("--config", job_values.get("LABCONTEXT_ROUTER_CONFIG", str(api.DEFAULT_CONFIG_PATH)))
        if job_config != config_path.resolve() or any(arg in options for arg in ("repair", "stop", "restart", "--repair-worker")):
            return None
        if data.get("EnvironmentVariables", {}).get("LABCONTEXT_ROUTER_CONFIG") not in (None, str(config_path)):
            raise RepairFailure("后台任务使用了不同配置，未自动停止", "launchagent_unverified")
        agent = cls(path, data["Label"])
        live = agent.call("print", f"{agent.domain}/{agent.label}", check=False)
        if live.returncode:
            return None
        match = re.search(r"\n\s*arguments = \{\n(.*?)\n\s*\}", live.stdout, re.S)
        live_args = [line.strip() for line in match[1].splitlines()] if match else []
        expected_program = str(data.get("Program") or args[0])
        if (live_args != args
                or not re.search(r"(?m)^\s*program = " + re.escape(expected_program) + r"\s*$", live.stdout)
                or not re.search(r"(?m)^\s*path = " + re.escape(str(path)) + r"\s*$", live.stdout)):
            raise RepairFailure("运行中的后台任务与安装配置不匹配，未自动停止", "launchagent_unverified")
        return agent

    def call(self, *args, check=True):
        result = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=15)
        if check and result.returncode:
            raise RepairFailure("LabContext 后台任务控制失败（launchctl）", "launchagent_control_failed")
        return result

    def pause(self):
        self.call("bootout", f"{self.domain}/{self.label}")
        self.paused = True

    def resume(self):
        if self.paused:
            self.call("bootstrap", self.domain, str(self.path))
            self.paused = False


def checked_stop(api, config_path: Path, values: dict[str, str]):
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            api.stop_running_stack(config_path, values)
    except SystemExit as exc:
        lines = output.getvalue().strip().splitlines()
        raise RepairFailure(str(exc) if str(exc) else (lines[-1] if lines else "无法安全停止当前连接"),
                            "stack_stop_refused") from None
    finally:
        print(output.getvalue().strip())


def transport_ports_open(api, config) -> bool:
    """A cheap failure gate only; open ports NEVER count as verified success."""
    if not api.port_is_open(api.parse_listen_addr(config.listen_addr)):
        return False
    for provider in config.providers:
        if not provider.enabled:
            continue
        parsed = urlsplit(provider.mcp_url)
        if parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if not api.port_is_open((parsed.hostname, port)):
                return False
    return True


def recover(api, config_path: Path, values: dict[str, str], *, timeout=45.0, on_result=None) -> int:
    """Success requires fresh capability checks AND a reachable connection center."""
    started = time.monotonic()
    timings = {}
    def timed(name, action):
        before = time.monotonic()
        try:
            return action()
        finally:
            timings[name] = timings.get(name, 0) + round((time.monotonic() - before) * 1000)
            print(f"repair stage={name} elapsedMs={timings[name]}")

    base = {"jobId": os.environ.get("LABCONTEXT_RECOVERY_JOB_ID", "cli"),
            "workerPid": os.getpid(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "suggestions": []}
    def report(phase, summary, *, persist=True, **extra):
        payload = {**base, "phase": phase, "summary": summary,
                   "timingsMs": {**timings, "total": round((time.monotonic() - started) * 1000)}, **extra}
        if phase in {"failed", "succeeded"}:
            payload["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if on_result is not None:
            on_result(payload)
        if persist:
            api.write_recovery_status(values, payload)

    log_path = Path(values.get("LABCONTEXT_RECOVERY_LOG_FILE", str(api.DEFAULT_RECOVERY_LOG_PATH))).expanduser()
    agent = None
    locked = False
    try:
        with repair_lock(api.runtime_status_path(values).with_suffix(".repair.lock")):
            locked = True
            with private_file(log_path) as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                print(f"\n{base['startedAt']} LabContext recovery")
                try:
                    config = api.load_config(config_path)
                    address = api.parse_listen_addr(config.listen_addr)
                    report("diagnosing", "正在验证 LabContext 连接")
                    # Avoid a 30-second MCP wait when a known local transport is down.
                    status = timed("initialCheck", lambda: api.fetch_router_status(
                        address, force=True, timeout=INITIAL_CHECK_SECONDS)
                        if transport_ports_open(api, config) else None)
                    if status and status.get("overall") == "ready" and dashboard_ready(api, values):
                        report("succeeded", "连接成功")
                        return 0
                    timed("configValidation", lambda: validate_local_provider(api, values))
                    agent = LaunchAgent.find(api, config_path, values)
                    # KeepAlive must be suspended BEFORE any SIGTERM/port cleanup.
                    if agent:
                        timed("pauseLaunchAgent", agent.pause)
                    timed("stop", lambda: checked_stop(api, config_path, values))
                    result, diagnostics, _ = timed("preflight", lambda: api.recovery_preflight(
                        config_path, values, stack_stopped=True, quick=True))
                    print(diagnostics)
                    if result:
                        # Diagnose the final attempt, not an earlier resolved conflict.
                        final = diagnostics.rsplit("After managed bridge cleanup:\n", 1)[-1]
                        failure = api.recovery_failure_from_diagnostics(final, values)
                        raise RepairFailure(str(failure["summary"]), str(failure["reasonCode"]), final)
                    report("restarting", "正在重建 LabContext 连接")
                    # Re-check only if another verified launcher appeared during SSH cleanup.
                    concurrent = api.read_runtime_status(api.runtime_status_path(values))
                    concurrent_pid = concurrent.get("launcherPid") if concurrent else None
                    if isinstance(concurrent_pid, int) and concurrent_pid > 1 and api.process_is_alive(concurrent_pid):
                        timed("stop", lambda: checked_stop(api, config_path, values))
                    child = None
                    if agent:
                        timed("start", agent.resume)
                    else:
                        script = values.get("LABCONTEXT_LAUNCHER_SCRIPT", str(api.SCRIPT_DIR / "labcontext.py"))
                        env_file = values.get("LABCONTEXT_ENV_FILE", str(api.DEFAULT_ENV_PATH))
                        child = subprocess.Popen(
                            [sys.executable, script, "--env-file", env_file, "--config", str(config_path)],
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            env=api.process_environment(values), start_new_session=True, close_fds=True)
                    report("verifying", "正在验证 Provider、SSH、Tunnel 与连接中心")
                    deadline = time.monotonic() + timeout
                    verifying_started = time.monotonic()
                    last_status = None
                    while time.monotonic() < deadline:
                        # Let listeners come up before asking for full MCP capabilities.
                        if not transport_ports_open(api, config):
                            if child and child.poll() not in (None, 0):
                                break
                            time.sleep(0.25)
                            continue
                        budget = min(VERIFY_CHECK_SECONDS, max(0.1, deadline - time.monotonic()))
                        last_status = api.fetch_router_status(address, force=True, timeout=budget)
                        if last_status and last_status.get("overall") == "ready" and dashboard_ready(api, values):
                            timings["verification"] = round((time.monotonic() - verifying_started) * 1000)
                            report("succeeded", "连接成功", detail="Provider、已启用传输及本机连接中心检查通过；云端插件需在目标账号另行验证。")
                            return 0
                        if child and child.poll() not in (None, 0):
                            break
                        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
                    timings["verification"] = round((time.monotonic() - verifying_started) * 1000)
                    if last_status and last_status.get("overall") == "ready":
                        raise RepairFailure("连接中心无法访问，请检查服务器 Web 服务与 SSH 本地转发", "dashboard_unavailable")
                    failure = api.runtime_recovery_failure(last_status)
                    summary, detail = str(failure["summary"]), str(failure["detail"])
                    if failure["reasonCode"] in {"provider_unavailable", "tunnel_unavailable"}:
                        summary += "：" + " ".join(detail.split())[:300]
                    raise RepairFailure(summary, str(failure["reasonCode"]), detail)
                finally:
                    # Never leave an existing login-time job disabled after a failed repair.
                    if agent and agent.paused:
                        agent.resume()
    except (RepairFailure, SystemExit, OSError, ValueError, api.RouterError, subprocess.TimeoutExpired) as exc:
        summary = str(exc) or "修复检查未通过，请运行 labcontext doctor 查看原因"
        # A newer worker must not have its status overwritten after this lock was released.
        current = api.read_runtime_status(Path(values.get("LABCONTEXT_RECOVERY_STATUS_FILE", str(api.DEFAULT_RECOVERY_STATUS_PATH))).expanduser())
        another_worker = bool(current and current.get("workerPid") != os.getpid()
                              and current.get("phase") in {"diagnosing", "restarting", "verifying"})
        ours = locked and not another_worker
        report("failed", summary[:600], persist=ours, reasonCode=getattr(exc, "code", "repair_failed"),
               detail=getattr(exc, "detail", "")[:12000], command="labcontext repair --verbose")
        return 2


def repair_cli(api, config_path: Path, values: dict[str, str], *, verbose=False) -> int:
    status = {}
    def update(payload):
        status.clear()
        status.update(payload)
    result = recover(api, config_path, values, on_result=update)
    reason = " ".join(str(status.get("summary", "修复未完成" )).split())
    print("labcontext: 连接成功" if result == 0 else f"labcontext: 连接失败：{reason}")
    if verbose:
        print(f"详细日志：{values.get('LABCONTEXT_RECOVERY_LOG_FILE', api.DEFAULT_RECOVERY_LOG_PATH)}")
        if result and status.get("detail"):
            print(status["detail"])
    return result
