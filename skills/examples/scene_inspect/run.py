"""
Skill: Scene Inspect
Reads the current Houdini scene and returns a structured summary.
"""
from bridge.client import HoudiniClient


def run(h: HoudiniClient):
    """Inspect the current Houdini scene and return a summary dict."""
    info = h.status()

    report = {
        "hip_file": info.get("hip_file"),
        "frame": info.get("frame"),
        "fps": info.get("fps"),
        "frame_range": info.get("frame_range"),
        "contexts": {},
    }

    # Inspect /obj
    if h.node_exists("/obj"):
        obj_tree = h.get_node_tree("/obj", depth=2)
        report["contexts"]["obj"] = obj_tree

    # Inspect /stage (LOPs)
    if h.node_exists("/stage"):
        stage_tree = h.get_node_tree("/stage", depth=2)
        report["contexts"]["stage"] = stage_tree

    # Inspect /out (ROPs)
    if h.node_exists("/out"):
        out_tree = h.get_node_tree("/out", depth=1)
        report["contexts"]["out"] = out_tree

    return report
