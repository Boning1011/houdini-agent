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
        width: image width in pixels (default: native viewport width).
        height: image height in pixels (default: native viewport height).
    """
    output_path = body.get("output", None)
    width = body.get("width", None)
    height = body.get("height", None)

    def task():
        # Find the scene viewer
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is None:
            raise RuntimeError("No Scene Viewer pane found. Is a viewport open?")

        # Determine output path
        if output_path:
            path = output_path
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        else:
            tmp_dir = os.path.join(tempfile.gettempdir(), "houdini_agent")
            os.makedirs(tmp_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(tmp_dir, f"viewport_{ts}.png")

        # Use native viewport resolution if not specified
        viewport = viewer.curViewport()
        vp_size = viewport.size()
        w = width or (vp_size[2] - vp_size[0])
        h = height or (vp_size[3] - vp_size[1])

        # Flipbook single frame with MPlay suppressed
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((hou.frame(), hou.frame()))
        settings.resolution((w, h))
        settings.output(path)
        settings.outputToMPlay(False)

        viewer.flipbook(viewport, settings)

        return {"path": path, "width": w, "height": h}

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500
