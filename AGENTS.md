# Houdini Agent — Instructions for AI Coding Agents

This repo is a toolkit for AI-controlled Houdini operations. You (the AI agent) use the bridge layer to observe, reason about, and act on Houdini scenes.

## Architecture

```
AI Agent (VS Code terminal / CLI)
    ↕ HTTP JSON
bridge/server.py (runs inside Houdini)
    ↕ hou module
Houdini Scene
```

## Quick Start

1. User pastes `scripts/start_server.py` into Houdini's Python Shell (or runs it via shelf tool)
2. You use `bridge/client.py` to communicate with Houdini

```python
from bridge.client import HoudiniClient
h = HoudiniClient()            # connects to localhost:8765
h.status()                     # health check
h.exec("hou.node('/obj').createNode('geo')")
tree = h.get_node_tree("/obj")
parms = h.get_parms("/obj/geo1")

# Execute with post-exec verification
h.exec("node.parm('tx').set(5)", verify=["/obj/geo1"])
# → {"result": None, "verify": {"/obj/geo1": {errors, geo, parms, cook_time}}}

# Capture viewport screenshot (returns path, then Read it to see the image)
img = h.screenshot()           # → {"path": "...", "width": 1280, "height": 720}

# Batch: multiple ops in one round-trip, one undo group
h.batch([
    {"code": "geo = hou.node('/obj').createNode('geo', 'my_geo')"},
    {"code": "hou.node('/obj/my_geo').createNode('box')"},
    {"code": "hou.node('/obj/my_geo').layoutChildren()", "verify": ["/obj/my_geo"]},
])
```

## Bridge API

| Method | Description |
|---|---|
| `status()` | Health check — returns server info |
| `exec(code, verify=[...])` | Execute Python in Houdini; optionally verify node health after |
| `batch(ops, stop_on_error)` | Execute multiple code snippets in one round-trip (single undo group) |
| `query(expression)` | Evaluate a Python expression and return the result |
| `get_node_tree(path)` | Get node hierarchy as nested dict |
| `get_parms(node_path)` | Get all parameters of a node |
| `set_parms(node_path, parms)` | Set parameters on a node |
| `get_attribs(node_path, attrib_class)` | Get geometry attribute metadata (name, type, size) |
| `attrib_info(node_path)` | Full geometry overview — all attrib names/types across all classes |
| `attrib_stats(node_path, attribs, attrib_class, samples)` | Value stats (min/max/mean/samples) for specific attributes |
| `attrib_values(node_path, attribs, attrib_class, start, count, stride, reverse)` | Read sampled attribute values with flexible pagination |
| `ui_state()` | What the user sees: selected nodes, network editor path, current frame |
| `screenshot(output, width, height)` | Capture viewport as PNG — returns file path you can `Read` to see the image |
| `create_node(parent, type, name)` | Create a node |
| `delete_node(path)` | Delete a node — **requires user confirmation** |
| `backup(directory)` | Save a timestamped .hip backup (default: `$HIP/.agent_backups/`) |
| `list_backups(directory)` | List available .hip backups, newest first |
| `restore_backup(path)` | Load a .hip backup — **requires user confirmation** |
| `undo_history(limit)` | Get log of agent's mutating operations |

## Safety Rules

**Do freely:**
- Read any scene data (node trees, parameters, attributes, geometry)
- Create new nodes
- Modify parameters on existing nodes
- Create/modify geometry and attributes

**Ask user first:**
- Saving .hip files
- Deleting nodes
- Restoring backups (`h.restore_backup()`)
- File I/O (import/export)
- Any operation that could destroy existing work

**Always:**
- **Start every task with `h.ui_state()`** — know what the user is looking at (selected nodes, network editor path) before doing anything. Use the selection and current network as context for ambiguous requests.
- Check node existence before modifying (`h.query(f"hou.node('{path}') is not None")`)
- Wrap risky operations in try/except via exec_code
- Inspect scene state before making changes (observe → reason → act)
- Use `verify=[node_paths]` on `exec()` to get post-execution health checks (errors, geo counts, parms) in one round-trip
- Use `screenshot()` after visual changes, then `Read` the image file to verify the result visually
- Use `batch()` for multi-step operations (create + wire + set parms) — one round-trip, one undo group, faster iteration

## Quick Actions — Zero Hesitation

When the user asks you to "look at", "check", or "see" something, act immediately using the Bridge API above. Do not search the codebase for how to call these methods — just use them directly. You have vision: capture a screenshot, read the image, and respond.

## Skills

Skills live in `skills/`. Each skill is a directory with:
- `skill.md` — when to use it, what it does
- `.py` files — implementation

After solving a new type of problem, consider creating a skill so the solution is reusable.
See `skills/README.md` for the skill authoring guide.

## Context Docs

Reference material for Houdini-specific knowledge:
- `context/houdini-python.md` — hou module patterns, thread safety, common gotchas
- `context/usd-patterns.md` — USD/LOPs workflows
- `context/kinefx-patterns.md` — KineFX reference
- `context/hda-development.md` — HDA parm templates, PythonModule callbacks, rig pose mapping
- `context/operation-patterns.md` — scene reading strategy, VEX gotchas, undo API, context retrieval

Consult these before writing Houdini Python code.

## File System & Working Directory

- **This repo is a reusable toolkit** — it gets reused across many different Houdini projects. Never write project-specific files (exports, scripts, assets, caches) into this repo.
- **`$HIP` is the project root.** The user's `$HIP` folder (where the .hip file lives) is the real working directory for the current Houdini project.
- All project file I/O — reading scene files, exporting geometry, saving images, importing assets, writing scripts for the project — should target `$HIP` (or subdirectories of it), **not** this repo.
- Retrieve `$HIP` at runtime: `h.query("hou.getenv('HIP')")`
- Keep this repo clean: only commit toolkit code (bridge, skills, context docs) here.

## Key Technical Notes

- The `hou` module is **not thread-safe**. All hou calls must run on Houdini's main thread.
- The server uses `hou.ui.addEventLoopCallback` to marshal calls from the HTTP thread to the main thread.
- Default server port: **8765**
- The server returns structured JSON with `{"status": "ok", "result": ...}` or `{"status": "error", "error": ...}`
- All mutating operations are wrapped in `hou.undos` blocks — the user can **Ctrl+Z** to undo agent actions
- Before multi-step operations, use `h.backup()` as a safety net
