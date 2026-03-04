"""Handlers for /exec and /query endpoints."""

import ast
import io
import traceback
from contextlib import redirect_stdout

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


def handle_exec(body):
    """Execute arbitrary Python in Houdini's main thread."""
    code = body.get("code", "")
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
        return r["value"], 200
    return {
        "success": False,
        "result": None,
        "output": "",
        "error": r.get("error") or r.get("traceback", "Unknown error"),
    }, 500


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
