"""Optional constrained MCP facade. Uses the same jobs; no HTTP server or agent loop."""
import json
from pathlib import Path
import sys

from . import jobs
from .config import CollabError, atomic_json, load, resolve, provider_path

PROPERTIES = {
    "model": {"type": "string"}, "prompt": {"type": "string"},
    "workspace": {"type": "string"}, "access": {"type": "string", "enum": ["text", "read", "exec"]},
    "job_id": {"type": "string"}, "timeout": {"type": "integer"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
}
FIELDS = {
    "run": (["model", "prompt"], ["model", "prompt", "workspace", "access", "timeout"]),
    "reply": (["job_id", "prompt"], ["job_id", "prompt", "timeout"]),
    "status": (["job_id"], ["job_id"]), "result": (["job_id"], ["job_id"]),
    "wait": (["job_id"], ["job_id", "timeout"]), "cancel": (["job_id"], ["job_id"]),
    "jobs": ([], ["workspace", "limit"]),
}


def policy():
    config = load()
    rules = config.get("mcp", {})
    if rules.get("enabled") is not True:
        raise CollabError("bridge_disabled", "Enable the local collaboration MCP policy explicitly")
    if not isinstance(rules.get("models"), list) or not isinstance(rules.get("allowedRoots"), list):
        raise CollabError("invalid_policy", "Configure MCP models and allowedRoots")
    return config, rules


def allowed(config, rules, model, roots, access):
    route = model if isinstance(model, dict) else resolve(config, model)
    accepted = [resolve(config, name) for name in rules["models"]]
    if not any((r["provider"], r["model"]) == (route["provider"], route["model"]) for r in accepted):
        raise CollabError("model_not_allowed", "Model is outside the MCP policy")
    if access == "exec" and rules.get("allowExec") is not True:
        raise CollabError("exec_not_allowed", "MCP execution is disabled")
    for root in roots:
        path = Path(root).expanduser().resolve()
        if not any(path == provider_path(p) or provider_path(p) in path.parents
                   for p in rules["allowedRoots"]):
            raise CollabError("workspace_not_allowed", "Workspace is outside the MCP policy")


def owned(job_id, config, rules):
    if not (jobs.directory(job_id) / "bridge.json").is_file():
        raise CollabError("job_not_allowed", "This job was not created through the MCP bridge")
    state = jobs.status(job_id)
    allowed(config, rules, state["route"], [r["path"] for r in state["workspaces"]], state["access"])
    return state


def tools():
    try:
        policy()
    except CollabError as exc:
        if exc.code == "bridge_disabled":
            return []
        raise
    return [{
        "name": "collab_" + name,
        "description": ("AImanager collaboration " + name +
                        ". Uses configured models and workspace policy; run/reply may consume model quota."
                        " Run returns a background job. Copy the returned job ID for later operations."),
        "inputSchema": {"type": "object", "properties": {k: PROPERTIES[k] for k in keys},
                        "required": required, "additionalProperties": False},
        "annotations": {"readOnlyHint": name in {"status", "result", "wait", "jobs"},
                        "destructiveHint": name in {"run", "reply", "cancel"}, "openWorldHint": name in {"run", "reply"}},
    } for name, (required, keys) in FIELDS.items()]


def dispatch(request):
    config, rules = policy()
    if not isinstance(request, dict) or set(request) - {"operation", "arguments"}:
        raise CollabError("invalid_request", "Expected operation and arguments")
    name, args = request.get("operation", ""), request.get("arguments", {})
    if not isinstance(name, str):
        raise CollabError("invalid_request", "Operation must be a string")
    name = name.removeprefix("collab_") if hasattr(name, "removeprefix") else (name[7:] if name.startswith("collab_") else name)
    if name == "tools":
        return {"tools": tools()}
    if name not in FIELDS or not isinstance(args, dict):
        raise CollabError("invalid_request", "Unknown bridge operation")
    required, keys = FIELDS[name]
    if set(args) - set(keys) or any(k not in args for k in required):
        raise CollabError("invalid_request", "Unsupported or missing bridge argument")
    for key, value in args.items():
        wanted = int if key in {"timeout", "limit"} else str
        if type(value) is not wanted:
            raise CollabError("invalid_request", "Invalid argument type")
    if "prompt" in args and len(args["prompt"].encode()) > jobs.MAX_FILE:
        raise CollabError("context_too_large", "MCP prompt exceeds 256 KiB")
    if name == "run":
        roots = [args["workspace"]] if args.get("workspace") else []
        access = args.get("access") or ("read" if roots else "text")
        allowed(config, rules, args["model"], roots, access)
        result = jobs.submit(config, args["model"], args["prompt"], [], "collaborator",
                             roots[0] if roots else str(Path.home()), args.get("timeout", 600),
                             workspaces=roots, access=access)
    elif name == "jobs":
        values = []
        for state in jobs.list_jobs(100, args.get("workspace")):
            try:
                owned(state["id"], config, rules)
                values.append(state)
            except CollabError:
                pass
        return {"items": values[:min(100, max(1, args.get("limit", 20)))]}
    else:
        owned(args["job_id"], config, rules)
        if name == "reply":
            result = jobs.reply(args["job_id"], args["prompt"], timeout=args.get("timeout"))
        elif name == "wait":
            return jobs.wait(args["job_id"], min(30, max(0, args.get("timeout", 10))))
        else:
            return getattr(jobs, name)(args["job_id"])
    atomic_json(jobs.directory(result["id"]) / "bridge.json", {"origin": "mcp"})
    return result


def serve():
    """Newline-delimited stdio MCP; HTTP/auth stay in the existing provider."""
    while True:
        line = sys.stdin.readline(jobs.MAX_CONTEXT + 1)
        if not line:
            break
        if len(line.encode()) > jobs.MAX_CONTEXT:
            break
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                request = {}
                raise CollabError("invalid_request", "Expected a JSON-RPC object")
            method = request.get("method")
            if "id" not in request:
                continue
            if method == "initialize":
                result = {"protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "AImanager collaboration", "version": "0.2.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tools()}
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    value = dispatch({"operation": params.get("name", ""), "arguments": params.get("arguments", {})})
                    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                except CollabError as exc:
                    result = {"isError": True, "content": [{"type": "text", "text": exc.code + ": " + str(exc)}]}
            else:
                raise CollabError("method_not_found", "Unknown MCP method")
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as exc:
            message = str(exc) if isinstance(exc, CollabError) else "Invalid request or unavailable local execution"
            response = {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32602, "message": message}}
        print(json.dumps(response, ensure_ascii=False), flush=True)
