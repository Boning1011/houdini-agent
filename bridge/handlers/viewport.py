"""Handler for viewport screenshot capture."""

import os
import tempfile
import time

import hou
from bridge.main_thread import _run_on_main_thread


def handle_screenshot(body):
    """Capture the current viewport and save as an image file.

    Optional body fields:
        output: file path to save the image (default: temp file).
        width: image width in pixels (default: 1280).
        height: image height in pixels (default: 720).
    """
    output_path = body.get("output", None)
    width = body.get("width", 1280)
    height = body.get("height", 720)

    def task():
        # Find the scene viewer
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is None:
            raise RuntimeError("No Scene Viewer pane found. Is a viewport open?")

        # Determine output path
        if output_path:
            path = output_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            tmp_dir = os.path.join(tempfile.gettempdir(), "houdini_agent")
            os.makedirs(tmp_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(tmp_dir, f"viewport_{ts}.png")

        # Configure flipbook settings for a single-frame capture
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((hou.frame(), hou.frame()))
        settings.resolution((width, height))
        settings.output(path)

        # Capture
        viewer.flipbook(viewer.curViewport(), settings)

        return {"path": path, "width": width, "height": height}

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
