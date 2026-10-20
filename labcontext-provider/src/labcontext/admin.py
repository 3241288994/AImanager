from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from typing import Any
import re

import tomlkit
import yaml

from . import __version__
from .config import ServerConfig, load_config
from .context import _inferred_assets, git_state, resolve_workspace
from .index import _connect, refresh_experiment_index
from .summarizer import _ensure_tables, request_summary
from .research_map import focus_capsule, list_map_proposals, load_research_map


PUBLIC_TOOLS = (
    ("list_workspaces", "Workspace discovery", "instant", ()),
    ("workspace_overview", "Deterministic workspace overview", "indexed", ()),
    ("research_context", "Structured research state", "instant", ()),
    ("search_evidence", "Bounded evidence search", "indexed", ()),
    ("get_evidence", "Evidence reference retrieval", "instant", ("search_evidence",)),
    ("inspect_file", "Exact bounded project-file inspection", "instant", ()),
    ("inspect_path", "Direct allowed-path inspection without workspace registration", "instant", ()),
    ("query_experiments", "Experiment lookup", "indexed", ()),
    ("compare_experiments", "Server-side experiment comparison", "indexed", ("query_experiments",)),
    ("request_analysis", "Asynchronous Codex synthesis", "codex", ("get_job",)),
    ("get_job", "Analysis progress and result", "instant", ()),
    ("collab_run", "Submit background collaboration (consumes the selected model's quota)", "instant", ("collab_status", "collab_result")),
    ("collab_reply", "Continue background collaboration (consumes the selected model's quota)", "instant", ("collab_status", "collab_result")),
    ("collab_status", "Collaboration progress", "instant", ()),
    ("collab_result", "Collaboration result", "instant", ()),
    ("collab_wait", "Collaboration status with up to 30 seconds of waiting", "instant", ()),
    ("collab_cancel", "Cancel collaboration", "instant", ()),
    ("collab_jobs", "Collaboration job list", "instant", ()),
)
ALWAYS_ENABLED = {"list_workspaces", "get_job"}
WORKER_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
WORKER_EFFORTS = {
    "gpt-5.6-sol": ("low", "medium", "high", "xhigh", "max", "ultra"),
    "gpt-5.6-terra": ("low", "medium", "high", "xhigh", "max", "ultra"),
    "gpt-5.6-luna": ("low", "medium", "high", "xhigh", "max"),
}
ASSET_LABELS = {
    "project_docs": ("项目说明", "论文、README 与设计文档"),
    "source_code": ("代码", "模型实现、脚本与测试"),
    "configuration": ("配置", "实验参数与运行配置"),
    "experiment_run": ("实验结果", "可比较的运行摘要与指标"),
    "research_state": ("研究记录", "研究目标、证据、决策与待办"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_home() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "labcontext"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def admin_token_file() -> Path:
    return Path(os.environ.get("LABCTX_ADMIN_TOKEN_FILE", str(_state_home() / "admin.token"))).expanduser()


def ensure_admin_token() -> str:
    path = admin_token_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        path.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


class RuntimeState:
    def __init__(self, config: ServerConfig):
        self._lock = threading.RLock()
        self._config = config
        self._policy_path = _state_home() / "tool-policy.json"
        self._token = ensure_admin_token()

    @property
    def token(self) -> str:
        return self._token

    def config(self) -> ServerConfig:
        with self._lock:
            return self._config

    def reload(self) -> ServerConfig:
        candidate = load_config(self._config.config_path)
        with self._lock:
            self._config = candidate
        return candidate

    def policy(self) -> dict[str, Any]:
        default = {"profile": "research", "disabled_tools": []}
        try:
            value = json.loads(self._policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        disabled = sorted({str(item) for item in value.get("disabled_tools", [])} - ALWAYS_ENABLED)
        return {"profile": str(value.get("profile", "custom")), "disabled_tools": disabled}

    def set_policy(self, profile: str, disabled_tools: list[str]) -> dict[str, Any]:
        known = {item[0] for item in PUBLIC_TOOLS}
        unknown = set(disabled_tools) - known
        if unknown:
            raise ValueError(f"unknown tools: {', '.join(sorted(unknown))}")
        value = {"profile": profile[:40] or "custom", "disabled_tools": sorted(set(disabled_tools) - ALWAYS_ENABLED)}
        temporary = self._policy_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self._policy_path)
        return self.policy()

    def enforce(self, tool_name: str) -> None:
        if tool_name in self.policy()["disabled_tools"]:
            raise ValueError(f"tool_disabled_by_policy: {tool_name}")

    def _mutate_config(self, mutate: Any) -> ServerConfig:
        path = self._config.config_path
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
        mutate(document)
        rendered = tomlkit.dumps(document)
        temporary = path.with_suffix(path.suffix + ".tmp")
        backup = path.with_suffix(path.suffix + ".bak")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.chmod(path.stat().st_mode & 0o777)
        load_config(temporary)
        shutil.copy2(path, backup)
        temporary.replace(path)
        try:
            return self.reload()
        except Exception:
            shutil.copy2(backup, path)
            self.reload()
            raise

    def set_default_workspace(self, workspace_id: str) -> ServerConfig:
        resolve_workspace(self.config(), workspace_id)
        return self._mutate_config(lambda doc: doc["registry"].__setitem__("default_workspace", workspace_id))

    def upsert_workspace(self, payload: dict[str, Any]) -> tuple[ServerConfig, str]:
        root = Path(str(payload.get("root", ""))).expanduser().resolve()
        current = self.config()
        if not root.is_dir() or not any(root == allowed or root.is_relative_to(allowed) for allowed in current.registry_allowed_roots):
            raise ValueError("workspace root must be an existing directory below registry.allowed_roots")
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("workspace name is required")
        workspace_id = str(payload.get("workspace_id", "")).strip() or _workspace_id(name, root, set(current.workspaces))
        if not all(ch.isalnum() or ch in "_-" for ch in workspace_id):
            raise ValueError("workspace_id must contain only letters, digits, _ or -")
        raw_assets = payload.get("assets", [])
        if not isinstance(raw_assets, list):
            raise ValueError("assets must be a list")
        auto_assets, auto_adapters = _detect_workspace_assets(root)
        if not raw_assets:
            raw_assets = auto_assets
        context_relative = str(payload.get("context_file") or ".labcontext/context.yaml")
        context_path = (root / context_relative).resolve()
        if not context_path.is_relative_to(root):
            raise ValueError("workspace context file must remain below workspace root")

        def mutate(doc: Any) -> None:
            table = tomlkit.table()
            table["name"] = name[:120]
            table["root"] = str(root)
            table["context_file"] = context_relative
            table["aliases"] = [str(item) for item in payload.get("aliases", [])][:20]
            table["adapters"] = [str(item) for item in payload.get("adapters") or auto_adapters][:20]
            assets = tomlkit.aot()
            for index, item in enumerate(raw_assets[:20]):
                asset = tomlkit.table()
                asset["id"] = str(item.get("id") or f"asset-{index + 1}")
                asset["kind"] = str(item.get("kind") or "project_docs")
                asset["include"] = [str(pattern) for pattern in item.get("include", ["**/*"])][:30]
                asset["exclude"] = [str(pattern) for pattern in item.get("exclude", [])][:30]
                asset["adapter"] = str(item.get("adapter") or "generic")
                asset["authority"] = str(item.get("authority") or "observed_artifact")
                asset["index_content"] = str(item.get("index_content") or "metadata")
                asset["allow_codex"] = bool(item.get("allow_codex", True))
                assets.append(asset)
            table["assets"] = assets
            doc["workspaces"][workspace_id] = table

        if not context_path.exists():
            _write_workspace_context(context_path, name, _derive_workspace_overview(root, name), {
                "schema_version": 1,
                "name": name,
                "overview": _derive_workspace_overview(root, name),
                "updated_at": utc_now(),
                "authority": "provisional",
                "generation": {"status": "not_started"},
            })
        return self._mutate_config(mutate), workspace_id

    def set_workspace_overview(self, workspace_id: str, overview: str) -> dict[str, Any]:
        workspace = resolve_workspace(self.config(), workspace_id)
        normalized = " ".join(str(overview).split()).strip()
        if not normalized or len(normalized) > 1200:
            raise ValueError("overview must contain 1 to 1200 characters")
        existing: dict[str, Any] = {}
        if workspace.context_file.is_file():
            try:
                loaded = yaml.safe_load(workspace.context_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, yaml.YAMLError):
                pass
        existing.update({"schema_version": 1, "name": workspace.name, "overview": normalized,
                         "updated_at": utc_now(), "authority": "user_reviewed",
                         "generation": {"status": "manual"}})
        _write_workspace_context(workspace.context_file, workspace.name, normalized, existing)
        return {"ok": True, "workspace_id": workspace.workspace_id, "overview": normalized,
                "context_file": str(workspace.context_file)}

    def delete_workspace(self, workspace_id: str) -> dict[str, Any]:
        config = self.config()
        workspace = resolve_workspace(config, workspace_id)
        if workspace.workspace_id == config.default_workspace_id:
            raise ValueError("default workspace cannot be deleted; choose another default first")

        def mutate(doc: Any) -> None:
            del doc["workspaces"][workspace.workspace_id]

        self._mutate_config(mutate)
        return {
            "ok": True,
            "workspace_id": workspace.workspace_id,
            "removed_from_registry": True,
            "project_files_deleted": False,
        }

    def generate_workspace_overview(self, workspace_id: str, refresh: bool = False) -> dict[str, Any]:
        workspace = resolve_workspace(self.config(), workspace_id)
        existing = _read_context_path(workspace.context_file)
        generation = existing.get("generation")
        if not refresh and isinstance(generation, dict):
            existing_job_id = str(generation.get("job_id") or "")
            if generation.get("status") == "completed":
                return {"workspace_id": workspace.workspace_id, "job_id": existing_job_id,
                        "status": "completed", "progress": "completed",
                        "overview": str(existing.get("overview") or ""),
                        "context_file": str(workspace.context_file), "cached": True}
            if generation.get("status") == "running" and existing_job_id:
                finalized = _finalize_overview_job(self.config(), workspace.workspace_id, existing_job_id)
                if finalized and finalized.get("status") != "not_found":
                    return finalized
        question = (
            "Create the canonical introductory overview for this research workspace. "
            "Inspect a small number of high-signal project files such as README, project instructions, "
            "research state, configuration entry points and recent experiment summaries. Also use the "
            "latest matching Codex CLI session as working context, but do not present its unsupported "
            "claims as verified facts. Put a self-contained 2-4 sentence Chinese project overview in "
            "objective, covering the research goal, main technical object, current stage and most useful "
            "recent direction. Keep current_status concise and evidence-grounded."
        )
        result = request_summary(
            self.config(), workspace.workspace_id, force=refresh, question=question,
            include_latest_session=True,
        )
        job_id = str(result.get("job_id") or "")
        if job_id:
            _mark_overview_generation(workspace, job_id, "running", self.config())
        finalized = _finalize_overview_job(self.config(), workspace.workspace_id, job_id)
        return finalized or {
            "workspace_id": workspace.workspace_id,
            "job_id": job_id,
            "status": result.get("status", "running"),
            "progress": result.get("progress", "queued"),
            "model": self.config().summarizer_model,
            "reasoning_effort": self.config().summarizer_reasoning_effort,
        }

    def set_worker_config(self, model: str, reasoning_effort: str) -> dict[str, Any]:
        model = str(model).strip()
        reasoning_effort = str(reasoning_effort).strip().lower()
        if model not in WORKER_MODELS:
            raise ValueError(f"unsupported worker model: {model}")
        if reasoning_effort not in WORKER_EFFORTS[model]:
            raise ValueError(f"unsupported reasoning effort for {model}: {reasoning_effort}")
        def mutate(doc: Any) -> None:
            doc["summarizer"]["model"] = model
            doc["summarizer"]["reasoning_effort"] = reasoning_effort
        self._mutate_config(mutate)
        return worker_config(self)


def _workspace_id(name: str, root: Path, existing: set[str]) -> str:
    def slug(value: str) -> str:
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.casefold())).strip("-")
    base = slug(name) or slug(root.name) or "workspace"
    candidate, suffix = base[:48], 2
    while candidate in existing:
        candidate = f"{base[:44]}-{suffix}"
        suffix += 1
    return candidate


def _derive_workspace_overview(root: Path, name: str) -> str:
    readmes = [root / "README.md", root / "README.rst", root / "README.txt", root / "README"]
    for path in readmes:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:160]
        except OSError:
            continue
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                continue
            if stripped.startswith(("#", "![", "[![", "<", "```", "---", "===")):
                continue
            current.append(re.sub(r"[*_`]", "", stripped))
        if current:
            paragraphs.append(" ".join(current))
        for paragraph in paragraphs:
            if 24 <= len(paragraph) <= 1200:
                return paragraph[:500]
    return f"{name} 科研工作区。LabContext 已自动识别其中可用的代码、文档、配置、实验结果和研究记录；请编辑这段概述以补充研究目标与当前阶段。"


def _write_workspace_context(path: Path, name: str, overview: str, value: dict[str, Any] | None = None) -> None:
    payload = value or {"schema_version": 1, "name": name, "overview": overview,
                        "updated_at": utc_now(), "authority": "auto_generated"}
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    backup = path.with_suffix(path.suffix + ".bak")
    temporary.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if path.exists():
        shutil.copy2(path, backup)
    temporary.replace(path)


def _read_context_path(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _mark_overview_generation(
    workspace: Any, job_id: str, status: str, config: ServerConfig,
    error: str | None = None,
) -> None:
    existing = _read_context_path(workspace.context_file)
    existing.update({
        "schema_version": 1,
        "name": workspace.name,
        "overview": str(existing.get("overview") or _derive_workspace_overview(workspace.root, workspace.name)),
        "updated_at": str(existing.get("updated_at") or utc_now()),
    })
    existing["generation"] = {
        "status": status,
        "job_id": job_id,
        "model": config.summarizer_model,
        "reasoning_effort": config.summarizer_reasoning_effort,
        **({"error": error[:500]} if error else {}),
    }
    _write_workspace_context(workspace.context_file, workspace.name, existing["overview"], existing)


def _finalize_overview_job(
    config: ServerConfig, workspace_id: str, job_id: str,
) -> dict[str, Any] | None:
    if not job_id:
        return None
    workspace = resolve_workspace(config, workspace_id)
    _ensure_tables(config)
    with _connect(config) as connection:
        row = connection.execute(
            "SELECT status,progress,summary_json,error FROM analysis_jobs WHERE workspace_id=? AND job_id=?",
            (workspace.workspace_id, job_id),
        ).fetchone()
    if row is None:
        return {"workspace_id": workspace.workspace_id, "job_id": job_id, "status": "not_found"}
    if row["status"] == "running":
        return {"workspace_id": workspace.workspace_id, "job_id": job_id,
                "status": "running", "progress": row["progress"]}
    if row["status"] != "ready":
        message = "Codex worker failed to generate the workspace overview"
        try:
            parsed_error = json.loads(row["error"] or "{}")
            message = str(parsed_error.get("message") or message)
        except json.JSONDecodeError:
            pass
        _mark_overview_generation(workspace, job_id, "failed", config, message)
        return {"workspace_id": workspace.workspace_id, "job_id": job_id,
                "status": "failed", "progress": row["progress"], "error": message}

    payload = json.loads(row["summary_json"])
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        raise ValueError("Codex overview job returned no structured summary")
    overview = " ".join(str(summary.get("objective") or "").split()).strip()
    if not overview:
        raise ValueError("Codex overview job returned an empty overview")
    overview = overview[:1200]
    session = summary.get("latest_codex_session")
    generator = {
        "type": "codex_analysis_worker",
        "model": config.summarizer_model,
        "reasoning_effort": config.summarizer_reasoning_effort,
        "job_id": job_id,
        "latest_session_id": session.get("session_id") if isinstance(session, dict) else None,
        "evidence_refs": list(summary.get("evidence_refs") or [])[:20],
    }
    context = {
        "schema_version": 1,
        "name": workspace.name,
        "overview": overview,
        "research_goal": str(summary.get("objective") or "")[:1200],
        "current_stage": str(summary.get("current_status") or "")[:2000],
        "recent_work": [str(item)[:600] for item in list(summary.get("recent_experiment_facts") or [])[:8]],
        "open_questions": [str(item)[:500] for item in list(summary.get("open_questions") or [])[:8]],
        "updated_at": utc_now(),
        "authority": "codex_generated",
        "generator": generator,
        "generation": {"status": "completed", "job_id": job_id},
    }
    _write_workspace_context(workspace.context_file, workspace.name, overview, context)
    return {"workspace_id": workspace.workspace_id, "job_id": job_id, "status": "completed",
            "progress": "completed", "overview": overview, "context_file": str(workspace.context_file)}


def _finalize_pending_overviews(config: ServerConfig) -> None:
    for workspace in config.workspaces.values():
        context = _read_context_path(workspace.context_file)
        generation = context.get("generation")
        if not isinstance(generation, dict) or generation.get("status") != "running":
            continue
        job_id = str(generation.get("job_id") or "")
        try:
            _finalize_overview_job(config, workspace.workspace_id, job_id)
        except (ValueError, OSError, json.JSONDecodeError):
            continue


def _detect_workspace_assets(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    candidates = [
        ("docs", "project_docs", ["README*", "docs/**/*", "paper/**/*"], "markdown", "text"),
        ("code", "source_code", ["src/**/*", "scripts/**/*", "tests/**/*", "*/src/**/*", "*/scripts/**/*", "*/tests/**/*"], "generic_code", "text"),
        ("configs", "configuration", ["configs/**/*", "schemas/**/*", "*/configs/**/*", "*/schemas/**/*", "*.toml", "*.yaml", "*.yml"], "structured_files", "text"),
        ("experiments", "experiment_run", ["runs/*/summary.json", "logs/*/summary.json", "results/*/summary.json", "outputs/*/summary.json", "*/runs/*/summary.json", "*/logs/*/summary.json", "*/results/*/summary.json", "*/outputs/*/summary.json"], "generic_experiments", "metrics"),
        ("research", "research_state", ["research/idea_runs/*/run_state.json", "research/idea_runs/*/research_contract.json", "research/idea_runs/*/claim_evidence.json", "research/idea_runs/*/decision.json", "research/idea_runs/*/experiment_journal.jsonl"], "research_dossier", "structured"),
    ]
    assets: list[dict[str, Any]] = []
    adapters = ["generic"]
    for asset_id, kind, patterns, adapter, index_content in candidates:
        found = any(next(root.glob(pattern), None) is not None for pattern in patterns)
        if not found:
            continue
        assets.append({"id": asset_id, "kind": kind, "include": patterns, "adapter": adapter,
                       "authority": "canonical_fact" if kind == "research_state" else "observed_artifact",
                       "index_content": index_content, "allow_codex": True})
        if adapter in {"generic_experiments", "research_dossier"}:
            adapters.append(adapter)
    return assets, adapters


def _asset_coverage(config: ServerConfig, workspace: Any, asset: Any) -> dict[str, Any]:
    files: set[Path] = set()
    total_bytes = 0
    truncated = False
    error = None
    try:
        for pattern in asset.include:
            for path in workspace.root.glob(pattern):
                if len(files) >= 5000:
                    truncated = True
                    break
                if not path.is_file():
                    continue
                relative = path.relative_to(workspace.root).as_posix()
                if any(fnmatch.fnmatch(relative, excluded) for excluded in asset.exclude):
                    continue
                files.add(path)
            if truncated:
                break
        for path in files:
            total_bytes += path.stat().st_size
    except OSError as exc:
        error = str(exc)[:200]
    newest = max((path.stat().st_mtime for path in files), default=None)
    return {
        "asset_id": asset.asset_id, "kind": asset.kind, "authority": asset.authority,
        "index_content": asset.index_content, "include": list(asset.include), "exclude": list(asset.exclude),
        "file_count": len(files), "total_bytes": total_bytes, "truncated": truncated,
        "newest_modified_at": datetime.fromtimestamp(newest, timezone.utc).isoformat() if newest else None,
        "status": "error" if error else "empty" if not files else "ready", "error": error,
    }


def workspace_cards(config: ServerConfig) -> list[dict[str, Any]]:
    cards = []
    for workspace in config.workspaces.values():
        coverages = [_asset_coverage(config, workspace, asset) for asset in _inferred_assets(workspace)]
        context = _read_workspace_context(workspace)
        context_status = "ready" if workspace.context_file.is_file() else "missing"
        overview = str(context.get("overview") or context.get("summary") or context.get("objective") or "").strip()
        authority = str(context.get("authority") or "")
        overview_source = (
            "reviewed" if authority == "user_reviewed" else
            "codex" if authority == "codex_generated" else
            "automatic"
        )
        if not overview:
            overview = _derive_workspace_overview(workspace.root, workspace.name)
        try:
            map_value = load_research_map(config, workspace.workspace_id)
            map_summary = focus_capsule(map_value)
            proposals = list_map_proposals(config, workspace.workspace_id)["proposals"]
            map_summary["pending_proposals"] = sum(item["status"] in {"pending", "generating"} for item in proposals)
        except (ValueError, OSError, sqlite3.Error) as error:
            map_summary = {"status": "error", "error": str(error)[:200], "map_revision": 0,
                           "pending_proposals": 0}
        readable_assets = []
        for item in coverages:
            label, meaning = ASSET_LABELS.get(item["kind"], (item["kind"], "已配置的工作区内容"))
            readable_assets.append({"kind": item["kind"], "label": label, "meaning": meaning,
                                    "file_count": item["file_count"], "status": item["status"],
                                    "newest_modified_at": item["newest_modified_at"]})
        cards.append({
            "workspace_id": workspace.workspace_id, "name": workspace.name, "root": str(workspace.root),
            "aliases": list(workspace.aliases), "adapters": list(workspace.adapters),
            "is_default": workspace.workspace_id == config.default_workspace_id,
            "status": "ready" if workspace.root.is_dir() else "unavailable", "git": git_state(workspace),
            "description": overview, "overview_source": overview_source,
            "context": {"path": str(workspace.context_file.relative_to(workspace.root)), "status": context_status,
                        "generation": context.get("generation") if isinstance(context.get("generation"), dict) else None},
            "assets": coverages, "readable_assets": readable_assets,
            "research_map": map_summary,
            "coverage": {"file_count": sum(item["file_count"] for item in coverages),
                         "total_bytes": sum(item["total_bytes"] for item in coverages),
                         "empty_assets": sum(item["status"] == "empty" for item in coverages)},
        })
    return cards


def _read_workspace_context(workspace: Any) -> dict[str, Any]:
    if not workspace.context_file.is_file():
        return {}
    try:
        value = yaml.safe_load(workspace.context_file.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def read_audit(limit: int = 100, workspace_id: str | None = None, tool: str | None = None, status: str | None = None) -> dict[str, Any]:
    path = _state_home() / "audit.jsonl"
    records: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if workspace_id and record.get("workspace_id") != workspace_id:
                continue
            if tool and record.get("event") != tool:
                continue
            if status and record.get("status") != status:
                continue
            records.append(record)
    records = records[-max(1, min(limit, 500)):][::-1]
    return {"records": records, "total_returned": len(records)}


def list_jobs(config: ServerConfig, limit: int = 50, workspace_id: str | None = None) -> dict[str, Any]:
    _ensure_tables(config)
    sql = "SELECT job_id,workspace_id,status,progress,started_at,updated_at,generated_at,error,summary_json FROM analysis_jobs"
    params: tuple[Any, ...] = ()
    if workspace_id:
        sql += " WHERE workspace_id=?"
        params = (workspace_id,)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params += (max(1, min(limit, 200)),)
    with _connect(config) as connection:
        rows = connection.execute(sql, params).fetchall()
    jobs = []
    for row in rows:
        error_type = None
        diagnostics = None
        if row["error"]:
            try:
                error = json.loads(row["error"])
                error_type, diagnostics = error.get("error_type"), error.get("diagnostics")
            except json.JSONDecodeError:
                error_type = "legacy_failure"
        if row["summary_json"]:
            try:
                diagnostics = json.loads(row["summary_json"]).get("analysis_diagnostics")
            except json.JSONDecodeError:
                pass
        jobs.append({
            "job_id": row["job_id"], "workspace_id": row["workspace_id"],
            "status": "completed" if row["status"] == "ready" else row["status"],
            "progress": row["progress"], "started_at": row["started_at"],
            "updated_at": row["updated_at"], "generated_at": row["generated_at"],
            "error_type": error_type, "diagnostics": diagnostics,
        })
    return {"jobs": jobs, "status_counts": dict(Counter(item["status"] for item in jobs))}


def tools_status(state: RuntimeState) -> dict[str, Any]:
    policy = state.policy()
    disabled = set(policy["disabled_tools"])
    return {"profile": policy["profile"], "tools": [
        {"name": name, "description": description, "latency_class": latency,
         "dependencies": list(dependencies), "enabled": name not in disabled,
         "read_only": name not in {"collab_run", "collab_reply", "collab_cancel"},
         "compute_cost": ("model_tokens" if name in {"collab_run", "collab_reply"}
                          else "codex_tokens" if latency == "codex" else "none")}
        for name, description, latency, dependencies in PUBLIC_TOOLS
        if not name.startswith("collab_") or getattr(state, "collaboration_available", False)
    ]}


def worker_config(state: RuntimeState) -> dict[str, Any]:
    config = state.config()
    return {
        "model": config.summarizer_model,
        "reasoning_effort": config.summarizer_reasoning_effort,
        "available_models": list(WORKER_MODELS),
        "available_efforts": {model: list(efforts) for model, efforts in WORKER_EFFORTS.items()},
        "applies_to": "new_analysis_jobs",
    }


def health_status(state: RuntimeState) -> dict[str, Any]:
    config = state.config()
    checks = []
    checks.append({"id": "labcontext", "label": "LabContext process", "status": "healthy", "detail": f"v{__version__}"})
    try:
        with _connect(config) as connection:
            connection.execute("SELECT 1").fetchone()
        db_status, db_detail = "healthy", str(config.database)
    except sqlite3.Error as exc:
        db_status, db_detail = "down", str(exc)[:200]
    checks.append({"id": "database", "label": "SQLite evidence index", "status": db_status, "detail": db_detail})
    ready = sum(workspace.root.is_dir() for workspace in config.workspaces.values())
    checks.append({"id": "workspaces", "label": "Workspace registry", "status": "healthy" if ready == len(config.workspaces) else "degraded", "detail": f"{ready}/{len(config.workspaces)} roots available"})
    codex = config.summarizer_command[0] if config.summarizer_command else ""
    codex_available = bool(codex and (Path(codex).is_file() or shutil.which(codex)))
    checks.append({"id": "codex_worker", "label": "Codex analysis worker", "status": "healthy" if codex_available else "down", "detail": f"{config.summarizer_model} / {config.summarizer_reasoning_effort}"})
    audit = read_audit(limit=1)["records"]
    recent_inbound = False
    if audit:
        try:
            observed_at = datetime.fromisoformat(str(audit[0].get("timestamp")))
            recent_inbound = (datetime.now(timezone.utc) - observed_at).total_seconds() <= 900
        except (TypeError, ValueError):
            pass
    checks.append({"id": "chatgpt_path", "label": "ChatGPT / tunnel path", "status": "healthy" if recent_inbound else "unknown", "detail": f"last inbound tool call: {audit[0].get('timestamp')}; only calls within 15 minutes prove the path" if audit else "No inbound call observed; Mac tunnel cannot be inspected from the server"})
    overall = "down" if any(item["status"] == "down" for item in checks) else "degraded" if any(item["status"] in {"degraded", "unknown"} for item in checks) else "healthy"
    return {"overall": overall, "generated_at": utc_now(), "checks": checks}


def dashboard_overview(state: RuntimeState) -> dict[str, Any]:
    config = state.config()
    _finalize_pending_overviews(config)
    return {
        "version": __version__, "generated_at": utc_now(), "default_workspace_id": config.default_workspace_id,
        "config_path": str(config.config_path), "admin_token_file": str(admin_token_file()),
        "health": health_status(state), "workspaces": workspace_cards(config),
        "tool_policy": tools_status(state), "worker_config": worker_config(state), "activity": read_audit(limit=40),
        "jobs": list_jobs(config, limit=30),
    }


def refresh_workspace(state: RuntimeState, workspace_id: str) -> dict[str, Any]:
    config = state.config()
    workspace = resolve_workspace(config, workspace_id)
    refresh = refresh_experiment_index(config, workspace)
    card = next(item for item in workspace_cards(config) if item["workspace_id"] == workspace.workspace_id)
    return {"workspace_id": workspace.workspace_id, "experiment_index": refresh, "workspace": card}


def test_model_tool(state: RuntimeState, tool_name: str, workspace_id: str | None = None) -> dict[str, Any]:
    from .context import list_workspaces_data, research_context_data, workspace_overview_data
    operations = {
        "list_workspaces": lambda config: list_workspaces_data(config),
        "workspace_overview": lambda config: workspace_overview_data(config, workspace_id),
        "research_context": lambda config: research_context_data(config, workspace_id, "active", None),
    }
    if tool_name not in operations:
        raise ValueError("admin test supports list_workspaces, workspace_overview, or research_context")
    state.enforce(tool_name)
    started = time.monotonic()
    result = operations[tool_name](state.config())
    encoded = json.dumps(result, ensure_ascii=False).encode()
    return {
        "tool": tool_name, "input": {"workspace_id": workspace_id}, "result": result,
        "response_bytes": len(encoded), "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "tested_at": utc_now(),
    }
