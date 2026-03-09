"""Handlers for scene-level endpoints: status, node tree, create/delete, snapshot, undo history."""

import hou
from bridge.main_thread import (
    _run_on_main_thread,
    _with_undo,
    _log_operation,
    _operation_log,
)


def handle_status(_body):
    """Health check — returns scene info."""
    def task():
        return {
            "connected": True,
            "hip_file": hou.hipFile.path(),
            "houdini_version": ".".join(str(x) for x in hou.applicationVersion()),
            "fps": hou.fps(),
            "frame_range": list(hou.playbar.frameRange()),
            "current_frame": hou.frame(),
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
    r = _run_on_main_thread(_with_undo(label, task))
    _log_operation("/create_node", label, r.get("ok", False))
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
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
    r = _run_on_main_thread(_with_undo(label, task))
    _log_operation("/delete_node", label, r.get("ok", False))
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
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
    """Return the full infoTree for a single node (equivalent to MMB popup)."""
    path = body.get("path", "")
    if not path:
        return {"success": False, "error": "No 'path' provided"}, 400
    verbose = body.get("verbose", False)
    output_index = body.get("output_index", 0)

    def task():
        node = hou.node(path)
        if node is None:
            raise ValueError(f"Node not found: {path}")
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
