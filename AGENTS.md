# Houdini Agent — Instructions for AI Coding Agents

This repo is a toolkit for AI-controlled Houdini operations. You (the AI agent) use the bridge layer to observe, reason about, and act on Houdini scenes.

## Architecture & Quick Start

`AI agent ↔ HTTP/JSON ↔ bridge/server.py (runs inside Houdini) ↔ hou`. Full setup and the complete API live in `README.md`.

The user starts the bridge (`scripts/start_server.py` or the panel); you drive it via `bridge/client.py`:

```python
from bridge.client import HoudiniClient
h = HoudiniClient()                                    # auto-discovers; pass port=N if multiple instances
h.exec("node.parm('tx').set(5)", verify=["/obj/geo1"])  # exec + post-edit health check, one round-trip
h.batch([                                              # multi-op, one round-trip, one undo group
    {"code": "geo = hou.node('/obj').createNode('geo','my_geo')"},
    {"code": "hou.node('/obj/my_geo').createNode('box')"},
    {"code": "hou.node('/obj/my_geo').layoutChildren()", "verify": ["/obj/my_geo"]},
])
```

## Bridge API (cheatsheet — full signatures in `bridge/client.py`)

- **Write:** `exec(code, verify=[paths])`, `batch(ops, stop_on_error)`, `create_node`, `set_parms`, `delete_node` (confirm)
- **Read scene:** `status()`, `ui_state()`, `scene_snapshot(path, depth)`, `node_info(path | paths=[...])`, `get_node_tree`, `get_parms`, `query(expr)`
- **Read geometry (progressive):** `attrib_info(path | paths=[...])` → `attrib_stats` → `attrib_values`
- **Visual:** `screenshot()` → then `Read` the returned path to see the image
- **Safety:** `backup()`, `list_backups()`, `undo_history()`, `restore_backup` (confirm)

`node_info` and `attrib_info` accept `paths=[...]` to read many nodes in one round-trip.

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
- OpenCL (SOP or COP) → read `context/opencl-patterns.md`
- COPs Python Snippet (`cop/pythonsnippet`) → read `context/cops-python-snippet.md`
  (this is **not** the same as OpenCL COPs and **not** the same as general `hou`
  Python — it has its own `kwargs`/`return-dict`/`ImageLayer` API)
- Scene operations, VEX, undo → read `context/operation-patterns.md`
- USD/LOPs → read `context/usd-patterns.md`
- KineFX → read `context/kinefx-patterns.md`
- hou module, thread safety → read `context/houdini-python.md`

Read **only the one doc** that matches the task. If none clearly matches, proceed without reading — do **not** read context docs "just in case" (reading all of them is ~16k tokens). Reach for another only when you actually hit something you can't resolve. When you delegate to a subagent, name the exact doc it should read (or tell it none is needed) — don't let it discover by scanning.

## Quick Actions — Zero Hesitation

When the user asks you to "look at", "check", or "see" something, act immediately using the Bridge API above. Do not search the codebase for how to call these methods — just use them directly. You have vision: capture a screenshot, read the image, and respond.

## Network Construction Style

Build networks a human can read at a glance: **one node = one clear operation**, named so its purpose is obvious without opening VEX; never hide unrelated logic inside a wrangle; use dedicated SOPs (`Group Create`, `Attribute Delete`, `Blast`) over one-line wrangles. Full rules in `context/network-layout.md`.

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
- `context/opencl-patterns.md` — OpenCL (SOP & COP), binding differences, silent-failure traps, SideFX example HDAs
- `context/cops-python-snippet.md` — `cop/pythonsnippet` API (kwargs / return-dict / ImageLayer), HDA-wrapping pitfalls
- `context/operation-patterns.md` — scene reading strategy, VEX gotchas, undo API, context retrieval
- `context/network-layout.md` — node positioning, network boxes, layout workflow
- `context/multi-agent-orchestration.md` — running parallel subagents (one instance = one writer)

Consult these before writing Houdini Python code.

## File System & Working Directory

- **This repo is a reusable toolkit** — it gets reused across many different Houdini projects. Never write project-specific files (exports, scripts, assets, caches) into this repo.
- **`$HIP` is the project root.** The user's `$HIP` folder (where the .hip file lives) is the real working directory for the current Houdini project.
- All project file I/O — reading scene files, exporting geometry, saving images, importing assets, writing scripts for the project — should target `$HIP` (or subdirectories of it), **not** this repo.
- Retrieve `$HIP` at runtime: `h.query("hou.getenv('HIP')")`
- Keep this repo clean: only commit toolkit code (bridge, skills, context docs) here.

## Session Reflection — Self-Evolution Loop

After significant work (multi-step tasks, debugging, HDA dev) — or when asked, or after friction/detours — write a reflection to `reflections/YYYY-MM-DD-topic.md` (format in `reflections/_TEMPLATE.md`). The high-value parts: **Toolkit Improvement Opportunities** (what should change in the codebase) and a specific **Waste Analysis** (exact calls, round-trip counts, context cost). A pattern seen in 2+ reflections should become a concrete change — a context doc, skill, API improvement, or AGENTS.md update.

## Key Technical Notes

- The `hou` module is **not thread-safe**. All hou calls must run on Houdini's main thread.
- The server uses `hou.ui.addEventLoopCallback` to marshal calls from the HTTP thread to the main thread.
- Default server port: **8765** — when busy (another Houdini instance), the server walks up to 8780.
- Multiple Houdinis: each running bridge writes a JSON entry to `%TEMP%/houdini_agent/instances/<pid>.json`. `HoudiniClient()` with no `port=` argument auto-discovers via that registry, pings each `/status` to prune dead entries, and picks by `hip_file` ⊂ `cwd`. If still ambiguous it raises with the full list — pass `port=N` to choose. Use `HoudiniClient.list_instances()` to see them all.
- The server returns structured JSON with `{"status": "ok", "result": ...}` or `{"status": "error", "error": ...}`
- All mutating operations are wrapped in `hou.undos` blocks — the user can **Ctrl+Z** to undo agent actions
- Before multi-step operations, use `h.backup()` as a safety net

## Architecture — Thin Server, Rich Client

**The server (`bridge/server.py`) must stay minimal.** It provides a small set of primitive endpoints (`exec`, `batch`, `query`, `scene_snapshot`, etc.) that run on Houdini's main thread. Do NOT add new server routes for convenience methods.

**All higher-level helpers belong in the client (`bridge/client.py`).** They compose existing primitives — just like `backup()`, `node_exists()`, and `list_backups()` already do. This keeps the server stable (no restart needed for new features) and the client easy to extend.
