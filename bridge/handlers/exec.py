"""Handlers for /exec and /query endpoints."""

import ast
import io
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout

import hou
from bridge import artifacts
from bridge.main_thread import (
    _run_on_main_thread,
    run_mutation,
    _exec_namespace,
)


def _extract_last_expr(code):
    """If the last statement is an expression, return (setup, expr) where setup
    is a compiled code object of everything before it (or None) and expr is a
    compiled eval-mode code object of the expression.  Otherwise (code, None).

    Compiling the AST nodes directly (instead of slicing source by line number)
    keeps semicolon-separated statements intact — `a = 1; a` used to drop the
    assignment because both statements share one line.  exec()/eval() accept
    both strings and code objects, so callers need no special-casing."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, None

    if not tree.body:
        return code, None

    last = tree.body[-1]
    if isinstance(last, ast.Expr):
        setup = None
        if len(tree.body) > 1:
            setup = compile(ast.Module(body=tree.body[:-1], type_ignores=[]),
                            "<bridge>", "exec")
        expr = compile(ast.Expression(last.value), "<bridge>", "eval")
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


def _normalize_observe(observe):
    if not observe:
        return []
    if isinstance(observe, (str, dict)):
        observe = [observe]
    result = []
    for item in observe:
        if isinstance(item, str):
            result.append({"path": item, "depth": 1})
        elif isinstance(item, dict) and item.get("path"):
            result.append({
                "path": item["path"],
                "depth": max(0, min(int(item.get("depth", 1)), 16)),
            })
    return result


def _capture_observed(scopes):
    from bridge.handlers.scene import _capture_subtree

    captured = []
    for scope in scopes:
        try:
            nodes = _capture_subtree(
                scope["path"], scope["depth"], include_root=True
            )
            captured.append({**scope, "nodes": nodes})
        except Exception as exc:
            captured.append({**scope, "nodes": {}, "error": str(exc)})
    return captured


def _diff_observed(before, after):
    from bridge.handlers.scene import _diff_snapshots

    changes = []
    for index, current in enumerate(after):
        previous = before[index] if index < len(before) else {"nodes": {}}
        entry = {
            "path": current["path"],
            "depth": current["depth"],
            "diff": _diff_snapshots(
                previous.get("nodes", {}), current.get("nodes", {}), details=False
            ),
        }
        if previous.get("error"):
            entry["before_error"] = previous["error"]
        if current.get("error"):
            entry["after_error"] = current["error"]
        changes.append(entry)
    return changes


def _execute_code(code, verify_paths=None, return_expr=None, observe=None,
                  artifact_threshold=None):
    """Execute code in the shared namespace and return a structured report."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    result_value = None
    error_str = None
    started = time.time()
    started_perf = time.perf_counter()
    request_id = uuid.uuid4().hex
    scopes = _normalize_observe(observe)
    before = _capture_observed(scopes) if scopes else []

    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            if return_expr is not None:
                exec(compile(code, "<bridge>", "exec"), _exec_namespace)
                result_value = eval(
                    compile(return_expr, "<bridge-return>", "eval"),
                    _exec_namespace,
                )
            else:
                setup_code, expr_code = _extract_last_expr(code)
                if setup_code is not None and setup_code != "":
                    exec(setup_code, _exec_namespace)
                if expr_code is not None:
                    result_value = eval(expr_code, _exec_namespace)
    except Exception:
        error_str = traceback.format_exc()

    after = _capture_observed(scopes) if scopes else []
    elapsed = time.perf_counter() - started_perf
    if artifact_threshold is not None and error_str is None:
        result_value = artifacts.externalize(
            result_value,
            threshold=artifact_threshold,
            name="exec-result-" + request_id,
        )

    resp = {
        "success": error_str is None,
        "result": result_value,
        "output": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": error_str,
        "elapsed": elapsed,
        "receipt": {
            "id": request_id,
            "started_at": started,
            "elapsed": elapsed,
            "observed": _diff_observed(before, after) if scopes else [],
        },
    }
    if verify_paths:
        resp["verify"] = _verify_nodes(verify_paths)
    return resp


def handle_exec(body):
    """Execute arbitrary Python in Houdini's main thread.

    Optional body fields:
        verify: list of node paths to inspect after execution.
    """
    code = body.get("code", "")
    verify_paths = body.get("verify", None)
    return_expr = body.get("return_expr", None)
    observe = body.get("observe", None)
    artifact_threshold = body.get("artifact_threshold", None)
    if not code:
        return {"success": False, "result": None, "output": "", "error": "No 'code' provided"}, 400

    def task():
        return _execute_code(
            code,
            verify_paths=verify_paths,
            return_expr=return_expr,
            observe=observe,
            artifact_threshold=artifact_threshold,
        )

    label = f"Agent: exec {code[:50]}"
    r = run_mutation("/exec", label, task, spotlight=verify_paths)
    if r.get("ok"):
        response = r["value"]
        response.setdefault("receipt", {})["operation"] = r.get("receipt")
        return response, 200
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
    default_artifact_threshold = body.get("artifact_threshold", None)
    if not ops:
        return {"success": False, "error": "No 'ops' provided"}, 400

    def task():
        results = []
        for op in ops:
            code = op.get("code", "")
            verify_paths = op.get("verify", None)
            entry = _execute_code(
                code,
                verify_paths=verify_paths,
                return_expr=op.get("return_expr", None),
                observe=op.get("observe", None),
                artifact_threshold=op.get(
                    "artifact_threshold", default_artifact_threshold
                ),
            )

            results.append(entry)

            if not entry["success"] and stop_on_error:
                break

        return results

    label = f"Agent: batch ({len(ops)} ops)"
    all_verify = [p for op in ops for p in (op.get("verify") or [])]
    r = run_mutation("/batch", label, task, spotlight=all_verify or None)
    if r.get("ok"):
        return {
            "success": True,
            "results": r["value"],
            "receipt": r.get("receipt"),
        }, 200
    return {"success": False, "error": r.get("error") or r.get("traceback", "Unknown error")}, 500


def handle_query(body):
    """Evaluate a Python expression and return the result."""
    import hou
    expression = body.get("expression", "")
    artifact_threshold = body.get("artifact_threshold", None)
    if not expression:
        return {"success": False, "error": "No 'expression' provided"}, 400

    def task():
        value = eval(expression, {"hou": hou, "__builtins__": __builtins__})
        if artifact_threshold is not None:
            value = artifacts.externalize(
                value, threshold=artifact_threshold, name="query-result"
            )
        return value

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
