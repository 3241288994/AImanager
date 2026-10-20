"""Private CLI profiles and bounded, command-allowlisted authorization sessions.

Never returns raw terminal output, credentials, or authorization codes to RPC.
Only official CLI login and /usage are permitted through the web session.
"""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

PROVIDERS = {"claude": "claude", "antigravity": "agy"}
FINAL = {"succeeded", "failed", "cancelled", "expired"}
AUTH_HOSTS = {"claude.ai", "claude.com", "console.anthropic.com", "auth.anthropic.com", "accounts.google.com", "antigravity.google", "antigravity.google.com", "codeassist.google.com"}
KEYS = re.compile(r"(?:sk-ant-[\w-]+|ya29\.[\w.-]+|Bearer\s+\S+)", re.I)


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Managed state directory must not be a symlink")
    os.chmod(path, 0o700)
    return path


def write_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
    os.replace(temporary, path)


def read_json(path, fallback=None):
    try:
        if path.is_symlink() or path.stat().st_size > 1048576:
            raise ValueError("Invalid managed state file")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback


@contextlib.contextmanager
def registry(root):
    private_dir(root)
    with (root / "registry.lock").open("a") as lock:
        os.chmod(root / "registry.lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = read_json(root / "accounts.json", {"version": 1, "accounts": [], "active": {}})
        yield value
        write_json(root / "accounts.json", value)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid managed profile or session ID")
    return value


def account(root, account_id):
    identifier(account_id)
    with registry(root) as value:
        for item in value["accounts"]:
            if item["id"] == account_id:
                return dict(item)
    raise ValueError("Unknown CLI account")


def update_account(root, account_id, **patch):
    with registry(root) as value:
        for item in value["accounts"]:
            if item["id"] == account_id:
                item.update(patch)
                return
    raise ValueError("Unknown CLI account")


def native(provider):
    if provider not in PROVIDERS:
        raise ValueError("Unsupported CLI provider")
    configured = os.environ.get("AIMANAGER_" + provider.upper() + "_BIN")
    managed = Path.home() / ".local/share/aimanager/bin" / PROVIDERS[provider]
    candidate = configured or (str(managed) if managed.is_file() else shutil.which(PROVIDERS[provider]))
    if not candidate or not Path(candidate).is_file() or not os.access(candidate, os.X_OK):
        raise ValueError(f"Official {PROVIDERS[provider]} CLI is not installed on this service host")
    # Do not recurse into a managed launcher from PATH.
    if Path(candidate).resolve() == Path(__file__).resolve():
        raise ValueError("Configure an absolute native CLI binary, not the AImanager launcher")
    return str(Path(candidate).resolve())


def profile_env(root, item):
    if item["provider"] == "antigravity" and sys.platform != "linux":
        raise ValueError("Managed Antigravity accounts currently require a Linux service host to isolate the desktop keyring")
    home = private_dir(private_dir(root / "profiles") / identifier(item["id"]))
    home = private_dir(home / "home")
    # Deliberately do not inherit API keys, provider routing, keyrings or project hooks.
    allowed = {"PATH", "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "TMPDIR", "SystemRoot"}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"), "TERM": "xterm-256color", "NO_COLOR": "1",
                "BROWSER": "true", "SSH_CONNECTION": "aimanager-managed-profile", "DISABLE_AUTOUPDATER": "1"})
    return home, env


def saved_antigravity_auth(root, item):
    """Read only the official profile's bounded OAuth record; never export it.

    This confirms a saved login, not subscription access or successful inference.
    Revocation/network/entitlement checks remain the official CLI's responsibility.
    """
    home, _ = profile_env(root, item)
    path = home / ".gemini/antigravity-cli/antigravity-oauth-token"
    note = "未找到此独立配置中的官方授权，请完成网页登录"
    missing = {"authStatus": "signed_out", "authNote": note, "checkedAt": int(time.time())}
    try:
        metadata = path.lstat()
        if any(p.is_symlink() for p in [home / ".gemini", path.parent, path]) or not path.is_file() or metadata.st_size > 32768 or metadata.st_mode & 0o077:
            return {"authStatus": "unknown", "authNote": "官方授权文件类型、大小或权限异常；未读取凭证", "checkedAt": int(time.time())}
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data.get("token", {})
        # Go's official OAuth record uses RFC3339Nano. Python 3.8 only
        # accepts microseconds; preserve timezone and truncate extra precision.
        expiry_text = re.sub(r"(\.\d{6})\d+(?=[Z+-]|$)", r"\1", str(token.get("expiry", "")))
        expiry = datetime.fromisoformat(expiry_text.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("Missing expiry timezone")
        access = isinstance(token.get("access_token"), str) and bool(token["access_token"])
        renewable = isinstance(token.get("refresh_token"), str) and bool(token["refresh_token"])
        if not access or (expiry <= datetime.now(timezone.utc) and not renewable):
            return {"authStatus": "signed_out", "authNote": "官方授权已过期且无法续期，请重新登录", "checkedAt": int(time.time())}
        return {"authStatus": "authenticated", "authMethod": "google_oauth", "authNote": "官方 CLI 已保存授权；额度与网络可用性单独检测", "checkedAt": int(time.time()), "credentialSavedAt": int(metadata.st_mtime)}
    except FileNotFoundError:
        return missing
    except (ValueError, TypeError, AttributeError, OSError):
        return {"authStatus": "unknown", "authNote": "无法识别官方授权文件；不会将其当作登录成功", "checkedAt": int(time.time())}


def check_auth(root, item):
    if item["provider"] == "antigravity":
        return saved_antigravity_auth(root, item)
    home, env = profile_env(root, item)
    binary = native(item["provider"])
    args = [binary, "auth", "status"] if item["provider"] == "claude" else [binary, "models"]
    try:
        # Command output stays private; only whitelisted auth fields are returned.
        result = subprocess.run(args, env=env, cwd=home, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
    except subprocess.TimeoutExpired:
        return {"authStatus": "unknown", "authNote": "Official CLI status check timed out"}
    if len(result.stdout) > 262144:
        return {"authStatus": "unknown", "authNote": "CLI status response exceeded the safe limit"}
    if item["provider"] == "claude":
        try:
            data = json.loads(result.stdout)
            logged_in = data.get("loggedIn") is True and result.returncode == 0
            method = data.get("authMethod")
            return {"authStatus": "authenticated" if logged_in else "signed_out",
                    "authMethod": method if method in {"claude.ai", "oauth_token", "none", "api_key", "api_key_helper", "third_party"} else "unknown",
                    "checkedAt": int(time.time())}
        except (ValueError, AttributeError):
            return {"authStatus": "unknown", "authNote": "This CLI version did not return supported auth JSON"}
    return {"authStatus": "unknown", "authNote": "This CLI version did not return supported auth status"}


def account_list(root):
    with registry(root) as value:
        items = [dict(item, active=value["active"].get(item["provider"]) == item["id"]) for item in value["accounts"]]
    return {"items": items, "summary": {"accounts": len(items), "authenticated": sum(i.get("authStatus") == "authenticated" for i in items), "quotaKnown": sum(i.get("quota", {}).get("state") == "available" for i in items)}}


def synchronize_accounts(root, force=False):
    # At most four independent status checks, each with a 15-second bound.
    # Ordinary polling reuses 60-second snapshots, not a new CLI per request.
    items = account_list(root)["items"]
    candidates = sorted((i for i in items if force or time.time() - i.get("checkedAt", 0) >= 60), key=lambda i: i.get("checkedAt", 0))[:4]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(item, pool.submit(check_auth, root, item)) for item in candidates]
        for item, future in futures:
            checked = future.result()
            checked.setdefault("authNote", None)
            update_account(root, item["id"], **checked)
    return account_list(root)


def claude_quota_windows(payload):
    labels = {"five_hour": "5 小时额度", "seven_day": "7 天额度", "seven_day_opus": "Opus 周额度", "seven_day_sonnet": "Sonnet 周额度", "seven_day_oauth_apps": "OAuth 应用周额度", "seven_day_cowork": "Cowork 周额度"}
    windows = []
    for key, label in labels.items():
        value = payload.get(key)
        if not isinstance(value, dict):
            continue
        used = value.get("utilization")
        if type(used) not in (int, float) or not 0 <= used <= 100:
            continue
        reset = value.get("resets_at")
        if not isinstance(reset, str) or len(reset) > 64:
            reset = None
        windows.append({"label": label, "usedPercent": round(used, 2), "remainingPercent": round(100-used, 2), "resetsAt": reset})
    return windows


def refresh_claude_quota(root, item, directory, status):
    """Use the read-only usage endpoint used by Claude's native /usage command."""
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError, URLError
    home, _ = profile_env(root, item)
    path = home / ".claude" / ".credentials.json"
    if not path.is_file():
        return False  # Older/native credential stores continue through the CLI.
    if path.is_symlink() or path.stat().st_size > 32768 or path.stat().st_mode & 0o077:
        raise ValueError("Claude credential file must be private and bounded")
    credentials = read_json(path).get("claudeAiOauth", {})
    token = credentials.get("accessToken")
    if not isinstance(token, str) or not token:
        return False
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # Never forward an OAuth header to another origin.
    status.update(phase="reading_usage", message="正在读取官方额度接口", updatedAt=int(time.time()))
    write_json(directory / "status.json", status)
    quota = None
    reason = "quota_not_reported"
    note = "官方未返回可识别额度，请稍后重试。"
    try:
        request = Request("https://api.anthropic.com/api/oauth/usage", headers={"Authorization": "Bearer " + token, "anthropic-beta": "oauth-2025-04-20", "User-Agent": "aimanager-quota/1.0"})
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = response.read(1048577)
        if len(data) > 1048576:
            raise ValueError("Usage response exceeds limit")
        payload = json.loads(data)
        windows = claude_quota_windows(payload) if isinstance(payload, dict) else []
        if windows:
            quota = {"state": "available", "source": "official_oauth_usage", "checkedAt": int(time.time()), "windows": windows}
    except HTTPError as error:
        reason = "authorization_required" if error.code in (401, 403) else "quota_request_failed"
        note = "授权已过期或无权限，请在 AI 接入中重新验证登录。" if error.code in (401, 403) else "官方额度接口暂不可用（HTTP %s），请稍后重试。" % error.code
    except (OSError, URLError):
        reason, note = "network_unavailable", "无法连接官方额度接口，请检查代理后重试。"
    except (ValueError, TypeError):
        pass
    if (directory / "cancel.json").exists():
        status.update(phase="cancelled", message="已取消额度刷新", updatedAt=int(time.time()))
        write_json(directory / "status.json", status)
        return True
    if quota is not None:
        update_account(root, item["id"], quota=quota)
        status.update(phase="succeeded", message="官方额度已同步", reasonCode=None)
    else:
        previous = account(root, item["id"]).get("quota", {})
        quota = dict(previous) if previous.get("state") == "available" else {"state": "unavailable", "source": "official_oauth_usage", "windows": [], "note": note}
        quota.update(lastAttemptAt=int(time.time()), lastError=note, reasonCode=reason)
        update_account(root, item["id"], quota=quota)
        status.update(phase="failed", message=note, reasonCode=reason)
    status.update(updatedAt=int(time.time()))
    write_json(directory / "status.json", status)
    return True


def refresh_models(root, item):
    """Read native model discovery without sending a generation request."""
    home, env = profile_env(root, item)
    snapshot = {"state": "unavailable", "items": [], "checkedAt": int(time.time())}
    try:
        if item["provider"] == "antigravity":
            # A temporary file bounds pipe memory even if a CLI emits excessive logs.
            import tempfile
            with tempfile.TemporaryFile() as output:
                result = subprocess.run([native("antigravity"), "models"], cwd=home, env=env,
                                        stdout=output, stderr=subprocess.DEVNULL, timeout=15)
                output.seek(0)
                text = output.read(65537)
            if result.returncode or len(text) > 65536:
                raise ValueError("Model discovery failed")
            for line in strip_terminal(text.decode("utf-8", errors="replace")).splitlines():
                columns = line.split("\t", 1)
                if len(columns) == 2 and re.fullmatch(r"[a-z][a-z0-9_.:/\[\]-]{1,100}", columns[0]):
                    snapshot["items"].append({"id": columns[0], "name": columns[1][:160]})
            snapshot.update(source="official_cli_models", note="官方 CLI 实时模型目录；实际调用仍受账号额度限制。")
        else:
            config = read_json(home / ".claude" / ".claude.json")
            for model in config.get("additionalModelOptionsCache", [])[:100]:
                if not isinstance(model, dict) or model.get("disabled"):
                    continue
                model_id = model.get("value", "")
                if re.fullmatch(r"[a-z][a-z0-9_.:/\[\]-]{1,100}", model_id):
                    snapshot["items"].append({"id": model_id, "name": str(model.get("label", model_id))[:160]})
            snapshot.update(source="official_cli_cache", note="官方 CLI 缓存的额外模型选项，非完整目录；基础模型请以 CLI /model 为准。")
        snapshot["items"] = snapshot["items"][:100]
        snapshot["state"] = "available" if snapshot["items"] else "unavailable"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        snapshot["note"] = "模型目录读取失败，请检查代理、登录状态及官方 CLI。"
    previous = item.get("models", {})
    if snapshot["state"] != "available" and previous.get("items"):
        snapshot = dict(previous, lastError=snapshot.get("note"), lastAttemptAt=int(time.time()))
    update_account(root, item["id"], models=snapshot)
    return snapshot


def strip_terminal(text):
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[\d*[GC]", " ", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)


def terminal_replies(chunk):
    # Reply only to terminal capability queries, never to arbitrary CLI prompts.
    pairs = [(b"\x1b[c", b"\x1b[?1;2c"), (b"\x1b[6n", b"\x1b[1;1R"),
             (b"\x1b[>c", b"\x1b[>0;95;0c"), (b"\x1b[?u", b"\x1b[?0u"),
             (b"\x1b[18t", b"\x1b[8;60;240t")]
    return b"".join(reply for query, reply in pairs if query in chunk)


def confirmation_prompt(text):
    return bool(re.search(r"select login method|press enter|hit enter|enter to (?:continue|confirm)|enter select|trust this folder|trust.*directory|choose the text style|select (?:a )?theme|choose your color scheme", text[-4000:], re.I))


def authorization_code_prompt(text):
    # Antigravity renders an input placeholder rather than an "Enter code"
    # sentence. Recognize that bounded placeholder as well as CLI prose.
    return bool(re.search(r"(?:paste|enter|输入|粘贴).{0,70}(?:code|验证码|授权码)|authorization code(?:\.{2,}|…|:)", text[-12000:], re.I))


def auth_url(text):
    from urllib.parse import urlsplit, parse_qs
    for candidate in re.findall(r"https://[^\s<>\x1b\x07\"']+", text):
        candidate = candidate.rstrip(").,;│┃")
        if len(candidate) > 8192:
            continue
        try:
            parsed = urlsplit(candidate)
            query = parse_qs(parsed.query)
            forbidden = {"access_token", "refresh_token", "id_token", "client_secret"}
            # Claude's official authorize URL uses code=true to choose its
            # manual-code flow. It is a mode flag, not a returned OAuth code.
            manual_flow = (parsed.hostname in {"claude.ai", "claude.com"}
                           and parsed.path in {"/oauth/authorize", "/cai/oauth/authorize"} and query.get("code") == ["true"])
            has_code = "code" in query and not manual_flow
            if parsed.hostname in AUTH_HOSTS and not parsed.username and not parsed.password and not parsed.fragment and not has_code and not (set(query) & forbidden):
                return candidate
        except ValueError:
            pass
    return None


def quota_windows(text):
    # Extract only explicitly labelled percentages from the official /usage panel.
    # Never add unlike limits together or reinterpret unknown values as zero.
    lines = [line.strip() for line in strip_terminal(text).splitlines() if line.strip()]
    result = []
    for index, line in enumerate(lines):
        match = re.search(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%\s*(used|remaining|left)", line, re.I)
        if not match:
            continue
        amount = float(match.group(1))
        if not 0 <= amount <= 100:
            continue
        prefix = re.sub(r"[█░▒▓▏▎▍▌▋▊▉━─│┃┌┐└┘]", "", line[:match.start()]).strip()
        label = prefix or (lines[index - 1] if index else "Quota window")
        if "@" in label or KEYS.search(label):
            label = "Quota window"
        label = re.sub(r"[^\w ()/.:+-]", "", label)[:100]
        if not label or "@" in label or KEYS.search(label):
            label = "Quota window"
        used = amount if match.group(2).lower() == "used" else 100 - amount
        entry = {"label": label, "usedPercent": round(used, 2), "remainingPercent": round(100 - used, 2), "resetsAt": None}
        if entry not in result:
            result.append(entry)
    return result[-20:]


def session_path(root, session_id):
    return root / "sessions" / identifier(session_id)


def public_session(value):
    return {key: value.get(key) for key in ("id", "accountId", "kind", "phase", "authorizationUrl", "message", "reasonCode", "startedAt", "updatedAt")}


def start_session(root, item, kind):
    native(item["provider"])
    if kind not in {"login", "usage"}:
        raise ValueError("Unsupported session kind")
    if kind == "usage" and item.get("authStatus") != "authenticated":
        raise ValueError("Sign in to this managed account before refreshing quota")
    sessions = private_dir(root / "sessions")
    with registry(root):
        active = []
        for child in sessions.iterdir():
            if not child.is_dir() or child.is_symlink():
                continue
            status = read_json(child / "status.json", {})
            if status.get("phase") not in FINAL and time.time() - status.get("startedAt", 0) < 960:
                active.append(status)
        existing = next((s for s in active if s.get("accountId") == item["id"]), None)
        if existing:
            return public_session(existing)
        if len(active) >= 4:
            raise ValueError("Four CLI sessions are already active; finish or cancel one first")
        session_id = uuid.uuid4().hex
        directory = private_dir(sessions / session_id)
        status = {"id": session_id, "accountId": item["id"], "kind": kind, "phase": "starting", "startedAt": int(time.time()), "updatedAt": int(time.time()), "message": "Starting the official CLI in an isolated profile"}
        write_json(directory / "status.json", status)
        with (directory / "worker-errors.txt").open("ab") as errors:
            os.chmod(directory / "worker-errors.txt", 0o600)
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--root", str(root), "--worker", session_id], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, start_new_session=True, close_fds=True)
        status["workerPid"] = child.pid
        write_json(directory / "status.json", status)
        threading.Thread(target=child.wait, daemon=True).start()
    return public_session(status)


def run_session(root, session_id):
    import pty
    import struct
    import termios
    directory = session_path(root, session_id)
    status = read_json(directory / "status.json")
    item = account(root, status["accountId"])
    home, env = profile_env(root, item)
    binary = native(item["provider"])
    kind = status["kind"]
    if kind == "usage" and item["provider"] == "claude" and refresh_claude_quota(root, item, directory, status):
        return
    args = [binary, "auth", "login", "--claudeai"] if item["provider"] == "claude" and kind == "login" else [binary]
    child, terminal = pty.fork()
    if child == 0:
        os.chdir(home)
        os.execve(binary, args, env)
    fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 240, 0, 0))
    text = ""
    sent_usage = False
    authenticated = False
    deadline = time.monotonic() + (900 if kind == "login" else 60)
    def publish(phase, message, url=None):
        status.update(phase=phase, message=message, authorizationUrl=url, updatedAt=int(time.time()))
        write_json(directory / "status.json", status)
    publish("starting", "Waiting for the official CLI")
    try:
        while time.monotonic() < deadline:
            if (directory / "cancel.json").exists():
                publish("cancelled", "Session cancelled; saved account credentials were not removed")
                return
            ready, _, _ = select.select([terminal], [], [], 0.3)
            if ready:
                try:
                    chunk = os.read(terminal, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                reply = terminal_replies(chunk)
                if reply:
                    os.write(terminal, reply)
                text = (text + chunk.decode("utf-8", errors="replace"))[-262144:]
            plain = strip_terminal(text)
            url = auth_url(text) or auth_url(plain)
            if kind == "login":
                if item["provider"] == "antigravity":
                    saved = saved_antigravity_auth(root, item)
                    if saved.get("authStatus") == "authenticated" and saved.get("credentialSavedAt", 0) >= status["startedAt"]:
                        update_account(root, item["id"], **saved)
                        authenticated = True
                        break
                if authorization_code_prompt(plain):
                    publish("awaiting_code", "Open the official authorization page, then paste its returned code here", url)
                elif url:
                    publish("awaiting_browser", "Complete authorization in your browser; do not share this temporary link", url)
                elif confirmation_prompt(plain):
                    message = "Continue with the selected Google OAuth login option" if "select login method" in plain.lower() else "The official CLI is waiting for Enter to continue"
                    publish("needs_confirmation", message)
            else:
                if re.search(r"terms of service.*data use|allowing.*collect", plain[-6000:], re.I | re.S):
                    status["reasonCode"] = "onboarding_required"
                    publish("failed", "请先在终端完成官方 CLI 的条款与数据使用选择，再刷新额度。")
                    break
                if re.search(r"select login method", plain[-4000:], re.I):
                    status["reasonCode"] = "onboarding_required"
                    publish("failed", "官方 CLI 尚未完成首次设置，请在 AI 接入中完成登录或在终端初始化。")
                    break
                if not sent_usage and re.search(r"(?:for shortcuts|\? for|try [\"“]|help for|^\s*[❯›>]\s*$|Welcome Claude; use /help)", plain[-6000:], re.I | re.M):
                    if not confirmation_prompt(plain):
                        os.write(terminal, b"/usage\r")
                        sent_usage = True
                        publish("reading_usage", "Reading the official /usage panel; no model prompt is submitted")
                if sent_usage and quota_windows(plain):
                    windows = quota_windows(plain)
                    update_account(root, item["id"], quota={"state": "available", "source": "official_cli_usage", "checkedAt": int(time.time()), "windows": windows})
                    publish("succeeded", "Official quota snapshot refreshed")
                    return
                if confirmation_prompt(plain):
                    publish("needs_confirmation", "The official CLI is waiting for Enter before displaying usage")
            mailbox = directory / "input.json"
            incoming = read_json(mailbox)
            if incoming:
                mailbox.unlink(missing_ok=True)
                if incoming.get("action") == "confirm" and status["phase"] == "needs_confirmation":
                    os.write(terminal, b"\r")
                    text = ""
                elif incoming.get("action") == "code" and status["phase"] == "awaiting_code":
                    code = incoming["code"]
                    os.write(terminal, code.encode("utf-8") + b"\r")
                    text = ""
                    publish("verifying", "The official CLI is verifying authorization; code is not retained")
            ended, exit_status = os.waitpid(child, os.WNOHANG)
            if ended:
                if kind == "login" and item["provider"] == "claude" and os.WIFEXITED(exit_status) and os.WEXITSTATUS(exit_status) == 0:
                    checked = check_auth(root, item)
                    authenticated = checked.get("authStatus") == "authenticated"
                break
        if kind == "login":
            if item["provider"] == "claude":
                checked = check_auth(root, item)
                authenticated = checked.get("authStatus") == "authenticated"
                if authenticated:
                    update_account(root, item["id"], **checked)
            else:
                checked = saved_antigravity_auth(root, item)
                authenticated = checked.get("authStatus") == "authenticated"
                update_account(root, item["id"], **checked)
            if authenticated:
                publish("succeeded", "Official CLI sign-in completed for this isolated account")
            else:
                reason = "authorization_not_verified"
                message = "Sign-in was not verified; retry in this profile or check server network/CLI compatibility"
                if re.search(r"timeout|timed out|connection refused|ECONN|TLS|proxy|failed to connect|network|unexpected EOF", plain, re.I):
                    reason, message = "network_unavailable", "Official CLI cannot reach its authentication service; check server proxy, DNS and TLS"
                elif re.search(r"keyring|keychain|secret service|dbus", plain, re.I):
                    reason, message = "credential_store_unavailable", "The official CLI could not initialize its isolated credential store"
                status["reasonCode"] = reason
                publish("expired" if time.monotonic() >= deadline else "failed", message)
        else:
            reason = status.get("reasonCode") or ("network_unavailable" if re.search(r"timeout|timed out|connection refused|ECONN|TLS|proxy|failed to connect|network|unexpected EOF", plain, re.I) else "quota_not_reported")
            note = status["message"] if reason == "onboarding_required" else ("网络连接失败，请检查代理后重试。" if reason == "network_unavailable" else "官方 CLI 未返回可识别额度，请完成终端初始化后重试。")
            previous = account(root, item["id"]).get("quota", {})
            quota = dict(previous) if previous.get("state") == "available" else {"state": "unavailable", "source": "official_cli_usage", "windows": [], "note": note}
            quota.update(lastAttemptAt=int(time.time()), lastError=note, reasonCode=reason)
            update_account(root, item["id"], quota=quota)
            status["reasonCode"] = reason
            publish("failed", note)
    finally:
        alive = False
        try:
            alive = os.waitpid(child, os.WNOHANG)[0] == 0
        except ChildProcessError:
            pass
        if alive:
            try:
                if os.getpgid(child) == child:
                    os.killpg(child, signal.SIGTERM)
                    time.sleep(0.1)
                    os.killpg(child, signal.SIGKILL)
                else:
                    os.kill(child, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        os.close(terminal)
        try:
            os.waitpid(child, 0)
        except ChildProcessError:
            pass
        (directory / "input.json").unlink(missing_ok=True)


def dispatch(root, request):
    action = request.get("action")
    if action == "list":
        return account_list(root)
    if action == "sync":
        return synchronize_accounts(root, request.get("force") is True)
    if action == "connect":
        provider = request.get("provider")
        native(provider)
        items = synchronize_accounts(root)["items"]
        item = next((i for i in items if i["provider"] == provider and i.get("authStatus") != "authenticated"), None)
        if item is None:
            count = sum(i["provider"] == provider for i in items)
            item = dispatch(root, {"action":"create", "provider":provider, "label":("Claude" if provider == "claude" else "Antigravity") + " " + str(count + 1)})
        return start_session(root, item, "login")
    if action == "create":
        provider = request.get("provider")
        label = request.get("label", "").strip()
        if provider not in PROVIDERS or not label or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise ValueError("Choose Claude/Antigravity and a label of 1–80 characters")
        with registry(root) as value:
            if len(value["accounts"]) >= 32:
                raise ValueError("At most 32 managed CLI accounts are supported")
            item = {"id": uuid.uuid4().hex, "provider": provider, "label": label, "authStatus": "unknown", "createdAt": int(time.time()), "quota": {"state": "unknown", "windows": []}}
            profile_env(root, item)
            value["accounts"].append(item)
        return item
    if action in {"select", "login", "usage", "check", "models"}:
        item = account(root, request.get("accountId"))
        if action == "models":
            return refresh_models(root, item)
        if action == "select":
            if item.get("authStatus") != "authenticated":
                raise ValueError("Sign in and verify this account before selecting it")
            with registry(root) as value:
                value["active"][item["provider"]] = item["id"]
            return {"activeAccountId": item["id"], "note": "Applies only to new aimanager-cli sessions; running tasks and native default profiles are unchanged"}
        if action == "check":
            checked = check_auth(root, item)
            checked.setdefault("authNote", None)
            update_account(root, item["id"], **checked)
            return checked
        return start_session(root, item, action)
    if action in {"session", "input", "cancel"}:
        directory = session_path(root, request.get("sessionId"))
        status = read_json(directory / "status.json")
        if not status:
            raise ValueError("Unknown authorization session")
        if status.get("kind") == "login" and status.get("phase") not in {"succeeded", "cancelled"}:
            item = account(root, status["accountId"])
            if item.get("authStatus") == "authenticated" and (item.get("credentialSavedAt", 0) >= status.get("startedAt", 0) or item.get("checkedAt", 0) >= status.get("startedAt", 0)):
                status.update(phase="succeeded", authorizationUrl=None, reasonCode=None, message="官方 CLI 登录已同步", updatedAt=int(time.time()))
                write_json(directory / "status.json", status)
        if status.get("phase") not in FINAL and time.time() - status.get("updatedAt", 0) > 960:
            status.update(phase="expired", authorizationUrl=None, message="Session expired; start a new authorization")
        if action == "cancel":
            write_json(directory / "cancel.json", {"cancel": True})
        if action == "input":
            if request.get("inputAction") == "confirm" and status["phase"] == "needs_confirmation":
                write_json(directory / "input.json", {"action": "confirm"})
            elif request.get("inputAction") == "code" and status["phase"] == "awaiting_code":
                code = request.get("code", "")
                if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.~:#/@?=&%+\-]{1,2048}", code):
                    raise ValueError("Invalid authorization code; do not submit a password or a shell command")
                write_json(directory / "input.json", {"action": "code", "code": code})
            else:
                raise ValueError("This session is not waiting for that input")
        return public_session(status)
    raise ValueError("Unsupported CLI account operation")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--worker")
    parser.add_argument("--run", choices=list(PROVIDERS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.worker:
        try:
            run_session(root, identifier(args.worker))
        except Exception as error:
            directory = session_path(root, args.worker)
            status = read_json(directory / "status.json", {})
            status.update(phase="failed", authorizationUrl=None, updatedAt=int(time.time()), message=f"CLI session failed ({type(error).__name__}); check binary installation and private profile permissions")
            write_json(directory / "status.json", status)
        return
    if args.run:
        with registry(root) as value:
            account_id = value["active"].get(args.run)
        if not account_id:
            raise SystemExit("No active managed account; select one in AImanager first")
        item = account(root, account_id)
        _, env = profile_env(root, item)
        binary = native(args.run)
        forwarded = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        # Preserve the user's working directory; only config/credential homes change.
        os.execve(binary, [binary] + forwarded, env)
    try:
        request = json.loads(sys.stdin.read(16385))
        if not isinstance(request, dict):
            raise ValueError("Invalid request")
        result = dispatch(root, request)
        print(json.dumps({"result": result}, ensure_ascii=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Exceptions generated here contain no child output or credential values.
        print(json.dumps({"error": str(error)[:300]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
