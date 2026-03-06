"""Handlers for /exec and /query endpoints."""

import ast
import io
import traceback
from contextlib import redirect_stdout

import hou
from bridge.main_thread import (
    _run_on_main_thread,
    _with_undo,
    _log_operation,
    _exec_namespace,
)


def _extract_last_expr(code):
    """If the last statement is an expression, return (setup_code, expr_code).
    Otherwise return (code, None)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, None

    if not tree.body:
        return code, None

    last = tree.body[-1]
    if isinstance(last, ast.Expr):
        if len(tree.body) == 1:
            setup = ""
        else:
            lines = code.split("\n")
            setup = "\n".join(lines[: last.lineno - 1])
        expr = ast.get_source_segment(code, last.value)
        if expr is None:
            lines = code.split("\n")
            expr = "\n".join(lines[last.lineno - 1 :]).strip()
        return setup, expr

    return code, None


def _verify_nodes(node_paths):
    """Collect health info for a list of node paths. Runs on main thread."""
    result = {}
    for path in node_paths:
        node = hou.node(path)
        if node is None:
            result[path] = {"exists": False}
            continue

        info = {"exists": True, "type": node.type().name()}

        # Errors and warnings
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

        # Cook time
        try:
            info["cook_time"] = node.cookTime()
        except Exception:
            pass

        # Non-default parms (compact)
        changed = {}
        for p in node.parms():
            try:
                if not p.isAtDefault():
                    changed[p.name()] = p.eval()
            except Exception:
                pass
        if changed:
            info["parms"] = changed

        # Geometry summary (if SOP)
        try:
            geo = node.geometry()
            if geo is not None:
                geo_info = {
                    "points": len(geo.points()),
                    "prims": len(geo.prims()),
                    "vertices": geo.intrinsicValue("vertexcount"),
                }
                # Bounding box
                try:
                    bbox = geo.boundingBox()
                    geo_info["bbox_min"] = list(bbox.minvec())
                    geo_info["bbox_max"] = list(bbox.maxvec())
                except Exception:
                    pass
                info["geo"] = geo_info
        except Exception:
            pass

        result[path] = info
    return result


def handle_exec(body):
    """Execute arbitrary Python in Houdini's main thread.

    Optional body fields:
        verify: list of node paths to inspect after execution.
    """
    code = body.get("code", "")
    verify_paths = body.get("verify", None)
    if not code:
        return {"success": False, "result": None, "output": "", "error": "No 'code' provided"}, 400

    def task():
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

        resp = {
            "success": error_str is None,
            "result": result_value,
            "output": stdout_buf.getvalue(),
            "error": error_str,
        }

        # Post-exec verification
        if verify_paths:
            resp["verify"] = _verify_nodes(verify_paths)

        return resp

    label = f"Agent: exec {code[:50]}"
    r = _run_on_main_thread(_with_undo(label, task))
    _log_operation("/exec", label, r.get("ok", False))
    if r.get("ok"):
        return r["value"], 200
    return {
        "success": False,
        "result": None,
        "output": "",
        "error": r.get("error") or r.get("traceback", "Unknown error"),
    }, 500


def handle_batch(body):
    """Execute multiple code snippets in a single main-thread dispatch.

    Body:
        ops: list of {code: str, verify?: [node_paths]}
        stop_on_error: bool (default True) — abort remaining ops on first failure
    """
    ops = body.get("ops", [])
    stop_on_error = body.get("stop_on_error", True)
    if not ops:
        return {"success": False, "error": "No 'ops' provided"}, 400

    def task():
        results = []
        for op in ops:
            code = op.get("code", "")
            verify_paths = op.get("verify", None)
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

            entry = {
                "success": error_str is None,
                "result": result_value,
                "output": stdout_buf.getvalue(),
                "error": error_str,
            }
            if verify_paths:
                entry["verify"] = _verify_nodes(verify_paths)

            results.append(entry)

            if error_str and stop_on_error:
                break

        return results

    label = f"Agent: batch ({len(ops)} ops)"
    r = _run_on_main_thread(_with_undo(label, task))
    _log_operation("/batch", label, r.get("ok", False))
    if r.get("ok"):
        return {"success": True, "results": r["value"]}, 200
    return {"success": False, "error": r.get("error") or r.get("traceback", "Unknown error")}, 500


def handle_query(body):
    """Evaluate a Python expression and return the result."""
    import hou
    expression = body.get("expression", "")
    if not expression:
        return {"success": False, "error": "No 'expression' provided"}, 400

    def task():
        return eval(expression, {"hou": hou, "__builtins__": __builtins__})

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
