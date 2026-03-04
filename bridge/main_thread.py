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
# Operation log — records mutating operations for /undo_history
# ---------------------------------------------------------------------------
_operation_log = []
_MAX_LOG_SIZE = 200


def _log_operation(endpoint, label, success):
    """Append a mutating-operation record."""
    _operation_log.append({
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": endpoint,
        "label": label,
        "success": success,
    })
    if len(_operation_log) > _MAX_LOG_SIZE:
        del _operation_log[:len(_operation_log) - _MAX_LOG_SIZE]


# ---------------------------------------------------------------------------
# Persistent exec namespace — variables survive between /exec calls
# ---------------------------------------------------------------------------
_exec_namespace = {"hou": hou, "__builtins__": __builtins__}
