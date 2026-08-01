"""
Main-thread marshalling, undo groups, and operation logging.

Houdini's `hou` module is NOT thread-safe — all hou calls must run on the main
thread.  This module provides:
  - _run_on_main_thread(task)  — queue a callable and wait for the result
  - _with_undo(label, func)   — wrap a callable in a hou.undos group
  - _log_operation(...)        — record a mutating operation for diagnostics
"""

import hou
import time as _time
import threading
import traceback
from queue import Queue, Empty

# ---------------------------------------------------------------------------
# Request queue — HTTP thread puts tasks here, main-thread callback pops them
# ---------------------------------------------------------------------------
_request_queue = Queue()


def _main_thread_processor():
    """Event-loop callback that processes queued requests on Houdini's main thread."""
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
    """Queue a callable for main-thread execution and block until done."""
    result_holder = {}
    event = threading.Event()
    _request_queue.put((task, result_holder, event))
    if not event.wait(timeout=timeout):
        return {"ok": False, "error": "Timed out waiting for main thread execution"}
    return result_holder


# ---------------------------------------------------------------------------
# Undo wrapper
# ---------------------------------------------------------------------------

def _with_undo(label, func):
    """Wrap *func* in a Houdini undo group.  Returns a new callable."""
    def wrapped():
        with hou.undos.group(label):
            return func()
    return wrapped


# ---------------------------------------------------------------------------
# Visual feedback wrapper (timelapse / OBS spectacle) — see bridge/feedback.py
# ---------------------------------------------------------------------------

def _result_ok(result):
    """Best-effort success read of a task's return value, for feedback colour."""
    if isinstance(result, dict):
        return result.get("success", True)
    if isinstance(result, list):
        return all(isinstance(e, dict) and e.get("success", True) for e in result)
    return True


def _with_feedback(label, spotlight, func):
    """Wrap *func* so that, after it runs on the main thread, we emit cosmetic
    feedback: a status-bar message, a network-editor flash, and an animated
    pan/zoom to the touched nodes.

    *spotlight* is either a list of node paths, or a callable taking the task's
    result and returning a list of paths (used when the path is only known after
    the task runs, e.g. create_node).  All feedback is strictly cook-free and any
    failure here is swallowed — feedback must never break a real operation.
    """
    def wrapped():
        result = func()
        try:
            from bridge import feedback
            feedback.announce(label, ok=_result_ok(result))
            paths = spotlight(result) if callable(spotlight) else spotlight
            if paths:
                feedback.spotlight(paths)
        except Exception:
            pass
        return result
    return wrapped


def run_mutation(endpoint, label, task, spotlight=None):
    """Single choke point for every mutating bridge op.

    Wraps *task* in an undo group + visual feedback, runs it on the main thread,
    records it in the operation log, and returns the raw result holder
    ({"ok": bool, "value"/"error"/"traceback": ...}).  Callers shape the HTTP
    response from that holder exactly as before.
    """
    wrapped = _with_undo(label, _with_feedback(label, spotlight, task))
    r = _run_on_main_thread(wrapped)
    r["receipt"] = _log_operation(endpoint, label, r.get("ok", False))
    return r


# ---------------------------------------------------------------------------
# Operation log — records mutating operations for /undo_history
# ---------------------------------------------------------------------------
_operation_log = []
_MAX_LOG_SIZE = 200
_op_seq = 0


def _log_operation(endpoint, label, success):
    """Append a mutating-operation record.

    Each entry carries a monotonically increasing ``seq`` so a UI (the panel)
    can stream new entries reliably even after the log is trimmed at the front.
    """
    global _op_seq
    _op_seq += 1
    entry = {
        "seq": _op_seq,
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": endpoint,
        "label": label,
        "success": success,
    }
    _operation_log.append(entry)
    if len(_operation_log) > _MAX_LOG_SIZE:
        del _operation_log[:len(_operation_log) - _MAX_LOG_SIZE]
    return dict(entry)


# ---------------------------------------------------------------------------
# Activity log — records EVERY bridge request (reads and writes) for the panel
# to stream.  Independent of the timelapse feedback; this is the "verbose" feed
# the user watches in the Houdini Agent panel.  Populated from server.do_POST.
# ---------------------------------------------------------------------------
_activity_log = []
_MAX_ACTIVITY = 300
_activity_seq = 0

# Endpoints worth surfacing as "writes" (coloured differently in the panel).
_WRITE_ENDPOINTS = {
    "/exec", "/batch", "/create_node", "/delete_node", "/set_parms",
    "/job/start", "/job/cancel",
}


def summarize_request(path, body):
    """Build a short one-line summary of a request for the activity log."""
    ep = path.lstrip("/")
    try:
        if "code" in body:                       # /exec
            return "%s: %s" % (ep, " ".join(str(body["code"]).split())[:70])
        if "ops" in body:                        # /batch
            return "%s: %d ops" % (ep, len(body["ops"]))
        if "expression" in body:                 # /query
            return "%s: %s" % (ep, str(body["expression"])[:70])
        if "type" in body:                       # /create_node
            return "%s: %s in %s" % (ep, body.get("type"), body.get("parent", ""))
        if "parms" in body:                      # /set_parms
            return "%s: %s %s" % (ep, body.get("path", ""), list(body["parms"].keys()))
        if "paths" in body:
            return "%s: %d nodes" % (ep, len(body["paths"]))
        if "path" in body:
            return "%s: %s" % (ep, body["path"])
    except Exception:
        pass
    return ep


def activity_ok(data, code):
    """Best-effort success read of a handler response for colouring."""
    if isinstance(data, dict):
        if "success" in data:
            return bool(data["success"])
        if "connected" in data:
            return bool(data["connected"])
    return 200 <= code < 300


def log_activity(path, summary, ok):
    """Append one entry to the activity log.  Cheap; safe to call per request.

    Each entry carries a monotonic ``seq`` so the panel can stream new entries
    even after the ring buffer trims at the front.  ``write`` marks mutating
    endpoints so the panel can colour them differently.
    """
    global _activity_seq
    _activity_seq += 1
    _activity_log.append({
        "seq": _activity_seq,
        "timestamp": _time.strftime("%H:%M:%S"),
        "endpoint": path,
        "summary": summary,
        "ok": ok,
        "write": path in _WRITE_ENDPOINTS,
    })
    if len(_activity_log) > _MAX_ACTIVITY:
        del _activity_log[:len(_activity_log) - _MAX_ACTIVITY]


# ---------------------------------------------------------------------------
# Persistent exec namespace — variables survive between /exec calls
# ---------------------------------------------------------------------------
_exec_namespace = {"hou": hou, "__builtins__": __builtins__}
