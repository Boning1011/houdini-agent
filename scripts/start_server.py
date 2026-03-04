"""
Quick-start script for the Houdini Agent bridge server.

Paste this into Houdini's Python Shell, or run it from a shelf tool.
"""

import sys
import os

# Add the repo root to sys.path so we can import bridge.server
# Adjust this path to where you cloned houdini-agent
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from bridge.server import start_server

start_server()  # default port 8765
