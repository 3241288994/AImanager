"""Native Claude OAuth and Gemini web proxy remain separate transports."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from .config import CollabError, read_json

MAX_RESPONSE = 4 * 1024 * 1024


def version_tuple(value):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise CollabError("invalid_version", "Cannot identify Claude Code version")
    return tuple(map(int, match.groups()))


def claude_version(config):
    try:
        output = subprocess.check_output(
            [str(Path(config["claude"]["binary"]).expanduser()), "--version"],
            stderr=subprocess.DEVNULL, timeout=10, text=True,
        )
        return ".".join(map(str, version_tuple(output)))
    except (OSError, subprocess.SubprocessError):
        raise CollabError("claude_unavailable", "Managed Claude Code binary is unavailable")


def manager(config):
    root = Path(config["claude"]["managerRoot"]).expanduser().resolve()
    path = root / "worker.py"
    if not path.is_file():
        raise CollabError("manager_unavailable", "Initialize AIManager's AI connections first")
    spec = importlib.util.spec_from_file_location("ai_collab_account_manager", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return root, module


def claude_account(config, account_id=None):
    root, module = manager(config)
    if not account_id:
        with module.registry(root) as registry:
            account_id = registry["active"].get("claude")
    if not account_id:
        raise CollabError("authentication_required", "Select a signed-in Claude Code account in AIManager")
    item = module.account(root, account_id)
    if item.get("provider") != "claude" or item.get("authStatus") != "authenticated":
        raise CollabError("authentication_required", "Selected managed Claude account is not authenticated")
    return root, module, item


def network_env(config):
    env = dict(os.environ)
    if config.get("proxy"):
        url = urllib.parse.urlsplit(config["proxy"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise CollabError("invalid_proxy", "Configure an HTTP proxy without credentials in its URL")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env[key] = config["proxy"]
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    return env


def claude_command(config, route, account_id, workspaces=None):
    version = claude_version(config)
    if route.get("minCliVersion") and version_tuple(version) < version_tuple(route["minCliVersion"]):
        raise CollabError("cli_upgrade_required", "Upgrade Claude Code to " + route["minCliVersion"] + " or newer")
    root, module, item = claude_account(config, account_id)
    # Reuse AIManager's isolated HOME and OAuth profile; pin the account at submission.
    _, env = module.profile_env(root, item)
    net = network_env(config)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                "all_proxy", "NO_PROXY", "no_proxy"):
        if key in net:
            env[key] = net[key]
    binary = str(Path(config["claude"]["binary"]).expanduser().resolve())
    command = [
        binary, "-p", "--model", route["model"], "--output-format", "json",
        "--tools", "", "--permission-mode", "dontAsk", "--disable-slash-commands",
        "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--no-session-persistence",
    ]
    if workspaces:
        if version_tuple(version) < (2, 1, 304):
            raise CollabError("cli_upgrade_required", "Workspace read mode requires the verified Claude Code 2.1.304+ flags")
        command[command.index("--tools") + 1] = "Read,Glob,Grep"
        command[command.index("--output-format") + 1] = "stream-json"
        deny = ["Read(//**/" + pattern + ")" for pattern in (
            ".env*", "auth.json", ".credentials.json", "*.token", "*rpc-token",
            "id_rsa*", "id_ed25519*", ".ssh/**", ".git/**",
        )]
        settings = {"disableAllHooks": True, "permissions": {
            "deny": deny, "blockReadsOutsideWorkingDirectories": True,
        }}
        command[command.index("--settings") + 1] = json.dumps(settings)
        command += ["--restricted", "--safe-mode", "--allowedTools", "Read,Glob,Grep",
                    "--verbose", "--max-turns", "30"]
        for workspace in workspaces:
            command += ["--add-dir", workspace["path"]]
    return command, env, version


def gemini_settings(config):
    settings = {}
    path = Path(config["geminiWeb"]["envFile"]).expanduser()
    if path.is_file():
        if path.stat().st_size > 65536:
            raise CollabError("invalid_credentials_file", "Gemini credential file exceeds size limit")
        for line in path.read_text().splitlines():
            name, sep, raw = line.partition("=")
            if sep and name in {"GEMINI_WEB_BASE_URL", "GEMINI_WEB_API_KEY"}:
                values = shlex.split(raw, comments=True)
                if len(values) == 1:
                    settings[name] = values[0]
    for key in ("GEMINI_WEB_BASE_URL", "GEMINI_WEB_API_KEY"):
        if key in os.environ:
            settings[key] = os.environ[key]
    base = config["geminiWeb"].get("resolvedBaseUrl") or settings.get("GEMINI_WEB_BASE_URL", "http://127.0.0.1:16969/v1")
    base = base.rstrip("/")
    url = urllib.parse.urlsplit(base)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise CollabError("invalid_endpoint", "Invalid Gemini web endpoint")
    if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise CollabError("invalid_endpoint", "Plain HTTP is supported only on loopback")
    if not settings.get("GEMINI_WEB_API_KEY"):
        raise CollabError("authentication_required", "Configure the existing Gemini web client credentials")
    return base, settings["GEMINI_WEB_API_KEY"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def gemini_request(config, path, body=None, timeout=20):
    if path not in {"/models", "/chat/completions"}:
        raise CollabError("unsupported_endpoint", "Only models and chat completions are supported")
    base, key = gemini_settings(config)
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        base + path, data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    # The existing web client uses a loopback SSH forward, never an outbound proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise CollabError("response_too_large", "Provider response exceeded 4 MiB")
            payload = json.loads(raw)
            serving = response.headers.get("X-Gemini-Web-Account")
            if isinstance(payload, dict) and serving and re.fullmatch(r"[\w.-]{1,128}", serving):
                payload["_collabServingAccount"] = serving
            return payload
    except urllib.error.HTTPError as error:
        code = "authentication_required" if error.code in (401, 403) else "provider_http_error"
        raise CollabError(code, "Gemini web returned HTTP " + str(error.code))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CollabError("network_error", "Gemini web request failed; check the existing tunnel")
    except ValueError:
        raise CollabError("invalid_response", "Gemini web returned invalid JSON")


def discovered_models(config, provider):
    if provider == "gemini-web":
        data = gemini_request(config, "/models")
        return [{"model": item["id"], "label": item.get("name", item["id"])}
                for item in data.get("data", [])[:200] if isinstance(item.get("id"), str)]
    root, module, item = claude_account(config)
    home, _ = module.profile_env(root, item)
    cached = read_json(home / ".claude/.claude.json")
    return [{"model": item["value"], "label": item.get("label", item["value"])}
            for item in cached.get("additionalModelOptionsCache", [])[:200]
            if isinstance(item, dict) and not item.get("disabled") and isinstance(item.get("value"), str)]


def parse_claude(payload, requested):
    if not isinstance(payload, dict) or payload.get("is_error") or payload.get("subtype") not in (None, "success"):
        raise CollabError("provider_error", "Claude Code did not complete successfully; check model access and account status")
    content = payload.get("result")
    if not isinstance(content, str) or not content.strip():
        raise CollabError("empty_response", "Claude Code returned no text")
    model_usage = payload.get("modelUsage") or {}
    reported = list(model_usage) if isinstance(model_usage, dict) else []
    top_model = payload.get("model")
    if top_model and top_model != requested:
        raise CollabError("model_mismatch", "Claude Code reported a different primary model")
    if top_model and top_model not in reported:
        reported.append(top_model)
    # A helper model may be listed alongside the requested one, but never silently
    # accept a result attributed solely to a different model.
    if not reported:
        raise CollabError("model_unverified", "Claude Code did not report model identity metadata")
    if requested not in reported:
        raise CollabError("model_mismatch", "Claude Code reported a different model than requested")
    requested_usage = model_usage.get(requested, {}) if isinstance(model_usage, dict) else {}
    if isinstance(requested_usage, dict) and requested_usage.get("outputTokens") == 0:
        others_generated = any(isinstance(v, dict) and isinstance(v.get("outputTokens"), (int, float))
                               and v["outputTokens"] > 0 for k, v in model_usage.items() if k != requested)
        if others_generated:
            raise CollabError("model_mismatch", "Only a different model reported generated output")
    return {"text": content, "reportedModels": reported, "usage": payload.get("usage"),
            "sessionId": payload.get("session_id"), "modelIdentityEvidence": "cli_metadata"}


def parse_claude_stream(raw, requested):
    final = None
    accesses = []
    pending = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise CollabError("invalid_response", "Claude Code returned an invalid stream event")
        if event.get("type") == "result":
            final = event
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name")
                    if name not in {"Read", "Glob", "Grep"}:
                        raise CollabError("unexpected_tool", "Workspace mode reported an unexpected tool")
                    arguments = block.get("input", {})
                    path = arguments.get("file_path") or arguments.get("path")
                    access = {"tool": name, "path": path, "status": "requested"}
                    accesses.append(access)
                    if block.get("id"):
                        pending[block["id"]] = access
        if event.get("type") == "user":
            for block in event.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    access = pending.get(block.get("tool_use_id"))
                    if access is not None:
                        access["status"] = "denied_or_failed" if block.get("is_error") else "succeeded"
    if final is None:
        raise CollabError("incomplete_response", "Claude Code stream has no final result")
    result = parse_claude(final, requested)
    result["fileAccesses"] = accesses
    return result


def parse_gemini(payload, requested):
    if not isinstance(payload, dict) or payload.get("error"):
        raise CollabError("provider_error", "Gemini web returned an error")
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise CollabError("invalid_response", "Gemini web response is missing content")
    if not isinstance(content, str) or not content.strip():
        raise CollabError("empty_response", "Gemini web returned no text")
    if choice.get("finish_reason") != "stop":
        raise CollabError("incomplete_response", "Gemini web response was truncated or interrupted")
    reported = payload.get("model")
    if not reported:
        raise CollabError("model_unverified", "Gemini web did not report model identity metadata")
    if reported != requested:
        raise CollabError("model_mismatch", "Gemini web reported a different model than requested")
    return {"text": content, "reportedModels": [reported] if reported else [],
            "usage": payload.get("usage"), "servingAccount": payload.get("_collabServingAccount"),
            "modelIdentityEvidence": "proxy_metadata"}
