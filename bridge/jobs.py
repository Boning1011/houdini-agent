"""Thread-safe in-process registry for asynchronous Houdini jobs."""

import copy
import threading
import time
import uuid
from collections import OrderedDict


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
_MAX_JOBS = 100
_lock = threading.RLock()
_jobs = OrderedDict()


def create(label):
    job_id = uuid.uuid4().hex
    now = time.time()
    record = {
        "id": job_id,
        "label": label,
        "state": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "result": None,
    }
    with _lock:
        _jobs[job_id] = record
        while len(_jobs) > _MAX_JOBS:
            oldest_terminal_id = next(
                (
                    candidate_id
                    for candidate_id, candidate in _jobs.items()
                    if candidate["state"] in TERMINAL_STATES
                ),
                None,
            )
            if oldest_terminal_id is None:
                # Never discard an active job merely to enforce the history cap.
                break
            del _jobs[oldest_terminal_id]
    return copy.deepcopy(record)


def get(job_id, include_result=True):
    with _lock:
        if job_id not in _jobs:
            raise KeyError("Unknown job id: " + str(job_id))
        value = copy.deepcopy(_jobs[job_id])
    if not include_result:
        value.pop("result", None)
    return value


def list_jobs(include_result=False):
    with _lock:
        values = [copy.deepcopy(value) for value in _jobs.values()]
    if not include_result:
        for value in values:
            value.pop("result", None)
    return values


def is_cancel_requested(job_id):
    with _lock:
        return bool(_jobs[job_id]["cancel_requested"])


def mark_running(job_id):
    with _lock:
        record = _jobs[job_id]
        if record["cancel_requested"]:
            record["state"] = "cancelled"
            record["finished_at"] = time.time()
            return False
        record["state"] = "running"
        record["started_at"] = time.time()
        return True


def finish(job_id, result, success):
    with _lock:
        record = _jobs[job_id]
        record["result"] = result
        record["state"] = "succeeded" if success else "failed"
        record["finished_at"] = time.time()


def fail(job_id, error):
    finish(
        job_id,
        {"success": False, "error": str(error)},
        success=False,
    )


def request_cancel(job_id):
    with _lock:
        if job_id not in _jobs:
            raise KeyError("Unknown job id: " + str(job_id))
        record = _jobs[job_id]
        record["cancel_requested"] = True
        if record["state"] == "queued":
            record["state"] = "cancelled"
            record["finished_at"] = time.time()
            effective = True
        else:
            # Arbitrary hou cooks cannot always be interrupted safely. Running
            # code can inspect the flag, but the bridge does not kill Houdini's
            # main thread.
            effective = record["state"] == "cancelled"
        return {
            "id": job_id,
            "state": record["state"],
            "cancel_requested": True,
            "effective": effective,
        }
