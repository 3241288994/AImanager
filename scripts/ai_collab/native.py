"""Small native CLI adapters. No agent loop, credential copying or shell interpolation."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .config import CollabError, read_json, provider_path, user_home


def binary(value):
    value = str(provider_path(value)) if "/" in value else shutil.which(value)
    if not value or not Path(value).is_file():
        raise CollabError("cli_unavailable", "Configured native executable is unavailable")
    return str(Path(value).resolve())


def codex_identity(config):
    settings = config.get("codex", {})
    home = provider_path(settings.get("home", "~/.codex"))
    try:
        auth = read_json(home / "auth.json", 65536)
    except (OSError, ValueError):
        raise CollabError("authentication_required", "Sign in to the configured Codex profile")
    # Never inherit an API key or alternate endpoint from this process.
    account = (auth.get("tokens") or {}).get("account_id")
    if auth.get("auth_mode") != "chatgpt" or not isinstance(account, str) or not account:
        raise CollabError("authentication_required", "Codex adapter requires the configured ChatGPT login")
    try:
        version = subprocess.check_output(
            [binary(settings.get("binary", "codex")), "--version"],
            stderr=subprocess.DEVNULL, text=True, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        raise CollabError("codex_unavailable", "Configured Codex executable did not answer --version")
    identity = hashlib.sha256((str(home) + "\0" + account).encode()).hexdigest()
    return home, identity, version


def codex_command(config, route, account_id, access, roots, session_id=None):
    home, identity, version = codex_identity(config)
    if identity != account_id:
        raise CollabError("account_changed", "Codex profile account changed; start a new explicit job")
    if access not in {"read", "exec"}:
        raise CollabError("access_not_supported", "Codex currently requires a read or exec workspace")
    if len(roots) != 1:
        raise CollabError("workspace_not_supported", "Codex adapter currently uses one workspace")
    allowed = {"PATH", "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE",
               "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "TMPDIR"}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(HOME=str(user_home()), CODEX_HOME=str(home), NO_COLOR="1")
    if config.get("proxy"):
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env[key] = config["proxy"]
    executable = binary(config.get("codex", {}).get("binary", "codex"))
    fs = {":minimal": "read", ":workspace_roots": "write" if access == "exec" else "read",
          "/usr": "read", "/lib": "read", "/lib64": "read",
          str(Path(executable).parent.parent): "read"}
    profile = "{ " + ", ".join(json.dumps(k) + "=" + json.dumps(v) for k, v in fs.items()) + " }"
    command = [executable,
               "--no-daemon", "-a", "never", "exec", "--ignore-user-config", "--ignore-rules",
               "--skip-git-repo-check", "--json", "-m", route["model"],
               "-c", 'default_permissions="ai_collab"',
               "-c", "permissions.ai_collab.filesystem=" + profile,
               "-c", "permissions.ai_collab.network.enabled=false",
               "-c", "web_search=\"disabled\"", "-c", "features.multi_agent=false",
               "-c", "features.enable_request_permissions_tool=false",
               "-c", "model_reasoning_effort=\"medium\""]
    if session_id:
        command += ["resume", session_id, "-"]
    else:
        command += ["-C", roots[0]["path"], "-"]
    return command, env, version


def parse_codex(raw, requested):
    session_id, completed, texts, usage, reported, operations = None, False, [], None, [], []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise CollabError("invalid_response", "Codex returned an invalid event")
        if event.get("type") == "turn.failed":
            raise CollabError("provider_error", "Codex did not finish successfully; inspect private logs")
        if event.get("type") == "thread.started":
            session_id = event.get("thread_id")
        if event.get("model"):
            reported.append(event["model"])
        if event.get("type") == "turn.completed":
            completed, usage = True, event.get("usage")
        item = event.get("item") or {}
        if event.get("type") == "item.completed":
            if item.get("type") == "agent_message" and item.get("text"):
                texts.append(item["text"])
            elif item.get("type") in {"command_execution", "file_change"}:
                operations.append({"type": item["type"], "status": item.get("status"),
                                   "exitCode": item.get("exit_code")})
    if reported and any(name != requested for name in reported):
        raise CollabError("model_mismatch", "Codex reported a different model")
    if not completed or not texts or not session_id:
        raise CollabError("incomplete_response", "Codex stream lacks a completed response or thread ID")
    return {"text": "\n\n".join(texts), "sessionId": session_id, "usage": usage,
            "reportedModels": sorted(set(reported)), "operations": operations,
            "modelIdentityEvidence": "cli_metadata" if reported else "explicit_request_only"}


def valid_session(value):
    return isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{32,36}", value)
