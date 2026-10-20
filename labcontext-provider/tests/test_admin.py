from pathlib import Path

from labcontext.admin import RuntimeState, test_model_tool as run_model_tool, tools_status
from labcontext.config import load_config


def make_config(tmp_path: Path) -> Path:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    config = tmp_path / "labcontext.toml"
    config.write_text(f'''[server]
host = "127.0.0.1"
port = 1455
path = "/mcp"

[project]
id = "first"
root = "{first}"
allowed_roots = ["."]
denied_globs = ["**/.env"]

[registry]
default_workspace = "first"
allowed_roots = ["{tmp_path}"]

[limits]
max_response_bytes = 12000

[storage]
database = "{tmp_path / 'state/index.db'}"
manifest_dir = "{tmp_path / 'state/manifests'}"
ingest_roots = []

[workspaces.first]
name = "First"
root = "{first}"
adapters = ["generic"]

[summarizer]
command = ["echo"]
timeout_seconds = 1
max_context_bytes = 100
''', encoding="utf-8")
    return config


def test_runtime_applies_default_workspace_and_tool_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "runtime"))
    state = RuntimeState(load_config(make_config(tmp_path)))
    state.upsert_workspace({"workspace_id": "second", "name": "Second", "root": str(tmp_path / "second")})
    state.set_default_workspace("second")
    assert state.config().default_workspace_id == "second"
    assert "second" in load_config(state.config().config_path).workspaces
    state.set_policy("fast", ["request_analysis", "get_job"])
    assert not any(item["name"].startswith("collab_") for item in tools_status(state)["tools"])
    state.collaboration_available = True
    tools = {item["name"]: item for item in tools_status(state)["tools"]}
    assert tools["collab_run"]["read_only"] is False
    assert tools["collab_run"]["compute_cost"] == "model_tokens"
    assert tools["collab_status"]["read_only"] is True
    assert tools["collab_status"]["compute_cost"] == "none"
    assert not tools["request_analysis"]["enabled"]
    assert tools["get_job"]["enabled"]
    generated = tmp_path / "second" / ".labcontext" / "context.yaml"
    assert generated.is_file()
    assert "Second 科研工作区" in generated.read_text(encoding="utf-8")


def test_workspace_id_assets_and_editable_overview_are_automatic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "runtime"))
    config = make_config(tmp_path)
    root = tmp_path / "second"
    (root / "src").mkdir()
    (root / "src" / "model.py").write_text("pass\n", encoding="utf-8")
    (root / "README.md").write_text("# Project\n\nA direct project explanation for researchers.\n", encoding="utf-8")
    state = RuntimeState(load_config(config))
    _, workspace_id = state.upsert_workspace({"name": "My Research", "root": str(root)})
    assert workspace_id == "my-research"
    workspace = state.config().workspaces["my-research"]
    assert {asset.kind for asset in workspace.assets} >= {"project_docs", "source_code"}
    assert "A direct project explanation" in workspace.context_file.read_text(encoding="utf-8")
    state.set_workspace_overview("my-research", "A manually reviewed project overview.")
    assert "A manually reviewed project overview" in workspace.context_file.read_text(encoding="utf-8")


def test_workspace_overview_generation_and_safe_registry_delete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "runtime"))
    state = RuntimeState(load_config(make_config(tmp_path)))
    _, workspace_id = state.upsert_workspace({"name": "Second", "root": str(tmp_path / "second")})
    monkeypatch.setattr("labcontext.admin.request_summary", lambda *args, **kwargs: {
        "workspace_id": workspace_id, "status": "running", "job_id": "ws_overview_test", "progress": "queued",
    })
    generated = state.generate_workspace_overview(workspace_id)
    assert generated["status"] == "not_found" or generated["status"] == "running"
    context = state.config().workspaces[workspace_id].context_file.read_text(encoding="utf-8")
    assert "ws_overview_test" in context
    assert "status: running" in context
    deleted = state.delete_workspace(workspace_id)
    assert deleted["project_files_deleted"] is False
    assert (tmp_path / "second").is_dir()
    assert workspace_id not in state.config().workspaces


def test_admin_tool_test_returns_model_facing_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "runtime"))
    state = RuntimeState(load_config(make_config(tmp_path)))
    result = run_model_tool(state, "list_workspaces")
    assert result["result"]["default_workspace_id"] == "first"
    assert result["response_bytes"] > 0


def test_worker_config_is_validated_and_hot_reloaded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "runtime"))
    state = RuntimeState(load_config(make_config(tmp_path)))
    result = state.set_worker_config("gpt-5.6-luna", "high")
    assert result["model"] == "gpt-5.6-luna"
    assert state.config().summarizer_reasoning_effort == "high"
