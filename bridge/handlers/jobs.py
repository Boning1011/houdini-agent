"""Asynchronous execution endpoints built on the existing main-thread queue."""

import threading
import traceback

from bridge import artifacts
from bridge import jobs
from bridge.handlers.exec import _execute_code
from bridge.main_thread import (
    _exec_namespace,
    _log_operation,
    _request_queue,
    _with_feedback,
    _with_undo,
)


def handle_job_start(body):
    code = body.get("code", "")
    if not code:
        return {"success": False, "error": "No 'code' provided"}, 400
    label = body.get("label") or "Agent job: " + " ".join(code.split())[:60]
    record = jobs.create(label)
    job_id = record["id"]

    def execute_job():
        if not jobs.mark_running(job_id):
            _log_operation("/job/start", label, False)
            return None
        try:
            _exec_namespace["HOUDINI_AGENT_JOB_ID"] = job_id
            response = _execute_code(
                code,
                verify_paths=body.get("verify"),
                return_expr=body.get("return_expr"),
                observe=body.get("observe"),
                artifact_threshold=body.get(
                    "artifact_threshold", artifacts.DEFAULT_THRESHOLD
                ),
            )
            response["receipt"]["job_id"] = job_id
            operation = _log_operation(
                "/job/start", label, bool(response.get("success", False))
            )
            response["receipt"]["operation"] = operation
            jobs.finish(job_id, response, success=response.get("success", False))
            return response
        except Exception:
            error = traceback.format_exc()
            jobs.fail(job_id, error)
            _log_operation("/job/start", label, False)
            return None

    wrapped = _with_undo(label, _with_feedback(label, body.get("verify"), execute_job))
    # The HTTP request returns immediately. The normal Houdini event-loop
    # processor executes this queued task on the main thread.
    _request_queue.put((wrapped, {}, threading.Event()))
    return {"success": True, "result": record}, 202


def handle_job_status(body):
    try:
        result = jobs.get(
            body.get("id", ""), include_result=body.get("include_result", True)
        )
    except KeyError as exc:
        return {"success": False, "error": str(exc)}, 404
    return {"success": True, "result": result}, 200


def handle_job_list(body):
    return {
        "success": True,
        "result": jobs.list_jobs(include_result=body.get("include_result", False)),
    }, 200


def handle_job_cancel(body):
    try:
        result = jobs.request_cancel(body.get("id", ""))
    except KeyError as exc:
        return {"success": False, "error": str(exc)}, 404
    return {"success": True, "result": result}, 200
