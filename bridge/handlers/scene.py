"""Scene-level endpoints and generic observation tokens."""

import hashlib
import json
import platform
from collections import OrderedDict

import hou
from bridge.main_thread import (
    _run_on_main_thread,
    run_mutation,
    _operation_log,
)


_OBSERVATIONS = OrderedDict()
_MAX_OBSERVATIONS = 32


def handle_status(_body):
    """Health check — returns scene info plus process identity for client-side discovery."""
    import os as _os
    from bridge import server as _server

    bound_port = None
    if _server._server_instance is not None:
        try:
            bound_port = _server._server_instance.server_address[1]
        except Exception:
            pass

    def task():
        ui_available = False
        try:
            ui_available = bool(hou.isUIAvailable())
        except Exception:
            pass

        qt_binding = None
        if ui_available:
            for module_name in ("PySide6", "PySide2"):
                try:
                    __import__(module_name)
                    qt_binding = module_name
                    break
                except Exception:
                    pass

        root = hou.node("/")
        return {
            "connected": True,
            "pid": _os.getpid(),
            "port": bound_port,
            "hip_file": hou.hipFile.path(),
            "houdini_version": ".".join(str(x) for x in hou.applicationVersion()),
            "fps": hou.fps(),
            "frame_range": list(hou.playbar.frameRange()),
            "current_frame": hou.frame(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "bridge_protocol": 2,
            "capabilities": {
                "ui": ui_available,
                "qt_binding": qt_binding,
                "node_session_id": bool(
                    root is not None
                    and hasattr(root, "sessionId")
                    and hasattr(hou, "nodeBySessionId")
                ),
                "scene_observe": True,
                "artifacts": True,
                "jobs": True,
                "pane_capture": ui_available and qt_binding is not None,
            },
        }

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return r["value"], 200
    return {"connected": False, "error": r.get("error")}, 500


def handle_get_node_tree(body):
    """Get node hierarchy as nested dict."""
    path = body.get("path", "/")
    depth = body.get("depth", 3)

    def task():
        node = hou.node(path)
        if node is None:
            raise ValueError(f"Node not found: {path}")
        return _node_to_dict(node, depth)

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_create_node(body):
    """Create a node under a parent."""
    parent = body.get("parent", "/obj")
    node_type = body.get("type", "")
    name = body.get("name", None)
    if not node_type:
        return {"success": False, "error": "No 'type' provided"}, 400

    def task():
        parent_node = hou.node(parent)
        if parent_node is None:
            raise ValueError(f"Parent node not found: {parent}")
        new_node = parent_node.createNode(node_type, name)
        return {"path": new_node.path(), "type": new_node.type().name()}

    label = f"Agent: create {node_type} in {parent}"
    r = run_mutation(
        "/create_node", label, task,
        spotlight=lambda res: [res["path"]] if isinstance(res, dict) and res.get("path") else None,
    )
    if r.get("ok"):
        return {
            "success": True,
            "result": r["value"],
            "receipt": r.get("receipt"),
        }, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_delete_node(body):
    """Delete a node by path."""
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400

    def task():
        node = hou.node(path)
        if node is None:
            raise ValueError(f"Node not found: {path}")
        node.destroy()
        return {"deleted": path}

    label = f"Agent: delete {path}"
    # Pan to the parent network — the node itself is gone after the task runs,
    # so we frame where it used to live.
    parent_path = path.rsplit("/", 1)[0] or "/"
    r = run_mutation("/delete_node", label, task, spotlight=[parent_path])
    if r.get("ok"):
        return {
            "success": True,
            "result": r["value"],
            "receipt": r.get("receipt"),
        }, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_scene_snapshot(body):
    """Build a rich snapshot of a subtree."""
    path = body.get("path", "/obj")
    depth = body.get("depth", 2)

    def task():
        root = hou.node(path)
        if root is None:
            raise ValueError(f"Node not found: {path}")

        result = {}

        def walk(node, d):
            for child in node.children():
                result[child.path()] = _snapshot_node(child)
                if d > 1:
                    walk(child, d - 1)

        walk(root, depth)
        return result

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_scene_observe(body):
    """Capture a subtree, return a reusable token, and optionally diff it.

    Unlike a continuously incremented revision counter, this observes manual
    user edits as well as bridge edits because the token is derived from the
    actual scene state at call time.
    """
    path = body.get("path", "/obj")
    depth = max(0, min(int(body.get("depth", 2)), 16))
    since = body.get("since")
    include_nodes = body.get("include_nodes", True)
    details = body.get("details", False)

    def task():
        nodes = _capture_subtree(path, depth, include_root=True)
        envelope = {
            "path": path,
            "depth": depth,
            "hip_file": hou.hipFile.path(),
            "frame": hou.frame(),
            "nodes": nodes,
        }
        canonical = json.dumps(
            envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        token = hashlib.sha256(canonical).hexdigest()
        previous = _OBSERVATIONS.get(since) if since else None
        _OBSERVATIONS[token] = envelope
        _OBSERVATIONS.move_to_end(token)
        while len(_OBSERVATIONS) > _MAX_OBSERVATIONS:
            _OBSERVATIONS.popitem(last=False)

        result = {
            "token": token,
            "path": path,
            "depth": depth,
            "frame": envelope["frame"],
            "since": since,
            "since_available": previous is not None if since else None,
        }
        if include_nodes:
            result["nodes"] = nodes
        if since:
            if previous is not None:
                result["diff"] = _diff_snapshots(
                    previous.get("nodes", {}), nodes, details=details
                )
            else:
                result["diff"] = None
        return result

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_ui_state(_body):
    """Return what the user is currently looking at: network editor path, selected nodes, etc."""
    def task():
        result = {}

        # Selected nodes
        result["selected_nodes"] = [n.path() for n in hou.selectedNodes()]

        # Network editor current path
        try:
            ne = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if ne:
                result["network_editor_path"] = ne.pwd().path()
        except Exception:
            pass

        # Current frame for context
        result["current_frame"] = hou.frame()

        return result

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_node_info(body):
    """Return the full infoTree for one or more nodes (equivalent to MMB popup).

    Accepts either "path" (single node) or "paths" (list of node paths).
    Returns a dict keyed by node path when using "paths", or a flat dict for "path".
    """
    paths = body.get("paths", None)
    single_path = body.get("path", "")
    if not paths and not single_path:
        return {"success": False, "error": "No 'path' or 'paths' provided"}, 400
    verbose = body.get("verbose", False)
    output_index = body.get("output_index", 0)

    if paths:
        def task():
            result = {}
            for p in paths:
                node = hou.node(p)
                if node is None:
                    result[p] = {"error": f"Node not found: {p}"}
                    continue
                tree = node.infoTree(verbose=verbose, output_index=output_index)
                result[p] = _info_tree_to_dict(tree)
            return result
    else:
        def task():
            node = hou.node(single_path)
            if node is None:
                raise ValueError(f"Node not found: {single_path}")
            tree = node.infoTree(verbose=verbose, output_index=output_index)
            return _info_tree_to_dict(tree)

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def handle_undo_history(body):
    """Return the operation log."""
    limit = body.get("limit", 50)
    return {"success": True, "result": _operation_log[-limit:]}, 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _info_tree_to_dict(tree):
    """Recursively convert a hou.NodeInfoTree to a plain dict."""
    d = {}
    if tree.rows():
        d["rows"] = [list(r) for r in tree.rows()]
    for name in tree.branchOrder():
        d[name] = _info_tree_to_dict(tree.branches()[name])
    return d


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
    """Build a rich snapshot dict for a single node."""
    info = {
        "type": node.type().name(),
        "inputs": [i.path() if i else None for i in node.inputs()],
        "outputs": [o.path() for o in node.outputs()],
    }
    try:
        info["session_id"] = node.sessionId()
    except Exception:
        pass

    changed_parms = {}
    for p in node.parms():
        try:
            if not p.isAtDefault():
                changed_parms[p.name()] = p.eval()
        except Exception:
            pass
    if changed_parms:
        info["parms"] = changed_parms

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


def _capture_subtree(path, depth, include_root=True):
    """Return a deterministic snapshot dict for *path* and its descendants."""
    root = hou.node(path)
    if root is None:
        raise ValueError(f"Node not found: {path}")
    result = {}
    if include_root:
        result[root.path()] = _snapshot_node(root)

    def walk(node, remaining):
        if remaining <= 0:
            return
        for child in node.children():
            result[child.path()] = _snapshot_node(child)
            walk(child, remaining - 1)

    walk(root, depth)
    return result


def _changed_fields(before, after):
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _diff_snapshots(before, after, details=False):
    """Compare two snapshot dicts, recognizing renames by node session ID."""
    before_paths = set(before)
    after_paths = set(after)
    removed = before_paths - after_paths
    added = after_paths - before_paths

    before_by_id = {
        value.get("session_id"): path
        for path, value in before.items()
        if value.get("session_id") is not None
    }
    after_by_id = {
        value.get("session_id"): path
        for path, value in after.items()
        if value.get("session_id") is not None
    }
    renamed = []
    for session_id in sorted(set(before_by_id) & set(after_by_id)):
        old_path = before_by_id[session_id]
        new_path = after_by_id[session_id]
        if old_path != new_path and old_path in removed and new_path in added:
            renamed.append({
                "session_id": session_id,
                "from": old_path,
                "to": new_path,
            })
            removed.remove(old_path)
            added.remove(new_path)

    changed = []
    for path in sorted(before_paths & after_paths):
        fields = _changed_fields(before[path], after[path])
        if fields:
            entry = {"path": path, "fields": fields}
            if details:
                entry["before"] = before[path]
                entry["after"] = after[path]
            changed.append(entry)

    return {
        "added": sorted(added),
        "removed": sorted(removed),
        "renamed": renamed,
        "changed": changed,
        "has_changes": bool(added or removed or renamed or changed),
    }
