"""Optional facade stays absent unless explicitly enabled by the local CLI."""
import asyncio
import json
import sys
from unittest import mock
import pytest

from fastmcp import FastMCP
from labcontext.collaboration import register_collaboration


def test_missing_cli_keeps_original_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_COLLAB_BIN", str(tmp_path / "missing"))
    mcp = FastMCP("test")
    register_collaboration(mcp)
    assert not asyncio.run(mcp.get_tools())


def test_disabled_bridge_keeps_original_tools(monkeypatch, tmp_path):
    exe = tmp_path / "bridge"
    exe.write_text(f"#!{sys.executable}\nprint('{{\"ok\": false}}')\n")
    exe.chmod(0o700)
    monkeypatch.setenv("AI_COLLAB_BIN", str(exe))
    mcp = FastMCP("test")
    register_collaboration(mcp)
    assert not asyncio.run(mcp.get_tools())


def test_tools_forward_structured_arguments(monkeypatch, tmp_path):
    exe = tmp_path / "bridge"
    captured = tmp_path / "request.json"
    exe.write_text(f"""#!{sys.executable}
import json,sys,pathlib
value=json.load(sys.stdin)
pathlib.Path({str(captured)!r}).write_text(json.dumps(value))
print(json.dumps({{"ok":True,"data":{{"tools":[{{"name":"collab_run"}}]}}}}))
""")
    exe.chmod(0o700)
    monkeypatch.setenv("AI_COLLAB_BIN", str(exe))
    mcp = FastMCP("test")
    register_collaboration(mcp)
    tools = asyncio.run(mcp.get_tools())
    assert len(tools) == 7
    assert tools["collab_status"].annotations.readOnlyHint
    asyncio.run(tools["collab_run"].run({
        "model": "fixture", "prompt": "$(must remain text)", "workspace": "/project", "access": "read",
    }))
    sent = json.loads(captured.read_text())
    assert sent["operation"] == "run"
    assert sent["arguments"]["prompt"] == "$(must remain text)"
    assert sent["arguments"]["workspace"] == "/project"
    runtime = mock.Mock()
    runtime.enforce.side_effect = ValueError("tool_disabled_by_policy")
    other = FastMCP("blocked")
    register_collaboration(other, runtime)
    blocked = asyncio.run(other.get_tools())
    with pytest.raises(Exception, match="tool_disabled_by_policy"):
        asyncio.run(blocked["collab_run"].run({"model": "fixture", "prompt": "task"}))
