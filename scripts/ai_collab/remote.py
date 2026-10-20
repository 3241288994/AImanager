"""SSH transport: a fixed remote entrypoint, structured stdin, remote-owned jobs."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .config import CollabError, load
from . import jobs

NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
OPERATIONS = {"run", "reply", "status", "result", "wait", "cancel", "jobs"}


def split_ref(value):
    if not isinstance(value, str) or ":" not in value:
        return None
    host, job_id = value.split(":", 1)
    if not re.fullmatch(NAME, host):
        raise CollabError("invalid_host", "Expected a configured host reference")
    jobs.directory(job_id)  # validate the opaque local part without reading it
    return host, job_id


def applies(args):
    return bool(getattr(args, "host", None) or split_ref(getattr(args, "job_id", None)))


def request(host, payload):
    config = load()
    settings = config.get("hosts", {}).get(host)
    if not settings or not re.fullmatch(NAME, host):
        raise CollabError("unknown_host", "Choose an explicitly configured SSH host")
    alias = settings.get("ssh", "")
    entry = settings.get("entrypoint", "~/.local/bin/ai-collab")
    if not re.fullmatch(NAME, alias) or not re.fullmatch(r"(?:/|~/)[A-Za-z0-9_./-]+", entry):
        raise CollabError("invalid_host", "SSH alias and fixed executable path are invalid")
    body = json.dumps(payload).encode()
    if len(body) > jobs.MAX_CONTEXT:
        raise CollabError("context_too_large", "Remote request exceeds 1 MiB")
    # Only this validated, fixed command reaches the remote shell. Task values
    # travel through stdin, never through command-line quoting.
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "--", alias, entry + " _remote"]
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=errors)
            child.communicate(body, timeout=135)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise CollabError("remote_timeout", "SSH response timed out; query remote jobs before repeating a submission")
        output.seek(0)
        raw = output.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise CollabError("output_limit", "Remote result exceeded the transport limit")
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise CollabError("remote_error", "Remote CLI returned no valid response; inspect the SSH connection")
    if not envelope.get("ok"):
        error = envelope.get("error", {})
        raise CollabError(error.get("code", "remote_error"), error.get("message", "Remote operation failed"))
    result = envelope["data"]
    if isinstance(result, dict):
        result["host"] = host
        for key in ("id", "jobId", "parentJobId", "conversationId"):
            if result.get(key):
                result[key] = host + ":" + result[key]
        for item in result.get("items", []):
            item["host"] = host
            for key in ("id", "jobId", "parentJobId", "conversationId"):
                if item.get(key):
                    item[key] = host + ":" + item[key]
    return result


def dispatch(args):
    ref = split_ref(getattr(args, "job_id", None))
    host = ref[0] if ref else args.host
    payload = {"operation": args.command}
    if ref:
        payload["job_id"] = ref[1]
    for name in ("model", "role", "workspace", "access", "timeout", "limit", "wait", "dry_run"):
        if hasattr(args, name):
            payload[name] = getattr(args, name)
    if args.command in {"run", "reply"}:
        import sys
        text = jobs.snapshot_file(args.prompt_file)[0] if args.prompt_file else args.prompt
        text = text if text is not None else sys.stdin.read(jobs.MAX_CONTEXT + 1)
        for value in args.file:
            content, metadata = jobs.snapshot_file(Path(value))
            text += "\n\nATTACHMENT " + json.dumps(metadata) + ":\n" + content
        after = getattr(args, "after", None)
        if after:
            other = split_ref(after)
            previous = request(other[0], {"operation": "result", "job_id": other[1]}) if other else jobs.result(after)
            text += "\n\nPREVIOUS RESULT:\n" + previous["text"]
        payload["prompt"] = text
    return request(host, payload)


def receive():
    import sys
    raw = sys.stdin.read(jobs.MAX_CONTEXT + 1)
    if len(raw.encode()) > jobs.MAX_CONTEXT:
        raise CollabError("context_too_large", "Remote request exceeds 1 MiB")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("operation") not in OPERATIONS:
        raise CollabError("unsupported_command", "Unsupported remote operation")
    operation = payload["operation"]
    if operation == "run":
        roots = payload.get("workspace") or []
        result = jobs.submit(load(), payload["model"], payload["prompt"], [],
                             payload.get("role", "collaborator"), roots[0] if roots else os.getcwd(),
                             payload.get("timeout", 600), dry_run=payload.get("dry_run", False),
                             workspaces=roots, access=payload.get("access"))
    elif operation == "reply":
        result = jobs.reply(payload["job_id"], payload["prompt"], timeout=payload.get("timeout"))
    elif operation == "jobs":
        return {"items": jobs.list_jobs(min(100, max(1, int(payload.get("limit", 20)))), payload.get("workspace"))}
    elif operation == "wait":
        return jobs.wait(payload["job_id"], min(60, max(0, int(payload.get("timeout", 30)))))
    else:
        return getattr(jobs, operation)(payload["job_id"])
    if payload.get("wait") and not payload.get("dry_run"):
        return jobs.wait(result["id"], min(60, max(0, int(payload["wait"]))))
    return result
