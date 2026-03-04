# Paste this into Houdini's Python Shell to start the bridge server.
# Edit the path below to point to your houdini-agent repo root.

import sys
REPO_ROOT = r"C:\Users\vvox\Documents\GitHub\houdini-agent"  # <-- edit this
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Force reload to pick up code changes without restarting Houdini
import importlib
import bridge.server
importlib.reload(bridge.server)

from bridge.server import start_server
start_server()  # default port 8765
