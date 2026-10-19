"""Also bootstrap when opening a hip directly, or launching Houdini Core.

123.py only runs for empty FX scenes. Reuse its idempotent bootstrap after
the UI is ready so the bridge and panel are available for every GUI launch.
"""
import os
import runpy

_agent_root = os.environ.get("HOUDINI_AGENT_ROOT")
if _agent_root:
    try:
        runpy.run_path(os.path.join(_agent_root, "scripts", "123.py"))
    except Exception as exc:
        print("[houdini-agent] UI-ready bootstrap failed: " + str(exc))
