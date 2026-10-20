"""Optional collaboration facade; parsing and execution stay outside LabContext."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


def register_collaboration(mcp: Any, runtime: Any = None) -> None:
    executable = Path(os.environ.get("AI_COLLAB_BIN", str(Path.home() / ".local/bin/ai-collab")))
    if not executable.is_file():
        return

    def call(operation: str, **arguments: Any) -> dict[str, Any]:
        if runtime is not None and operation != "tools":
            runtime.enforce("collab_" + operation)
        arguments = {key: value for key, value in arguments.items() if value is not None}
        body = json.dumps({"operation": operation, "arguments": arguments}).encode()
        if len(body) > 1024 * 1024:
            return {"ok": False, "error": {"code": "context_too_large"}}
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                process = subprocess.Popen([str(executable), "bridge"], stdin=subprocess.PIPE,
                                           stdout=output, stderr=errors)
                process.communicate(body, timeout=45)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return {"ok": False, "error": {"code": "bridge_timeout", "message": "Check jobs before resubmitting"}}
            except OSError:
                return {"ok": False, "error": {"code": "bridge_unavailable"}}
            output.seek(0)
            raw = output.read(5 * 1024 * 1024 + 1)
        try:
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError()
            return json.loads(raw)
        except ValueError:
            return {"ok": False, "error": {"code": "invalid_bridge_response"}}

    discovery = call("tools")
    if not discovery.get("ok") or not discovery.get("data", {}).get("tools"):
        return
    if runtime is not None:
        runtime.collaboration_available = True

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
    def collab_run(model: str, prompt: str, workspace: str | None = None,
                   access: str | None = None, timeout: int = 600) -> dict[str, Any]:
        """Start a background collaboration with a configured named model. Workspace is on this provider's host. Access text/read/exec is limited by deployment policy; exec requires explicit task authorization. Returns a job ID, not a completed task. Calls may consume model quota."""
        return call("run", model=model, prompt=prompt, workspace=workspace, access=access, timeout=timeout)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
    def collab_reply(job_id: str, prompt: str, timeout: int = 600) -> dict[str, Any]:
        """Continue the newest successful collaboration job with the same model, identity and scope. Returns a new job ID; does not change permissions or retry failed tasks."""
        return call("reply", job_id=job_id, prompt=prompt, timeout=timeout)

    @mcp.tool(annotations={"readOnlyHint": True})
    def collab_status(job_id: str) -> dict[str, Any]:
        """Read this provider's collaboration job state; no new model call."""
        return call("status", job_id=job_id)

    @mcp.tool(annotations={"readOnlyHint": True})
    def collab_result(job_id: str) -> dict[str, Any]:
        """Read a successful collaboration result. Reported checks need coordinator verification."""
        return call("result", job_id=job_id)

    @mcp.tool(annotations={"readOnlyHint": True})
    def collab_wait(job_id: str, timeout: int = 10) -> dict[str, Any]:
        """Wait at most 30 seconds for a collaboration; return progress if still running."""
        return call("wait", job_id=job_id, timeout=timeout)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def collab_cancel(job_id: str) -> dict[str, Any]:
        """Request cancellation of a collaboration worker; separately launched experiments may continue."""
        return call("cancel", job_id=job_id)

    @mcp.tool(annotations={"readOnlyHint": True})
    def collab_jobs(workspace: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List jobs created through this provider's collaboration bridge within current policy."""
        return call("jobs", workspace=workspace, limit=limit)
