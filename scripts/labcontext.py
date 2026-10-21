#!/usr/bin/env python3
"""One-command supervisor for the optional LabContext router and transports."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from labcontext_router import DEFAULT_CONFIG_PATH, RouterError, load_config, parse_listen_addr
from labcontext_connections import ConnectionError, ConnectionStore
from labcontext_tunnel_control import TunnelControl


DEFAULT_ENV_PATH = Path("~/.config/labcontext/launcher.env").expanduser()
DEFAULT_STATUS_PATH = Path("~/.local/state/labcontext-router/launcher-status.json").expanduser()
DEFAULT_RECOVERY_STATUS_PATH = Path("~/.local/state/labcontext-router/recovery-status.json").expanduser()
DEFAULT_RECOVERY_LOG_PATH = Path("~/.local/state/labcontext-router/recovery.log").expanduser()
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:48761/labcontext/"
REMOTE_BRIDGE_PROCESS_NAME = "labcontext-ssh-bridge"
SCRIPT_DIR = Path(__file__).resolve().parent
ROUTER_SCRIPT = SCRIPT_DIR / "labcontext_router.py"

REMOTE_BRIDGE_SCRIPT = r'''set -eu
state_file=$1
case "$state_file" in
  /*) ;;
  *) state_file="$HOME/$state_file" ;;
esac
state_dir=${state_file%/*}
mkdir -p "$state_dir"
umask 077
temporary="${state_file}.$$"
printf '%s %s\n' "$PPID" "$$" > "$temporary"
mv "$temporary" "$state_file"
cleanup() {
  current=
  if [ -r "$state_file" ]; then
    IFS= read -r current < "$state_file" || true
  fi
  if [ "$current" = "$PPID $$" ]; then
    rm -f "$state_file"
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 0' HUP INT TERM
while :; do
  sleep 3600 &
  wait "$!" || true
done'''

REMOTE_BRIDGE_CLEANUP_SCRIPT = r'''set -eu
state_file=$1
case "$state_file" in
  /*) ;;
  *) state_file="$HOME/$state_file" ;;
esac
if [ ! -r "$state_file" ]; then
  printf '%s\n' 'managed bridge marker is absent' >&2
  exit 3
fi
IFS=' ' read -r session_pid shell_pid < "$state_file" || true
case "$session_pid" in
  ''|*[!0-9]*) printf '%s\n' 'managed bridge session PID is invalid' >&2; exit 4 ;;
esac
case "$shell_pid" in
  ''|*[!0-9]*) printf '%s\n' 'managed bridge shell PID is invalid' >&2; exit 4 ;;
esac
if ! kill -0 "$session_pid" 2>/dev/null || ! kill -0 "$shell_pid" 2>/dev/null; then
  printf '%s\n' 'managed bridge marker refers to an exited process' >&2
  exit 3
fi
shell_command=$(ps -p "$shell_pid" -o args= 2>/dev/null || true)
case "$shell_command" in
  *labcontext-ssh-bridge*) ;;
  *) printf '%s\n' 'marker shell is not a managed LabContext bridge' >&2; exit 4 ;;
esac
actual_parent=$(ps -p "$shell_pid" -o ppid= 2>/dev/null | tr -d ' ')
if [ "$actual_parent" != "$session_pid" ]; then
  printf '%s\n' 'managed bridge parent-child relationship changed' >&2
  exit 4
fi
session_command=$(ps -p "$session_pid" -o args= 2>/dev/null || true)
case "$session_command" in
  sshd:*) ;;
  *) printf '%s\n' 'marker parent is not an sshd session' >&2; exit 4 ;;
esac
kill -TERM "$session_pid"
attempt=0
while kill -0 "$session_pid" 2>/dev/null && [ "$attempt" -lt 50 ]; do
  attempt=$((attempt + 1))
  sleep 0.1
done
if kill -0 "$session_pid" 2>/dev/null; then
  printf '%s\n' 'managed LabContext bridge did not stop in time' >&2
  exit 5
fi
rm -f "$state_file"
printf '%s\n' "stopped managed LabContext SSH session PID $session_pid"'''


def fail(message: str) -> NoReturn:
    raise SystemExit(f"labcontext: {message}")


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            fail(f"invalid line {number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum():
            fail(f"invalid variable name on line {number} in {path}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = os.path.expanduser(value)
    return values


def process_environment(values: dict[str, str]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(values)
    return environment


def render_provider(provider_id: str, port: int, token_file: str) -> str:
    label = "This computer" if provider_id == "local" else "Research server"
    return f'''[[providers]]
id = "{provider_id}"
label = "{label}"
mcp_url = "http://127.0.0.1:{port}/mcp"
admin_url = "http://127.0.0.1:{port}/admin"
admin_token_file = "{token_file}"
enabled = true
timeout_seconds = 20
minimum_version = "0.7.0"
'''


def init_config(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser()
    env_path = args.env_file.expanduser()
    existing = [path for path in (config_path, env_path) if path.exists()]
    if existing and not args.force:
        fail("refusing to overwrite existing configuration: " + ", ".join(map(str, existing)))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    providers: list[str] = []
    if args.mode in {"local", "hybrid"}:
        local_port = 1456 if args.mode == "hybrid" else 1455
        providers.append(render_provider("local", local_port, "~/.local/state/labcontext-local/admin.token"))
    if args.mode in {"server", "hybrid"}:
        providers.append(render_provider("server", 1455, "~/.local/state/labcontext/admin.token"))
    config_path.write_text(
        '''[router]
listen_addr = "127.0.0.1:1460"
cors_origins = ["http://127.0.0.1:48761", "http://localhost:48761"]

''' + "\n".join(providers),
        encoding="utf-8",
    )
    enable_ssh = args.mode in {"server", "hybrid"} and bool(args.ssh_host)
    env_path.write_text(
        "\n".join([
            f"LABCONTEXT_MODE={args.mode}",
            f"LABCONTEXT_ROUTER_CONFIG={config_path}",
            f"LABCONTEXT_ENABLE_SSH={'1' if enable_ssh else '0'}",
            f"LABCONTEXT_SSH_HOST={args.ssh_host or ''}",
            "LABCONTEXT_SSH_BATCH_MODE=1",
            "LABCONTEXT_SSH_CONNECT_TIMEOUT=8",
            "LABCONTEXT_SSH_SERVER_ALIVE_INTERVAL=30",
            "LABCONTEXT_SSH_SERVER_ALIVE_COUNT_MAX=3",
            "LABCONTEXT_SERVER_MCP_LOCAL_PORT=1455",
            "LABCONTEXT_SERVER_MCP_REMOTE_PORT=1455",
            "LABCONTEXT_SERVER_WEB_LOCAL_PORT=48761",
            "LABCONTEXT_SERVER_WEB_REMOTE_PORT=48761",
            f"LABCONTEXT_ENABLE_TUNNEL={'1' if args.tunnel_profile else '0'}",
            f"LABCONTEXT_TUNNEL_PROFILE={args.tunnel_profile or 'labcontext'}",
            "LABCONTEXT_TUNNEL_CLIENT=tunnel-client",
            "LABCONTEXT_TUNNEL_HEALTH_URL=http://127.0.0.1:8080",
            "LABCONTEXT_STATUS_FILE=~/.local/state/labcontext-router/launcher-status.json",
            "LABCONTEXT_DASHBOARD_URL=http://127.0.0.1:48761/labcontext/",
            "# LABCONTEXT_SECRET_ENV_FILE=~/.config/labcontext/secrets.env",
            "# Optional SSH settings: identity/config files and a reverse proxy forwarding pair.",
            "# LABCONTEXT_SSH_IDENTITY_FILE=~/.ssh/id_ed25519",
            "# LABCONTEXT_SSH_CONFIG_FILE=~/.ssh/config",
            "# LABCONTEXT_SERVER_PROXY_REMOTE_PORT=17987",
            "# LABCONTEXT_LOCAL_PROXY_PORT=7897",
            "# Optional: start an independently installed local Provider with the same command.",
            "# LABCONTEXT_LOCAL_PROVIDER_COMMAND=labcontext-provider --listen 127.0.0.1:1456",
            "",
            "# Keep CONTROL_PLANE_API_KEY in this chmod-600 file or inject it from your secret manager.",
            "# CONTROL_PLANE_API_KEY=replace-me",
            "",
        ]),
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)
    print(f"created {config_path}")
    print(f"created {env_path} (mode {args.mode})")
    print("edit provider ports/token paths if needed, then run: labcontext doctor && labcontext")
    return 0


def require_program(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        fail(f"required program is not installed or not on PATH: {name}")
    return resolved


def local_provider_command(values: dict[str, str]) -> list[str] | None:
    raw = values.get("LABCONTEXT_LOCAL_PROVIDER_COMMAND", "").strip()
    if not raw:
        return None
    command = shlex.split(raw)
    if not command:
        return None
    command[0] = require_program(command[0])
    return command


def doctor(config_path: Path, values: dict[str, str]) -> int:
    config = load_config(config_path)
    address = parse_listen_addr(config.listen_addr)
    print(f"router config: ok ({config_path})")
    print(f"router endpoint: http://{address[0]}:{address[1]}/mcp")
    print("providers: " + ", ".join(provider.id for provider in config.providers if provider.enabled))
    provider_command = local_provider_command(values)
    print(f"local Provider process: {'configured' if provider_command else 'externally managed'}")
    if parse_bool(values.get("LABCONTEXT_ENABLE_SSH")):
        require_program("ssh")
        if not values.get("LABCONTEXT_SSH_HOST"):
            fail("LABCONTEXT_ENABLE_SSH=1 requires LABCONTEXT_SSH_HOST")
        print(f"SSH bridge: configured ({values['LABCONTEXT_SSH_HOST']})")
        ok, detail = probe_ssh(values)
        if not ok:
            print(f"SSH connection: failed ({detail})", file=sys.stderr)
            print_ssh_recovery_hint(values)
            return 2
        print(f"SSH connection: ok ({detail})")
        ssh_runtime = runtime_component(values, "ssh-bridge")
        if not ssh_runtime or ssh_runtime.get("status") != "running":
            forwarding_ok, forwarding_detail = probe_ssh_remote_forward(values)
            if not forwarding_ok:
                print(f"SSH reverse forwarding: failed ({forwarding_detail})", file=sys.stderr)
                print(
                    "recovery: the remote listen port may still belong to an older SSH session; "
                    "inspect that session or choose another LABCONTEXT_SERVER_PROXY_REMOTE_PORT, then run labcontext repair",
                    file=sys.stderr,
                )
                return 2
            if forwarding_detail:
                print(f"SSH reverse forwarding: ok ({forwarding_detail})")
    else:
        print("SSH bridge: disabled")
    if parse_bool(values.get("LABCONTEXT_ENABLE_TUNNEL")):
        require_program(values.get("LABCONTEXT_TUNNEL_CLIENT", "tunnel-client"))
        store = ConnectionStore(values)
        profile = store.get()
        if profile["credentialMode"] == "file":
            store.environment(profile, {})  # Validate without printing or launching credentials.
        print(f"Secure MCP Tunnel: configured ({profile['profile']})")
    else:
        print("Secure MCP Tunnel: disabled")
    runtime = fetch_router_status(address)
    if runtime:
        print(f"runtime: {runtime.get('overall', 'ready')} (router already running)")
    else:
        print("runtime: stopped or not reachable")
    return 0


def ssh_option_command(values: dict[str, str]) -> list[str]:
    command = [require_program("ssh")]
    config_file = values.get("LABCONTEXT_SSH_CONFIG_FILE")
    if config_file:
        command.extend(["-F", config_file])
    if parse_bool(values.get("LABCONTEXT_SSH_BATCH_MODE"), default=True):
        command.extend(["-o", "BatchMode=yes"])
    alive_interval = values.get("LABCONTEXT_SSH_SERVER_ALIVE_INTERVAL", "30")
    alive_count = values.get("LABCONTEXT_SSH_SERVER_ALIVE_COUNT_MAX", "3")
    command.extend([
        "-o", f"ServerAliveInterval={alive_interval}",
        "-o", f"ServerAliveCountMax={alive_count}",
    ])
    identity = values.get("LABCONTEXT_SSH_IDENTITY_FILE")
    if identity:
        command.extend(["-i", identity])
    return command


def _forward_port(value: str) -> str:
    endpoint = value.strip().split()[0]
    return endpoint.rsplit(":", 1)[-1].strip("[]")


def remote_bridge_state_file(values: dict[str, str]) -> str:
    configured = values.get("LABCONTEXT_SSH_REMOTE_STATE_FILE", "").strip()
    if configured:
        if any(character in configured for character in ("\0", "\n", "\r")):
            fail("LABCONTEXT_SSH_REMOTE_STATE_FILE contains an invalid character")
        return configured
    port = values.get("LABCONTEXT_SERVER_PROXY_REMOTE_PORT", "session").strip()
    safe_port = port if port.isdigit() else "session"
    return f".local/state/labcontext/ssh-bridge-{safe_port}.pid"


def remote_shell_command(script: str, process_name: str, *arguments: str) -> str:
    quoted = " ".join(shlex.quote(item) for item in arguments)
    suffix = f" {quoted}" if quoted else ""
    return f"sh -c {shlex.quote(script)} {shlex.quote(process_name)}{suffix}"


def ssh_config_forwardings(values: dict[str, str]) -> tuple[set[str], set[str]]:
    host = values.get("LABCONTEXT_SSH_HOST", "").strip()
    if not host:
        return set(), set()
    command = ssh_option_command(values)
    command.extend(["-G", host])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set(), set()
    if result.returncode != 0:
        return set(), set()
    local: set[str] = set()
    remote: set[str] = set()
    for raw_line in result.stdout.splitlines():
        key, _, value = raw_line.partition(" ")
        if key == "localforward" and value:
            local.add(_forward_port(value))
        elif key == "remoteforward" and value:
            remote.add(_forward_port(value))
    return local, remote


def ssh_command(values: dict[str, str]) -> list[str]:
    command = ssh_option_command(values)
    remote_proxy = values.get("LABCONTEXT_SERVER_PROXY_REMOTE_PORT")
    command.extend(["-T" if remote_proxy else "-N", "-o", "ExitOnForwardFailure=yes"])
    configured_local, configured_remote = ssh_config_forwardings(values)
    local_mcp = values.get("LABCONTEXT_SERVER_MCP_LOCAL_PORT", "1455")
    remote_mcp = values.get("LABCONTEXT_SERVER_MCP_REMOTE_PORT", "1455")
    if local_mcp not in configured_local:
        command.extend(["-L", f"127.0.0.1:{local_mcp}:127.0.0.1:{remote_mcp}"])
    local_web = values.get("LABCONTEXT_SERVER_WEB_LOCAL_PORT")
    remote_web = values.get("LABCONTEXT_SERVER_WEB_REMOTE_PORT", "48761")
    if local_web and local_web not in configured_local:
        command.extend(["-L", f"127.0.0.1:{local_web}:127.0.0.1:{remote_web}"])
    local_proxy = values.get("LABCONTEXT_LOCAL_PROXY_PORT")
    if bool(remote_proxy) != bool(local_proxy):
        fail("reverse proxy forwarding requires both LABCONTEXT_SERVER_PROXY_REMOTE_PORT and LABCONTEXT_LOCAL_PROXY_PORT")
    if remote_proxy and local_proxy and remote_proxy not in configured_remote:
        command.extend(["-R", f"127.0.0.1:{remote_proxy}:127.0.0.1:{local_proxy}"])
    command.append(values["LABCONTEXT_SSH_HOST"])
    if remote_proxy:
        command.append(remote_shell_command(
            REMOTE_BRIDGE_SCRIPT,
            REMOTE_BRIDGE_PROCESS_NAME,
            remote_bridge_state_file(values),
        ))
    return command


def cleanup_managed_remote_forward(values: dict[str, str]) -> tuple[bool, str]:
    host = values.get("LABCONTEXT_SSH_HOST", "").strip()
    if not host:
        return False, "SSH host is not configured"
    if not values.get("LABCONTEXT_SERVER_PROXY_REMOTE_PORT"):
        return False, "reverse proxy forwarding is not configured"
    command = ssh_option_command(values)
    command.extend([
        "-o", "ClearAllForwardings=yes",
        "-o", f"ConnectTimeout={values.get('LABCONTEXT_SSH_CONNECT_TIMEOUT', '8')}",
        host,
        remote_shell_command(
            REMOTE_BRIDGE_CLEANUP_SCRIPT,
            "labcontext-ssh-bridge-cleanup",
            remote_bridge_state_file(values),
        ),
    ])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        return False, "managed remote bridge cleanup timed out"
    except OSError as exc:
        return False, str(exc)
    output = "\n".join(
        line.strip()
        for line in (result.stdout, result.stderr)
        if line.strip()
    )
    if result.returncode == 0:
        return True, output or "stopped managed LabContext bridge"
    return False, output or f"managed remote bridge cleanup exited with status {result.returncode}"


def probe_ssh(values: dict[str, str]) -> tuple[bool, str]:
    host = values.get("LABCONTEXT_SSH_HOST", "").strip()
    if not host:
        return False, "SSH host is not configured"
    command = ssh_option_command(values)
    command.extend([
        "-o", "ClearAllForwardings=yes",
        "-o", f"ConnectTimeout={values.get('LABCONTEXT_SSH_CONNECT_TIMEOUT', '8')}",
        host,
        "true",
    ])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        return False, "connection timed out"
    except OSError as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, host
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    detail = lines[-1] if lines else f"ssh exited with status {result.returncode}"
    return False, detail.replace(str(Path.home()), "~")


def probe_ssh_remote_forward(values: dict[str, str]) -> tuple[bool, str]:
    remote_proxy = values.get("LABCONTEXT_SERVER_PROXY_REMOTE_PORT")
    local_proxy = values.get("LABCONTEXT_LOCAL_PROXY_PORT")
    if not remote_proxy and not local_proxy:
        return True, "not configured"
    if not remote_proxy or not local_proxy:
        return False, "both reverse proxy ports must be configured"
    configured_local, configured_remote = ssh_config_forwardings(values)
    if configured_local or configured_remote:
        return True, "declared by SSH config; standalone port probe skipped"
    host = values["LABCONTEXT_SSH_HOST"]
    command = ssh_option_command(values)
    command.extend([
        "-o", f"ConnectTimeout={values.get('LABCONTEXT_SSH_CONNECT_TIMEOUT', '8')}",
        "-o", "ExitOnForwardFailure=yes",
        "-R", f"127.0.0.1:{remote_proxy}:127.0.0.1:{local_proxy}",
        host,
        "true",
    ])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except subprocess.TimeoutExpired:
        return False, "forwarding probe timed out"
    except OSError as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, f"remote 127.0.0.1:{remote_proxy} is available"
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    detail = lines[-1] if lines else f"ssh exited with status {result.returncode}"
    return False, detail.replace(str(Path.home()), "~")


def print_ssh_recovery_hint(values: dict[str, str]) -> None:
    host = values.get("LABCONTEXT_SSH_HOST", "your-server")
    print("recovery:", file=sys.stderr)
    if values.get("LABCONTEXT_SSH_CONFIG_FILE") == "/dev/null":
        print(
            "  launcher.env disables ~/.ssh/config; SSH aliases, ProxyJump, and host-specific algorithms are ignored",
            file=sys.stderr,
        )
    print(
        f"  verify: ssh -o ClearAllForwardings=yes {shlex.quote(host)} true",
        file=sys.stderr,
    )
    print("  after correcting launcher.env, run: labcontext repair", file=sys.stderr)


def wait_for_router(address: tuple[str, int], process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(f"router exited during startup with status {process.returncode}")
        try:
            with socket.create_connection(address, timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    fail(f"router did not start on {address[0]}:{address[1]} within 10 seconds")


def router_base_url(address: tuple[str, int]) -> str:
    return f"http://{address[0]}:{address[1]}"


def fetch_json(url: str, timeout: float = 1.5) -> dict[str, object] | None:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=timeout)
        value = json.loads(response.read().decode("utf-8") or "{}")
        return value if isinstance(value, dict) else None
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def fetch_router_status(address: tuple[str, int]) -> dict[str, object] | None:
    base = router_base_url(address)
    status = fetch_json(f"{base}/api/status")
    router = status.get("router") if status else None
    if isinstance(router, dict) and router.get("name") == "LabContext Router":
        return status
    # Older routers do not expose /api/status. Recognize their health payload so
    # an upgrade does not accidentally start a duplicate stack.
    legacy = fetch_json(f"{base}/healthz")
    if legacy and legacy.get("ok") is True and isinstance(legacy.get("providers"), list):
        return {
            "overall": "legacy",
            "router": {"name": "LabContext Router", "version": "older than 0.3.0"},
            "providers": legacy["providers"],
        }
    return None


def port_is_open(address: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(address, timeout=0.3):
            return True
    except OSError:
        return False


def runtime_status_path(values: dict[str, str]) -> Path:
    return Path(values.get("LABCONTEXT_STATUS_FILE", str(DEFAULT_STATUS_PATH))).expanduser()


def process_status(
    label: str,
    process: subprocess.Popen[bytes],
    started: dict[str, float] | None = None,
    restart_after: dict[str, float] | None = None,
    restart_attempts: dict[str, int] | None = None,
) -> dict[str, object]:
    status = process.poll()
    component_id = {
        "local Provider": "local-provider",
        "SSH bridge": "ssh-bridge",
        "LabContext Router": "router",
        "Secure MCP Tunnel": "secure-mcp-tunnel",
    }.get(label, label.lower().replace(" ", "-"))
    if status is None:
        process_state = (
            "starting"
            if started and time.monotonic() - started.get(label, 0) < 2
            else "running"
        )
    elif restart_after and label in restart_after:
        process_state = "retrying"
    else:
        process_state = "exited"
    result: dict[str, object] = {
        "id": component_id,
        "label": label,
        "pid": process.pid,
        "status": process_state,
        "exitCode": status,
    }
    if restart_after and label in restart_after:
        remaining = max(0.0, restart_after[label] - time.monotonic())
        result["retryInSeconds"] = int(remaining + 0.999)
    if restart_attempts and restart_attempts.get(label):
        result["restartAttempts"] = restart_attempts[label]
    return result


def write_runtime_status(
    path: Path,
    started_at: str,
    processes: list[tuple[str, subprocess.Popen[bytes]]],
    phase: str,
    started: dict[str, float] | None = None,
    restart_after: dict[str, float] | None = None,
    restart_attempts: dict[str, int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "tunnelControlVersion": 1,
        "launcherPid": os.getpid(),
        "startedAt": started_at,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": phase,
        "components": [
            process_status(label, process, started, restart_after, restart_attempts)
            for label, process in processes
        ],
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def show_status(config_path: Path) -> int:
    config = load_config(config_path)
    address = parse_listen_addr(config.listen_addr)
    status = fetch_router_status(address)
    if not status:
        fail(f"LabContext Router is not reachable at {router_base_url(address)}")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def read_runtime_status(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def runtime_component(values: dict[str, str], component_id: str) -> dict[str, object] | None:
    runtime = read_runtime_status(runtime_status_path(values))
    components = runtime.get("components") if runtime else None
    if not isinstance(components, list):
        return None
    return next(
        (item for item in components if isinstance(item, dict) and item.get("id") == component_id),
        None,
    )


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_is_labcontext_launcher(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    command = result.stdout.strip().lower()
    return bool(command) and "labcontext" in command and "labcontext_router" not in command


def process_is_labcontext_component(
    pid: int,
    component_id: str,
    config_path: Path,
    values: dict[str, str],
) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        process_group = os.getpgid(pid)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        return False
    command = result.stdout.strip()
    if not command or process_group != pid:
        return False
    if component_id == "router":
        return "labcontext_router.py" in command and str(config_path) in command
    if component_id == "ssh-bridge":
        host = values.get("LABCONTEXT_SSH_HOST", "")
        return bool(host) and "ExitOnForwardFailure=yes" in command and host in command
    if component_id == "secure-mcp-tunnel":
        profile = ConnectionStore(values).get()["profile"]
        return "tunnel-client" in command and " run " in f" {command} " and f"--profile {profile}" in command
    if component_id == "local-provider":
        expected = local_provider_command(values)
        if not expected:
            return False
        index = 0
        if Path(expected[0]).name == "env":
            index = 1
            while index < len(expected) and "=" in expected[index]:
                index += 1
        identity = expected[index:]
        return bool(identity) and all(argument in command for argument in identity)
    return False


def stop_verified_orphan_components(
    config_path: Path,
    values: dict[str, str],
    runtime: dict[str, object],
) -> bool:
    components = runtime.get("components")
    if not isinstance(components, list):
        return False
    candidates: list[tuple[str, int]] = []
    for item in components:
        if not isinstance(item, dict):
            continue
        component_id = item.get("id")
        pid = item.get("pid")
        if not isinstance(component_id, str) or not isinstance(pid, int) or pid <= 1:
            continue
        if process_is_alive(pid):
            candidates.append((component_id, pid))
    if not candidates:
        return False
    for component_id, pid in candidates:
        if not process_is_labcontext_component(pid, component_id, config_path, values):
            fail(
                f"refusing to signal orphan PID {pid}: component {component_id} "
                "does not match the recorded LabContext command"
            )
    print("labcontext: verified stale launcher; stopping recorded orphan components")
    for _, pid in reversed(candidates):
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not any(process_is_alive(pid) for _, pid in candidates):
            try:
                runtime_status_path(values).unlink()
            except FileNotFoundError:
                pass
            print("labcontext: verified orphan components stopped cleanly")
            return True
        time.sleep(0.1)
    remaining = [str(pid) for _, pid in candidates if process_is_alive(pid)]
    fail(
        "verified orphan components did not stop cleanly within 10 seconds: "
        + ", ".join(remaining)
    )


def stop_running_stack(config_path: Path, values: dict[str, str]) -> bool:
    config = load_config(config_path)
    address = parse_listen_addr(config.listen_addr)
    status_path = runtime_status_path(values)
    runtime = read_runtime_status(status_path)
    launcher_pid = runtime.get("launcherPid") if runtime else None
    if not isinstance(launcher_pid, int) or launcher_pid <= 1 or not process_is_alive(launcher_pid):
        if runtime and stop_verified_orphan_components(config_path, values, runtime):
            return True
        router_status = fetch_router_status(address)
        if router_status:
            router = router_status.get("router")
            router_pid = router.get("pid", "unknown") if isinstance(router, dict) else "unknown"
            fail(
                "Router is running but its launcher cannot be verified; "
                f"inspect PID {router_pid} before stopping it"
            )
        print("labcontext: stack is not running")
        return False
    if not process_is_labcontext_launcher(launcher_pid):
        fail(f"refusing to signal PID {launcher_pid}: it is not a verified labcontext launcher")
    print(f"labcontext: stopping existing launcher PID {launcher_pid}")
    os.kill(launcher_pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not process_is_alive(launcher_pid) and not port_is_open(address):
            print("labcontext: previous stack stopped cleanly")
            return True
        time.sleep(0.1)
    fail(
        f"launcher PID {launcher_pid} did not stop cleanly within 10 seconds; "
        "no force kill was attempted"
    )


def recovery_preflight(
    config_path: Path,
    values: dict[str, str],
) -> tuple[int, str, bool]:
    result, diagnostics = capture_doctor(config_path, values)
    if result == 0 or "remote port forwarding failed" not in diagnostics.lower():
        return result, diagnostics, False

    stop_running_stack(config_path, values)
    stack_stopped = True
    retry_result, retry_diagnostics = capture_doctor(config_path, values)
    diagnostics = "\n\n".join((
        diagnostics,
        "After stopping the verified local LabContext stack:\n" + retry_diagnostics,
    ))
    if retry_result == 0:
        return 0, diagnostics, stack_stopped
    if "remote port forwarding failed" not in retry_diagnostics.lower():
        return retry_result, diagnostics, stack_stopped

    cleaned, cleanup_detail = cleanup_managed_remote_forward(values)
    diagnostics += "\n\nManaged remote bridge cleanup:\n" + cleanup_detail
    if not cleaned:
        return retry_result, diagnostics, stack_stopped

    final_result, final_diagnostics = wait_for_post_cleanup_validation(config_path, values)
    diagnostics += "\n\nAfter managed bridge cleanup:\n" + final_diagnostics
    return final_result, diagnostics, stack_stopped


def wait_for_post_cleanup_validation(
    config_path: Path,
    values: dict[str, str],
    timeout_seconds: float = 15.0,
) -> tuple[int, str]:
    """Wait for remote teardown or a concurrently starting healthy stack.

    A managed remote SSH session can disappear just as another verified
    LabContext launcher claims the same reverse-forward port. Treating that
    short hand-off as a stale-port failure makes a successful repair look
    broken, so re-check both the doctor probe and the Router's real status for
    a bounded period.
    """
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    address: tuple[str, int] | None = None
    last_result = 2
    last_diagnostics = "post-cleanup validation did not run"

    while True:
        last_result, last_diagnostics = capture_doctor(config_path, values)
        if last_result == 0:
            return 0, last_diagnostics
        if "remote port forwarding failed" not in last_diagnostics.lower():
            return last_result, last_diagnostics

        if address is None:
            address = parse_listen_addr(load_config(config_path).listen_addr)
        runtime = fetch_router_status(address)
        if runtime and runtime.get("overall") == "ready":
            return 0, "\n".join((
                last_diagnostics,
                "runtime: ready (a new healthy LabContext stack took ownership during cleanup)",
            ))

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last_result, last_diagnostics
        time.sleep(min(0.5, remaining))


def repair(config_path: Path, values: dict[str, str]) -> int:
    config = load_config(config_path)
    address = parse_listen_addr(config.listen_addr)
    status = fetch_router_status(address)
    if status and status.get("overall") == "ready":
        print("labcontext: all configured components already passed real capability checks")
        return 0
    print("labcontext: validating configuration before recovery")
    validation, diagnostics, stack_stopped = recovery_preflight(config_path, values)
    if diagnostics:
        print(diagnostics, file=sys.stderr if validation != 0 else sys.stdout)
    if validation != 0:
        print("labcontext: repair stopped because the remaining conflict could not be safely claimed", file=sys.stderr)
        return validation
    if not stack_stopped:
        stop_running_stack(config_path, values)
    print("labcontext: starting a fresh stack with the current configuration")
    return run(config_path, values)


def recover_bridge_conflict(values: dict[str, str], *, allow_cleanup: bool = True) -> tuple[bool, str]:
    """Recover only a verified managed session after a failed bridge exit.

    The caller must have observed its own bridge exit first; probing a port
    while that bridge is alive would mistake our own listener for a conflict.
    """
    ok, detail = probe_ssh_remote_forward(values)
    if ok or "remote port forwarding failed" not in detail.lower():
        return False, detail
    if not allow_cleanup:
        return False, f"{detail}\nAutomatic cleanup limit reached; run labcontext repair after inspecting competing sessions."
    cleaned, cleanup_detail = cleanup_managed_remote_forward(values)
    if not cleaned:
        return False, f"{detail}\nAutomatic cleanup refused: {cleanup_detail}"
    deadline = time.monotonic() + 15
    while True:
        ok, detail = probe_ssh_remote_forward(values)
        if ok:
            return True, cleanup_detail
        if "remote port forwarding failed" not in detail.lower() or time.monotonic() >= deadline:
            return False, f"{cleanup_detail}\nReverse forwarding still unavailable: {detail}"
        time.sleep(0.5)


def write_recovery_status(values: dict[str, str], payload: dict[str, object]) -> None:
    path = Path(values.get(
        "LABCONTEXT_RECOVERY_STATUS_FILE", str(DEFAULT_RECOVERY_STATUS_PATH),
    )).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schemaVersion"] = 1
    payload["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def recovery_failure_from_diagnostics(output: str, values: dict[str, str]) -> dict[str, object]:
    normalized = output.lower()
    if "remote port forwarding failed" in normalized:
        port = values.get("LABCONTEXT_SERVER_PROXY_REMOTE_PORT", "17987")
        marker = remote_bridge_state_file(values)
        return {
            "reasonCode": "ssh_reverse_port_in_use",
            "summary": f"服务器反向转发端口 {port} 已被占用，且无法确认占用者属于当前 LabContext",
            "detail": output,
            "suggestions": [
                f"新版会通过远端标记 {marker} 自动清理自己留下的会话；缺少标记时不会误杀其他 SSH 转发。",
                f"在服务器确认占用 127.0.0.1:{port} 的进程属于旧版 LabContext 会话后将其停止，或更换 LABCONTEXT_SERVER_PROXY_REMOTE_PORT。",
                "处理后再次点击“一键修复”。",
            ],
            "command": "labcontext repair",
        }
    if "permission denied" in normalized or "publickey" in normalized:
        return {
            "reasonCode": "ssh_authentication_failed",
            "summary": "SSH 身份验证失败，自动修复不会修改密钥或登录配置",
            "detail": output,
            "suggestions": [
                "确认 launcher.env 使用了正确的 SSH 别名、配置文件或私钥。",
                "先在终端验证 SSH 登录，再次点击“一键修复”。",
            ],
            "command": "labcontext doctor",
        }
    if "timed out" in normalized or "operation timed out" in normalized:
        return {
            "reasonCode": "ssh_connection_timeout",
            "summary": "SSH 连接超时，当前网络无法到达服务器",
            "detail": output,
            "suggestions": ["检查 VPN、校园网、跳板机和服务器地址，然后再次尝试。"],
            "command": "labcontext doctor",
        }
    if "required program is not installed" in normalized:
        return {
            "reasonCode": "dependency_missing",
            "summary": "缺少 LabContext 启动所需的本机程序",
            "detail": output,
            "suggestions": ["安装诊断中指出的程序，确认它位于 PATH 后再次尝试。"],
            "command": "labcontext doctor",
        }
    return {
        "reasonCode": "diagnostics_failed",
        "summary": "安全检查未通过，未改动当前运行进程",
        "detail": output or "labcontext doctor 未返回更多信息",
        "suggestions": ["按上方原始诊断修正配置后再次点击“一键修复”。"],
        "command": "labcontext repair",
    }


def runtime_recovery_failure(status: dict[str, object] | None) -> dict[str, object]:
    if not status:
        return {
            "reasonCode": "router_start_timeout",
            "summary": "重启后 Router 未能在限定时间内响应",
            "detail": "未能读取 http://127.0.0.1:1460/api/status。",
            "suggestions": ["查看恢复日志并运行 labcontext doctor。"],
            "command": "labcontext doctor",
        }
    providers = status.get("providers")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("status") != "ready":
                label = provider.get("label") or provider.get("id") or "Provider"
                detail = provider.get("error") or provider.get("adminError") or "真实能力检查未通过"
                return {
                    "reasonCode": "provider_unavailable",
                    "summary": f"{label} 在重启后仍不可用",
                    "detail": str(detail),
                    "suggestions": ["检查对应 Provider 服务与端口，再次执行修复。"],
                    "command": "labcontext status",
                }
    tunnel = status.get("tunnel")
    if isinstance(tunnel, dict) and tunnel.get("enabled") and tunnel.get("status") != "ready":
        return {
            "reasonCode": "tunnel_unavailable",
            "summary": "OpenAI Tunnel 在重启后仍未就绪",
            "detail": str(tunnel.get("detail") or "Tunnel 健康检查失败"),
            "suggestions": ["检查 tunnel profile 和 OpenAI Tunnel 登录状态。"],
            "command": "labcontext connections reconnect",
        }
    return {
        "reasonCode": "recovery_verification_failed",
        "summary": "重启已完成，但完整能力检查仍未通过",
        "detail": json.dumps(status, ensure_ascii=False)[:6000],
        "suggestions": ["复制诊断信息，并运行 labcontext doctor 获取进一步原因。"],
        "command": "labcontext doctor",
    }


def capture_doctor(config_path: Path, values: dict[str, str]) -> tuple[int, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = doctor(config_path, values)
    except SystemExit as exc:
        result = exc.code if isinstance(exc.code, int) else 2
        if exc.code and not isinstance(exc.code, int):
            stderr.write(str(exc.code))
    except (RouterError, OSError, ValueError) as exc:
        result = 2
        stderr.write(f"labcontext: {exc}")
    output = "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue()) if part.strip())
    return int(result), output[-12000:]


def recovery_worker(config_path: Path, values: dict[str, str]) -> int:
    # Give the HTTP handler enough time to return 202 before the old Router is stopped.
    time.sleep(0.8)
    job_id = os.environ.get("LABCONTEXT_RECOVERY_JOB_ID", "unknown")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    base: dict[str, object] = {
        "jobId": job_id,
        "workerPid": os.getpid(),
        "startedAt": started_at,
        "suggestions": [],
    }
    write_recovery_status(values, {
        **base,
        "phase": "diagnosing",
        "summary": "正在检查 SSH、端口、Provider 与 Tunnel 配置",
    })
    try:
        result, diagnostics, stack_stopped = recovery_preflight(config_path, values)
    except (SystemExit, RouterError, OSError, ValueError) as exc:
        result = 2
        diagnostics = str(exc)
        stack_stopped = False
    if result != 0:
        write_recovery_status(values, {
            **base,
            "phase": "failed",
            **recovery_failure_from_diagnostics(diagnostics, values),
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return result

    current = fetch_router_status(parse_listen_addr(load_config(config_path).listen_addr))
    if current and current.get("overall") == "ready":
        write_recovery_status(values, {
            **base,
            "phase": "succeeded",
            "summary": "LabContext 已恢复，无需重启",
            "detail": diagnostics,
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return 0

    write_recovery_status(values, {
        **base,
        "phase": "restarting",
        "summary": "安全检查通过，正在重建 LabContext 连接",
        "detail": diagnostics,
    })
    if not stack_stopped:
        try:
            stop_running_stack(config_path, values)
        except (SystemExit, RouterError, OSError, ValueError) as exc:
            failure = recovery_failure_from_diagnostics(str(exc), values)
            write_recovery_status(values, {
                **base,
                "phase": "failed",
                **failure,
                "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return 2

    env_path = Path(values.get("LABCONTEXT_ENV_FILE", str(DEFAULT_ENV_PATH))).expanduser()
    launcher_script = Path(values.get("LABCONTEXT_LAUNCHER_SCRIPT", str(Path(__file__).resolve()))).expanduser()
    log_path = Path(values.get(
        "LABCONTEXT_RECOVERY_LOG_FILE", str(DEFAULT_RECOVERY_LOG_PATH),
    )).expanduser()
    command = [
        sys.executable, str(launcher_script),
        "--env-file", str(env_path),
        "--config", str(config_path),
    ]
    try:
        with log_path.open("ab", buffering=0) as log_handle:
            launcher = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=process_environment(values),
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        write_recovery_status(values, {
            **base,
            "phase": "failed",
            "reasonCode": "launcher_start_failed",
            "summary": "诊断通过，但新的 LabContext 启动器无法启动",
            "detail": str(exc),
            "suggestions": ["运行 labcontext 检查启动器安装与权限。"],
            "command": "labcontext",
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        return 2

    write_recovery_status(values, {
        **base,
        "phase": "verifying",
        "summary": "连接已重建，正在执行真实能力验证",
        "launcherPid": launcher.pid,
    })
    address = parse_listen_addr(load_config(config_path).listen_addr)
    deadline = time.monotonic() + 45
    last_status: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_status = fetch_router_status(address)
        if last_status and last_status.get("overall") == "ready":
            write_recovery_status(values, {
                **base,
                "phase": "succeeded",
                "summary": "一键修复完成，LabContext 本机链路已恢复",
                "detail": "Provider 真实调用及已启用传输检查通过；ChatGPT 插件需在目标账号单独验证。",
                "launcherPid": launcher.pid,
                "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            return 0
        # A concurrent launcher may already own the stack; run() exits zero
        # in that case. Keep validating the live Router during its startup,
        # instead of reporting failure because this redundant child exited.
        if launcher.poll() not in (None, 0):
            break
        time.sleep(1)

    write_recovery_status(values, {
        **base,
        "phase": "failed",
        **runtime_recovery_failure(last_status),
        "launcherPid": launcher.pid,
        "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return 2


def stop_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _, process in reversed(processes):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 4
    for _, process in reversed(processes):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run(config_path: Path, values: dict[str, str]) -> int:
    config = load_config(config_path)
    address = parse_listen_addr(config.listen_addr)
    environment = process_environment(values)
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    restart_commands: dict[str, list[str]] = {}
    restart_environments: dict[str, dict[str, str]] = {}
    process_started: dict[str, float] = {}
    restart_after: dict[str, float] = {}
    restart_attempts: dict[str, int] = {}
    status_path = runtime_status_path(values)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    shutting_down = False
    bridge_cleanup_attempted = False

    def start_component(label: str, command: list[str], restart: bool = True,
                        component_env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
        child_env = component_env if component_env is not None else environment
        process = subprocess.Popen(command, env=child_env, start_new_session=True)
        processes.append((label, process))
        process_started[label] = time.monotonic()
        if restart:
            restart_commands[label] = command
            restart_environments[label] = child_env
        return process

    store = ConnectionStore(values)
    tunnel_control: TunnelControl | None = None

    def stop_tunnel() -> None:
        owned = [(label, process) for label, process in processes if label == "Secure MCP Tunnel"]
        stop_processes(owned)
        processes[:] = [(label, process) for label, process in processes if label != "Secure MCP Tunnel"]
        restart_commands.pop("Secure MCP Tunnel", None)
        restart_after.pop("Secure MCP Tunnel", None)

    def start_tunnel(profile: dict[str, object]) -> subprocess.Popen[bytes]:
        client = require_program(values.get("LABCONTEXT_TUNNEL_CLIENT", "tunnel-client"))
        return start_component("Secure MCP Tunnel", [client, "run", "--profile", str(profile["profile"])],
                               component_env=store.environment(profile, environment))

    existing = fetch_router_status(address)
    if existing:
        print(
            f"labcontext: already running at {router_base_url(address)} "
            f"({existing.get('overall', 'ready')}); no duplicate processes were started"
        )
        dashboard = values.get("LABCONTEXT_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)
        if dashboard:
            print(f"labcontext: connection center {dashboard}")
        return 0
    if port_is_open(address):
        fail(
            f"router port {address[0]}:{address[1]} is occupied by a process "
            "that is not a compatible LabContext Router"
        )

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        provider_command = local_provider_command(values)
        if provider_command:
            start_component("local Provider", provider_command)
        if parse_bool(values.get("LABCONTEXT_ENABLE_SSH")):
            if not values.get("LABCONTEXT_SSH_HOST"):
                fail("LABCONTEXT_ENABLE_SSH=1 requires LABCONTEXT_SSH_HOST")
            start_component("SSH bridge", ssh_command(values))
        write_runtime_status(
            status_path, started_at, processes, "starting",
            process_started, restart_after, restart_attempts,
        )
        router = start_component("LabContext Router", [
            sys.executable, str(ROUTER_SCRIPT), "--config", str(config_path),
        ], restart=False)
        write_runtime_status(
            status_path, started_at, processes, "starting",
            process_started, restart_after, restart_attempts,
        )
        wait_for_router(address, router)
        if parse_bool(values.get("LABCONTEXT_ENABLE_TUNNEL")):
            client = require_program(values.get("LABCONTEXT_TUNNEL_CLIENT", "tunnel-client"))
            try:
                start_tunnel(store.get())
            except (ConnectionError, OSError):
                print("labcontext: Tunnel could not start; check its dedicated credential file and run labcontext connections reconnect. Project services remain running.", file=sys.stderr)
            tunnel_control = TunnelControl(store, environment, client, start_tunnel, stop_tunnel)
        write_runtime_status(
            status_path, started_at, processes, "running",
            process_started, restart_after, restart_attempts,
        )
        labels = " + ".join(label for label, _ in processes)
        print(f"labcontext: running {labels}; press Ctrl-C to stop")
        dashboard = values.get("LABCONTEXT_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)
        if dashboard:
            print(f"labcontext: connection center {dashboard}")
        last_snapshot = ""
        while not shutting_down:
            router_status = router.poll()
            if router_status is not None:
                fail(f"LabContext Router exited unexpectedly with status {router_status}")
            if tunnel_control:
                tunnel_control.tick()
            now = time.monotonic()
            for index, (label, process) in enumerate(processes):
                if label == "LabContext Router" or label not in restart_commands:
                    continue
                status = process.poll()
                if status is None:
                    if now - process_started.get(label, now) >= 30:
                        restart_attempts[label] = 0
                    continue
                if label not in restart_after:
                    if label == "SSH bridge" and status == 255:
                        # Bounded to one cleanup per launcher lifetime: never
                        # repeatedly evict a competing machine's managed bridge.
                        recovered, detail = recover_bridge_conflict(
                            values, allow_cleanup=not bridge_cleanup_attempted,
                        )
                        bridge_cleanup_attempted = True
                        print(f"labcontext: automatic SSH recovery: {detail}", file=sys.stderr)
                        if not recovered and "remote port forwarding failed" in detail.lower():
                            write_recovery_status(values, {
                                "phase": "failed",
                                **recovery_failure_from_diagnostics(detail, values),
                            })
                            # Keep local access available, but stop retrying a
                            # persistent bind failure until an explicit repair.
                            restart_commands.pop(label, None)
                            continue
                    attempt = restart_attempts.get(label, 0) + 1
                    restart_attempts[label] = attempt
                    restart_after[label] = now + min(30, 2 ** min(attempt - 1, 4))
                    print(
                        f"labcontext: {label} exited with status {status}; "
                        f"retrying in {round(restart_after[label] - now)}s",
                        file=sys.stderr,
                    )
                    continue
                if now < restart_after[label]:
                    continue
                replacement = subprocess.Popen(
                    restart_commands[label], env=restart_environments[label], start_new_session=True,
                )
                processes[index] = (label, replacement)
                process_started[label] = now
                restart_after.pop(label, None)
                print(f"labcontext: restarted {label} (PID {replacement.pid})")
            snapshot = json.dumps([
                process_status(
                    label, process, process_started, restart_after, restart_attempts,
                )
                for label, process in processes
            ], sort_keys=True)
            if snapshot != last_snapshot:
                write_runtime_status(
                    status_path, started_at, processes, "running",
                    process_started, restart_after, restart_attempts,
                )
                last_snapshot = snapshot
            time.sleep(0.5)
    finally:
        if processes:
            write_runtime_status(
                status_path, started_at, processes, "stopping",
                process_started, restart_after, restart_attempts,
            )
        stop_processes(processes)
        try:
            status_path.unlink()
        except FileNotFoundError:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional LabContext providers behind one MCP endpoint")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--repair-worker", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")
    init_parser = subparsers.add_parser("init", help="create a local, server, or hybrid configuration")
    init_parser.add_argument("mode", choices=("local", "server", "hybrid"))
    init_parser.add_argument("--ssh-host", help="SSH host or alias for the server provider")
    init_parser.add_argument("--tunnel-profile", help="tunnel-client profile that points to the router")
    init_parser.add_argument("--force", action="store_true")
    subparsers.add_parser("doctor", help="validate configuration and dependencies")
    subparsers.add_parser("status", help="show layered runtime and connection diagnostics")
    subparsers.add_parser("repair", help="validate, stop a degraded stack, and restart it cleanly")
    subparsers.add_parser("restart", help="stop the current stack and start it with current configuration")
    subparsers.add_parser("stop", help="stop the current supervised stack cleanly")
    from labcontext_connection_cli import add_parser, connections_command
    add_parser(subparsers)
    args = parser.parse_args()
    values = load_env(args.env_file.expanduser())
    secret_env_file = values.get("LABCONTEXT_SECRET_ENV_FILE")
    if secret_env_file:
        secret_values = load_env(Path(secret_env_file).expanduser())
        secret_values.update(values)
        values = secret_values
    env_path = args.env_file.expanduser()
    config_path = (args.config or Path(values.get("LABCONTEXT_ROUTER_CONFIG", str(DEFAULT_CONFIG_PATH)))).expanduser()
    values["LABCONTEXT_ENV_FILE"] = str(env_path)
    values["LABCONTEXT_ROUTER_CONFIG"] = str(config_path)
    values["LABCONTEXT_LAUNCHER_SCRIPT"] = str(Path(__file__).resolve())
    # Select metadata only. Dedicated credentials are injected into the Tunnel
    # child, never into Provider, Router or SSH subprocesses.
    if args.command != "init":
        try:
            active = ConnectionStore(values).get()
            values["LABCONTEXT_TUNNEL_PROFILE"] = active["profile"]
            values["LABCONTEXT_TUNNEL_HEALTH_URL"] = active["healthUrl"]
        except ConnectionError as exc:
            fail(str(exc))
    values.setdefault("LABCONTEXT_RECOVERY_STATUS_FILE", str(DEFAULT_RECOVERY_STATUS_PATH))
    values.setdefault("LABCONTEXT_RECOVERY_LOG_FILE", str(DEFAULT_RECOVERY_LOG_PATH))
    for key in ("LABCONTEXT_RECOVERY_STATUS_FILE", "LABCONTEXT_RECOVERY_LOG_FILE"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    if args.command == "init":
        args.config = config_path
        return init_config(args)
    if args.command == "connections":
        try:
            address = parse_listen_addr(load_config(config_path).listen_addr)
            return connections_command(args, values, router_base_url(address))
        except ConnectionError as exc:
            fail(str(exc))
    if args.command == "doctor":
        return doctor(config_path, values)
    if args.command == "status":
        return show_status(config_path)
    if args.command == "repair":
        return repair(config_path, values)
    if args.command == "restart":
        stop_running_stack(config_path, values)
        return run(config_path, values)
    if args.command == "stop":
        stop_running_stack(config_path, values)
        return 0
    if args.repair_worker:
        return recovery_worker(config_path, values)
    return run(config_path, values)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RouterError, OSError, ValueError) as exc:
        fail(str(exc))
