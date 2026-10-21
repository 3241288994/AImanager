#!/usr/bin/env python3
"""Offline integration fixture. No OpenAI requests and no credential output."""
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

if "doctor" in sys.argv:
    # Emulate the real client's listener probe, including an occupied old
    # Tunnel port. Preflight must use an ephemeral port without stopping it.
    port = int(os.environ["TEST_TUNNEL_PORT"])
    if "--health.listen-addr" in sys.argv:
        address = sys.argv[sys.argv.index("--health.listen-addr") + 1]
        assert address == "127.0.0.1:0"
        port = 0
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(2)
    raise SystemExit(0)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def log_message(self, *_args):
        pass


HTTPServer(("127.0.0.1", int(os.environ["TEST_TUNNEL_PORT"])), Health).serve_forever()
