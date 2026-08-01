"""Viewport and generic Houdini pane capture."""

import os
import tempfile
import time

import hou
from bridge.main_thread import _run_on_main_thread


def handle_screenshot(body):
    """Capture the viewport, a Houdini pane, window, or desktop.

    Optional body fields:
        output: file path to save the image (default: temp file).
        width: image width in pixels (default: native viewport width).
        height: image height in pixels (default: native viewport height).
        target: viewport (default), pane, network_editor, parameters, window,
                or desktop.
        pane_name: exact Houdini pane-tab name for target=pane.
        pane_type: pane type name such as NetworkEditor or Parm.
    """
    output_path = body.get("output", None)
    width = body.get("width", None)
    height = body.get("height", None)
    target = str(body.get("target", "viewport")).lower()
    pane_name = body.get("pane_name")
    pane_type = body.get("pane_type")

    def task():
        if target == "viewport":
            return _capture_viewport(output_path, width, height)
        return _capture_qt_target(
            target,
            output_path=output_path,
            width=width,
            height=height,
            pane_name=pane_name,
            pane_type=pane_type,
        )

    r = _run_on_main_thread(task)
    if r.get("ok"):
        return {"success": True, "result": r["value"]}, 200
    return {"success": False, "error": r.get("error")}, 500


def _make_output_path(output_path, prefix):
    if output_path:
        path = output_path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return path
    tmp_dir = os.path.join(tempfile.gettempdir(), "houdini_agent")
    os.makedirs(tmp_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(tmp_dir, f"{prefix}_{ts}.png")


def _capture_viewport(output_path, width, height):
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None:
        raise RuntimeError("No Scene Viewer pane found. Is a viewport open?")

    path = _make_output_path(output_path, "viewport")

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

    return {"path": path, "width": w, "height": h, "target": "viewport"}


def _qt_api():
    try:
        from PySide6 import QtCore, QtGui
        return QtCore, QtGui, "PySide6"
    except ImportError:
        try:
            from PySide2 import QtCore, QtGui
            return QtCore, QtGui, "PySide2"
        except ImportError:
            raise RuntimeError("No supported Qt binding is available")


def _find_pane(pane_name=None, pane_type=None):
    panes = list(hou.ui.paneTabs())
    if pane_name:
        for pane in panes:
            if pane.name() == pane_name:
                return pane
        raise RuntimeError("Pane not found by name: " + str(pane_name))
    if pane_type:
        wanted = str(pane_type).lower().replace("_", "")
        for pane in panes:
            current = pane.type().name().lower().replace("_", "")
            if current == wanted:
                return pane
        available = sorted({pane.type().name() for pane in panes})
        raise RuntimeError(
            "Pane type %s is not open. Available: %s"
            % (pane_type, ", ".join(available))
        )
    try:
        pane = hou.ui.paneTabUnderCursor()
        if pane is not None:
            return pane
    except Exception:
        pass
    if panes:
        return panes[0]
    raise RuntimeError("No Houdini pane tabs are open")


def _capture_qt_target(target, output_path, width, height, pane_name, pane_type):
    if not hou.isUIAvailable():
        raise RuntimeError("Pane capture requires a graphical Houdini session")
    QtCore, QtGui, qt_binding = _qt_api()

    aliases = {
        "network": "NetworkEditor",
        "network_editor": "NetworkEditor",
        "parameters": "Parm",
        "parameter_editor": "Parm",
    }
    if target in aliases:
        pane_type = aliases[target]
        target = "pane"

    pane = None
    if target in ("pane", "window"):
        pane = _find_pane(pane_name=pane_name, pane_type=pane_type)

    app = QtGui.QGuiApplication.instance()
    if app is None:
        raise RuntimeError("Qt application is not available")

    if target == "pane":
        rect = pane.qtScreenGeometry()
        widget = pane.qtParentWindow()
        _raise_window(widget, app, QtCore)
        screen = app.screenAt(rect.center()) or app.primaryScreen()
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        prefix = "pane_" + pane.type().name().lower()
        actual_target = pane.type().name()
        raised_window = True
    elif target == "window":
        widget = pane.qtParentWindow()
        _raise_window(widget, app, QtCore)
        rect = widget.frameGeometry()
        screen = app.screenAt(rect.center()) or app.primaryScreen()
        pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
        prefix = "houdini_window"
        actual_target = "window"
        raised_window = True
    elif target == "desktop":
        try:
            cursor = QtGui.QCursor.pos()
            screen = app.screenAt(cursor) or app.primaryScreen()
        except Exception:
            screen = app.primaryScreen()
        pixmap = screen.grabWindow(0)
        prefix = "desktop"
        actual_target = "desktop"
        raised_window = False
    else:
        raise ValueError(
            "Unknown screenshot target %r. Use viewport, pane, network_editor, "
            "parameters, window, or desktop." % target
        )

    if width or height:
        current = pixmap.size()
        target_w = int(width or current.width())
        target_h = int(height or current.height())
        keep_aspect = getattr(QtCore.Qt, "KeepAspectRatio", None)
        smooth = getattr(QtCore.Qt, "SmoothTransformation", None)
        if hasattr(QtCore.Qt, "AspectRatioMode"):
            keep_aspect = QtCore.Qt.AspectRatioMode.KeepAspectRatio
        if hasattr(QtCore.Qt, "TransformationMode"):
            smooth = QtCore.Qt.TransformationMode.SmoothTransformation
        pixmap = pixmap.scaled(target_w, target_h, keep_aspect, smooth)

    path = _make_output_path(output_path, prefix)
    if not pixmap.save(path):
        raise RuntimeError("Qt failed to save screenshot: " + path)
    return {
        "path": path,
        "width": pixmap.width(),
        "height": pixmap.height(),
        "target": actual_target,
        "qt_binding": qt_binding,
        "pane_name": pane.name() if pane is not None else None,
        "raised_window": raised_window,
    }


def _raise_window(widget, app, QtCore):
    """Bring a Houdini window forward before screen capture.

    Houdini pane tabs do not expose an off-screen render API and QWidget.grab()
    can fall back to compositor pixels for its native windows. Raising the
    window is the only cross-version way to avoid photographing an occluder.
    """
    widget.show()
    widget.raise_()
    widget.activateWindow()
    try:
        handle = widget.windowHandle()
        if handle is not None:
            handle.requestActivate()
    except Exception:
        pass
    app.processEvents()
    QtCore.QThread.msleep(75)
    app.processEvents()
