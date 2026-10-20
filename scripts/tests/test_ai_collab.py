"""Offline regressions for model routing, bounded jobs and provider provenance."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from ai_collab import jobs, providers
from ai_collab.config import CollabError, atomic_json, defaults, load, resolve


class Endpoint(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def send(self, value, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        with contextlib.suppress(BrokenPipeError):
            self.wfile.write(json.dumps(value).encode())

    def do_GET(self):
        self.send({"data": [{"id": "gemini-argon", "name": "4 Argon"}]})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(request)
        text = request["messages"][0]["content"]
        if "SLOW_FIXTURE" in text:
            time.sleep(8)
        if "AUTH_FAIL_FIXTURE" in text:
            self.send({"error": "private-upstream-secret"}, 401)
            return
        model = "different-model" if "MISMATCH_FIXTURE" in text else request["model"]
        finish = "length" if "TRUNCATED_FIXTURE" in text else "stop"
        self.send({"model": model, "choices": [{"message": {"content": "fixture answer"}, "finish_reason": finish}]})


class CollaborationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = defaults()
        self.env = mock.patch.dict(os.environ, {
            "AI_COLLAB_CONFIG": str(self.root / "config.json"),
            "AI_COLLAB_STATE_DIR": str(self.root / "state"),
            "GEMINI_WEB_API_KEY": "private-test-token",
        })
        self.env.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        os.environ["GEMINI_WEB_BASE_URL"] = "http://127.0.0.1:{}/v1".format(self.server.server_port)
        self.config["geminiWeb"]["envFile"] = str(self.root / "absent.env")
        atomic_json(self.root / "config.json", self.config)
        Endpoint.calls = []
        self.submitted = []

    def tearDown(self):
        for job_id in self.submitted:
            with contextlib.suppress(Exception):
                jobs.cancel(job_id)
                jobs.wait(job_id, 5)
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def cli(self, *args):
        completed = subprocess.run([sys.executable, str(SCRIPTS / "ai_collab_cli.py")] + list(args),
                                   capture_output=True, text=True, timeout=20)
        return completed.returncode, json.loads(completed.stdout)

    def submit(self, prompt="task", timeout=10, model="gemini4"):
        value = jobs.submit(self.config, model, prompt, [], "reviewer", str(self.root), timeout)
        self.submitted.append(value["id"])
        return value["id"]

    def test_named_model_aliases_and_default_preserve_provider(self):
        for name in ("opus5.5", "Opus 5.5", "claude opus5.5", "claude-opus-5-5", "claude"):
            route = resolve(self.config, name)
            self.assertEqual((route["provider"], route["model"]), ("claude-code", "claude-opus-5-5"))
        self.assertEqual(resolve(self.config, "Gemini 4")["provider"], "gemini-web")
        with self.assertRaises(CollabError):
            resolve(self.config, "opus9.9")

    def test_unknown_model_never_submits(self):
        code, payload = self.cli("run", "--model", "opus9.9", "--prompt", "hello")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "unknown_model")
        self.assertEqual(Endpoint.calls, [])

    def test_alias_collision_leaves_original_config_unchanged(self):
        before = (self.root / "config.json").read_bytes()
        code, payload = self.cli("alias", "set", "another", "--provider", "gemini-web",
                                 "--model", "another-model", "--alias", "OPUS 5.5")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "ambiguous_alias")
        self.assertEqual((self.root / "config.json").read_bytes(), before)

    def test_new_version_and_default_do_not_change_versioned_alias(self):
        code, _ = self.cli("alias", "set", "future-opus", "--provider", "claude-code", "--model", "claude-test-new")
        self.assertEqual(code, 0)
        code, _ = self.cli("alias", "default", "claude", "future-opus")
        self.assertEqual(code, 0)
        self.assertEqual(resolve(load(), "opus5.5")["model"], "claude-opus-5-5")
        self.assertEqual(resolve(load(), "claude")["model"], "claude-test-new")

    def test_context_manifest_and_dry_run_do_not_send_requests(self):
        path = self.root / "example.py"
        path.write_text("print('ok')\n")
        value = jobs.submit(self.config, "gemini4", "review", [str(path)], "reviewer",
                            str(self.root), 10, dry_run=True)
        self.assertTrue(value["dryRun"])
        self.assertEqual(value["contextFiles"][0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(Endpoint.calls, [])
        self.assertFalse((self.root / "state/jobs").exists())

    def test_sensitive_binary_and_oversized_context_rejected(self):
        for name, content in ((".env.local", b"SECRET=x"), ("auth.json", b"{}"),
                              ("test.bin", b"\x00\xff"), ("large.txt", b"a" * (jobs.MAX_FILE + 1))):
            path = self.root / name
            path.write_bytes(content)
            with self.assertRaises(CollabError):
                jobs.snapshot_file(path)

    def test_successful_job_and_result_preserve_provenance(self):
        job_id = self.submit()
        state = jobs.wait(job_id, 10)
        self.assertEqual(state["state"], "succeeded", state)
        result = jobs.result(job_id)
        self.assertEqual(result["requestedModel"], "gemini-argon")
        self.assertEqual(result["modelIdentityEvidence"], "proxy_metadata")
        self.assertEqual(result["text"], "fixture answer")
        self.assertEqual(len(Endpoint.calls), 1)
        self.assertEqual((jobs.directory(job_id) / "input.txt").stat().st_mode & 0o077, 0)

    def test_model_mismatch_and_truncation_are_failures(self):
        for prompt, expected in (("MISMATCH_FIXTURE", "model_mismatch"), ("TRUNCATED_FIXTURE", "incomplete_response")):
            state = jobs.wait(self.submit(prompt), 10)
            self.assertEqual(state["state"], "failed")
            self.assertEqual(state["error"]["code"], expected)

    def test_upstream_error_is_redacted_and_not_retried(self):
        state = jobs.wait(self.submit("AUTH_FAIL_FIXTURE"), 10)
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["error"]["code"], "authentication_required")
        self.assertNotIn("private-upstream-secret", json.dumps(state))
        self.assertNotIn("private-test-token", json.dumps(state))
        self.assertEqual(len(Endpoint.calls), 1)

    def test_cancel_is_scoped_to_worker_and_no_result_is_accepted(self):
        job_id = self.submit("SLOW_FIXTURE")
        deadline = time.monotonic() + 3
        while not Endpoint.calls and time.monotonic() < deadline:
            time.sleep(0.05)
        jobs.cancel(job_id)
        state = jobs.wait(job_id, 5)
        self.assertEqual(state["state"], "cancelled", state)
        with self.assertRaises(CollabError):
            jobs.result(job_id)
        self.assertEqual(len(Endpoint.calls), 1)

    def test_timeout_is_terminal_without_automatic_retry(self):
        state = jobs.wait(self.submit("SLOW_FIXTURE", timeout=5), 9)
        self.assertEqual(state["state"], "timed_out", state)
        self.assertEqual(len(Endpoint.calls), 1)

    def test_claude_errors_and_mismatched_models_are_not_success(self):
        for payload in (
            {"is_error": True, "result": "failed"},
            {"subtype": "error_max_turns", "result": "partial"},
            {"result": "answer", "modelUsage": {"other-model": {}}},
        ):
            with self.assertRaises(CollabError):
                providers.parse_claude(payload, "claude-opus-5-5")
        self.assertEqual(providers.parse_claude(
            {"result": "ok", "modelUsage": {"claude-opus-5-5": {}}}, "claude-opus-5-5"
        )["reportedModels"], ["claude-opus-5-5"])

    def test_claude_command_disables_tool_execution_and_keeps_oauth_profile(self):
        module = mock.Mock()
        module.profile_env.return_value = (self.root, {"HOME": str(self.root), "PATH": os.environ["PATH"]})
        with mock.patch.object(providers, "claude_version", return_value="2.1.304"), \
                mock.patch.object(providers, "claude_account", return_value=(self.root, module, {"id": "a" * 32})):
            cmd, env, _ = providers.claude_command(self.config, resolve(self.config, "opus5.5"), "a" * 32)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("--bare", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(env["HOME"], str(self.root))
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_claude_minimum_version_is_enforced_before_call(self):
        with mock.patch.object(providers, "claude_version", return_value="2.1.278"):
            with self.assertRaises(CollabError) as caught:
                providers.claude_command(self.config, resolve(self.config, "opus5.5"), "a" * 32)
        self.assertEqual(caught.exception.code, "cli_upgrade_required")

    def test_reused_pid_is_interrupted_without_signalling_it(self):
        job_id = "a" * 32
        atomic_json(jobs.directory(job_id) / "status.json",
                    {"id": job_id, "state": "running", "createdAt": time.time(),
                     "workerPid": os.getpid(), "workerIdentity": "not-the-real-starttime"})
        self.assertEqual(jobs.status(job_id)["state"], "interrupted")
        self.assertTrue(jobs.cancel(job_id)["cancelRequested"])
        self.assertTrue((jobs.directory(job_id) / "cancel.json").is_file())

    def test_default_cannot_be_replaced_with_a_different_provider(self):
        code, payload = self.cli("alias", "set", "opus5.5", "--replace",
                                 "--provider", "gemini-web", "--model", "gemini-argon")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "provider_mismatch")
        self.assertEqual(resolve(load(), "claude")["provider"], "claude-code")

    def test_malformed_config_has_a_json_error(self):
        for invalid in ([], {"schemaVersion": 1, "models": {"bad": "string"}}):
            atomic_json(self.root / "config.json", invalid)
            code, payload = self.cli("models")
            self.assertEqual(code, 1)
            self.assertEqual(payload["error"]["code"], "invalid_config")

    def test_cancel_before_start_does_not_call_provider(self):
        with mock.patch.object(jobs.subprocess, "Popen"):
            job_id = self.submit()
        jobs.cancel(job_id)
        jobs.run_worker(job_id)
        self.assertEqual(jobs.status(job_id)["state"], "cancelled")
        self.assertEqual(Endpoint.calls, [])

    def test_successful_worker_cannot_be_replayed(self):
        job_id = self.submit()
        self.assertEqual(jobs.wait(job_id, 10)["state"], "succeeded")
        jobs.run_worker(job_id)
        self.assertEqual(len(Endpoint.calls), 1)

    def test_sigterm_worker_stops_its_provider_and_records_terminal_state(self):
        job_id = self.submit("SLOW_FIXTURE")
        deadline = time.monotonic() + 4
        while not Endpoint.calls and time.monotonic() < deadline:
            time.sleep(0.05)
        state = jobs.status(job_id)
        self.assertEqual(jobs.process_identity(state["workerPid"]), state["workerIdentity"])
        os.kill(state["workerPid"], signal.SIGTERM)
        state = jobs.wait(job_id, 5)
        self.assertEqual(state["state"], "interrupted", state)
        self.assertIsNone(jobs.process_identity(state["providerPid"]))

    def test_terminate_failure_is_bounded_and_does_not_throw(self):
        child = mock.Mock(pid=123)
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired("test", 3)
        with mock.patch.object(jobs.os, "killpg", side_effect=ProcessLookupError):
            self.assertFalse(jobs.terminate(child))
        self.assertEqual(child.wait.call_count, 2)

    def test_workspace_is_only_available_for_claude(self):
        code, payload = self.cli("run", "--model", "gemini4", "--prompt", "review", "--workspace", str(self.root))
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "workspace_not_supported")
        self.assertEqual(Endpoint.calls, [])

    def test_workspace_command_contains_native_read_boundaries(self):
        module = mock.Mock()
        module.profile_env.return_value = (self.root, {"HOME": str(self.root), "PATH": os.environ["PATH"]})
        roots = jobs.workspace_manifest([str(self.root)])
        with mock.patch.object(providers, "claude_version", return_value="2.1.304"), \
                mock.patch.object(providers, "claude_account", return_value=(self.root, module, {"id": "a" * 32})):
            cmd, _, _ = providers.claude_command(self.config, resolve(self.config, "opus5.5"), "a" * 32, roots)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(cmd[cmd.index("--add-dir") + 1], str(self.root))
        self.assertIn("--restricted", cmd)
        self.assertIn("--safe-mode", cmd)
        self.assertNotIn("Bash", cmd[cmd.index("--tools") + 1])
        settings = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertTrue(settings["permissions"]["blockReadsOutsideWorkingDirectories"])
        self.assertIn("Read(//**/.env*)", settings["permissions"]["deny"])

    def test_workspace_stream_requires_final_result_and_keeps_access_trace(self):
        event = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read",
                                                                  "input": {"file_path": "/project/main.py"}}]}}
        final = {"type": "result", "subtype": "success", "result": "review",
                 "modelUsage": {"claude-opus-5-5": {"outputTokens": 10}}}
        trace = "\n".join(json.dumps(e) for e in (event, final))
        result = providers.parse_claude_stream(trace, "claude-opus-5-5")
        self.assertEqual(result["fileAccesses"], [{"tool": "Read", "path": "/project/main.py", "status": "requested"}])
        with self.assertRaises(CollabError):
            providers.parse_claude_stream(json.dumps(event), "claude-opus-5-5")
        event["message"]["content"][0]["name"] = "Bash"
        with self.assertRaises(CollabError):
            providers.parse_claude_stream("\n".join(json.dumps(e) for e in (event, final)), "claude-opus-5-5")

    def test_missing_or_contradictory_model_identity_is_not_success(self):
        for payload in (
            {"result": "answer"},
            {"result": "answer", "model": "other", "modelUsage": {"claude-opus-5-5": {}}},
            {"result": "answer", "modelUsage": {"claude-opus-5-5": {"outputTokens": 0}, "other": {"outputTokens": 9}}},
        ):
            with self.assertRaises(CollabError):
                providers.parse_claude(payload, "claude-opus-5-5")
        with self.assertRaises(CollabError):
            providers.parse_gemini({"choices": [{"message": {"content": "text"}, "finish_reason": "stop"}]}, "gemini-argon")

    def test_followup_keeps_previous_text_exactly(self):
        job_id = self.submit()
        self.assertEqual(jobs.wait(job_id, 10)["state"], "succeeded")
        content, _ = jobs.prepare_prompt("follow up", [], "reviewer", after=job_id)
        self.assertIn("fixture answer", content)
        self.assertIn(job_id, content)

    def test_request_discovery_and_invalid_cli_are_json(self):
        code, value = self.cli("--json", "request", "--provider", "gemini-web", "--path", "/models")
        self.assertEqual(code, 0)
        self.assertEqual(value["data"]["data"][0]["id"], "gemini-argon")
        code, value = self.cli("--json", "nonexistent")
        self.assertEqual(code, 1)
        self.assertFalse(value["ok"])


if __name__ == "__main__":
    os.umask(0o077)
    unittest.main()
