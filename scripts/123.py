"""
Auto-start the Houdini Agent bridge server and ensure the Python Panel is
registered when Houdini launches.

Houdini runs this script every time a new (empty) scene is created, including
at GUI startup. The bridge's own guard in start_server() makes re-entry a no-op,
and panel registration is idempotent (mtime-checked copy + menu de-dup).

Opt out: HOUDINI_AGENT_AUTOSTART=0
Custom port: HOUDINI_AGENT_PORT=<n>
"""

import os
import shutil
import sys

import hou


def _ensure_panel_registered(repo_root):
    """Copy the .pypanel into user prefs and ensure it shows in the pane tab menu.

    pypanel registration and menu inclusion are separate steps in Houdini —
    installFile() registers an interface but does not add it to
    hou.pypanel.menuInterfaces(), which is a curated list persisted in user prefs.
    """
    src = os.path.join(repo_root, "panels", "houdini_agent.pypanel")
    if not os.path.isfile(src):
        return

    dst_dir = os.path.join(hou.homeHoudiniDirectory(), "python_panels")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "houdini_agent.pypanel")

    if not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
        shutil.copy2(src, dst)

    hou.pypanel.installFile(dst)

    menu = list(hou.pypanel.menuInterfaces())
    if "houdini_agent" not in menu:
        menu.append("houdini_agent")
        hou.pypanel.setMenuInterfaces(menu)


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

    try:
        _ensure_panel_registered(repo_root)
    except Exception as e:
        print(f"[houdini-agent] panel registration failed: {e}")

    from bridge.server import start_server

    port_env = os.environ.get("HOUDINI_AGENT_PORT")
    if port_env:
        start_server(port=int(port_env))
    else:
        start_server()


try:
    _bootstrap()
except Exception as _e:
    # Never let an autostart failure take Houdini down with us — Houdini
    # treats unhandled exceptions in 123.py as fatal startup errors.
    print(f"[houdini-agent] autostart failed: {_e}")
