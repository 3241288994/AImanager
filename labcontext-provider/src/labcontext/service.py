from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import hmac
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .admin import RuntimeState, dashboard_overview, read_audit, refresh_workspace, test_model_tool, tools_status, list_jobs
from .config import ServerConfig
from .context import (
    get_evidence_data, inspect_file_data, list_workspaces_data, research_context_data,
    resolve_workspace, search_evidence_data, workspace_overview_data,
)
from .direct_path import inspect_path_data
from .collaboration import register_collaboration
from .index import compare_experiments as compare_indexed_experiments
from .index import query_experiments as query_indexed_experiments
from .summarizer import get_job as get_analysis_job
from .summarizer import recover_interrupted_jobs, request_analysis as start_analysis
from .research_map import (
    ResearchMapConflict, ResearchMapError, apply_map_patch, apply_map_proposal,
    initialize_research_map, list_map_proposals, reject_map_proposal,
    research_map_bundle, review_with_latest_session, save_layout,
)


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=False, capture_output=True,
        text=True, timeout=5,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _audit(event: str, details: dict[str, Any]) -> None:
    """Write metadata only; never persist tool inputs, content, or secrets."""
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    state_dir = base / "labcontext"
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **details}
    audit_file = state_dir / "audit.jsonl"
    audit_file.touch(mode=0o600, exist_ok=True)
    audit_file.chmod(0o600)
    with audit_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _workspace_resolution(workspace_id: str | None) -> str:
    """Record whether a tool followed the live default or an explicit model choice."""
    return "configured_default" if not workspace_id else "explicit_workspace_id"


def project_snapshot_data(config: ServerConfig) -> dict[str, Any]:
    """Build the phase-1 snapshot without exposing any project file content."""
    commit = _git(config.project.root, "rev-parse", "--short", "HEAD")
    branch = _git(config.project.root, "branch", "--show-current")
    head_ref = _git(config.project.root, "symbolic-ref", "--quiet", "--short", "HEAD")
    dirty = _git(config.project.root, "status", "--porcelain")
    if commit:
        head_state = "committed"
    elif head_ref:
        head_state = "unborn"
    else:
        head_state = "unavailable"
    _audit("project_snapshot", {"project": config.project.project_id, "commit": commit})
    return {
        "project": config.project.project_id, "root": str(config.project.root),
        "git": {
            "commit": commit,
            "branch": branch,
            "head_state": head_state,
            "dirty": bool(dirty),
        },
        "access_policy": {"mode": "read-only",
                          "allowed_roots": list(config.project.allowed_roots),
                          "denied_globs": list(config.project.denied_globs),
                          "max_response_bytes": config.project.max_response_bytes},
            "phase": "Explicit run manifests and on-demand Codex workspace summaries are available.",
    }


def build_server(config: ServerConfig) -> FastMCP:
    recover_interrupted_jobs(config)
    runtime = RuntimeState(config)
    mcp = FastMCP(
        name="LabContext",
        version=__version__,
        instructions=(
            "Read-only evidence gateway for project workspaces and explicitly allowed absolute paths. "
            "When the user pastes an absolute file or directory path, use inspect_path without first "
            "registering a workspace. For a PDF, use view=pages and follow next_start_page until the "
            "needed sections are covered, or use view=search for targeted terms; do not infer the "
            "document's contents from its filename. Use workspace_overview "
            "for a normal project summary; it is fast and deterministic. Use research_context, "
            "query_experiments, compare_experiments, and search_evidence/get_evidence for targeted facts. "
            "When an exact project file path is already known, use inspect_file instead of searching for it. "
            "When the user says current/default workspace without naming a project, always omit workspace_id "
            "so the server resolves the live configured default; never reuse a workspace ID from earlier chat. "
            "Only use request_analysis when semantic synthesis across workspace assets or the latest Codex "
            "session is genuinely needed; then poll exactly its returned job_id with get_job."
        ),
    )

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def list_workspaces() -> dict[str, Any]:
        """List registered research workspaces, aliases, default ID and capabilities. Use only when the user asks what projects exist or a named project cannot be resolved; ordinary requests may omit workspace_id and use the default."""
        runtime.enforce("list_workspaces")
        current = runtime.config()
        result = list_workspaces_data(current)
        _audit("list_workspaces", {"result_count": len(result["workspaces"]),
                                    "default_workspace_id": result["default_workspace_id"]})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def workspace_overview(workspace_id: str | None = None) -> dict[str, Any]:
        """Return a fast deterministic project overview with Git state, typed assets, active research, recent experiments, and up to three compact recent Codex-session digests. Treat working_context as unverified continuity context, never as research evidence. For 'current/default workspace', MUST omit workspace_id so the server uses its live configured default; only pass workspace_id when the user explicitly names a project. Never copy an ID from earlier chat. This tool does not invoke Codex and unknown IDs are errors."""
        runtime.enforce("workspace_overview")
        result = workspace_overview_data(runtime.config(), workspace_id)
        _audit("workspace_overview", {"workspace_id": result["resolved_workspace_id"],
                                      "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def research_context(
        workspace_id: str | None = None, research_id: str = "active",
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return normalized objectives, hypotheses, claims, evidence, decisions and open questions from a structured research adapter. Use after workspace_overview for research-status or claim-support questions. Unstructured projects return coverage=unstructured and explicit missing sections instead of inferred facts."""
        runtime.enforce("research_context")
        result = research_context_data(runtime.config(), workspace_id, research_id, sections)
        _audit("research_context", {"workspace_id": result["resolved_workspace_id"], "research_id": research_id,
                                    "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def search_evidence(
        query: str, workspace_id: str | None = None,
        scopes: list[str] | None = None, limit: int = 8,
    ) -> dict[str, Any]:
        """Search configured code, docs, configs, research state and experiment assets. Returns bounded snippets plus stable evidence_ref, path, line range, hash, timestamp and authority. Use it to locate evidence; call get_evidence only for the most relevant returned refs."""
        runtime.enforce("search_evidence")
        result = search_evidence_data(runtime.config(), query, workspace_id, scopes, limit)
        _audit("search_evidence", {"workspace_id": result["resolved_workspace_id"], "result_count": len(result["results"]),
                                   "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def get_evidence(
        evidence_refs: list[str], workspace_id: str | None = None, detail: str = "excerpt",
    ) -> dict[str, Any]:
        """Read 1-8 refs returned by search_evidence or research_context. Returns bounded content, workspace, path, location, authority and indexed/current hashes. A changed file returns stale_reference; arbitrary paths are not accepted."""
        runtime.enforce("get_evidence")
        result = get_evidence_data(runtime.config(), evidence_refs, workspace_id, detail)
        _audit("get_evidence", {"workspace_id": result["resolved_workspace_id"], "result_count": len(result["results"]),
                                "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def inspect_file(
        path: str, workspace_id: str | None = None, view: str = "outline",
        query: str | None = None, start_line: int | None = None,
        end_line: int | None = None, json_pointer: str | None = None,
        max_chars: int = 8000, start_page: int | None = None, end_page: int | None = None,
    ) -> dict[str, Any]:
        """Inspect an exact file inside a registered workspace, even when not indexed. Uses the same formats as inspect_path: common code/config/log/text, HTML, PDF, DOCX, XLSX, PPTX and IPYNB. Views: auto, outline, search, lines (at most 200 extracted lines), full_bounded; JSON also supports json_pointer. PDF supports pages with 1-based start_page/end_page (at most 20 pages); scanned PDFs require OCR. Office text includes sheet/cell or slide labels, without running formulas, macros or notebook code. Prefer workspace-relative paths; absolute paths must remain inside this workspace. Credentials, denied paths and unsupported binaries remain blocked. Returns evidence references."""
        runtime.enforce("inspect_file")
        result = inspect_file_data(
            runtime.config(), path, workspace_id, view, query,
            start_line, end_line, json_pointer, max_chars, start_page, end_page,
        )
        _audit("inspect_file", {
            "workspace_id": result["resolved_workspace_id"], "path": result["path"],
            "view": result["view"], "workspace_resolution": _workspace_resolution(workspace_id),
        })
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def inspect_path(
        path: str, view: str = "auto", query: str | None = None,
        start_line: int | None = None, end_line: int | None = None,
        start_page: int | None = None, end_page: int | None = None,
        json_pointer: str | None = None, depth: int = 2,
        max_entries: int = 200, max_chars: int = 8000,
    ) -> dict[str, Any]:
        """Inspect an absolute file or directory below registry.allowed_roots without registering a workspace. Shares the inspect_file format registry: common code/config/log/text, HTML, PDF, DOCX, XLSX, PPTX and IPYNB. A directory returns a bounded tree (depth 1-3, at most 400 entries). Views: auto, outline, search, lines, full_bounded; JSON also supports json_pointer. PDF supports pages with 1-based start_page/end_page (at most 20 pages); scanned PDFs require OCR. Office text includes sheet/cell or slide labels, without running formulas, macros or notebook code. Credentials, denied paths, unsupported binaries and oversized files remain blocked."""
        runtime.enforce("inspect_path")
        result = inspect_path_data(
            runtime.config(), path, view, query, start_line, end_line,
            start_page, end_page, json_pointer, depth, max_entries, max_chars,
        )
        _audit("inspect_path", {
            "path": result["path"], "path_type": result["path_type"],
            "view": result["view"],
        })
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def query_experiments(
        workspace_id: str | None = None, query: str = "",
        experiment_ids: list[str] | None = None, metrics: list[str] | None = None,
        filters: dict[str, Any] | None = None, detail: str = "summary", limit: int = 10,
    ) -> dict[str, Any]:
        """Find experiments by text/metric name or retrieve exact experiment_ids. detail is summary, metrics, or manifest; optional metrics limits returned fields. The server incrementally refreshes configured experiment assets and returns evidence paths/hashes. Use compare_experiments for deltas."""
        runtime.enforce("query_experiments")
        current = runtime.config()
        workspace = resolve_workspace(current, workspace_id)
        result = query_indexed_experiments(
            current, workspace, query, experiment_ids, metrics, filters, detail, limit,
        )
        _audit("query_experiments", {"workspace_id": workspace.workspace_id, "result_count": result["result_count"],
                                     "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def compare_experiments(
        experiment_ids: list[str], workspace_id: str | None = None,
        metrics: list[str] | None = None, include_config_diff: bool = False,
    ) -> dict[str, Any]:
        """Compare 2-8 exact experiment IDs server-side. Returns an aligned metric matrix, absolute deltas from the first ID, missing IDs, comparability warnings, evidence and optional config differences. Missing values remain null and are never treated as zero."""
        runtime.enforce("compare_experiments")
        current = runtime.config()
        workspace = resolve_workspace(current, workspace_id)
        result = compare_indexed_experiments(current, workspace, experiment_ids, metrics, include_config_diff)
        _audit("compare_experiments", {"workspace_id": workspace.workspace_id, "experiment_count": len(experiment_ids),
                                       "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def request_analysis(
        workspace_id: str | None = None, question: str = "",
        include_latest_session: bool = True, refresh: bool = False,
    ) -> dict[str, Any]:
        """Start or reuse an asynchronous read-only Codex analysis for cross-asset synthesis or latest-session handoff. Do not use for a normal overview or deterministic metric lookup. Returns immediately with one job_id; poll only that ID via get_job and do not retry with refresh while it is running."""
        runtime.enforce("request_analysis")
        current = runtime.config()
        workspace = resolve_workspace(current, workspace_id)
        result = start_analysis(current, workspace.workspace_id, question, include_latest_session, refresh)
        _audit("request_analysis", {"workspace_id": workspace.workspace_id, "status": result["status"],
                                    "workspace_resolution": _workspace_resolution(workspace_id)})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def get_job(job_id: str, wait_seconds: int = 0) -> dict[str, Any]:
        """Get one asynchronous job by exact job_id. Returns running progress with updated_at, or completed verified_facts/Codex analysis, or a structured failed/interrupted error. wait_seconds is bounded to 0-20; reuse the same job_id rather than starting another analysis."""
        runtime.enforce("get_job")
        result = get_analysis_job(runtime.config(), job_id, wait_seconds)
        _audit("get_job", {"job_id": job_id, "status": result["status"]})
        return result

    def authorized(request: Request) -> bool:
        provided = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return bool(provided) and hmac.compare_digest(provided, runtime.token)

    def denied() -> JSONResponse:
        return JSONResponse({"error": "admin_auth_required"}, status_code=401)

    @mcp.custom_route("/admin/overview", methods=["GET"], include_in_schema=False)
    async def admin_overview(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        return JSONResponse(dashboard_overview(runtime))

    @mcp.custom_route("/admin/activity", methods=["GET"], include_in_schema=False)
    async def admin_activity(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        params = request.query_params
        return JSONResponse(read_audit(
            limit=int(params.get("limit", "100")), workspace_id=params.get("workspace_id"),
            tool=params.get("tool"), status=params.get("status"),
        ))

    @mcp.custom_route("/admin/jobs", methods=["GET"], include_in_schema=False)
    async def admin_jobs(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        params = request.query_params
        return JSONResponse(list_jobs(runtime.config(), int(params.get("limit", "100")), params.get("workspace_id")))

    @mcp.custom_route("/admin/default-workspace", methods=["POST"], include_in_schema=False)
    async def admin_set_default(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            previous_workspace_id = runtime.config().default_workspace_id
            updated = runtime.set_default_workspace(str(payload.get("workspace_id", "")))
            _audit("admin_set_default_workspace", {
                "workspace_id": updated.default_workspace_id,
                "previous_workspace_id": previous_workspace_id,
                "status": "completed",
            })
            return JSONResponse({"ok": True, "default_workspace_id": updated.default_workspace_id})
        except (ValueError, OSError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/workspaces", methods=["POST"], include_in_schema=False)
    async def admin_upsert_workspace(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            updated, workspace_id = runtime.upsert_workspace(payload)
            generation = runtime.generate_workspace_overview(workspace_id, refresh=False)
            map_initialization = initialize_research_map(runtime.config(), workspace_id, actor="workspace_onboarding")
            return JSONResponse({"ok": True, "workspace_id": workspace_id,
                                 "default_workspace_id": updated.default_workspace_id,
                                 "overview_generation": generation,
                                 "research_map_initialization": {
                                     "revision": map_initialization["revision"],
                                     "cached": map_initialization["cached"],
                                 }})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/delete-workspace", methods=["POST"], include_in_schema=False)
    async def admin_delete_workspace(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(runtime.delete_workspace(str(payload.get("workspace_id", ""))))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/workspace-overview", methods=["POST"], include_in_schema=False)
    async def admin_set_workspace_overview(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(runtime.set_workspace_overview(
                str(payload.get("workspace_id", "")), str(payload.get("overview", "")),
            ))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/generate-workspace-overview", methods=["POST"], include_in_schema=False)
    async def admin_generate_workspace_overview(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(runtime.generate_workspace_overview(
                str(payload.get("workspace_id", "")), bool(payload.get("refresh", False)),
            ))
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/worker-config", methods=["POST"], include_in_schema=False)
    async def admin_set_worker_config(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(runtime.set_worker_config(
                str(payload.get("model", "")), str(payload.get("reasoning_effort", "")),
            ))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/tool-policy", methods=["POST"], include_in_schema=False)
    async def admin_tool_policy(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            runtime.set_policy(str(payload.get("profile", "custom")), list(payload.get("disabled_tools", [])))
            return JSONResponse(tools_status(runtime))
        except (ValueError, OSError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/refresh-workspace", methods=["POST"], include_in_schema=False)
    async def admin_refresh_workspace(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(refresh_workspace(runtime, str(payload.get("workspace_id", ""))))
        except (ValueError, OSError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/test-tool", methods=["POST"], include_in_schema=False)
    async def admin_test_tool(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(test_model_tool(runtime, str(payload.get("tool", "")), payload.get("workspace_id")))
        except (ValueError, OSError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map", methods=["GET"], include_in_schema=False)
    async def admin_research_map(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            workspace_id = str(request.query_params.get("workspace_id") or "")
            if not workspace_id:
                raise ValueError("workspace_id is required")
            result = research_map_bundle(runtime.config(), workspace_id)
            result["proposals"] = list_map_proposals(runtime.config(), workspace_id)["proposals"]
            return JSONResponse(result)
        except (ResearchMapError, ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map/initialize", methods=["POST"], include_in_schema=False)
    async def admin_initialize_research_map(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(initialize_research_map(
                runtime.config(), str(payload.get("workspace_id") or ""), actor="user",
            ))
        except (ResearchMapError, ValueError, OSError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map/layout", methods=["POST"], include_in_schema=False)
    async def admin_save_research_map_layout(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(save_layout(
                runtime.config(), str(payload.get("workspace_id") or ""),
                payload.get("layout") or {}, actor="user",
            ))
        except (ResearchMapError, ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map/patch", methods=["POST"], include_in_schema=False)
    async def admin_apply_research_map_patch(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            return JSONResponse(apply_map_patch(
                runtime.config(), str(payload.get("workspace_id") or ""),
                payload.get("patch") or {}, actor="user",
            ))
        except ResearchMapConflict as exc:
            return JSONResponse({"error": str(exc), "error_type": "revision_conflict"}, status_code=409)
        except (ResearchMapError, ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map/review", methods=["POST"], include_in_schema=False)
    async def admin_review_research_map(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            result = review_with_latest_session(
                runtime.config(), str(payload.get("workspace_id") or ""),
                prefer_queue=bool(payload.get("prefer_queue", True)),
            )
            _audit("admin_review_research_map", {
                "workspace_id": result["workspace_id"], "status": result["status"],
                "proposal_id": result.get("proposal_id"),
            })
            return JSONResponse(result)
        except (ResearchMapError, ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @mcp.custom_route("/admin/research-map/proposal", methods=["POST"], include_in_schema=False)
    async def admin_research_map_proposal_action(request: Request) -> JSONResponse:
        if not authorized(request):
            return denied()
        try:
            payload = await request.json()
            workspace_id = str(payload.get("workspace_id") or "")
            proposal_id = str(payload.get("proposal_id") or "")
            action = str(payload.get("action") or "")
            if action == "apply":
                return JSONResponse(apply_map_proposal(runtime.config(), workspace_id, proposal_id))
            if action == "reject":
                return JSONResponse(reject_map_proposal(runtime.config(), workspace_id, proposal_id))
            raise ValueError("action must be apply or reject")
        except ResearchMapConflict as exc:
            return JSONResponse({"error": str(exc), "error_type": "revision_conflict"}, status_code=409)
        except (ResearchMapError, ValueError, OSError, KeyError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    register_collaboration(mcp, runtime)
    return mcp


def run_server(config: ServerConfig) -> None:
    build_server(config).run(transport="streamable-http", host=config.host,
                             port=config.port, path=config.path)
