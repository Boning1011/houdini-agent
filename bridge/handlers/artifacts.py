"""HTTP handlers for opaque bridge artifacts."""

from bridge import artifacts


def handle_artifact_info(body):
    artifact_id = body.get("id", "")
    try:
        result = artifacts.info(artifact_id)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"success": False, "error": str(exc)}, 404
    return {"success": True, "result": result}, 200


def handle_artifact_read(body):
    artifact_id = body.get("id", "")
    try:
        result = artifacts.read(
            artifact_id,
            offset=body.get("offset", 0),
            limit=body.get("limit", 64 * 1024),
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        return {"success": False, "error": str(exc)}, 404
    return {"success": True, "result": result}, 200
