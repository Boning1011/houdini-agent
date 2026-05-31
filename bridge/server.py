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
import socket
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from bridge import discovery
from bridge.main_thread import _main_thread_processor
from bridge.handlers import POST_HANDLERS

DEFAULT_PORT = 8765


class _ExclusiveHTTPServer(HTTPServer):
    """HTTPServer that refuses to share a port with another process.

    Python's stock HTTPServer sets `allow_reuse_address = 1`, which turns on
    SO_REUSEADDR. On Linux that flag only affects TIME_WAIT. **On Windows it
    lets multiple processes bind the same port at the same time** — the OS
    then routes incoming connections to whichever socket it picks, with no
    error to either side. That is the actual reason two Houdini bridges can
    both claim ":8765" with no complaint: bind() succeeds for both, our
    port-fallback never triggers, and external clients hit a random instance.

    Setting SO_EXCLUSIVEADDRUSE (Windows only) before bind makes the second
    process get EADDRINUSE, which is what we wanted all along. SO_REUSEADDR
    must stay off — the two flags are mutually exclusive on the same socket.
    """
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                )
            except OSError:
                pass
        super().server_bind()

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


PORT_SEARCH_RANGE = 16


def start_server(port=DEFAULT_PORT, port_search_range=PORT_SEARCH_RANGE):
    """Start the Houdini Agent bridge server.

    If `port` is already bound (e.g. another Houdini instance is running),
    walks up to `port_search_range` consecutive ports before giving up. The
    bound port is whatever start_server() actually grabbed — read it back via
    _server_instance.server_address[1] (the panel does this).
    """
    global _server_instance

    if _server_instance is not None:
        print("[houdini-agent] Server already running.")
        return

    server = None
    bound_port = None
    last_error = None
    for offset in range(port_search_range):
        try_port = port + offset
        try:
            server = _ExclusiveHTTPServer(("127.0.0.1", try_port), HoudiniRequestHandler)
            bound_port = try_port
            break
        except OSError as e:
            last_error = e
            continue

    if server is None:
        print(f"[houdini-agent] Could not bind any port in "
              f"{port}-{port + port_search_range - 1}: {last_error}")
        return

    _server_instance = server
    hou.ui.addEventLoopCallback(_main_thread_processor)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    discovery.register(bound_port)

    if bound_port == port:
        print(f"[houdini-agent] Bridge server started on http://127.0.0.1:{bound_port}")
    else:
        print(f"[houdini-agent] Bridge server started on http://127.0.0.1:{bound_port} "
              f"(default {port} was busy)")
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

    discovery.unregister()
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

    server = None
    bound_port = None
    last_error = None
    for offset in range(PORT_SEARCH_RANGE):
        try_port = port + offset
        try:
            server = _ExclusiveHTTPServer(("127.0.0.1", try_port), HoudiniRequestHandler)
            bound_port = try_port
            break
        except OSError as e:
            last_error = e
            continue
    if server is None:
        print(f"[houdini-agent] Could not bind any port in "
              f"{port}-{port + PORT_SEARCH_RANGE - 1}: {last_error}")
        return

    _server_instance = server
    _headless_stop = threading.Event()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    discovery.register(bound_port)

    if bound_port == port:
        print(f"[houdini-agent] Bridge server (headless) on http://127.0.0.1:{bound_port}")
    else:
        print(f"[houdini-agent] Bridge server (headless) on http://127.0.0.1:{bound_port} "
              f"(default {port} was busy)")
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
        discovery.unregister()
        _server_instance = None
        _headless_stop = None
        print("[houdini-agent] Server stopped.")
