"""
Handler registry — maps endpoint paths to handler functions.

Each handler has the signature:
    handle(body: dict) -> (response_dict, status_code)
"""

from bridge.handlers.exec import handle_exec, handle_batch, handle_query
from bridge.handlers.scene import (
    handle_status,
    handle_get_node_tree,
    handle_create_node,
    handle_delete_node,
    handle_scene_snapshot,
    handle_scene_observe,
    handle_ui_state,
    handle_node_info,
    handle_undo_history,
)
from bridge.handlers.parms import handle_get_parms, handle_set_parms
from bridge.handlers.geometry import (
    handle_get_attribs,
    handle_attrib_info,
    handle_attrib_stats,
    handle_attrib_values,
)
from bridge.handlers.viewport import handle_screenshot
from bridge.handlers.artifacts import handle_artifact_info, handle_artifact_read
from bridge.handlers.jobs import (
    handle_job_start,
    handle_job_status,
    handle_job_list,
    handle_job_cancel,
)

# Endpoint -> handler function.  Add new endpoints here.
POST_HANDLERS = {
    "/exec":           handle_exec,
    "/batch":          handle_batch,
    "/query":          handle_query,
    "/get_node_tree":  handle_get_node_tree,
    "/get_parms":      handle_get_parms,
    "/set_parms":      handle_set_parms,
    "/get_attribs":    handle_get_attribs,
    "/attrib_info":    handle_attrib_info,
    "/attrib_stats":   handle_attrib_stats,
    "/attrib_values":  handle_attrib_values,
    "/create_node":    handle_create_node,
    "/delete_node":    handle_delete_node,
    "/scene_snapshot": handle_scene_snapshot,
    "/scene_observe":  handle_scene_observe,
    "/screenshot":     handle_screenshot,
    "/ui_state":       handle_ui_state,
    "/node_info":      handle_node_info,
    "/undo_history":   handle_undo_history,
    "/artifact/info":  handle_artifact_info,
    "/artifact/read":  handle_artifact_read,
    "/job/start":      handle_job_start,
    "/job/status":     handle_job_status,
    "/job/list":       handle_job_list,
    "/job/cancel":     handle_job_cancel,
}
