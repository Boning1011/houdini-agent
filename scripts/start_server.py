# Paste this into Houdini's Python Shell to start the bridge server.
# Requires HOUDINI_AGENT_ROOT env var (set via Houdini package JSON).

import sys
import os
REPO_ROOT = os.environ.get("HOUDINI_AGENT_ROOT")
if not REPO_ROOT:
    raise RuntimeError(
        "HOUDINI_AGENT_ROOT is not set. "
        "Set it in your Houdini package JSON or run:\n"
        "  import os; os.environ['HOUDINI_AGENT_ROOT'] = r'C:\\path\\to\\houdini-agent'\n"
        "before running this script."
    )
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Force reload to pick up code changes without restarting Houdini
import importlib
import bridge.server
importlib.reload(bridge.server)

from bridge.server import start_server
start_server()  # default port 8765
