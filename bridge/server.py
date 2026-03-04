"""
Houdini-side HTTP server for the Houdini Agent bridge.

Thin routing skeleton — all endpoint logic lives in bridge.handlers.
Runs inside Houdini as a background thread.
"""

import hou
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from bridge.main_thread import _main_thread_processor
from bridge.handlers import POST_HANDLERS

DEFAULT_PORT = 8765

# Shared state
_server_instance = None


class HoudiniRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler — routes to handler functions."""

    def log_message(self, format, *args):
        pass  # Suppress default stderr logging

    def _send_json(self, data, status_code=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self._send_json({})

    def do_GET(self):
        if self.path == "/status":
            from bridge.handlers.scene import handle_status
            data, code = handle_status({})
            self._send_json(data, code)
        else:
            self._send_json({"success": False, "error": f"Unknown endpoint: {self.path}"}, 404)

    def do_POST(self):
        try:
            body = self._read_body()
        except json.JSONDecodeError as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        handler = POST_HANDLERS.get(self.path)
        if handler:
            data, code = handler(body)
            self._send_json(data, code)
        else:
            self._send_json({"success": False, "error": f"Unknown endpoint: {self.path}"}, 404)


def start_server(port=DEFAULT_PORT):
    """Start the Houdini Agent bridge server."""
    global _server_instance

    if _server_instance is not None:
        print("[houdini-agent] Server already running.")
        return

    server = HTTPServer(("127.0.0.1", port), HoudiniRequestHandler)
    _server_instance = server

    hou.ui.addEventLoopCallback(_main_thread_processor)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[houdini-agent] Bridge server started on http://127.0.0.1:{port}")
    endpoints = ["/status"] + list(POST_HANDLERS.keys())
    print(f"[houdini-agent] Endpoints: {', '.join(endpoints)}")


def stop_server():
    """Stop the Houdini Agent bridge server."""
    global _server_instance

    if _server_instance is None:
        print("[houdini-agent] No server running.")
        return

    hou.ui.removeEventLoopCallback(_main_thread_processor)
    _server_instance.shutdown()
    _server_instance = None
    print("[houdini-agent] Server stopped.")
