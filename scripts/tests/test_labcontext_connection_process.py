"""Real local processes only: never uses a user's installed launcher or secrets."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from labcontext_connections import ConnectionStore
from test_labcontext_router import start_fake


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ConnectionProcessTest(unittest.TestCase):
    def test_real_tunnel_switch_keeps_router_and_provider_alive(self):
        scripts = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider, provider_url = start_fake("local")
            self.addCleanup(provider.server_close)
            self.addCleanup(provider.shutdown)
            router_port, tunnel_port = unused_port(), unused_port()
            config = root / "config.toml"
            config.write_text(f'[router]\nlisten_addr = "127.0.0.1:{router_port}"\n[[providers]]\nid="local"\nmcp_url="{provider_url}/mcp"\n')
            client = root / "fake-tunnel"
            client.write_text((scripts / "tests/fixtures/fake_tunnel.py").read_text())
            client.chmod(0o700)
            env_file = root / "launcher.env"
            values = {"LABCONTEXT_ENABLE_SSH": "0", "LABCONTEXT_ENABLE_TUNNEL": "1",
                      "LABCONTEXT_TUNNEL_PROFILE": "old", "LABCONTEXT_TUNNEL_CLIENT": str(client),
                      "LABCONTEXT_TUNNEL_HEALTH_URL": f"http://127.0.0.1:{tunnel_port}",
                      "LABCONTEXT_STATUS_FILE": str(root / "launcher.json"), "TEST_TUNNEL_PORT": str(tunnel_port),
                      "LABCONTEXT_ENV_FILE": str(env_file), "CONTROL_PLANE_API_KEY": "offline-original-test-key"}
            env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
            original_env = env_file.read_bytes()
            secret = root / "future.env"
            secret.write_text("CONTROL_PLANE_API_KEY=offline-new-test-key\n")
            secret.chmod(0o600)
            store = ConnectionStore(values)
            store.add({"id": "next", "label": "Next", "profile": "new", "healthUrl": values["LABCONTEXT_TUNNEL_HEALTH_URL"],
                       "credentialMode": "file", "secretFile": str(secret)})
            opener = build_opener(ProxyHandler({}))
            base = f"http://127.0.0.1:{router_port}"
            def get(path):
                with opener.open(base + path, timeout=2) as response:
                    return json.loads(response.read())
            launcher = subprocess.Popen([sys.executable, str(scripts / "labcontext.py"), "--env-file", str(env_file), "--config", str(config)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                initial = None
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        initial = get("/api/status")
                        if initial["overall"] == "ready":
                            break
                    except OSError:
                        pass
                    time.sleep(0.1)
                self.assertIsNotNone(initial)
                self.assertEqual(initial["overall"], "ready")
                old_tunnel = next(item["pid"] for item in initial["launcher"]["components"] if item["id"] == "secure-mcp-tunnel")
                result = subprocess.run([sys.executable, str(scripts / "labcontext.py"), "--env-file", str(env_file),
                                         "--config", str(config), "connections", "use", "next"],
                                        capture_output=True, text=True, timeout=55)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    access = get("/api/connections")
                    if access["operation"]["phase"] in {"succeeded", "failed"}:
                        break
                    time.sleep(0.2)
                self.assertEqual(access["operation"]["phase"], "succeeded", access)
                after = get("/api/status")
                self.assertEqual(initial["router"]["pid"], after["router"]["pid"])
                self.assertEqual(launcher.pid, after["launcher"]["launcherPid"])
                self.assertEqual(after["providers"][0]["status"], "ready")
                self.assertNotEqual(old_tunnel, next(item["pid"] for item in after["launcher"]["components"] if item["id"] == "secure-mcp-tunnel"))
                self.assertEqual(access["activeId"], "next")
                self.assertNotIn("verification", access)
                self.assertEqual(env_file.read_bytes(), original_env)
                # A missing future credential at the next launch must not take
                # project services down, nor fall back to the original API key.
                launcher.terminate()
                launcher.wait(timeout=10)
                secret.unlink()
                launcher = subprocess.Popen([sys.executable, str(scripts / "labcontext.py"), "--env-file", str(env_file), "--config", str(config)],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        recovered = get("/api/status")
                        if recovered["launcher"]["launcherPid"] == launcher.pid:
                            break
                    except (OSError, KeyError):
                        pass
                    time.sleep(0.1)
                self.assertIsNone(launcher.poll())
                self.assertEqual(recovered["providers"][0]["status"], "ready")
                self.assertEqual(recovered["tunnel"]["status"], "unavailable")
                self.assertTrue(get("/api/connections")["canReconnect"])
                self.assertFalse(any(item["id"] == "secure-mcp-tunnel" for item in recovered["launcher"]["components"]))
            finally:
                launcher.terminate()
                try:
                    launcher.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    launcher.kill()
                    launcher.wait()

    def test_install_copies_all_modules_without_running_services(self):
        scripts = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["bash", str(scripts / "install-labcontext.sh")], check=True, capture_output=True,
                           env={**os.environ, "LABCONTEXT_INSTALL_ROOT": str(root / "lib"), "LABCONTEXT_BIN_DIR": str(root / "bin")})
            result = subprocess.run([str(root / "bin/labcontext"), "connections", "--help"], check=True, capture_output=True, text=True)
            self.assertIn("snapshot", result.stdout)
            self.assertIn("reconnect", result.stdout)
