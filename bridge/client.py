"""
External client for the Houdini Agent bridge.

Used by Claude Code (or any external process) to communicate with the
Houdini-side server over HTTP JSON.

Usage:
    from bridge.client import HoudiniClient
    h = HoudiniClient()
    h.status()
    h.exec_code("hou.node('/obj').createNode('geo')")
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
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Houdini at {self.base_url}. "
                f"Is the server running? ({e})"
            )

        if result.get("status") == "error":
            error_msg = result.get("error", "Unknown error")
            tb = result.get("traceback", "")
            raise RuntimeError(f"Houdini error: {error_msg}\n{tb}".strip())

        return result.get("result")

    def _post(self, path, body):
        return self._request("POST", path, body)

    def _get(self, path):
        return self._request("GET", path)

    # --- Public API ---

    def status(self):
        """Health check. Returns hip file path, fps, current frame, frame range."""
        return self._get("/status")

    def exec_code(self, code):
        """Execute arbitrary Python code in Houdini's main thread.

        To return a value, assign it to a variable named `result`:
            h.exec_code("result = hou.node('/obj').children()")
        """
        return self._post("/exec", {"code": code})

    def query(self, expression):
        """Evaluate a Python expression in Houdini and return the result.

        Example:
            h.query("hou.node('/obj/geo1') is not None")  # True/False
            h.query("hou.frame()")  # current frame number
        """
        return self._post("/query", {"expression": expression})

    def get_node_tree(self, path="/", depth=3):
        """Get the node hierarchy as a nested dict.

        Args:
            path: Root path to start from (default: "/")
            depth: How deep to recurse (default: 3)
        """
        return self._post("/get_node_tree", {"path": path, "depth": depth})

    def get_parms(self, node_path):
        """Get all parameter values of a node as a dict."""
        return self._post("/get_parms", {"path": node_path})

    def set_parms(self, node_path, parms):
        """Set parameters on a node.

        Args:
            node_path: Path to the node
            parms: Dict of {param_name: value}
        """
        return self._post("/set_parms", {"path": node_path, "parms": parms})

    def get_attribs(self, node_path, attrib_class="point"):
        """Get geometry attribute info from a node.

        Args:
            node_path: Path to a SOP node with geometry
            attrib_class: One of "point", "prim", "vertex", "detail"
        """
        return self._post("/get_attribs", {"path": node_path, "attrib_class": attrib_class})

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
        return self._post("/create_node", body)

    def delete_node(self, path):
        """Delete a node. Use with caution.

        Args:
            path: Path to the node to delete
        """
        return self._post("/delete_node", {"path": path})

    def node_exists(self, path):
        """Check if a node exists at the given path."""
        return self.query(f"hou.node('{path}') is not None")
