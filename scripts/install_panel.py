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
# Uses HOUDINI_AGENT_ROOT env var, or prompts user to set it
repo_root = os.environ.get("HOUDINI_AGENT_ROOT")
if not repo_root:
    raise RuntimeError(
        "HOUDINI_AGENT_ROOT is not set. "
        "Set it in your Houdini package JSON or run:\n"
        "  import os; os.environ['HOUDINI_AGENT_ROOT'] = r'C:\\path\\to\\houdini-agent'\n"
        "before running this script."
    )
src = os.path.join(repo_root, "panels", "houdini_agent.pypanel")

# Houdini's user python_panels directory
dst_dir = os.path.join(hou.homeHoudiniDirectory(), "python_panels")
os.makedirs(dst_dir, exist_ok=True)
dst = os.path.join(dst_dir, "houdini_agent.pypanel")

shutil.copy2(src, dst)
hou.pypanel.installFile(dst)

# pypanel registration and menu inclusion are separate concerns in Houdini.
# installFile() registers the interface; setMenuInterfaces() controls what
# shows up in the pane tab menu.
menu = list(hou.pypanel.menuInterfaces())
if "houdini_agent" not in menu:
    menu.append("houdini_agent")
    hou.pypanel.setMenuInterfaces(menu)

print(f"[houdini-agent] Installed panel to: {dst}")
print("[houdini-agent] Look for: New Pane Tab Type > Houdini Agent")
