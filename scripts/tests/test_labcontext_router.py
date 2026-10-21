from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from labcontext import (  # noqa: E402
    cleanup_managed_remote_forward,
    probe_ssh,
    probe_ssh_remote_forward,
    process_is_labcontext_component,
    process_status,
    recovery_failure_from_diagnostics,
    recovery_preflight,
    recovery_worker,
    recover_bridge_conflict,
    ssh_command,
    stop_verified_orphan_components,
    wait_for_post_cleanup_validation,
)
from labcontext_router import (  # noqa: E402
    LabContextRouter,
    ProviderConfig,
    ROUTER_VERSION,
    RouterConfig,
    RouterError,
    RouterServer,
    UpstreamMcp,
)


class FakeLabContextHandler(BaseHTTPRequestHandler):
    workspace_id = "shared"
    source_name = "unknown"
    calls: list[dict] = []

    def reply(self, value: dict | None, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(value).encode() if value is not None else b""
        self.send_response(200)
        for key, item in (headers or {}).items():
            self.send_header(key, item)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/admin/overview":
            self.reply({"default_workspace_id": self.workspace_id, "workspaces": []})
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.calls.append(value)
        if self.path == "/admin/workspaces":
            self.reply({"ok": True, "workspace_id": "created"})
            return
        if self.path != "/mcp":
            self.send_error(404)
            return
        method = value.get("method")
        if method == "initialize":
            self.reply({
                "jsonrpc": "2.0",
                "id": value.get("id"),
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "LabContext", "version": "0.7.0"},
                },
            }, {"Mcp-Session-Id": "fake-session"})
            return
        if method == "notifications/initialized":
            self.reply(None)
            return
        if method == "tools/list":
            tools = [
                {"name": "list_workspaces", "description": "List", "inputSchema": {"type": "object", "properties": {}}},
                {"name": "workspace_overview", "description": "Overview", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}}, "required": ["workspace_id"]}},
                {"name": "get_job", "description": "Job", "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}}},
                {"name": "inspect_path", "description": "Direct path", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
                {"name": "collab_run", "description": "Run", "inputSchema": {"type": "object", "properties": {"model": {"type": "string"}}}},
                {"name": "collab_status", "description": "Status", "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}}},
            ]
            self.reply({"jsonrpc": "2.0", "id": value.get("id"), "result": {"tools": tools}})
            return
        params = value.get("params", {})
        tool = params.get("name")
        arguments = params.get("arguments", {})
        if tool == "list_workspaces":
            payload = {
                "default_workspace_id": self.workspace_id,
                "workspaces": [{"workspace_id": self.workspace_id, "name": f"{self.source_name} project"}],
            }
        elif tool == "get_job":
            payload = {"job_id": arguments.get("job_id"), "status": "completed"}
        elif tool == "inspect_path":
            payload = {"path": arguments.get("path"), "provider": self.source_name, "path_type": "file"}
        elif tool.startswith("collab_"):
            payload = {"ok": True, "data": {"id": arguments.get("job_id", "a" * 32),
                       "conversationId": "a" * 32, "parentJobId": None}}
        else:
            payload = {"workspace_id": arguments.get("workspace_id"), "provider": self.source_name}
        result = {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "structuredContent": payload,
        }
        self.reply({"jsonrpc": "2.0", "id": value.get("id"), "result": result})

    def log_message(self, *_args: object) -> None:
        pass


def start_fake(name: str) -> tuple[ThreadingHTTPServer, str]:
    handler = type(f"{name.title()}Handler", (FakeLabContextHandler,), {
        "source_name": name,
        "calls": [],
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


class RouterTest(unittest.TestCase):
    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        environment = mock.patch.dict(os.environ, {
            "LABCONTEXT_STATUS_FILE": str(Path(state.name) / "launcher.json"),
            "LABCONTEXT_ENV_FILE": str(Path(state.name) / "launcher.env"),
            "LABCONTEXT_ENABLE_TUNNEL": "0",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.local_server, local_url = start_fake("local")
        self.remote_server, remote_url = start_fake("server")
        providers = [
            ProviderConfig("local", "Local", f"{local_url}/mcp", f"{local_url}/admin"),
            ProviderConfig("server", "Server", f"{remote_url}/mcp", f"{remote_url}/admin"),
        ]
        self.router = LabContextRouter(RouterConfig(providers=providers))

    def tearDown(self) -> None:
        self.local_server.shutdown()
        self.remote_server.shutdown()
        self.local_server.server_close()
        self.remote_server.server_close()

    def test_lists_and_qualifies_workspaces_from_both_providers(self) -> None:
        result = self.router.call_tool("list_workspaces", {})
        payload = result["structuredContent"]
        self.assertEqual({item["workspace_ref"] for item in payload["workspaces"]}, {"local:shared", "server:shared"})
        self.assertEqual(payload["default_workspace_refs"], {"local": "local:shared", "server": "server:shared"})
        self.assertEqual({item["status"] for item in payload["sources"]}, {"ready"})

        local = self.router.call_tool("list_workspaces", {"source": "local"})["structuredContent"]
        self.assertEqual(local["default_workspace_id"], "shared")

    def test_initialize_reports_current_router_version(self) -> None:
        status, response, _session_id = self.router.handle_rpc({"id": 1, "method": "initialize"})
        self.assertEqual(status, 200)
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["result"]["serverInfo"]["version"], ROUTER_VERSION)

    def test_connection_management_does_not_expand_model_tool_surface(self) -> None:
        names = {tool["name"] for tool in self.router._tools()[0]}
        self.assertTrue(names.isdisjoint({"connection_check", "connections_use", "connections_snapshot", "restart", "read_secret"}))
        with self.assertRaises(RouterError):
            self.router.call_tool("connection_check", {})

    def test_connection_management_rejects_cross_origin_forms_and_rebinding(self) -> None:
        from urllib.request import Request, build_opener, ProxyHandler
        from urllib.error import HTTPError
        server = RouterServer(("127.0.0.1", 0), self.router)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = build_opener(ProxyHandler({}))
        url = f"http://127.0.0.1:{server.server_port}/api/connections/action"
        for headers in ({"Content-Type": "text/plain"}, {"Content-Type": "application/json", "Origin": "https://evil.test"},
                        {"Content-Type": "application/json", "Host": "evil.test"}):
            with self.subTest(headers=headers), self.assertRaises(HTTPError):
                opener.open(Request(url, data=b"{}", headers=headers), timeout=2)
        self.assertFalse(self.router.connections.catalog_path.exists())
        with mock.patch.object(self.router, "access_action", return_value={"phase": "queued"}):
            with opener.open(Request(url, data=b"{}", headers={"Content-Type": "application/json"}), timeout=2) as response:
                self.assertEqual(response.status, 202)
        for endpoint in ("snapshot", "verify"):
            with self.assertRaises(HTTPError) as raised:
                opener.open(Request(url.rsplit("/", 1)[0] + "/" + endpoint, data=b"{}", headers={"Content-Type": "application/json"}), timeout=2)
            self.assertEqual(raised.exception.code, 404)

    def test_old_launcher_is_not_implicitly_restarted_for_access_changes(self) -> None:
        with mock.patch.object(self.router, "_launcher_status", return_value={"status": "running", "launcherPid": os.getpid()}), \
                self.assertRaisesRegex(RouterError, "更新本机"):
            self.router.access_action({"action": "reconnect", "connectionId": "current"})

    def test_tool_schema_accepts_workspace_ref_instead_of_workspace_id(self) -> None:
        tools, _ = self.router._tools(force=True)
        schema = next(item["inputSchema"] for item in tools if item["name"] == "workspace_overview")
        self.assertNotIn("required", schema)
        self.assertIn({"required": ["workspace_ref"]}, schema["allOf"][0]["anyOf"])

    def test_direct_path_schema_requires_source_without_workspace_registration(self) -> None:
        tools, _ = self.router._tools(force=True)
        schema = next(item["inputSchema"] for item in tools if item["name"] == "inspect_path")
        self.assertEqual(set(schema["required"]), {"path", "source"})
        self.assertNotIn("workspace_ref", schema["properties"])
        result = self.router.call_tool("inspect_path", {
            "source": "server", "path": "/mnt/research/project/README.md",
        })
        self.assertEqual(result["structuredContent"]["provider"], "server")
        self.assertEqual(result["structuredContent"]["source"], "server")

    def test_requires_a_qualified_reference_for_ambiguous_ids(self) -> None:
        with self.assertRaisesRegex(RouterError, "exists in multiple providers"):
            self.router.call_tool("workspace_overview", {"workspace_id": "shared"})
        result = self.router.call_tool("workspace_overview", {"workspace_ref": "local:shared"})
        self.assertEqual(result["structuredContent"]["provider"], "local")
        self.assertEqual(result["structuredContent"]["workspace_ref"], "local:shared")
        self.assertEqual(result["structuredContent"]["source"], "local")

    def test_job_ids_keep_their_provider(self) -> None:
        result = self.router.call_tool("get_job", {"job_id": "server:job-1"})
        self.assertEqual(result["structuredContent"]["job_id"], "server:job-1")
        self.assertEqual(result["structuredContent"]["source"], "server")

    def test_collaboration_jobs_preserve_source_without_workspace_registration(self) -> None:
        tools, _ = self.router._tools(force=True)
        schema = next(t["inputSchema"] for t in tools if t["name"] == "collab_run")
        self.assertNotIn("workspace_ref", schema["properties"])
        result = self.router.call_tool("collab_run", {"source": "server", "model": "fixture"})
        task = result["structuredContent"]["data"]
        self.assertEqual(task["id"], "server:" + "a" * 32)
        result = self.router.call_tool("collab_status", {"job_id": task["id"]})
        self.assertEqual(result["structuredContent"]["data"]["id"], task["id"])
        sent = self.remote_server.RequestHandlerClass.calls[-1]
        self.assertEqual(sent["params"]["arguments"], {"job_id": "a" * 32})
        with self.assertRaises(RouterError):
            self.router.call_tool("collab_status", {"job_id": task["id"], "source": "local"})

    def test_collaboration_timeout_never_replays_submission(self) -> None:
        client = UpstreamMcp(ProviderConfig("server", "Server", "http://127.0.0.1/mcp", "http://127.0.0.1/admin"))
        client._session_id = "existing"
        with mock.patch.object(client, "_request", side_effect=RouterError("timeout")) as request, \
                mock.patch.object(client, "_initialize") as initialize:
            with self.assertRaises(RouterError):
                client.call("tools/call", {"name": "collab_run", "arguments": {"prompt": "task"}})
        self.assertEqual(request.call_count, 1)
        initialize.assert_not_called()

    def test_admin_bridge_maps_web_keys(self) -> None:
        result = self.router.admin_call("local", "upsertWorkspace", {
            "workspaceId": "one",
            "nestedValue": {"someKey": True},
        })
        self.assertEqual(result, {"ok": True, "workspaceId": "created"})
        calls = self.local_server.RequestHandlerClass.calls
        self.assertEqual(calls[-1]["workspace_id"], "one")
        self.assertEqual(calls[-1]["nested_value"], {"some_key": True})

    def test_provider_probe_reports_ready(self) -> None:
        statuses = self.router.provider_status(probe=True)
        self.assertEqual([item["status"] for item in statuses], ["ready", "ready"])
        self.assertEqual([item["adminStatus"] for item in statuses], ["ready", "ready"])
        self.assertEqual([item["serverVersion"] for item in statuses], ["0.7.0", "0.7.0"])
        self.assertEqual([item["workspaceCount"] for item in statuses], [1, 1])

    def test_provider_probe_rejects_an_incompatible_identity(self) -> None:
        self.router.providers["local"].server_info = {"name": "Unexpected", "version": "9.0.0"}
        self.router.providers["local"]._session_id = "fake-session"
        statuses = self.router.provider_status(probe=True)
        self.assertEqual(statuses[0]["status"], "unavailable")
        self.assertIn("identity mismatch", statuses[0]["error"])

    def test_connection_status_requires_capability_checks_not_only_ports(self) -> None:
        with mock.patch.dict("os.environ", {"LABCONTEXT_ENABLE_TUNNEL": "0"}):
            status = self.router.connection_status()
        self.assertEqual(status["overall"], "ready")
        self.assertEqual(status["router"]["version"], ROUTER_VERSION)
        self.assertEqual(status["tunnel"]["status"], "disabled")
        self.assertEqual({item["serverName"] for item in status["providers"]}, {"LabContext"})

    def test_downstream_session_delete_is_accepted(self) -> None:
        server = RouterServer(("127.0.0.1", 0), self.router)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            from urllib.request import Request, urlopen

            request = Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                method="DELETE",
            )
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 204)
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/status", timeout=2) as response:
                status = json.loads(response.read())
                self.assertEqual(status["overall"], "ready")
                self.assertEqual(status["router"]["name"], "LabContext Router")
            with mock.patch.object(self.router, "start_recovery", return_value={
                "schemaVersion": 1, "phase": "queued", "summary": "queued",
            }):
                repair_request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/recovery/repair",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(repair_request, timeout=2) as response:
                    self.assertEqual(response.status, 202)
                    self.assertEqual(json.loads(response.read())["phase"], "queued")
        finally:
            server.shutdown()
            server.server_close()

    def test_recovery_request_starts_a_detached_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "recovery.json"
            log_path = Path(directory) / "recovery.log"
            environment = {
                "LABCONTEXT_RECOVERY_STATUS_FILE": str(status_path),
                "LABCONTEXT_RECOVERY_LOG_FILE": str(log_path),
                "LABCONTEXT_LAUNCHER_SCRIPT": str(SCRIPTS / "labcontext.py"),
                "LABCONTEXT_ENV_FILE": str(Path(directory) / "launcher.env"),
                "LABCONTEXT_ROUTER_CONFIG": str(Path(directory) / "config.toml"),
            }
            worker = mock.Mock(pid=4321)
            with mock.patch.dict(os.environ, environment, clear=False), \
                    mock.patch.object(self.router, "connection_status", return_value={"overall": "degraded"}), \
                    mock.patch("labcontext_router.subprocess.Popen", return_value=worker) as popen:
                result = self.router.start_recovery()
            self.assertEqual(result["phase"], "queued")
            self.assertEqual(result["workerPid"], 4321)
            self.assertEqual(json.loads(status_path.read_text(encoding="utf-8"))["jobId"], result["jobId"])
            self.assertIn("--repair-worker", popen.call_args.args[0])
            self.assertTrue(popen.call_args.kwargs["start_new_session"])


class LauncherTest(unittest.TestCase):
    def test_recovery_reports_remote_reverse_port_conflict(self) -> None:
        result = recovery_failure_from_diagnostics(
            "Error: remote port forwarding failed for listen port 17987",
            {"LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987"},
        )
        self.assertEqual(result["reasonCode"], "ssh_reverse_port_in_use")
        self.assertIn("17987", result["summary"])

    def test_failed_optional_component_reports_retry_state(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(23)"])
        process.wait(timeout=2)
        status = process_status(
            "SSH bridge",
            process,
            {"SSH bridge": 0},
            {"SSH bridge": 10**12},
            {"SSH bridge": 2},
        )
        self.assertEqual(status["status"], "retrying")
        self.assertEqual(status["exitCode"], 23)
        self.assertEqual(status["restartAttempts"], 2)

    def test_stale_launcher_cleanup_stops_only_verified_component_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status_path = Path(directory) / "launcher-status.json"
            status_path.write_text("{}", encoding="utf-8")
            alive = {101, 202}

            def is_alive(pid: int) -> bool:
                return pid in alive

            def kill_group(pid: int, _signal: int) -> None:
                alive.discard(pid)

            runtime = {
                "components": [
                    {"id": "local-provider", "pid": 101},
                    {"id": "router", "pid": 202},
                ],
            }
            with mock.patch("labcontext.process_is_alive", side_effect=is_alive), \
                    mock.patch("labcontext.process_is_labcontext_component", return_value=True), \
                    mock.patch("labcontext.os.killpg", side_effect=kill_group) as killpg:
                stopped = stop_verified_orphan_components(
                    Path("/tmp/config.toml"),
                    {"LABCONTEXT_STATUS_FILE": str(status_path)},
                    runtime,
                )
            self.assertTrue(stopped)
            self.assertFalse(status_path.exists())
            self.assertEqual({call.args[0] for call in killpg.call_args_list}, {101, 202})

    def test_component_identity_accepts_env_wrapped_local_provider(self) -> None:
        actual = subprocess.CompletedProcess(
            args=["ps"],
            returncode=0,
            stdout="/usr/bin/python /opt/provider/.venv/bin/labctx --config /private/provider.toml serve\n",
            stderr="",
        )
        with mock.patch("labcontext.subprocess.run", return_value=actual), \
                mock.patch("labcontext.os.getpgid", return_value=101), \
                mock.patch("labcontext.require_program", return_value="/usr/bin/env"):
            matched = process_is_labcontext_component(
                101,
                "local-provider",
                Path("/tmp/router.toml"),
                {
                    "LABCONTEXT_LOCAL_PROVIDER_COMMAND": (
                        "/usr/bin/env XDG_STATE_HOME=/private/state "
                        "/opt/provider/.venv/bin/labctx --config /private/provider.toml serve"
                    ),
                },
            )
        self.assertTrue(matched)

    def test_stale_launcher_cleanup_refuses_unverified_component(self) -> None:
        runtime = {"components": [{"id": "router", "pid": 202}]}
        with mock.patch("labcontext.process_is_alive", return_value=True), \
                mock.patch("labcontext.process_is_labcontext_component", return_value=False), \
                mock.patch("labcontext.os.killpg") as killpg:
            with self.assertRaisesRegex(SystemExit, "does not match"):
                stop_verified_orphan_components(
                    Path("/tmp/config.toml"),
                    {},
                    runtime,
                )
        killpg.assert_not_called()

    def test_init_generates_decoupled_hybrid_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            env_file = Path(directory) / "launcher.env"
            result = subprocess.run([
                sys.executable,
                str(SCRIPTS / "labcontext.py"),
                "--config", str(config),
                "--env-file", str(env_file),
                "init", "hybrid",
                "--ssh-host", "research-host",
                "--tunnel-profile", "labcontext",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            source = config.read_text(encoding="utf-8")
            self.assertIn('id = "local"', source)
            self.assertIn('id = "server"', source)
            self.assertIn("127.0.0.1:1456/mcp", source)
            self.assertIn("127.0.0.1:1455/mcp", source)
            environment = env_file.read_text(encoding="utf-8")
            self.assertIn("LABCONTEXT_ENABLE_SSH=1", environment)
            self.assertIn("LABCONTEXT_SSH_HOST=research-host", environment)

    def test_ssh_command_preserves_identity_keepalive_and_reverse_proxy(self) -> None:
        with mock.patch("labcontext.ssh_config_forwardings", return_value=(set(), set())):
            command = ssh_command({
                "LABCONTEXT_SSH_HOST": "research-host",
                "LABCONTEXT_SSH_IDENTITY_FILE": "/private/key",
                "LABCONTEXT_SSH_CONFIG_FILE": "/dev/null",
                "LABCONTEXT_SERVER_MCP_LOCAL_PORT": "1455",
                "LABCONTEXT_SERVER_MCP_REMOTE_PORT": "1455",
                "LABCONTEXT_SERVER_WEB_LOCAL_PORT": "48761",
                "LABCONTEXT_SERVER_WEB_REMOTE_PORT": "48761",
                "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
                "LABCONTEXT_LOCAL_PROXY_PORT": "7897",
            })
        self.assertIn("/private/key", command)
        self.assertIn("ServerAliveInterval=30", command)
        self.assertIn("127.0.0.1:17987:127.0.0.1:7897", command)
        self.assertIn("-T", command)
        self.assertNotIn("-N", command)
        self.assertIn("labcontext-ssh-bridge", command[-1])
        self.assertIn("ssh-bridge-17987.pid", command[-1])

    def test_ssh_command_reuses_matching_forwardings_from_alias(self) -> None:
        with mock.patch(
            "labcontext.ssh_config_forwardings",
            return_value=({"1455", "48761"}, {"17987"}),
        ):
            command = ssh_command({
                "LABCONTEXT_SSH_HOST": "research-host",
                "LABCONTEXT_SERVER_MCP_LOCAL_PORT": "1455",
                "LABCONTEXT_SERVER_MCP_REMOTE_PORT": "1455",
                "LABCONTEXT_SERVER_WEB_LOCAL_PORT": "48761",
                "LABCONTEXT_SERVER_WEB_REMOTE_PORT": "48761",
                "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
                "LABCONTEXT_LOCAL_PROXY_PORT": "7897",
            })
        self.assertNotIn("-L", command)
        self.assertNotIn("-R", command)
        self.assertEqual(command[-2], "research-host")
        self.assertIn("labcontext-ssh-bridge", command[-1])

    def test_managed_remote_cleanup_uses_clear_forwardings_and_marker(self) -> None:
        result = subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout="stopped managed LabContext bridge PID 42\n", stderr="",
        )
        with mock.patch("labcontext.subprocess.run", return_value=result) as run:
            ok, detail = cleanup_managed_remote_forward({
                "LABCONTEXT_SSH_HOST": "research-host",
                "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
            })
        self.assertTrue(ok)
        self.assertIn("PID 42", detail)
        command = run.call_args.args[0]
        self.assertIn("ClearAllForwardings=yes", command)
        self.assertIn("ssh-bridge-17987.pid", command[-1])

    def test_recovery_preflight_cleans_only_managed_remote_conflict(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.capture_doctor", side_effect=[
            (2, conflict),
            (2, conflict),
            (0, "router config: ok"),
        ]), mock.patch("labcontext.stop_running_stack", return_value=True) as stop, \
                mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(True, "stopped PID 42")) as cleanup:
            result, diagnostics, stack_stopped = recovery_preflight(
                Path("/tmp/config.toml"),
                {
                    "LABCONTEXT_SSH_HOST": "research-host",
                    "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
                },
            )
        self.assertEqual(result, 0)
        self.assertTrue(stack_stopped)
        self.assertIn("stopped PID 42", diagnostics)
        stop.assert_called_once()
        cleanup.assert_called_once()

    def test_recovery_preflight_does_not_claim_unmarked_remote_conflict(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.capture_doctor", side_effect=[
            (2, conflict),
            (2, conflict),
        ]), mock.patch("labcontext.stop_running_stack", return_value=True), \
                mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(False, "marker is absent")):
            result, diagnostics, stack_stopped = recovery_preflight(
                Path("/tmp/config.toml"),
                {
                    "LABCONTEXT_SSH_HOST": "research-host",
                    "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
                },
            )
        self.assertEqual(result, 2)
        self.assertTrue(stack_stopped)
        self.assertIn("marker is absent", diagnostics)

    def test_post_cleanup_validation_accepts_new_healthy_stack(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        config = mock.Mock(listen_addr="127.0.0.1:1460")
        with mock.patch("labcontext.capture_doctor", return_value=(2, conflict)), \
                mock.patch("labcontext.load_config", return_value=config), \
                mock.patch("labcontext.fetch_router_status", return_value={"overall": "ready"}):
            result, diagnostics = wait_for_post_cleanup_validation(
                Path("/tmp/config.toml"),
                {"LABCONTEXT_SSH_HOST": "research-host"},
            )
        self.assertEqual(result, 0)
        self.assertIn("new healthy LabContext stack took ownership", diagnostics)

    def test_post_cleanup_validation_waits_for_remote_port_release(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        config = mock.Mock(listen_addr="127.0.0.1:1460")
        with mock.patch("labcontext.capture_doctor", side_effect=[
            (2, conflict),
            (0, "router config: ok"),
        ]), mock.patch("labcontext.load_config", return_value=config), \
                mock.patch("labcontext.fetch_router_status", return_value=None), \
                mock.patch("labcontext.time.sleep") as sleep:
            result, diagnostics = wait_for_post_cleanup_validation(
                Path("/tmp/config.toml"),
                {"LABCONTEXT_SSH_HOST": "research-host"},
            )
        self.assertEqual(result, 0)
        self.assertEqual(diagnostics, "router config: ok")
        sleep.assert_called_once()

    def test_ssh_probe_disables_forwardings_and_reports_auth_failure(self) -> None:
        result = subprocess.CompletedProcess(
            args=["ssh"], returncode=255, stdout="", stderr="Permission denied (publickey).\n",
        )
        with mock.patch("labcontext.subprocess.run", return_value=result) as run:
            ok, detail = probe_ssh({"LABCONTEXT_SSH_HOST": "research-host"})
        self.assertFalse(ok)
        self.assertIn("Permission denied", detail)
        self.assertIn("ClearAllForwardings=yes", run.call_args.args[0])

    def test_reverse_forward_probe_reports_remote_port_conflict(self) -> None:
        result = subprocess.CompletedProcess(
            args=["ssh"], returncode=255, stdout="",
            stderr="Error: remote port forwarding failed for listen port 17987\n",
        )
        with mock.patch("labcontext.ssh_config_forwardings", return_value=(set(), set())), \
                mock.patch("labcontext.subprocess.run", return_value=result):
            ok, detail = probe_ssh_remote_forward({
                "LABCONTEXT_SSH_HOST": "research-host",
                "LABCONTEXT_SERVER_PROXY_REMOTE_PORT": "17987",
                "LABCONTEXT_LOCAL_PROXY_PORT": "7897",
            })
        self.assertFalse(ok)
        self.assertIn("remote port forwarding failed", detail)

    def test_automatic_bridge_recovery_cleans_and_verifies(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.probe_ssh_remote_forward", side_effect=[
            (False, conflict), (False, conflict), (True, "ok"),
        ]), mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(True, "stopped PID 42")) as cleanup, \
                mock.patch("labcontext.time.sleep"):
            ok, detail = recover_bridge_conflict({})
        self.assertTrue(ok)
        self.assertIn("PID 42", detail)
        cleanup.assert_called_once()

    def test_automatic_bridge_recovery_refuses_unmarked_conflict(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.probe_ssh_remote_forward", return_value=(False, conflict)), \
                mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(False, "marker is absent")):
            ok, detail = recover_bridge_conflict({})
        self.assertFalse(ok)
        self.assertIn("cleanup refused", detail)
        self.assertIn("marker is absent", detail)

    def test_automatic_bridge_recovery_does_not_clean_network_failure(self) -> None:
        with mock.patch("labcontext.probe_ssh_remote_forward", return_value=(False, "Connection closed")), \
                mock.patch("labcontext.cleanup_managed_remote_forward") as cleanup:
            ok, detail = recover_bridge_conflict({})
        self.assertFalse(ok)
        self.assertEqual(detail, "Connection closed")
        cleanup.assert_not_called()

    def test_automatic_bridge_recovery_reports_persistent_conflict(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.probe_ssh_remote_forward", return_value=(False, conflict)), \
                mock.patch("labcontext.cleanup_managed_remote_forward", return_value=(True, "stopped PID 42")), \
                mock.patch("labcontext.time.monotonic", side_effect=[0, 16]):
            ok, detail = recover_bridge_conflict({})
        self.assertFalse(ok)
        self.assertIn("still unavailable", detail)

    def test_automatic_bridge_recovery_never_repeatedly_evicts_sessions(self) -> None:
        conflict = "Error: remote port forwarding failed for listen port 17987"
        with mock.patch("labcontext.probe_ssh_remote_forward", return_value=(False, conflict)), \
                mock.patch("labcontext.cleanup_managed_remote_forward") as cleanup:
            ok, detail = recover_bridge_conflict({}, allow_cleanup=False)
        self.assertFalse(ok)
        self.assertIn("limit reached", detail)
        cleanup.assert_not_called()

    def test_recovery_worker_waits_for_concurrent_launcher_to_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            values = {"LABCONTEXT_RECOVERY_LOG_FILE": str(Path(directory) / "repair.log")}
            child = mock.Mock(pid=42)
            child.poll.return_value = 0
            with mock.patch("labcontext.recovery_preflight", return_value=(0, "ok", True)), \
                    mock.patch("labcontext.fetch_router_status", side_effect=[None, {"overall": "degraded"}, {"overall": "ready"}]), \
                    mock.patch("labcontext.load_config", return_value=mock.Mock(listen_addr="127.0.0.1:1460")), \
                    mock.patch("labcontext.subprocess.Popen", return_value=child), \
                    mock.patch("labcontext.time.sleep"), \
                    mock.patch("labcontext.write_recovery_status") as write:
                result = recovery_worker(Path(directory) / "config.toml", values)
            self.assertEqual(result, 0)
            self.assertEqual(write.call_args.args[1]["phase"], "succeeded")


if __name__ == "__main__":
    unittest.main()
