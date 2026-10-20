import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import subprocess
import time

from . import VERSION, jobs, providers, native
from .config import CollabError, atomic_json, config_path, defaults, load, resolve, state_path, validate


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CollabError("invalid_arguments", message)


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError("expected {}..{}".format(low, high))
        return number
    return parse


def parser():
    p = Parser(description="Delegate bounded tasks to a named model using existing AIManager accounts.")
    p.add_argument("--version", action="version", version=VERSION)
    p.add_argument("--json", action="store_true", help="Stable JSON envelope (also the default)")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create personal model routing; preserve an existing configuration")
    init.add_argument("--proxy", help="Existing HTTP forward proxy for native Claude Code")
    sub.add_parser("doctor", help="Check configured CLI, selected account and Gemini model endpoint")
    models = sub.add_parser("models", help="List configured names and optionally discover upstream models")
    models.add_argument("--refresh", action="store_true")
    names = sub.add_parser("resolve", help="Resolve a user model name without inference or fallback")
    names.add_argument("model")
    alias = sub.add_parser("alias", help="Maintain explicit model bindings and provider defaults")
    aliases = alias.add_subparsers(dest="action", required=True)
    setter = aliases.add_parser("set", help="Register a verified upstream model ID")
    setter.add_argument("name")
    setter.add_argument("--provider", required=True, choices=("claude-code", "gemini-web", "codex-cli"))
    setter.add_argument("--model", required=True)
    setter.add_argument("--alias", action="append", default=[])
    setter.add_argument("--min-cli-version")
    setter.add_argument("--replace", action="store_true")
    default = aliases.add_parser("default", help="Choose the default for an unversioned provider name")
    default.add_argument("provider", choices=("claude", "gemini", "codex"))
    default.add_argument("name")
    run = sub.add_parser("run", help="Submit a task with text context or native workspace access")
    run.add_argument("--model", required=True)
    prompt = run.add_mutually_exclusive_group()
    prompt.add_argument("--prompt")
    prompt.add_argument("--prompt-file", type=Path)
    run.add_argument("--file", action="append", default=[])
    run.add_argument("--workspace", action="append", default=[], help="Native CLI project root; read-only unless --access exec")
    run.add_argument("--role", choices=list(jobs.ROLES), default="collaborator")
    run.add_argument("--cwd", default=os.getcwd())
    run.add_argument("--access", choices=("text", "read", "exec"))
    run.add_argument("--host", help="Configured SSH host; never a shell command")
    run.add_argument("--timeout", type=bounded_int(5, 1800), default=600)
    run.add_argument("--wait", type=bounded_int(0, 60), default=0, metavar="SECONDS")
    run.add_argument("--after", help="Include the successful result of this previous job")
    run.add_argument("--dry-run", action="store_true")
    for name, description in (
        ("status", "Read task state"), ("result", "Read a successful result"),
        ("cancel", "Request local cancellation without retrying upstream"),
        ("wait", "Wait up to 60 seconds for a task"),
    ):
        cmd = sub.add_parser(name, help=description)
        cmd.add_argument("job_id")
        if name == "wait":
            cmd.add_argument("--timeout", type=bounded_int(0, 60), default=30)
    listing = sub.add_parser("jobs", help="List recent tasks")
    listing.add_argument("--limit", type=bounded_int(1, 100), default=20)
    listing.add_argument("--workspace")
    listing.add_argument("--host")
    reply = sub.add_parser("reply", help="Continue a persisted conversation without changing identity or permissions")
    reply.add_argument("job_id")
    content = reply.add_mutually_exclusive_group()
    content.add_argument("--prompt")
    content.add_argument("--prompt-file", type=Path)
    reply.add_argument("--file", action="append", default=[])
    reply.add_argument("--timeout", type=bounded_int(5, 1800))
    reply.add_argument("--wait", type=bounded_int(0, 60), default=0)
    sub.add_parser("bridge", help="One structured request on stdin, constrained by the configured MCP policy")
    sub.add_parser("mcp", help="Optional stdio MCP facade over the same constrained operations")
    sub.add_parser("_remote", help=argparse.SUPPRESS)
    request = sub.add_parser("request", help="Read-only provider escape hatch")
    request.add_argument("--provider", choices=("gemini-web",), required=True)
    request.add_argument("--path", choices=("/models",), required=True)
    return p


def doctor(config):
    checks = {}
    try:
        version = providers.claude_version(config)
        _, _, item = providers.claude_account(config)
        route = resolve(config, config["defaults"]["claude"])
        minimum = route.get("minCliVersion", "0.0.0")
        compatible = providers.version_tuple(version) >= providers.version_tuple(minimum)
        checks["claude-code"] = {
            "state": "configured" if compatible else "upgrade_required",
            "cliVersion": version, "accountId": item["id"], "authSource": "aimanager_managed_oauth",
            "model": route["model"], "generationVerified": False,
        }
    except (CollabError, OSError, ValueError) as error:
        checks["claude-code"] = {"state": "unavailable", "reasonCode": getattr(error, "code", "configuration_error")}
    try:
        items = providers.discovered_models(config, "gemini-web")
        route = resolve(config, config["defaults"]["gemini"])
        advertised = route["model"] in [item["model"] for item in items]
        checks["gemini-web"] = {"state": "configured" if advertised else "model_not_advertised",
                                "authSource": "existing_web_client", "models": items,
                                "generationVerified": False}
    except (CollabError, OSError, ValueError) as error:
        checks["gemini-web"] = {"state": "unavailable", "reasonCode": getattr(error, "code", "configuration_error")}
    if any(r.get("provider") == "codex-cli" for r in config["models"].values()):
        try:
            _, _, version = native.codex_identity(config)
            checks["codex-cli"] = {"state":"configured", "cliVersion":version, "generationVerified":False}
        except (CollabError, OSError, subprocess.SubprocessError):
            checks["codex-cli"] = {"state":"unavailable"}
    return {"version": VERSION, "checks": checks,
            "readyForSmokeTest": all(c["state"] == "configured" for c in checks.values())}


def dispatch(args):
    if args.command in {"init", "alias"}:
        path = config_path().with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return dispatch_locked(args)
    return dispatch_locked(args)


def dispatch_locked(args):
    if args.command == "init":
        path = config_path()
        if path.exists():
            load()
            return {"config": str(path), "created": False}
        value = defaults()
        value["proxy"] = args.proxy
        providers.network_env(value)
        atomic_json(path, value)
        return {"config": str(path), "created": True}
    from . import remote
    if remote.applies(args):
        return remote.dispatch(args)
    if args.command == "_remote":
        return remote.receive()
    if args.command == "bridge":
        from .bridge import dispatch as bridge_dispatch
        raw = sys.stdin.read(jobs.MAX_CONTEXT + 1)
        if len(raw.encode()) > jobs.MAX_CONTEXT:
            raise CollabError("context_too_large", "Bridge request exceeds 1 MiB")
        return bridge_dispatch(json.loads(raw))
    if args.command == "mcp":
        from .bridge import serve
        serve()
        raise SystemExit(0)
    if args.command in ("status", "result", "cancel"):
        return getattr(jobs, args.command)(args.job_id)
    if args.command == "wait":
        return jobs.wait(args.job_id, args.timeout)
    if args.command == "jobs":
        return {"items": jobs.list_jobs(args.limit, args.workspace)}
    config = load()
    if args.command == "doctor":
        return doctor(config)
    if args.command == "resolve":
        route = resolve(config, args.model)
        route["capabilities"] = {"access": ["text"] if route["provider"] == "gemini-web" else
                                 (["read", "exec"] if route["provider"] == "codex-cli" else ["text", "read", "exec"]),
                                 "continuation": "messages" if route["provider"] == "gemini-web" else "native",
                                 "executionRequiresDependencies": route["provider"] == "claude-code"}
        return route
    if args.command == "models":
        result = {"configured": config["models"], "defaults": config["defaults"]}
        if args.refresh:
            discovery = {}
            for provider in ("claude-code", "gemini-web"):
                try:
                    discovery[provider] = {"items": providers.discovered_models(config, provider),
                                           "source": "official_cli_partial_cache" if provider == "claude-code" else "proxy_model_catalog"}
                except (CollabError, OSError, ValueError) as error:
                    discovery[provider] = {"error": getattr(error, "code", "discovery_failed")}
            result.update(discovered=discovery, checkedAt=time.time())
            atomic_json(state_path() / "models.json", result)
        return result
    if args.command == "alias":
        if args.action == "set":
            if args.name in config["models"] and not args.replace:
                raise CollabError("alias_exists", "Use --replace to explicitly replace an existing binding")
            config["models"][args.name] = {"provider": args.provider, "model": args.model, "aliases": args.alias}
            if args.min_cli_version:
                providers.version_tuple(args.min_cli_version)
                config["models"][args.name]["minCliVersion"] = args.min_cli_version
        else:
            route = resolve(config, args.name)
            expected = {"claude":"claude-code", "gemini":"gemini-web", "codex":"codex-cli"}[args.provider]
            if route["provider"] != expected:
                raise CollabError("provider_mismatch", "Default must preserve the selected provider")
            config["defaults"][args.provider] = route["name"]
        validate(config)
        previous = config_path()
        atomic_json(previous.with_suffix(".previous.json"), load())
        atomic_json(previous, config)
        return {"config": str(previous), "models": config["models"], "defaults": config["defaults"]}
    if args.command == "request":
        return providers.gemini_request(config, args.path)
    if args.command in {"run", "reply"}:
        if args.prompt_file:
            prompt, _ = jobs.snapshot_file(args.prompt_file)
        elif args.prompt is not None:
            prompt = args.prompt
        else:
            prompt = sys.stdin.read(jobs.MAX_CONTEXT + 1)
        if args.command == "reply":
            submitted = jobs.reply(args.job_id, prompt, args.file, args.timeout)
        else:
            if args.after and remote.split_ref(args.after):
                host, previous_id = remote.split_ref(args.after)
                previous = remote.request(host, {"operation": "result", "job_id": previous_id})
                prompt += "\n\nPREVIOUS COLLABORATION RESULT (job {}):\n{}".format(args.after, previous["text"])
                args.after = None
            submitted = jobs.submit(config, args.model, prompt, args.file, args.role, args.cwd,
                                    args.timeout, args.after, args.dry_run, args.workspace, args.access)
        if args.wait and not getattr(args, "dry_run", False):
            submitted = jobs.wait(submitted["id"], args.wait)
        return submitted
    raise CollabError("unsupported_command", "Unsupported command")


def main(argv=None):
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] in ("_worker", "_gemini"):
        (jobs.run_worker if argv[0] == "_worker" else jobs.gemini_child)(argv[1])
        return
    # Permit --json on either side of subcommands.
    argv = [arg for arg in argv if arg != "--json"]
    try:
        args = parser().parse_args(argv)
        data = dispatch(args)
        print(json.dumps({"schemaVersion": 1, "ok": True, "data": data}, ensure_ascii=False))
        if args.command == "doctor" and not data["readyForSmokeTest"]:
            raise SystemExit(1)
        if args.command in ("run", "reply", "wait") and data.get("state") in jobs.FINAL - {"succeeded"}:
            raise SystemExit(1)
    except CollabError as error:
        print(json.dumps({"schemaVersion": 1, "ok": False, "error": {"code": error.code, "message": str(error)}}))
        raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"schemaVersion": 1, "ok": False,
                          "error": {"code": "configuration_or_io_error", "message": "Check local config, file paths and permissions"}}))
        raise SystemExit(1)
