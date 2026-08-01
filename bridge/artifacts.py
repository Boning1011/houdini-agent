"""Process-local artifact storage for results that are too large for JSON.

The bridge and client normally run on the same machine, but artifacts are
addressed by opaque IDs instead of arbitrary paths.  This keeps the protocol
usable for remote clients later and prevents the read endpoint from becoming a
general filesystem reader.
"""

import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid


DEFAULT_THRESHOLD = 256 * 1024
MAX_READ_SIZE = 1024 * 1024
MAX_ARTIFACTS = 128
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_lock = threading.RLock()


def _root_dir():
    path = os.path.join(
        tempfile.gettempdir(), "houdini_agent", "artifacts", str(os.getpid())
    )
    os.makedirs(path, exist_ok=True)
    return path


def _json_default(value):
    """Best-effort conversion for hou objects and other rich Python values."""
    if hasattr(value, "path") and callable(value.path):
        try:
            return {"type": type(value).__name__, "path": value.path()}
        except Exception:
            pass
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)


def _paths(artifact_id):
    if not isinstance(artifact_id, str) or not _ID_RE.match(artifact_id):
        raise ValueError("Invalid artifact id")
    root = _root_dir()
    return (
        os.path.join(root, artifact_id + ".data"),
        os.path.join(root, artifact_id + ".meta.json"),
    )


def _descriptor(meta):
    return {
        "$artifact": meta["id"],
        "kind": meta["kind"],
        "encoding": meta["encoding"],
        "size": meta["size"],
        "sha256": meta["sha256"],
        "path": meta["path"],
        "created_at": meta["created_at"],
        "preview": meta.get("preview", ""),
    }


def create(value, name=None):
    """Persist *value* and return an opaque artifact descriptor."""
    if isinstance(value, bytes):
        payload = value
        kind = "binary"
        encoding = "base64"
        preview = base64.b64encode(payload[:96]).decode("ascii")
    elif isinstance(value, str):
        payload = value.encode("utf-8")
        kind = "text"
        encoding = "utf-8"
        preview = value[:512]
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        payload = text.encode("utf-8")
        kind = "json"
        encoding = "utf-8"
        preview = text[:512]

    artifact_id = uuid.uuid4().hex
    data_path, meta_path = _paths(artifact_id)
    meta = {
        "id": artifact_id,
        "name": name,
        "kind": kind,
        "encoding": encoding,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "path": data_path,
        "created_at": time.time(),
        "preview": preview,
    }
    with _lock:
        with open(data_path, "wb") as handle:
            handle.write(payload)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, sort_keys=True)
        _prune_locked()
    return _descriptor(meta)


def _prune_locked():
    """Bound temp storage without adding a user-facing deletion workflow."""
    root = _root_dir()
    meta_files = [
        os.path.join(root, name)
        for name in os.listdir(root)
        if name.endswith(".meta.json")
    ]
    if len(meta_files) <= MAX_ARTIFACTS:
        return
    meta_files.sort(key=os.path.getmtime)
    for meta_path in meta_files[:len(meta_files) - MAX_ARTIFACTS]:
        artifact_id = os.path.basename(meta_path).split(".", 1)[0]
        try:
            data_path, _ = _paths(artifact_id)
            os.remove(data_path)
        except OSError:
            pass
        try:
            os.remove(meta_path)
        except OSError:
            pass


def externalize(value, threshold=DEFAULT_THRESHOLD, name=None):
    """Return *value* inline when small, otherwise return an artifact descriptor.

    Bytes are always artifacts because JSON has no native byte representation.
    Values that cannot be represented faithfully by JSON are normalized through
    the same conversion used by :func:`create`.
    """
    try:
        threshold = max(0, int(threshold))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD

    if isinstance(value, bytes):
        return create(value, name=name)
    if isinstance(value, str):
        if len(value.encode("utf-8")) > threshold:
            return create(value, name=name)
        return value

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    if len(payload) > threshold:
        return create(value, name=name)
    # Round-trip to guarantee the HTTP layer receives JSON-safe primitives.
    return json.loads(payload.decode("utf-8"))


def info(artifact_id):
    """Return metadata for an artifact, or raise FileNotFoundError."""
    data_path, meta_path = _paths(artifact_id)
    with _lock:
        with open(meta_path, "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    if not os.path.isfile(data_path):
        raise FileNotFoundError("Artifact data is missing: " + artifact_id)
    return _descriptor(meta)


def read(artifact_id, offset=0, limit=64 * 1024):
    """Read a bounded artifact chunk.

    Offsets and limits are measured in bytes. Binary chunks are returned as
    base64; UTF-8 text chunks use replacement characters only when a requested
    boundary splits a multibyte code point.
    """
    descriptor = info(artifact_id)
    data_path, _meta_path = _paths(artifact_id)
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), MAX_READ_SIZE))

    if descriptor["kind"] == "binary":
        with open(data_path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read(limit)
        next_offset = offset + len(chunk)
        eof = next_offset >= descriptor["size"]
        content = base64.b64encode(chunk).decode("ascii")
    else:
        with open(data_path, "rb") as handle:
            handle.seek(offset)
            raw = handle.read(limit + 4)
        cut = min(limit, len(raw))
        while cut > 0:
            try:
                content = raw[:cut].decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                if exc.reason == "unexpected end of data":
                    cut = exc.start
                else:
                    raise
        else:
            # A single UTF-8 character can be four bytes. For very small limits,
            # return that complete character so readers always make progress.
            content = None
            for expanded in range(1, min(len(raw), 4) + 1):
                try:
                    content = raw[:expanded].decode("utf-8")
                    cut = expanded
                    break
                except UnicodeDecodeError:
                    pass
            if content is None:
                raise UnicodeDecodeError(
                    "utf-8", raw, 0, min(len(raw), 4),
                    "artifact does not contain valid UTF-8",
                )
        next_offset = offset + cut
        eof = next_offset >= descriptor["size"]

    return {
        "artifact": descriptor,
        "offset": offset,
        "next_offset": next_offset,
        "eof": eof,
        "content": content,
    }


def is_descriptor(value):
    return isinstance(value, dict) and isinstance(value.get("$artifact"), str)
