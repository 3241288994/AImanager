#!/usr/bin/env python3
"""Offline integration fixture. No OpenAI requests and no credential output."""
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

if "doctor" in sys.argv:
    raise SystemExit(0)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def log_message(self, *_args):
        pass


HTTPServer(("127.0.0.1", int(os.environ["TEST_TUNNEL_PORT"])), Health).serve_forever()
