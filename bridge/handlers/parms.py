"""Handlers for /get_parms and /set_parms endpoints."""

import hou
from bridge.main_thread import _run_on_main_thread, _with_undo, _log_operation


def handle_get_parms(body):
    """Get all parameters of a node."""
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

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
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_set_parms(body):
    """Set parameters on a node."""
    path = body.get("path", "")
    parms = body.get("parms", {})
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

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
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
