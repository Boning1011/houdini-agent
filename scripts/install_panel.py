"""
One-time installer: copies the .pypanel file to Houdini's python_panels directory
so it shows up in the pane tab menu.

Run from anywhere:
    python scripts/install_panel.py

Or paste into Houdini's Python Shell.
"""

import shutil
import os
import hou

# Source .pypanel file in this repo
# Hardcoded path — works when pasted into Houdini's Python Shell (no __file__)
repo_root = r"C:\Users\vvox\Documents\GitHub\houdini-agent"
src = os.path.join(repo_root, "panels", "houdini_agent.pypanel")

# Houdini's user python_panels directory
dst_dir = os.path.join(hou.homeHoudiniDirectory(), "python_panels")
os.makedirs(dst_dir, exist_ok=True)
dst = os.path.join(dst_dir, "houdini_agent.pypanel")

shutil.copy2(src, dst)
print(f"[houdini-agent] Installed panel to: {dst}")
print("[houdini-agent] Restart Houdini or refresh panels to see it.")
print("[houdini-agent] Look for: New Pane Tab Type > Houdini Agent")
