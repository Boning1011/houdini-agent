"""
Handler registry — maps endpoint paths to handler functions.

Each handler has the signature:
    handle(body: dict) -> (response_dict, status_code)
"""

from bridge.handlers.exec import handle_exec, handle_query
from bridge.handlers.scene import (
    handle_status,
    handle_get_node_tree,
    handle_create_node,
    handle_delete_node,
    handle_scene_snapshot,
    handle_undo_history,
)
from bridge.handlers.parms import handle_get_parms, handle_set_parms
from bridge.handlers.geometry import (
    handle_get_attribs,
    handle_attrib_info,
    handle_attrib_stats,
    handle_attrib_values,
)

# Endpoint -> handler function.  Add new endpoints here.
POST_HANDLERS = {
    "/exec":           handle_exec,
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
    "/undo_history":   handle_undo_history,
}
