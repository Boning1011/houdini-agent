# Houdini Agent

A toolkit that lets AI agents (Claude Code) control SideFX Houdini from the outside via a Python bridge.

## The Thinking Behind This

I've been using Houdini for over eight years. It's the most powerful tool I have, and also the one where I spend the most time on work that requires expertise but not necessarily human judgment — debugging VEX, tracing attribute flows, navigating deep node graphs to find where something went wrong.

When coding agents got good enough to hold context across real multi-step tasks, I realized: Houdini is a visual programming environment built on Python. Give an agent access to that Python layer with enough context about how Houdini works, and it can handle a surprising amount of the execution while I focus on the decisions.

That's what this is. Not a demo — a production tool I use every day.

### Design choices

**Thin, general interface.** The bridge is a few hundred lines marshalling `hou` calls over HTTP. The agent writes Python directly, the same way I would in Houdini's Python Shell. I chose not to wrap common operations into specialized endpoints because Houdini's power comes from composability — any fixed workflow I pre-build becomes a constraint the moment I need something different. Instead, structured endpoints handle *reading* (scene snapshots, geometry inspection, node info), while *writing* is `exec()` and `batch()` with the full expressiveness of the `hou` module. This design gets more useful over time without changes: as agents get better at reasoning, this same thin interface lets them do more.

**Context over code.** Instead of hard-coding Houdini knowledge into the bridge, I keep it in plain Markdown files (`context/`). Eight years of "here's how you actually do this" — VEX patterns, HDA conventions, KineFX workflows — in a form the agent can read before acting. When Houdini changes or I learn a better pattern, I update a text file, not the codebase.

**Built to last.** HTTP, JSON, Python, undo blocks. No framework dependencies, no abstractions that might not age well. The less there is to break, the longer it lasts. I want to still be using this a year from now, through Houdini upgrades and whatever the next generation of agents looks like.

---

## How It Works

```
AI Agent (VS Code terminal / CLI)
    ↕ HTTP JSON
bridge/server.py (runs inside Houdini)
    ↕ hou module
Houdini Scene
```

A lightweight HTTP server runs inside Houdini. An external Python client sends commands and queries over JSON. The server marshals all calls to Houdini's main thread for thread safety. All mutating operations are wrapped in `hou.undos` blocks — the user can **Ctrl+Z** to undo agent actions.

## Setup

All scripts and panels locate the repo via the **`HOUDINI_AGENT_ROOT`** environment variable. Set it once and everything works — no hardcoded paths.

### Option 1: Houdini Package (recommended for teams)

Create a package JSON in `~/Documents/houdiniX.X/packages/` (e.g. `houdini_agent.json`):

```json
{
    "env": [
        { "HOUDINI_AGENT_ROOT": "C:/path/to/houdini-agent" }
    ],
    "path": "$HOUDINI_AGENT_ROOT"
}
```

This sets the env var automatically when Houdini launches and works across all team machines (each with their own package file pointing to their local clone).

### Option 2: System environment variable

Set `HOUDINI_AGENT_ROOT` in your OS environment (Windows: System Properties > Environment Variables, or your shell profile). Houdini will inherit it on launch.

## Quick Start

### Option A: Python Panel (recommended)

1. In Houdini's Python Shell, run:
   ```python
   exec(open(r"C:\path\to\houdini-agent\scripts\install_panel.py").read())
   ```
2. Restart Houdini (or refresh panels).
3. Open **New Pane Tab Type > Houdini Agent** — click **Start Server**.

The panel provides Start/Stop controls, port config, status display, and a live log. It also hot-reloads bridge code on each start, so you don't need to restart Houdini after code changes.

### Option B: Python Shell

In Houdini's Python Shell:
```python
from bridge.server import start_server
start_server()
```

### Connect from outside

```python
from bridge.client import HoudiniClient
h = HoudiniClient()               # localhost:8765
h.status()                         # hip file, houdini version, fps, etc.

# Execute code in Houdini
h.exec("hou.node('/obj').createNode('geo')")

# Execute with post-exec verification
h.exec("node.parm('tx').set(5)", verify=["/obj/geo1"])
# → {"result": None, "verify": {"/obj/geo1": {errors, geo, parms, cook_time}}}

# Batch: multiple ops in one round-trip, one undo group
h.batch([
    {"code": "geo = hou.node('/obj').createNode('geo', 'my_geo')"},
    {"code": "hou.node('/obj/my_geo').createNode('box')"},
    {"code": "hou.node('/obj/my_geo').layoutChildren()", "verify": ["/obj/my_geo"]},
])

# Capture viewport screenshot
img = h.screenshot()               # → {"path": "...", "width": 1280, "height": 720}
```

## API

### Core

| Method | Description |
|---|---|
| `status()` | Health check — returns server info, hip file, Houdini version |
| `exec(code, verify=[...])` | Execute Python in Houdini; optionally verify node health after |
| `batch(ops, stop_on_error)` | Multiple code snippets in one round-trip (single undo group) |
| `query(expression)` | Evaluate a Python expression and return the result |

### Scene & Nodes

| Method | Description |
|---|---|
| `get_node_tree(path, depth)` | Node hierarchy as nested dict |
| `scene_snapshot(path, depth)` | Rich snapshot — nodes, connections, non-default parms, flags, errors |
| `node_info(node_path)` or `node_info(paths=[...])` | Full node info tree (MMB popup) — cook time, geo counts, attribs, memory, bbox. Batch mode supported |
| `create_node(parent, type, name)` | Create a node |
| `delete_node(path)` | Delete a node |
| `node_exists(path)` | Check if a node exists |
| `ui_state()` | What the user sees: selected nodes, network editor path, current frame |

### Parameters

| Method | Description |
|---|---|
| `get_parms(node_path)` | Read all parameters of a node |
| `set_parms(node_path, parms)` | Set parameters on a node |

### Geometry Attributes

| Method | Description |
|---|---|
| `get_attribs(node_path, class)` | Attribute metadata for a single class |
| `attrib_info(node_path)` or `attrib_info(paths=[...])` | Full geometry overview — all attrib names/types across all classes. Batch mode supported |
| `attrib_stats(node_path, attribs, class, samples)` | Value stats: min/max/mean/samples for numeric, unique/top for strings |
| `attrib_values(node_path, attribs, class, start, count, stride, reverse)` | Read sampled attribute values with flexible pagination |

### Viewport

| Method | Description |
|---|---|
| `screenshot(output, width, height)` | Capture viewport as PNG — returns file path |

### Undo & Backup

| Method | Description |
|---|---|
| `undo_history(limit)` | Log of agent's mutating operations |
| `backup(directory)` | Save a timestamped .hip backup (default: `$HIP/.agent_backups/`) |
| `list_backups(directory)` | List available .hip backups, newest first |
| `restore_backup(path)` | Load a .hip backup |

## Repo Structure

```
├── AGENTS.md                      # Instructions for AI coding agents
├── bridge/
│   ├── server.py                  # Houdini-side HTTP server
│   ├── client.py                  # External Python client
│   ├── main_thread.py             # Main-thread marshalling
│   └── handlers/
│       ├── exec.py                # Code execution & batch
│       ├── scene.py               # Node tree, snapshot, ui_state
│       ├── parms.py               # Parameter read/write
│       ├── geometry.py            # Attribute info/stats/values
│       └── viewport.py            # Screenshot capture
├── panels/
│   ├── houdini_agent.pypanel      # PythonPanel definition
│   └── houdini_agent_panel.py     # Panel UI (Start/Stop, status, log)
├── skills/
│   ├── README.md                  # Skill authoring guide
│   └── examples/                  # Example skills
├── context/
│   ├── houdini-python.md          # hou module reference
│   ├── usd-patterns.md            # USD/LOPs patterns
│   ├── kinefx-patterns.md         # KineFX reference
│   ├── hda-development.md         # HDA parm templates, callbacks, rig mapping
│   └── operation-patterns.md      # Scene reading, VEX gotchas, undo API
└── scripts/
    ├── start_server.py            # Quick-start for Houdini Python Shell
    └── install_panel.py           # One-time panel installer
```

## Key Features

- **Thread-safe execution** — all `hou` calls are marshalled to Houdini's main thread
- **Verify on exec** — pass `verify=[node_paths]` to get post-execution health checks (errors, geometry counts, parms, cook time) in one round-trip
- **Batch operations** — multiple code snippets in a single dispatch, wrapped in one undo group
- **Undo support** — every mutation is wrapped in `hou.undos` blocks; users can Ctrl+Z agent actions
- **Backups** — timestamped .hip snapshots before risky operations
- **Viewport capture** — screenshot the viewport at native resolution, then use AI vision to verify visual results
- **Geometry inspection** — progressive drill-down: `attrib_info` → `attrib_stats` → `attrib_values`
- **Scene snapshots** — one call to get nodes, connections, non-default parms, flags, and errors for an entire network
- **Python Panel UI** — Start/Stop server with a GUI inside Houdini, with hot-reload on each start

## For AI Agent Authors

See [AGENTS.md](AGENTS.md) for full instructions on how AI agents should use this toolkit, including safety rules, context docs, and workflow patterns.
