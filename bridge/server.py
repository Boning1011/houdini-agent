"""
Houdini-side HTTP server for the Houdini Agent bridge.

Runs inside Houdini as a background thread. Receives JSON requests over HTTP,
marshals them to Houdini's main thread via hou.ui.addEventLoopCallback,
and returns JSON responses.

Usage: Execute this file in Houdini's Python Shell, or use scripts/start_server.py.
"""

import hou
import json
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue, Empty

DEFAULT_PORT = 8765

# Shared queue for main-thread execution
_request_queue = Queue()
_server_instance = None


def _main_thread_processor():
    """Event loop callback that processes queued requests on Houdini's main thread."""
    while not _request_queue.empty():
        try:
            task, result_holder, event = _request_queue.get_nowait()
            try:
                result = task()
                result_holder["status"] = "ok"
                result_holder["result"] = result
            except Exception as e:
                result_holder["status"] = "error"
                result_holder["error"] = str(e)
                result_holder["traceback"] = traceback.format_exc()
            finally:
                event.set()
        except Empty:
            break


def _run_on_main_thread(task, timeout=30):
    """Queue a callable for main-thread execution and wait for the result."""
    result_holder = {}
    event = threading.Event()
    _request_queue.put((task, result_holder, event))
    if not event.wait(timeout=timeout):
        return {"status": "error", "error": "Timed out waiting for main thread execution"}
    return result_holder


class HoudiniRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Houdini Agent bridge."""

    def log_message(self, format, *args):
        # Suppress default stderr logging
        pass

    def _send_json(self, data, status_code=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        else:
            self._send_json({"status": "error", "error": f"Unknown endpoint: {self.path}"}, 404)

    def do_POST(self):
        try:
            body = self._read_body()
        except json.JSONDecodeError as e:
            self._send_json({"status": "error", "error": f"Invalid JSON: {e}"}, 400)
            return

        handlers = {
            "/exec": self._handle_exec,
            "/query": self._handle_query,
            "/get_node_tree": self._handle_get_node_tree,
            "/get_parms": self._handle_get_parms,
            "/set_parms": self._handle_set_parms,
            "/get_attribs": self._handle_get_attribs,
            "/create_node": self._handle_create_node,
            "/delete_node": self._handle_delete_node,
        }

        handler = handlers.get(self.path)
        if handler:
            handler(body)
        else:
            self._send_json({"status": "error", "error": f"Unknown endpoint: {self.path}"}, 404)

    # --- Endpoint handlers ---

    def _handle_status(self):
        def task():
            return {
                "hip_file": hou.hipFile.path(),
                "fps": hou.fps(),
                "frame": hou.frame(),
                "frame_range": list(hou.playbar.frameRange()),
            }
        self._send_json(_run_on_main_thread(task))

    def _handle_exec(self, body):
        code = body.get("code", "")
        if not code:
            self._send_json({"status": "error", "error": "No 'code' provided"}, 400)
            return

        def task():
            local_vars = {}
            exec(code, {"hou": hou, "__builtins__": __builtins__}, local_vars)
            return local_vars.get("result", None)

        self._send_json(_run_on_main_thread(task))

    def _handle_query(self, body):
        expression = body.get("expression", "")
        if not expression:
            self._send_json({"status": "error", "error": "No 'expression' provided"}, 400)
            return

        def task():
            return eval(expression, {"hou": hou, "__builtins__": __builtins__})

        self._send_json(_run_on_main_thread(task))

    def _handle_get_node_tree(self, body):
        path = body.get("path", "/")
        depth = body.get("depth", 3)

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            return _node_to_dict(node, depth)

        self._send_json(_run_on_main_thread(task))

    def _handle_get_parms(self, body):
        path = body.get("path", "")
        if not path:
            self._send_json({"status": "error", "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            result = {}
            for parm in node.parms():
                try:
                    result[parm.name()] = parm.eval()
                except Exception:
                    result[parm.name()] = str(parm.rawValue())
            return result

        self._send_json(_run_on_main_thread(task))

    def _handle_set_parms(self, body):
        path = body.get("path", "")
        parms = body.get("parms", {})
        if not path:
            self._send_json({"status": "error", "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            for name, value in parms.items():
                parm = node.parm(name)
                if parm is None:
                    raise ValueError(f"Parameter not found: {name} on {path}")
                parm.set(value)
            return {"set": list(parms.keys())}

        self._send_json(_run_on_main_thread(task))

    def _handle_get_attribs(self, body):
        path = body.get("path", "")
        attrib_class = body.get("attrib_class", "point")
        if not path:
            self._send_json({"status": "error", "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            geo = node.geometry()
            if geo is None:
                raise ValueError(f"No geometry on node: {path}")

            class_map = {
                "point": geo.pointAttribs,
                "prim": geo.primAttribs,
                "vertex": geo.vertexAttribs,
                "detail": geo.globalAttribs,
            }
            attrib_fn = class_map.get(attrib_class)
            if attrib_fn is None:
                raise ValueError(f"Invalid attrib_class: {attrib_class}. Use: point, prim, vertex, detail")

            result = []
            for attrib in attrib_fn():
                result.append({
                    "name": attrib.name(),
                    "type": attrib.dataType().name(),
                    "size": attrib.size(),
                })
            return result

        self._send_json(_run_on_main_thread(task))

    def _handle_create_node(self, body):
        parent = body.get("parent", "/obj")
        node_type = body.get("type", "")
        name = body.get("name", None)
        if not node_type:
            self._send_json({"status": "error", "error": "No 'type' provided"}, 400)
            return

        def task():
            parent_node = hou.node(parent)
            if parent_node is None:
                raise ValueError(f"Parent node not found: {parent}")
            new_node = parent_node.createNode(node_type, name)
            return {"path": new_node.path(), "type": new_node.type().name()}

        self._send_json(_run_on_main_thread(task))

    def _handle_delete_node(self, body):
        path = body.get("path", "")
        if not path:
            self._send_json({"status": "error", "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            node.destroy()
            return {"deleted": path}

        self._send_json(_run_on_main_thread(task))


def _node_to_dict(node, depth):
    """Recursively convert a node to a dictionary representation."""
    info = {
        "path": node.path(),
        "type": node.type().name(),
        "name": node.name(),
    }
    if depth > 0 and len(node.children()) > 0:
        info["children"] = [_node_to_dict(c, depth - 1) for c in node.children()]
    return info


def start_server(port=DEFAULT_PORT):
    """Start the Houdini Agent bridge server."""
    global _server_instance

    if _server_instance is not None:
        print(f"[houdini-agent] Server already running.")
        return

    server = HTTPServer(("127.0.0.1", port), HoudiniRequestHandler)
    _server_instance = server

    # Register main-thread processor
    hou.ui.addEventLoopCallback(_main_thread_processor)

    # Run HTTP server in a daemon thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[houdini-agent] Server started on http://127.0.0.1:{port}")


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
