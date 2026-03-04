"""
Houdini-side HTTP server for the Houdini Agent bridge.

Runs inside Houdini as a background thread. Receives JSON requests over HTTP,
marshals them to Houdini's main thread via hou.ui.addEventLoopCallback,
and returns JSON responses.

Usage: Paste scripts/start_server.py into Houdini's Python Shell.
"""

import hou
import ast
import io
import json
import sys
import time as _time
import threading
import traceback
from contextlib import redirect_stdout
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue, Empty

DEFAULT_PORT = 8765

# Shared state
_request_queue = Queue()
_server_instance = None

# Persistent namespace for /exec — variables survive between calls
_exec_namespace = {"hou": hou, "__builtins__": __builtins__}

# Operation log — records mutating operations for diagnostics
_operation_log = []
_MAX_LOG_SIZE = 200


def _with_undo(label, func):
    """Wrap func in a Houdini undo group. Returns a new callable."""
    def wrapped():
        with hou.undos.group(label):
            return func()
    return wrapped


def _log_operation(endpoint, label, success):
    """Record a mutating operation in the operation log."""
    _operation_log.append({
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": endpoint,
        "label": label,
        "success": success,
    })
    if len(_operation_log) > _MAX_LOG_SIZE:
        del _operation_log[:len(_operation_log) - _MAX_LOG_SIZE]


def _main_thread_processor():
    """Event loop callback that processes queued requests on Houdini's main thread."""
    while not _request_queue.empty():
        try:
            task, result_holder, event = _request_queue.get_nowait()
            try:
                result = task()
                result_holder["value"] = result
                result_holder["ok"] = True
            except Exception as e:
                result_holder["ok"] = False
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
        return {"ok": False, "error": "Timed out waiting for main thread execution"}
    return result_holder


def _extract_last_expr(code):
    """If the last statement in code is an expression, return (setup_code, expr_code).
    Otherwise return (code, None)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, None

    if not tree.body:
        return code, None

    last = tree.body[-1]
    if isinstance(last, ast.Expr):
        # Split: everything before the last statement, and the last expression
        if len(tree.body) == 1:
            setup = ""
        else:
            # Get source lines for everything before the last statement
            lines = code.split("\n")
            setup = "\n".join(lines[: last.lineno - 1])
        expr = ast.get_source_segment(code, last.value)
        if expr is None:
            # Fallback: use the line(s) of the expression
            lines = code.split("\n")
            expr = "\n".join(lines[last.lineno - 1 :])
            # Strip any leading whitespace artifacts
            expr = expr.strip()
        return setup, expr

    return code, None


class HoudiniRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Houdini Agent bridge."""

    def log_message(self, format, *args):
        pass  # Suppress default stderr logging

    def _send_json(self, data, status_code=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # CORS headers
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
        """Handle CORS preflight requests."""
        self._send_json({})

    def do_GET(self):
        if self.path == "/status":
            self._handle_status()
        else:
            self._send_json({"success": False, "error": f"Unknown endpoint: {self.path}"}, 404)

    # Single source of truth for POST endpoints — add new handlers here
    _post_handlers = {
        "/exec": "_handle_exec",
        "/query": "_handle_query",
        "/get_node_tree": "_handle_get_node_tree",
        "/get_parms": "_handle_get_parms",
        "/set_parms": "_handle_set_parms",
        "/get_attribs": "_handle_get_attribs",
        "/attrib_info": "_handle_attrib_info",
        "/attrib_stats": "_handle_attrib_stats",
        "/attrib_values": "_handle_attrib_values",
        "/create_node": "_handle_create_node",
        "/delete_node": "_handle_delete_node",
        "/scene_snapshot": "_handle_scene_snapshot",
        "/undo_history": "_handle_undo_history",
    }

    def do_POST(self):
        try:
            body = self._read_body()
        except json.JSONDecodeError as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        method_name = self._post_handlers.get(self.path)
        if method_name:
            getattr(self, method_name)(body)
        else:
            self._send_json({"success": False, "error": f"Unknown endpoint: {self.path}"}, 404)

    # --- Endpoint handlers ---

    def _handle_status(self):
        def task():
            return {
                "connected": True,
                "hip_file": hou.hipFile.path(),
                "houdini_version": ".".join(str(x) for x in hou.applicationVersion()),
                "fps": hou.fps(),
                "frame_range": list(hou.playbar.frameRange()),
                "current_frame": hou.frame(),
            }

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json(r["value"])
        else:
            self._send_json({"connected": False, "error": r.get("error")}, 500)

    def _handle_exec(self, body):
        code = body.get("code", "")
        if not code:
            self._send_json({"success": False, "result": None, "output": "", "error": "No 'code' provided"}, 400)
            return

        def task():
            # Capture stdout
            stdout_buf = io.StringIO()
            result_value = None
            error_str = None

            setup_code, expr_code = _extract_last_expr(code)

            try:
                with redirect_stdout(stdout_buf):
                    if setup_code:
                        exec(compile(setup_code, "<bridge>", "exec"), _exec_namespace)
                    if expr_code:
                        result_value = eval(compile(expr_code, "<bridge>", "eval"), _exec_namespace)
            except Exception:
                error_str = traceback.format_exc()

            return {
                "success": error_str is None,
                "result": result_value,
                "output": stdout_buf.getvalue(),
                "error": error_str,
            }

        label = f"Agent: exec {code[:50]}"
        r = _run_on_main_thread(_with_undo(label, task))
        _log_operation("/exec", label, r.get("ok", False))
        if r.get("ok"):
            self._send_json(r["value"])
        else:
            self._send_json({
                "success": False,
                "result": None,
                "output": "",
                "error": r.get("error") or r.get("traceback", "Unknown error"),
            }, 500)

    def _handle_query(self, body):
        expression = body.get("expression", "")
        if not expression:
            self._send_json({"success": False, "error": "No 'expression' provided"}, 400)
            return

        def task():
            return eval(expression, {"hou": hou, "__builtins__": __builtins__})

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_get_node_tree(self, body):
        path = body.get("path", "/")
        depth = body.get("depth", 3)

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            return _node_to_dict(node, depth)

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_get_parms(self, body):
        path = body.get("path", "")
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
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

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_set_parms(self, body):
        path = body.get("path", "")
        parms = body.get("parms", {})
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
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

        label = f"Agent: set_parms {path}"
        r = _run_on_main_thread(_with_undo(label, task))
        _log_operation("/set_parms", label, r.get("ok", False))
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_get_attribs(self, body):
        path = body.get("path", "")
        attrib_class = body.get("attrib_class", "point")
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
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

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_attrib_info(self, body):
        """Return attribute names/types across ALL classes. No values — pure structure."""
        path = body.get("path", "")
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            geo = node.geometry()
            if geo is None:
                raise ValueError(f"No geometry on node: {path}")

            def attrib_list(attribs):
                return [{"name": a.name(), "type": a.dataType().name(), "size": a.size()} for a in attribs]

            return {
                "point_count": len(geo.points()),
                "prim_count": len(geo.prims()),
                "vertex_count": geo.intrinsicValue("vertexcount"),
                "point_attribs": attrib_list(geo.pointAttribs()),
                "prim_attribs": attrib_list(geo.primAttribs()),
                "vertex_attribs": attrib_list(geo.vertexAttribs()),
                "detail_attribs": attrib_list(geo.globalAttribs()),
            }

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_attrib_stats(self, body):
        """Compute stats (min/max/mean/samples) for specific attributes."""
        path = body.get("path", "")
        attrib_class = body.get("attrib_class", "point")
        attrib_names = body.get("attribs", None)  # None = all
        num_samples = min(body.get("samples", 5), 50)
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            geo = node.geometry()
            if geo is None:
                raise ValueError(f"No geometry on node: {path}")

            class_config = {
                "point": (geo.pointAttribs, geo.pointFloatAttribValues, geo.pointIntAttribValues, geo.pointStringAttribValues, len(geo.points())),
                "prim": (geo.primAttribs, geo.primFloatAttribValues, geo.primIntAttribValues, geo.primStringAttribValues, len(geo.prims())),
                "vertex": (geo.vertexAttribs, geo.vertexFloatAttribValues, geo.vertexIntAttribValues, geo.vertexStringAttribValues, geo.intrinsicValue("vertexcount")),
                "detail": (geo.globalAttribs, None, None, None, 1),
            }
            cfg = class_config.get(attrib_class)
            if cfg is None:
                raise ValueError(f"Invalid attrib_class: {attrib_class}. Use: point, prim, vertex, detail")

            attribs_fn, float_fn, int_fn, string_fn, elem_count = cfg

            # Filter to requested attribs
            attribs = attribs_fn()
            if attrib_names:
                name_set = set(attrib_names)
                attribs = [a for a in attribs if a.name() in name_set]

            # Compute evenly-spaced sample indices
            if elem_count <= num_samples:
                sample_indices = list(range(elem_count))
            else:
                step = (elem_count - 1) / max(num_samples - 1, 1)
                sample_indices = [int(round(i * step)) for i in range(num_samples)]

            import math

            def _scalar_stats(vals):
                """Compute min/max/mean/stddev for a flat sequence of numbers."""
                n = len(vals)
                mn = min(vals)
                mx = max(vals)
                s = sum(vals)
                mean = s / n
                # Two-pass stddev for numerical stability
                var = sum((v - mean) ** 2 for v in vals) / n
                return mn, mx, mean, math.sqrt(var)

            result = {}
            for attrib in attribs:
                name = attrib.name()
                dtype = attrib.dataType().name()
                size = attrib.size()
                info = {"type": dtype, "size": size, "count": elem_count}

                if attrib_class == "detail":
                    try:
                        info["value"] = attrib.defaultValue() if elem_count == 0 else geo.attribValue(name)
                    except Exception:
                        info["value"] = None
                    result[name] = info
                    continue

                if dtype in ("Float", "Int"):
                    vals = float_fn(name) if dtype == "Float" else int_fn(name)
                    if not vals:
                        result[name] = info
                        continue

                    if size == 1:
                        mn, mx, mean, stddev = _scalar_stats(vals)
                        info["min"] = mn
                        info["max"] = mx
                        info["mean"] = mean
                        info["stddev"] = stddev
                        info["samples"] = {
                            "indices": sample_indices,
                            "values": [vals[i] for i in sample_indices],
                        }
                    else:
                        # Component-wise stats
                        mins, maxs, means, stddevs = [], [], [], []
                        for c in range(size):
                            comp = vals[c::size]
                            mn, mx, mean, sd = _scalar_stats(comp)
                            mins.append(mn)
                            maxs.append(mx)
                            means.append(mean)
                            stddevs.append(sd)
                        info["min"] = mins
                        info["max"] = maxs
                        info["mean"] = means
                        info["stddev"] = stddevs
                        info["samples"] = {
                            "indices": sample_indices,
                            "values": [list(vals[i * size:(i + 1) * size]) for i in sample_indices],
                        }
                        # Magnitude stats for vectors (distance from origin)
                        n = elem_count
                        mag_min = float("inf")
                        mag_max = 0.0
                        mag_sum = 0.0
                        mag_sq_sum = 0.0
                        for i in range(n):
                            sq = sum(vals[i * size + c] ** 2 for c in range(size))
                            mag = math.sqrt(sq)
                            if mag < mag_min:
                                mag_min = mag
                            if mag > mag_max:
                                mag_max = mag
                            mag_sum += mag
                            mag_sq_sum += mag * mag
                        mag_mean = mag_sum / n
                        mag_var = mag_sq_sum / n - mag_mean ** 2
                        info["magnitude"] = {
                            "min": mag_min,
                            "max": mag_max,
                            "mean": mag_mean,
                            "stddev": math.sqrt(max(mag_var, 0)),
                        }

                elif dtype in ("String",):
                    vals = string_fn(name)
                    from collections import Counter
                    counts = Counter(vals)
                    info["unique_count"] = len(counts)
                    info["top_values"] = dict(counts.most_common(50))
                    info["samples"] = {
                        "indices": sample_indices,
                        "values": [vals[i] for i in sample_indices],
                    }

                result[name] = info
            return result

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_attrib_values(self, body):
        """Read sampled attribute values with flexible pagination."""
        path = body.get("path", "")
        attrib_class = body.get("attrib_class", "point")
        attrib_names = body.get("attribs", None)  # None = all
        start = body.get("start", 0)
        count = min(body.get("count", 20), 5000)  # server cap
        stride = max(body.get("stride", 1), 1)
        reverse = body.get("reverse", False)
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            geo = node.geometry()
            if geo is None:
                raise ValueError(f"No geometry on node: {path}")

            class_config = {
                "point": (geo.pointAttribs, geo.pointFloatAttribValues, geo.pointIntAttribValues, geo.pointStringAttribValues, len(geo.points())),
                "prim": (geo.primAttribs, geo.primFloatAttribValues, geo.primIntAttribValues, geo.primStringAttribValues, len(geo.prims())),
                "vertex": (geo.vertexAttribs, geo.vertexFloatAttribValues, geo.vertexIntAttribValues, geo.vertexStringAttribValues, geo.intrinsicValue("vertexcount")),
                "detail": (geo.globalAttribs, None, None, None, 1),
            }
            cfg = class_config.get(attrib_class)
            if cfg is None:
                raise ValueError(f"Invalid attrib_class: {attrib_class}. Use: point, prim, vertex, detail")

            attribs_fn, float_fn, int_fn, string_fn, total = cfg

            # Filter attribs
            attribs = attribs_fn()
            if attrib_names:
                name_set = set(attrib_names)
                attribs = [a for a in attribs if a.name() in name_set]

            # Compute indices
            if reverse:
                indices = list(range(total - 1 - start, -1, -stride))[:count]
            else:
                indices = list(range(start, total, stride))[:count]

            if attrib_class == "detail":
                # Detail has exactly 1 element
                attrib_data = {}
                for attrib in attribs:
                    try:
                        attrib_data[attrib.name()] = {
                            "type": attrib.dataType().name(),
                            "size": attrib.size(),
                            "values": [geo.attribValue(attrib.name())],
                        }
                    except Exception:
                        attrib_data[attrib.name()] = {"type": attrib.dataType().name(), "size": attrib.size(), "values": []}
                return {"total_count": 1, "sampled_count": 1, "indices": [0], "attribs": attrib_data}

            attrib_data = {}
            for attrib in attribs:
                name = attrib.name()
                dtype = attrib.dataType().name()
                size = attrib.size()

                if dtype in ("Float",):
                    vals = float_fn(name)
                elif dtype in ("Int",):
                    vals = int_fn(name)
                elif dtype in ("String",):
                    vals = string_fn(name)
                else:
                    continue

                if dtype in ("String",):
                    sampled = [vals[i] for i in indices]
                elif size == 1:
                    sampled = [vals[i] for i in indices]
                else:
                    sampled = [list(vals[i * size:(i + 1) * size]) for i in indices]

                attrib_data[name] = {"type": dtype, "size": size, "values": sampled}

            return {
                "total_count": total,
                "sampled_count": len(indices),
                "indices": indices,
                "attribs": attrib_data,
            }

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_create_node(self, body):
        parent = body.get("parent", "/obj")
        node_type = body.get("type", "")
        name = body.get("name", None)
        if not node_type:
            self._send_json({"success": False, "error": "No 'type' provided"}, 400)
            return

        def task():
            parent_node = hou.node(parent)
            if parent_node is None:
                raise ValueError(f"Parent node not found: {parent}")
            new_node = parent_node.createNode(node_type, name)
            return {"path": new_node.path(), "type": new_node.type().name()}

        label = f"Agent: create {node_type} in {parent}"
        r = _run_on_main_thread(_with_undo(label, task))
        _log_operation("/create_node", label, r.get("ok", False))
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_scene_snapshot(self, body):
        path = body.get("path", "/obj")
        depth = body.get("depth", 2)

        def task():
            root = hou.node(path)
            if root is None:
                raise ValueError(f"Node not found: {path}")

            result = {}

            def walk(node, d):
                children = node.children()
                if not children:
                    return
                for child in children:
                    result[child.path()] = _snapshot_node(child)
                    if d > 1:
                        walk(child, d - 1)

            walk(root, depth)
            return result

        r = _run_on_main_thread(task)
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_delete_node(self, body):
        path = body.get("path", "")
        if not path:
            self._send_json({"success": False, "error": "No 'path' provided"}, 400)
            return

        def task():
            node = hou.node(path)
            if node is None:
                raise ValueError(f"Node not found: {path}")
            node.destroy()
            return {"deleted": path}

        label = f"Agent: delete {path}"
        r = _run_on_main_thread(_with_undo(label, task))
        _log_operation("/delete_node", label, r.get("ok", False))
        if r.get("ok"):
            self._send_json({"success": True, "result": r["value"]})
        else:
            self._send_json({"success": False, "error": r.get("error")}, 500)

    def _handle_undo_history(self, body):
        limit = body.get("limit", 50)
        self._send_json({"success": True, "result": _operation_log[-limit:]})


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


def _snapshot_node(node):
    """Build a rich snapshot dict for a single node (used by /scene_snapshot)."""
    info = {
        "type": node.type().name(),
        "inputs": [i.path() if i else None for i in node.inputs()],
        "outputs": [o.path() for o in node.outputs()],
    }

    # Only non-default parameters — dramatically reduces noise
    changed_parms = {}
    for p in node.parms():
        try:
            if not p.isAtDefault():
                changed_parms[p.name()] = p.eval()
        except Exception:
            pass
    if changed_parms:
        info["parms"] = changed_parms

    # Flags — only include what the node type supports
    flags = {}
    if hasattr(node, "isDisplayFlagSet"):
        try:
            flags["display"] = node.isDisplayFlagSet()
        except Exception:
            pass
    if hasattr(node, "isRenderFlagSet"):
        try:
            flags["render"] = node.isRenderFlagSet()
        except Exception:
            pass
    try:
        flags["bypass"] = node.isBypassed()
    except Exception:
        pass
    if flags:
        info["flags"] = flags

    # Errors and warnings — only if present
    try:
        errs = node.errors()
        if errs:
            info["errors"] = errs
    except Exception:
        pass
    try:
        warns = node.warnings()
        if warns:
            info["warnings"] = warns
    except Exception:
        pass

    return info


def start_server(port=DEFAULT_PORT):
    """Start the Houdini Agent bridge server."""
    global _server_instance

    if _server_instance is not None:
        print("[houdini-agent] Server already running.")
        return

    server = HTTPServer(("127.0.0.1", port), HoudiniRequestHandler)
    _server_instance = server

    # Register main-thread processor
    hou.ui.addEventLoopCallback(_main_thread_processor)

    # Run HTTP server in a daemon thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[houdini-agent] Bridge server started on http://127.0.0.1:{port}")
    # Derive endpoint list from the handler — stays in sync automatically
    endpoints = ["/status"] + list(HoudiniRequestHandler._post_handlers.keys())
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
