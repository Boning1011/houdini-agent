"""
Auto-start the Houdini Agent bridge server when Houdini launches.

Houdini runs this script every time a new (empty) scene is created, including
at GUI startup. The bridge's own guard in start_server() makes re-entry a no-op.

Opt out: HOUDINI_AGENT_AUTOSTART=0
Custom port: HOUDINI_AGENT_PORT=<n>
"""

import os
import sys

import hou


def _bootstrap():
    if os.environ.get("HOUDINI_AGENT_AUTOSTART", "1") == "0":
        return

    # GUI-mode autostart only. Headless (hython) lacks the UI event loop the
    # bridge currently relies on; that path is started explicitly by the user.
    if not hou.isUIAvailable():
        return

    repo_root = os.environ.get("HOUDINI_AGENT_ROOT")
    if not repo_root:
        print("[houdini-agent] HOUDINI_AGENT_ROOT not set; skipping autostart.")
        return

    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from bridge.server import start_server

    port_env = os.environ.get("HOUDINI_AGENT_PORT")
    if port_env:
        start_server(port=int(port_env))
    else:
        start_server()


_bootstrap()
