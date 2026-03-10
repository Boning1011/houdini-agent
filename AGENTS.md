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
| `scene_snapshot(path, depth)` | Rich snapshot — nodes, connections, non-default parms, flags, errors |
| `node_info(node_path)` or `node_info(paths=[...])` | Full node info (MMB popup) — cook time, geo counts, attribs, memory, bbox. Batch mode for multiple nodes in one round-trip |
| `get_parms(node_path)` | Get all parameters of a node |
| `set_parms(node_path, parms)` | Set parameters on a node |
| `attrib_info(node_path)` or `attrib_info(paths=[...])` | Geometry overview — counts + attrib names/types. Batch mode for multiple nodes in one round-trip |
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

## Progressive Inspection — Don't Over-Fetch

Scene data has three levels of detail. Use the minimum level needed — don't jump to level 3 when level 1 suffices.

**Level 1 — Network overview** (use once at task start):
```python
h.ui_state()                                    # where is the user?
h.scene_snapshot("/obj/geo1", depth=1)           # all nodes: types, connections, non-default parms, flags
```
This is like looking at the node network. `scene_snapshot` returns ~400 bytes/node and **includes the full connection graph** (`inputs`/`outputs` per node). Don't call it repeatedly after every edit — use `exec(..., verify=[paths])` for post-edit checks on specific nodes.

**Connection tracing:** After a `scene_snapshot`, trace connections **client-side** by walking the dict. Never call `query("node.input(0).path()")` in a loop — `scene_snapshot` already has this data.

**Level 2 — Single node detail** (when debugging a specific node):
```python
h.node_info("/obj/geo1/scatter1")                # MMB popup: cook time, geo counts, attrib list, memory, bbox
h.node_info(paths=["/obj/geo1/box1", "/obj/geo1/scatter1"])  # batch: multiple nodes, one round-trip
```
This is like pressing MMB on a node. Use it when you need to understand *what a node produced* — not for every node in the network.

**Level 3 — Geometry data** (when you need to understand attributes for writing VEX/Python):
```python
h.attrib_info("/obj/geo1/scatter1")              # structure: counts + attrib names/types/sizes (programmatic dict)
h.attrib_info(paths=["/obj/geo1/box1", "/obj/geo1/scatter1"])  # batch: scan multiple nodes in one round-trip
h.attrib_stats("/obj/geo1/scatter1", ["P", "N"]) # stats: min/max/mean + samples
h.attrib_values("/obj/geo1/scatter1", ["P"])      # raw values with pagination
```
This is the Geometry Spreadsheet equivalent — use it when you need to know exact attribute names, types, and which class they belong to.

**Avoid redundant calls:**
- `scene_snapshot` already includes non-default parms. Don't follow up with `get_parms` unless you specifically need default parameter values too.
- When verifying an edit, use `exec(..., verify=[paths])` — it returns errors, geo counts, and cook time in the same round-trip. Don't re-snapshot the entire network.

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
- **After saving/updating any HDA**, commit and push the `.hda`/`.hdalc` file to its git repo (see `context/hda-development.md` "Auto Git Commit & Push"). This is mandatory — every HDA save must be versioned.
- **Start every task with `h.ui_state()`** — know what the user is looking at (selected nodes, network editor path) before doing anything. Use the selection and current network as context for ambiguous requests.
- Check node existence before modifying (`h.query(f"hou.node('{path}') is not None")`)
- Wrap risky operations in try/except via exec_code
- Inspect scene state before making changes (observe → reason → act)
- Use `verify=[node_paths]` on `exec()` to get post-execution health checks (errors, geo counts, parms) in one round-trip
- Use `screenshot()` after visual changes, then `Read` the image file to verify the result visually
- Use `batch()` for multi-step operations (create + wire + set parms) — one round-trip, one undo group, faster iteration

## Context First — Read Before You Answer

Before answering any Houdini-related question or writing Houdini Python code, **read the relevant `context/` docs first**. Do not answer from memory alone.

- HDA questions → read `context/hda-development.md`
- Scene operations, VEX, undo → read `context/operation-patterns.md`
- USD/LOPs → read `context/usd-patterns.md`
- KineFX → read `context/kinefx-patterns.md`
- hou module, thread safety → read `context/houdini-python.md`

If unsure which doc is relevant, scan all of them. The cost of reading a file is near zero; the cost of a wrong answer is high.

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

## Session Reflection — Self-Evolution Loop

After completing significant work (multi-step Houdini tasks, debugging sessions, HDA development), write a reflection to `reflections/YYYY-MM-DD-brief-topic.md`. See `reflections/_TEMPLATE.md` for the format.

**When to reflect:**
- After any session where you hit friction, made detours, or discovered something new
- When the user explicitly asks
- At the end of a long session with 3+ distinct tasks

**What makes a good reflection:**
- The **Toolkit Improvement Opportunities** section is the most important — it's what drives actual changes to the codebase
- Be brutally specific in **Waste Analysis** — name exact API calls, count round-trips, estimate context cost
- **Critical Path** should be a reproducible recipe: "if I had to redo this from scratch, here's the minimum steps"

**What to do with reflections:**
- Reflections accumulate in `reflections/`. Periodically, the user (or agent) reviews them in batch to identify recurring friction and prioritize toolkit improvements.
- If a pattern appears in 2+ reflections, it should become a concrete change: a new context doc, a skill, an API improvement, or an AGENTS.md update.

## Key Technical Notes

- The `hou` module is **not thread-safe**. All hou calls must run on Houdini's main thread.
- The server uses `hou.ui.addEventLoopCallback` to marshal calls from the HTTP thread to the main thread.
- Default server port: **8765**
- The server returns structured JSON with `{"status": "ok", "result": ...}` or `{"status": "error", "error": ...}`
- All mutating operations are wrapped in `hou.undos` blocks — the user can **Ctrl+Z** to undo agent actions
- Before multi-step operations, use `h.backup()` as a safety net

## Architecture — Thin Server, Rich Client

**The server (`bridge/server.py`) must stay minimal.** It provides a small set of primitive endpoints (`exec`, `batch`, `query`, `scene_snapshot`, etc.) that run on Houdini's main thread. Do NOT add new server routes for convenience methods.

**All higher-level helpers belong in the client (`bridge/client.py`).** They compose existing primitives — just like `backup()`, `node_exists()`, and `list_backups()` already do. This keeps the server stable (no restart needed for new features) and the client easy to extend.
