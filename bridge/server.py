"""
Houdini-side HTTP server for the Houdini Agent bridge.

Thin routing skeleton — all endpoint logic lives in bridge.handlers.
GUI mode runs as a background thread driven by Houdini's UI event loop.
Headless mode (hython) runs HTTP on a background thread and pumps the
main-thread queue from the calling thread.
"""

import hou
import json
import os
import signal
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from bridge.main_thread import _main_thread_processor
from bridge.handlers import POST_HANDLERS

DEFAULT_PORT = 8765

# Shared state
_server_instance = None
_headless_stop = None


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
    global _server_instance, _headless_stop

    if _server_instance is None:
        print("[houdini-agent] No server running.")
        return

    if _headless_stop is not None:
        _headless_stop.set()
        _headless_stop = None
    else:
        hou.ui.removeEventLoopCallback(_main_thread_processor)
        _server_instance.shutdown()

    _server_instance = None
    print("[houdini-agent] Server stopped.")


def serve_headless(port=DEFAULT_PORT, poll_interval=0.02):
    """Run the bridge in a hython process. Blocks until SIGINT/SIGTERM.

    Houdini's UI event loop is what marshals HTTP-thread tasks back to the
    main thread in GUI mode. In hython there is no UI loop, so the calling
    thread (the one that invoked this function — by definition the main
    thread) drives the queue itself in a poll loop.
    """
    global _server_instance, _headless_stop

    if _server_instance is not None:
        print("[houdini-agent] Server already running.")
        return

    server = HTTPServer(("127.0.0.1", port), HoudiniRequestHandler)
    _server_instance = server
    _headless_stop = threading.Event()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[houdini-agent] Bridge server (headless) on http://127.0.0.1:{port}")
    print(f"[houdini-agent] PID {os.getpid()} (SIGINT/SIGTERM to stop)")
    endpoints = ["/status"] + list(POST_HANDLERS.keys())
    print(f"[houdini-agent] Endpoints: {', '.join(endpoints)}")

    def _shutdown(signum, frame):
        if _headless_stop is not None:
            _headless_stop.set()

    prev_int = signal.signal(signal.SIGINT, _shutdown)
    prev_term = signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not _headless_stop.is_set():
            _main_thread_processor()
            time.sleep(poll_interval)
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        server.shutdown()
        _server_instance = None
        _headless_stop = None
        print("[houdini-agent] Server stopped.")
