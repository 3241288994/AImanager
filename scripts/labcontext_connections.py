"""Private connection profiles and backend-only Tunnel control records.

No OpenAI passwords, cookies or literal API keys belong in the catalog. Management
is local-only; none of these operations are exposed as model tools.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import socket
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit


class ConnectionError(ValueError):
    pass


def timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > 128 * 1024:
            raise ConnectionError("连接状态文件过大，请检查本机配置。")
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ConnectionError("连接配置无法读取；请检查文件格式和权限。") from exc
    if not isinstance(value, dict):
        raise ConnectionError("连接配置必须为 JSON 对象。")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Do not silently steal a stale lock or overwrite another operation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:  # POSIX is the supported supervisor runtime; conservative fallback.
        fcntl = None
    if fcntl is not None:
        # Kernel locks disappear when a crashed process exits. Keep the empty
        # inode in place; unlinking a flock'ed file would allow a second lock.
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ConnectionError("连接锁文件权限无效，请检查本机配置目录。")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConnectionError("连接配置正在被另一个操作使用；请稍后重试。") from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        return
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ConnectionError("连接配置正在被另一个操作使用；请稍后重试。") from exc
    try:
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def safe_name(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise ConnectionError("接入 ID 和 Tunnel profile 仅允许 1–64 位字母、数字、横线、下划线。")
    if value.startswith(("sk-", "sess-")):
        raise ConnectionError("接入名称不能使用密钥或会话令牌，请使用普通备注名。")
    return value


def health_address(url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 80
    except ValueError as exc:
        raise ConnectionError("Tunnel 健康地址无效。") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or not 1 <= port <= 65535):
        raise ConnectionError("Tunnel 健康地址只能是本机 IPv4 回环 HTTP 地址，不得包含路径或凭据。")
    return "127.0.0.1", port


def port_open(url: str) -> bool:
    try:
        with socket.create_connection(health_address(url), timeout=0.2):
            return True
    except OSError:
        return False


def tunnel_preflight_command(client: str, profile: str) -> list[str]:
    # doctor binds its health port too. The old managed Tunnel must remain
    # running during preflight, so probe an ephemeral loopback port here. The
    # real target health port is checked after stopping only our owned child.
    return [client, "doctor", "--profile", profile, "--explain",
            "--health.listen-addr", "127.0.0.1:0"]


def credential_file(path: str) -> dict[str, str]:
    """Read one narrowly-scoped key, never arbitrary process environment overrides."""
    target = Path(path).expanduser()
    try:
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or (hasattr(os, "getuid") and info.st_uid != os.getuid()) or info.st_size > 16_384):
            raise ConnectionError("凭据文件须属于当前用户、为普通文件且权限为 0600；不接受符号链接。")
        lines = target.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ConnectionError("无法读取接入专用凭据文件；请在本机创建并设置 chmod 600。") from exc
    values: dict[str, str] = {}
    for raw in lines:
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        key, separator, value = raw.partition("=")
        if key.strip() != "CONTROL_PLANE_API_KEY" or not separator or key.strip() in values:
            raise ConnectionError("专用凭据文件只能包含一项 CONTROL_PLANE_API_KEY，不执行 shell 内容。")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not value or any(char.isspace() for char in value):
            raise ConnectionError("专用凭据文件中的 CONTROL_PLANE_API_KEY 为空或格式无效。")
        values[key.strip()] = value
    if not values:
        raise ConnectionError("专用凭据文件缺少 CONTROL_PLANE_API_KEY。")
    return values


class ConnectionStore:
    def __init__(self, values: Mapping[str, str]):
        self.values = dict(values)
        env_path = Path(values.get("LABCONTEXT_ENV_FILE", "~/.config/labcontext/launcher.env")).expanduser()
        state_path = Path(values.get("LABCONTEXT_STATUS_FILE", "~/.local/state/labcontext-router/launcher-status.json")).expanduser()
        self.catalog_path = env_path.with_name("connections.json")
        self.operation_path = state_path.with_name("connection-operation.json")
        self.request_path = state_path.with_name("connection-request.json")

    def legacy(self) -> dict[str, Any]:
        return {"id": "current", "label": "当前接入", "profile": self.values.get("LABCONTEXT_TUNNEL_PROFILE", "labcontext"),
                "healthUrl": self.values.get("LABCONTEXT_TUNNEL_HEALTH_URL", "http://127.0.0.1:8080"),
                "credentialMode": "launcher", "secretFile": ""}

    @staticmethod
    def validate(profile: dict[str, Any]) -> dict[str, Any]:
        safe_name(profile.get("id"))
        safe_name(profile.get("profile"))
        label = profile.get("label")
        if not isinstance(label, str) or not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
            raise ConnectionError("接入备注须为 1–80 个可打印字符，请勿填写密码或密钥。")
        if re.search(r"\b(?:sk-|sess-)", label):
            raise ConnectionError("接入备注不能包含密钥或会话令牌。")
        health_address(str(profile.get("healthUrl", "")))
        if profile.get("credentialMode") not in {"launcher", "file"}:
            raise ConnectionError("接入凭据类型无效。")
        if profile.get("credentialMode") == "launcher" and profile.get("id") != "current":
            raise ConnectionError("新接入必须引用独立凭据文件，不能继承旧账号密钥。")
        if profile.get("credentialMode") == "file":
            secret_file = profile.get("secretFile")
            if not isinstance(secret_file, str) or not Path(secret_file).expanduser().is_absolute():
                raise ConnectionError("接入凭据文件须为本机绝对路径；此处只保存路径，不保存密钥。")
        allowed = {"id", "label", "profile", "healthUrl", "credentialMode", "secretFile"}
        if set(profile) - allowed:
            raise ConnectionError("接入配置包含不支持的字段；禁止保存明文密钥或浏览器凭据。")
        return profile

    def catalog(self) -> dict[str, Any]:
        data = read_json(self.catalog_path)
        if data is None:
            return {"schemaVersion": 1, "activeId": "current", "profiles": [self.legacy()]}
        profiles = data.get("profiles")
        if data.get("schemaVersion") != 1 or not isinstance(profiles, list) or not 1 <= len(profiles) <= 32:
            raise ConnectionError("接入配置版本或数量无效。")
        ids: set[str] = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ConnectionError("接入配置条目无效。")
            self.validate(profile)
            if profile["id"] in ids:
                raise ConnectionError("接入 ID 重复。")
            ids.add(profile["id"])
        if data.get("activeId") not in ids:
            raise ConnectionError("当前接入 ID 不存在。")
        return data

    def get(self, connection_id: str | None = None) -> dict[str, Any]:
        data = self.catalog()
        target = connection_id or data["activeId"]
        for profile in data["profiles"]:
            if profile["id"] == target:
                return dict(profile)
        raise ConnectionError("接入配置不存在，请先在本机登记。")

    def public(self) -> dict[str, Any]:
        data = self.catalog()
        operation = read_json(self.operation_path) or {"phase": "idle", "summary": "未执行接入切换"}
        if operation.get("phase") in {"queued", "checking", "verifying"}:
            try:
                pid = operation.get("launcherPid")
                if not isinstance(pid, int) or pid <= 1:
                    raise ProcessLookupError()
                os.kill(pid, 0)
            except ProcessLookupError:
                operation = {**operation, "phase": "failed", "reasonCode": "launcher_exited",
                             "summary": "启动器已退出，操作结果不能确认；接入选择以当前配置为准，请重新启动 labcontext。"}
            except PermissionError:
                pass
        return {"schemaVersion": 1, "activeId": data["activeId"], "saved": self.catalog_path.exists(),
                "profiles": [{key: value for key, value in profile.items() if key != "secretFile"}
                             for profile in data["profiles"]],
                "operation": operation}

    def snapshot(self) -> dict[str, Any]:
        with locked(self.catalog_path.with_suffix(".lock")):
            data = self.catalog()
            write_json(self.catalog_path, data)
        return self.public()

    def add(self, profile: dict[str, Any]) -> None:
        self.validate(profile)
        with locked(self.catalog_path.with_suffix(".lock")):
            data = self.catalog()
            if len(data["profiles"]) >= 32 or any(item["id"] == profile["id"] for item in data["profiles"]):
                raise ConnectionError("接入 ID 已存在或数量已达上限，不会覆盖现有配置。")
            data["profiles"].append(profile)
            write_json(self.catalog_path, data)

    def activate(self, connection_id: str) -> None:
        with locked(self.catalog_path.with_suffix(".lock")):
            data = self.catalog()
            self.get(connection_id)
            data["activeId"] = connection_id
            write_json(self.catalog_path, data)

    def environment(self, profile: dict[str, Any], base: Mapping[str, str]) -> dict[str, str]:
        self.validate(profile)
        result = dict(base)
        if profile["credentialMode"] == "file":
            result.pop("CONTROL_PLANE_API_KEY", None)
            result.update(credential_file(profile["secretFile"]))
        result["LABCONTEXT_TUNNEL_PROFILE"] = profile["profile"]
        result["LABCONTEXT_TUNNEL_HEALTH_URL"] = profile["healthUrl"]
        return result

    def request(self, action: str, connection_id: str, launcher_pid: int) -> dict[str, Any]:
        if action not in {"switch", "reconnect"}:
            raise ConnectionError("不支持此接入操作。")
        profile = self.get(connection_id)
        if action == "reconnect" and profile["id"] != self.catalog()["activeId"]:
            raise ConnectionError("重连只能针对当前接入；更换接入请使用 switch。")
        with locked(self.request_path.with_suffix(".lock")):
            current = self.public()["operation"]
            if current.get("phase") in {"queued", "checking", "verifying"}:
                raise ConnectionError("已有 Tunnel 操作正在进行，请等待结果。")
            operation = {"jobId": secrets.token_hex(12), "action": action, "connectionId": connection_id,
                         "launcherPid": launcher_pid, "phase": "queued", "summary": "仅重连 Tunnel 的任务已创建",
                         "startedAt": timestamp()}
            write_json(self.operation_path, operation)
            write_json(self.request_path, operation)
        return operation
