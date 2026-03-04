"""
External client for the Houdini Agent bridge.

Used by Claude Code (or any external process) to communicate with the
Houdini-side server over HTTP JSON.

Usage:
    from bridge.client import HoudiniClient
    h = HoudiniClient()
    h.status()
    h.exec("hou.node('/obj').createNode('geo')")
"""

import json
import urllib.request
import urllib.error

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 30


class HoudiniClient:
    """Client for communicating with the Houdini Agent bridge server."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout

    def _request(self, method, path, body=None):
        """Send an HTTP request and return the parsed JSON response."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Houdini at {self.base_url}. "
                f"Is the server running? ({e})"
            )

    def _post(self, path, body):
        return self._request("POST", path, body)

    def _get(self, path):
        return self._request("GET", path)

    # --- Public API ---

    def status(self):
        """Health check. Returns scene info dict with hip_file, houdini_version, fps, etc."""
        return self._get("/status")

    def exec(self, code):
        """Execute Python code in Houdini and return the result value.

        The last expression in the code is automatically captured and returned.
        Variables persist between calls (shared namespace).

        Examples:
            h.exec("hou.node('/obj').createNode('geo')")
            children = h.exec("[c.path() for c in hou.node('/obj').children()]")
        """
        resp = self._post("/exec", {"code": code})
        if not resp.get("success"):
            error = resp.get("error", "Unknown error")
            raise RuntimeError(f"Houdini error:\n{error}")
        return resp.get("result")

    def raw_exec(self, code):
        """Execute Python code and return the full response dict.

        Returns:
            {"success": bool, "result": any, "output": str, "error": str|None}
        """
        return self._post("/exec", {"code": code})

    def exec_code(self, code):
        """Alias for exec() — backwards compatibility."""
        return self.exec(code)

    def query(self, expression):
        """Evaluate a Python expression in Houdini and return the result.

        Example:
            h.query("hou.node('/obj/geo1') is not None")  # True/False
            h.query("hou.frame()")  # current frame number
        """
        resp = self._post("/query", {"expression": expression})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def get_node_tree(self, path="/", depth=3):
        """Get the node hierarchy as a nested dict."""
        resp = self._post("/get_node_tree", {"path": path, "depth": depth})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def get_parms(self, node_path):
        """Get all parameter values of a node as a dict."""
        resp = self._post("/get_parms", {"path": node_path})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def set_parms(self, node_path, parms):
        """Set parameters on a node.

        Args:
            node_path: Path to the node
            parms: Dict of {param_name: value}
        """
        resp = self._post("/set_parms", {"path": node_path, "parms": parms})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def get_attribs(self, node_path, attrib_class="point"):
        """Get geometry attribute info from a node.

        Args:
            node_path: Path to a SOP node with geometry
            attrib_class: One of "point", "prim", "vertex", "detail"
        """
        resp = self._post("/get_attribs", {"path": node_path, "attrib_class": attrib_class})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def create_node(self, parent, node_type, name=None):
        """Create a new node.

        Args:
            parent: Path to the parent node (e.g., "/obj")
            node_type: Node type to create (e.g., "geo", "null")
            name: Optional name for the new node

        Returns:
            Dict with "path" and "type" of the created node.
        """
        body = {"parent": parent, "type": node_type}
        if name:
            body["name"] = name
        resp = self._post("/create_node", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def delete_node(self, path):
        """Delete a node. Use with caution."""
        resp = self._post("/delete_node", {"path": path})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def scene_snapshot(self, path="/obj", depth=2):
        """Get a rich snapshot of a network — nodes, connections, non-default parms, flags, errors.

        One call replaces: get_node_tree + get_parms per node + connection queries.

        Args:
            path: Root network path to snapshot (default "/obj")
            depth: How many levels deep to traverse (default 2)

        Returns:
            Dict keyed by node path, each value containing:
            type, inputs, outputs, parms (non-default only), flags, errors, warnings
        """
        resp = self._post("/scene_snapshot", {"path": path, "depth": depth})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def node_exists(self, path):
        """Check if a node exists at the given path."""
        return self.query(f"hou.node('{path}') is not None")
