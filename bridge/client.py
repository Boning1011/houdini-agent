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

import base64
import json
import os
import time
import urllib.request
import urllib.error

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 30
DISCOVERY_PING_TIMEOUT = 1.0


def _ping_status(host, port, timeout=DISCOVERY_PING_TIMEOUT):
    """Hit /status on a candidate port. Returns the parsed dict or None if dead."""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/status", timeout=timeout
        ) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _discover_instances(host=DEFAULT_HOST, timeout=DISCOVERY_PING_TIMEOUT):
    """Read the registry, ping each entry, prune dead ones, return live instances.

    Each entry is merged with the fresh /status response so callers see the
    current hip_file (the user may have opened a different .hip since start).
    """
    # Import lazily — the bridge package may not be importable from every
    # client context, and we want a friendly ImportError if it isn't.
    from bridge import discovery

    live = []
    for entry in discovery.list_entries():
        info = _ping_status(host, entry["port"], timeout=timeout)
        if info is None:
            try:
                os.remove(entry["_path"])
            except OSError:
                pass
            continue
        live.append({**entry, **info})
    return live


class HoudiniClient:
    """Client for communicating with the Houdini Agent bridge server.

    When `port` is omitted, auto-discovers a running Houdini via the on-disk
    registry. Raises ConnectionError with a list of options if multiple live
    instances exist and none can be matched by `hip_file` against `cwd`.
    """

    def __init__(self, host=DEFAULT_HOST, port=None, timeout=DEFAULT_TIMEOUT):
        if port is None:
            port = self._discover_port(host)
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.timeout = timeout

    @staticmethod
    def _discover_port(host):
        live = _discover_instances(host)

        if not live:
            raise ConnectionError(
                "No Houdini bridge servers found. Start the bridge from the "
                "Houdini Agent panel or scripts/start_server.py, or pass "
                "port=N explicitly."
            )

        if len(live) == 1:
            return live[0]["port"]

        # Multiple instances — prefer one whose hip_file is inside cwd
        cwd = os.path.abspath(os.getcwd())
        matches = []
        for inst in live:
            hip = inst.get("hip_file") or ""
            if not hip:
                continue
            hip_dir = os.path.dirname(os.path.abspath(hip))
            if hip_dir and (cwd == hip_dir or cwd.startswith(hip_dir + os.sep)):
                matches.append(inst)
        if len(matches) == 1:
            return matches[0]["port"]

        lines = ["Multiple Houdini bridge servers running. Pass port= explicitly:"]
        now = time.time()
        for inst in sorted(live, key=lambda x: -x.get("started_at", 0)):
            age_min = (now - inst.get("started_at", now)) / 60
            hip = inst.get("hip_file") or "(unsaved)"
            lines.append(
                f"  port={inst['port']}  hip={hip}  pid={inst['pid']}  "
                f"started {age_min:.0f}m ago"
            )
        raise ConnectionError("\n".join(lines))

    @staticmethod
    def list_instances(host=DEFAULT_HOST, timeout=DISCOVERY_PING_TIMEOUT):
        """Enumerate live Houdini bridge servers visible to this machine.

        Returns a list of dicts with at least pid, port, started_at, hip_file,
        houdini_version. Use this when you're not sure which Houdini is which.
        """
        return _discover_instances(host=host, timeout=timeout)

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
        except urllib.error.HTTPError as e:
            # Server returned an error status — try to read the JSON body
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                raise RuntimeError(f"Houdini server error {e.code}: {e.reason}")
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

    def capabilities(self):
        """Return runtime-discovered bridge/Houdini capabilities."""
        return self.status().get("capabilities", {})

    def exec(self, code, verify=None, return_expr=None, observe=None,
             artifact_threshold=None, detailed=False):
        """Execute Python code in Houdini and return the result value.

        The last expression in the code is automatically captured and returned.
        Variables persist between calls (shared namespace).

        Args:
            code: Python code to execute.
            verify: Optional list of node paths to inspect after execution.
                    When provided, returns a dict with "result" and "verify" keys
                    instead of just the result value.
            return_expr: Explicit expression to evaluate after the code. Useful
                         when the script cannot end in a convenient expression.
            observe: Optional scene scopes to diff before and after execution.
                     Items may be node paths or {"path": str, "depth": int}.
            artifact_threshold: Externalize larger result values into an opaque
                                artifact when their JSON size exceeds this many
                                bytes. None keeps the legacy inline behavior.
            detailed: Return the full execution report, including stdout,
                      stderr, timing, verification, and mutation receipt.

        Examples:
            h.exec("hou.node('/obj').createNode('geo')")
            h.exec("node.parm('tx').set(5)", verify=["/obj/geo1"])
        """
        body = {"code": code}
        if verify:
            body["verify"] = verify
        if return_expr is not None:
            body["return_expr"] = return_expr
        if observe:
            body["observe"] = observe
        if artifact_threshold is not None:
            body["artifact_threshold"] = artifact_threshold
        resp = self._post("/exec", body)
        if not resp.get("success"):
            error = resp.get("error", "Unknown error")
            raise RuntimeError(f"Houdini error:\n{error}")
        if detailed:
            return resp
        if verify or observe:
            value = {"result": resp.get("result")}
            if verify:
                value["verify"] = resp.get("verify", {})
            if observe:
                value["receipt"] = resp.get("receipt", {})
            return value
        return resp.get("result")

    def raw_exec(self, code, verify=None, return_expr=None, observe=None,
                 artifact_threshold=None):
        """Execute Python code and return the full response dict.

        Returns:
            {"success": bool, "result": any, "output": str, "error": str|None,
             "verify": dict|None}
        """
        body = {"code": code}
        if verify:
            body["verify"] = verify
        if return_expr is not None:
            body["return_expr"] = return_expr
        if observe:
            body["observe"] = observe
        if artifact_threshold is not None:
            body["artifact_threshold"] = artifact_threshold
        return self._post("/exec", body)

    def batch(self, ops, stop_on_error=True, artifact_threshold=None,
              detailed=False):
        """Execute multiple code snippets in one round-trip.

        All ops run in a single main-thread dispatch and one undo group.

        Args:
            ops: List of dicts, each with:
                - code (str): Python code to execute
                - verify (list[str], optional): node paths to inspect after this op
            stop_on_error: If True (default), stop on first failure.

        Returns:
            List of result dicts, one per op (same format as raw_exec).

        Example:
            h.batch([
                {"code": "hou.node('/obj').createNode('geo', 'my_geo')"},
                {"code": "hou.node('/obj/my_geo').createNode('box')"},
                {"code": "hou.node('/obj/my_geo').layoutChildren()"},
            ])
        """
        body = {"ops": ops, "stop_on_error": stop_on_error}
        if artifact_threshold is not None:
            body["artifact_threshold"] = artifact_threshold
        resp = self._post("/batch", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        if detailed:
            return resp
        return resp.get("results")

    def exec_code(self, code, verify=None):
        """Alias for exec() — backwards compatibility."""
        return self.exec(code, verify=verify)

    def query(self, expression, artifact_threshold=None):
        """Evaluate a Python expression in Houdini and return the result.

        Example:
            h.query("hou.node('/obj/geo1') is not None")  # True/False
            h.query("hou.frame()")  # current frame number
        """
        body = {"expression": expression}
        if artifact_threshold is not None:
            body["artifact_threshold"] = artifact_threshold
        resp = self._post("/query", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def evaluate(self, expression, artifact_threshold=256 * 1024):
        """Evaluate arbitrary Houdini Python with automatic large-result storage.

        Small JSON-compatible values are returned inline. Large text, arrays,
        dictionaries, or byte payloads return an artifact descriptor accepted
        by artifact_info/read_artifact/read_artifact_all.
        """
        return self.query(expression, artifact_threshold=artifact_threshold)

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

    def set_parms(self, node_path, parms, detailed=False):
        """Set parameters on a node.

        Args:
            node_path: Path to the node
            parms: Dict of {param_name: value}
        """
        resp = self._post("/set_parms", {"path": node_path, "parms": parms})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        if detailed:
            return resp
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

    def attrib_info(self, node_path=None, paths=None):
        """Geometry structure overview — all attribute names/types across all classes.

        Returns point/prim/vertex/detail counts and attribute lists with name, type, size.
        No values — just the structure.

        Args:
            node_path: Path to a single SOP node
            paths: List of SOP node paths (batch mode — one round-trip for all)

        Returns:
            Single node: flat info dict.
            Batch (paths): dict keyed by node path.
        """
        body = {}
        if paths:
            body["paths"] = paths
        elif node_path:
            body["path"] = node_path
        else:
            raise ValueError("Provide either node_path or paths")
        resp = self._post("/attrib_info", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def attrib_stats(self, node_path, attribs=None, attrib_class="point", samples=5):
        """Value statistics for specific attributes in a class.

        Returns min/max/mean for numeric attrs, unique_count/top_values for strings,
        plus evenly-spaced sample values.

        Args:
            node_path: Path to a SOP node with geometry
            attribs: List of attribute names, or None for all in the class
            attrib_class: One of "point", "prim", "vertex", "detail"
            samples: Number of evenly-spaced sample values to include (default 5, max 50)
        """
        body = {"path": node_path, "attrib_class": attrib_class, "samples": samples}
        if attribs:
            body["attribs"] = attribs
        resp = self._post("/attrib_stats", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def attrib_values(self, node_path, attribs=None, attrib_class="point",
                      start=0, count=20, stride=1, reverse=False):
        """Read sampled attribute values from geometry.

        Targeted drill-down — use attrib_info and attrib_stats first for overview.

        Args:
            node_path: Path to a SOP node with geometry
            attribs: List of attribute names, or None for all
            attrib_class: One of "point", "prim", "vertex", "detail"
            start: Offset from beginning (or end if reverse)
            count: Max elements to return (default 20, server cap 5000)
            stride: Sample every Nth element (default 1)
            reverse: If True, read from last element backward
        """
        body = {"path": node_path, "attrib_class": attrib_class,
                "start": start, "count": count, "stride": stride, "reverse": reverse}
        if attribs:
            body["attribs"] = attribs
        resp = self._post("/attrib_values", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def create_node(self, parent, node_type, name=None, detailed=False):
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
        if detailed:
            return resp
        return resp.get("result")

    def delete_node(self, path, detailed=False):
        """Delete a node. Use with caution."""
        resp = self._post("/delete_node", {"path": path})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        if detailed:
            return resp
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

    def observe_scene(self, path="/obj", depth=2, since=None,
                      include_nodes=True, details=False):
        """Observe actual scene state and optionally diff against a prior token.

        Tokens are computed from the scene itself, so manual user edits are
        visible even when they did not pass through the bridge. Nodes include a
        session-stable ID when the running Houdini version exposes one.

        Args:
            path: Root node/network to observe.
            depth: Descendant depth, 0-16.
            since: Token returned by an earlier observe_scene call.
            include_nodes: Include the current snapshot. Set False for a compact
                           change-only poll after the first observation.
            details: Include full before/after values for changed nodes.
        """
        body = {
            "path": path,
            "depth": depth,
            "include_nodes": include_nodes,
            "details": details,
        }
        if since:
            body["since"] = since
        resp = self._post("/scene_observe", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def ui_state(self):
        """Get what the user is currently looking at.

        Returns dict with:
        - selected_nodes: list of selected node paths
        - network_editor_path: current network editor location
        - current_frame: current timeline frame
        """
        resp = self._post("/ui_state", {})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def screenshot(self, output=None, width=None, height=None, target="viewport",
                   pane_name=None, pane_type=None):
        """Capture the current viewport as an image.

        Args:
            output: File path to save the image (default: auto temp file).
            width: Image width in pixels (default: native viewport width).
            height: Image height in pixels (default: native viewport height).
            target: viewport (legacy default), pane, network_editor,
                    parameters, window, or desktop.
            pane_name: Exact pane-tab name when target is pane/window.
            pane_type: Pane type name such as NetworkEditor or Parm.

        Returns:
            Dict with "path", "width", "height" of the saved image.
        """
        body = {"target": target}
        if output:
            body["output"] = output
        if width:
            body["width"] = width
        if height:
            body["height"] = height
        if pane_name:
            body["pane_name"] = pane_name
        if pane_type:
            body["pane_type"] = pane_type
        resp = self._post("/screenshot", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def capture(self, target="network_editor", output=None, width=None,
                height=None, pane_name=None, pane_type=None):
        """Capture any observable Houdini UI surface.

        This is the discoverable general form of screenshot(); screenshot()
        remains backward compatible with viewport capture.
        """
        return self.screenshot(
            output=output,
            width=width,
            height=height,
            target=target,
            pane_name=pane_name,
            pane_type=pane_type,
        )

    def node_info(self, node_path=None, paths=None, verbose=False, output_index=0):
        """Get the full node info tree (equivalent to MMB popup).

        Use this to inspect nodes in detail — cook time, geometry counts,
        attribute lists, memory, bbox, etc.  Content varies by context
        (SOP/LOP/OBJ/DOP).

        Args:
            node_path: Path to a single node
            paths: List of node paths (batch mode — one round-trip for all)
            verbose: Include extra detail (may be slower)
            output_index: Which output to query for multi-output nodes

        Returns:
            Single node: flat info dict.
            Batch (paths): dict keyed by node path.
        """
        body = {"verbose": verbose, "output_index": output_index}
        if paths:
            body["paths"] = paths
        elif node_path:
            body["path"] = node_path
        else:
            raise ValueError("Provide either node_path or paths")
        resp = self._post("/node_info", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def node_exists(self, path):
        """Check if a node exists at the given path."""
        return self.query(f"hou.node('{path}') is not None")

    def node_by_session_id(self, session_id):
        """Resolve a session-stable node identity after a rename or move.

        Returns the current path or None. Check capabilities()["node_session_id"]
        when targeting older Houdini builds.
        """
        expression = (
            "(lambda n: n.path() if n is not None else None)("
            "hou.nodeBySessionId(%d) if hasattr(hou, 'nodeBySessionId') else None)"
            % int(session_id)
        )
        return self.query(expression)

    # --- Generic Artifacts ---

    @staticmethod
    def is_artifact(value):
        """Return True when *value* is an artifact descriptor."""
        return isinstance(value, dict) and isinstance(value.get("$artifact"), str)

    def artifact_info(self, artifact):
        """Return metadata for an artifact descriptor or ID."""
        artifact_id = artifact.get("$artifact") if isinstance(artifact, dict) else artifact
        resp = self._post("/artifact/info", {"id": artifact_id})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def read_artifact(self, artifact, offset=0, limit=64 * 1024):
        """Read one bounded text/JSON/binary chunk from an artifact."""
        artifact_id = artifact.get("$artifact") if isinstance(artifact, dict) else artifact
        resp = self._post(
            "/artifact/read",
            {"id": artifact_id, "offset": offset, "limit": limit},
        )
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def read_artifact_all(self, artifact, chunk_size=256 * 1024,
                          parse_json=True):
        """Read a complete artifact, optionally decoding JSON automatically."""
        parts = []
        offset = 0
        descriptor = None
        while True:
            chunk = self.read_artifact(artifact, offset=offset, limit=chunk_size)
            descriptor = chunk["artifact"]
            content = chunk["content"]
            if descriptor["kind"] == "binary":
                parts.append(base64.b64decode(content.encode("ascii")))
            else:
                parts.append(content)
            if chunk["eof"]:
                break
            offset = chunk["next_offset"]
        if descriptor and descriptor["kind"] == "binary":
            return b"".join(parts)
        text = "".join(parts)
        if parse_json and descriptor and descriptor["kind"] == "json":
            return json.loads(text)
        return text

    # --- Asynchronous Jobs ---

    def start_job(self, code, label=None, verify=None, return_expr=None,
                  observe=None, artifact_threshold=256 * 1024):
        """Queue Houdini Python and return immediately with a persistent job ID.

        Jobs execute serially on Houdini's main thread. Queued jobs can be
        cancelled. Cancellation of a running arbitrary hou cook is only a
        request because Houdini does not guarantee safe interruption. Long
        Python loops may cooperate by checking
        `bridge.jobs.is_cancel_requested(HOUDINI_AGENT_JOB_ID)`.
        """
        body = {"code": code}
        if label:
            body["label"] = label
        if verify:
            body["verify"] = verify
        if return_expr is not None:
            body["return_expr"] = return_expr
        if observe:
            body["observe"] = observe
        if artifact_threshold is not None:
            body["artifact_threshold"] = artifact_threshold
        resp = self._post("/job/start", body)
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def job_status(self, job, include_result=True):
        """Get the current state of a job descriptor or ID."""
        job_id = job.get("id") if isinstance(job, dict) else job
        resp = self._post(
            "/job/status",
            {"id": job_id, "include_result": include_result},
        )
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def list_jobs(self, include_result=False):
        """List jobs retained by this Houdini bridge process."""
        resp = self._post("/job/list", {"include_result": include_result})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def cancel_job(self, job):
        """Cancel a queued job or request cooperative cancellation of a running job."""
        job_id = job.get("id") if isinstance(job, dict) else job
        resp = self._post("/job/cancel", {"id": job_id})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def wait_job(self, job, timeout=None, poll_interval=0.25):
        """Poll a job until it reaches a terminal state.

        A client timeout does not cancel or lose the Houdini job; callers can
        reconnect later and query the same ID.
        """
        job_id = job.get("id") if isinstance(job, dict) else job
        started = time.time()
        while True:
            status = self.job_status(job_id, include_result=True)
            if status.get("state") in ("succeeded", "failed", "cancelled"):
                return status
            if timeout is not None and time.time() - started >= timeout:
                raise TimeoutError("Timed out waiting for Houdini job " + str(job_id))
            time.sleep(max(0.01, poll_interval))

    # --- Undo & Backup ---

    def undo_history(self, limit=50):
        """Get the server-side log of mutating operations."""
        resp = self._post("/undo_history", {"limit": limit})
        if not resp.get("success"):
            raise RuntimeError(f"Houdini error: {resp.get('error', 'Unknown error')}")
        return resp.get("result")

    def backup(self, directory=None):
        """Save a timestamped .hip backup. Returns the backup file path.

        Default location: $HIP/.agent_backups/
        """
        dir_repr = repr(directory) if directory else "None"
        code = f"""
import os, time as _t
_hip_path = hou.hipFile.path()
_hip_dir = os.path.dirname(_hip_path)
_hip_name = os.path.splitext(os.path.basename(_hip_path))[0]
_backup_dir = {dir_repr} or os.path.join(_hip_dir, ".agent_backups")
os.makedirs(_backup_dir, exist_ok=True)
_ts = _t.strftime("%Y%m%d_%H%M%S")
_backup_path = os.path.join(_backup_dir, f"{{_hip_name}}_{{_ts}}.hip")
hou.hipFile.save(_backup_path)
hou.hipFile.setName(_hip_path)
_backup_path
"""
        return self.exec(code)

    def list_backups(self, directory=None):
        """List available .hip backups, newest first."""
        dir_repr = repr(directory) if directory else "None"
        code = f"""
import os, glob as _glob
_hip_path = hou.hipFile.path()
_hip_dir = os.path.dirname(_hip_path)
_backup_dir = {dir_repr} or os.path.join(_hip_dir, ".agent_backups")
if os.path.isdir(_backup_dir):
    _files = _glob.glob(os.path.join(_backup_dir, "*.hip"))
    _result = sorted(_files, key=os.path.getmtime, reverse=True)
else:
    _result = []
_result
"""
        return self.exec(code)

    def restore_backup(self, backup_path):
        """Load a previously saved .hip backup.

        WARNING: This replaces the current scene. Requires user confirmation.
        """
        return self.exec(f"hou.hipFile.load({repr(backup_path)})\nhou.hipFile.path()")
