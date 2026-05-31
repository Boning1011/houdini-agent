"""Per-process registry so external clients can find live bridge servers.

The OS gives the second Houdini instance whatever port the first didn't grab —
typically 8766. An external `HoudiniClient()` defaulting to 8765 would then
silently target the older instance (or worse, a zombie). Each server writes a
JSON entry here on startup so clients can enumerate live instances by PID and
port instead of guessing.

Liveness is *not* tracked here. The client confirms each entry is alive by
calling `/status`, which also returns the current `hip_file` — that way the
registry stays simple and stale entries are pruned naturally.
"""
import atexit
import json
import os
import tempfile
import time

REGISTRY_DIR = os.path.join(tempfile.gettempdir(), "houdini_agent", "instances")


def _entry_path(pid=None):
    return os.path.join(REGISTRY_DIR, f"{pid or os.getpid()}.json")


def register(port):
    """Write this process's registry entry. Returns the file path, or None on failure.

    Also evicts any other PID's entry claiming the same port — those are stale
    leftovers from a crash that didn't run atexit. (The OS released the port
    when the process died, and we just rebound it.)
    """
    try:
        os.makedirs(REGISTRY_DIR, exist_ok=True)
    except OSError:
        return None

    my_pid = os.getpid()
    for entry in list_entries():
        if entry.get("port") == port and entry.get("pid") != my_pid:
            try:
                os.remove(entry["_path"])
            except OSError:
                pass

    path = _entry_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pid": my_pid, "port": port, "started_at": time.time()}, f)
    except OSError:
        return None
    atexit.register(unregister)
    return path


def unregister():
    try:
        os.remove(_entry_path())
    except OSError:
        pass


def list_entries():
    """Return all on-disk entries. Does not check liveness — that's the client's job."""
    if not os.path.isdir(REGISTRY_DIR):
        return []
    out = []
    for name in os.listdir(REGISTRY_DIR):
        if not name.endswith(".json"):
            continue
        p = os.path.join(REGISTRY_DIR, name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, json.JSONDecodeError):
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        entry["_path"] = p
        out.append(entry)
    return out
