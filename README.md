# Houdini Agent

Houdini Agent is an open-source toolkit created and maintained by [Bo-Ning Li](https://boningli.com). It lets AI coding agents control SideFX Houdini from the outside through a zero-dependency Python bridge.

**Design notes:** [boningli.com/blog/houdini-agent-design-philosophy](https://boningli.com/blog/houdini-agent-design-philosophy)

## The Thinking Behind This

I've been using Houdini for over eight years. It's the most powerful tool I have, and also the one where I spend the most time on work that requires expertise but not necessarily human judgment — debugging VEX, tracing attribute flows, navigating deep node graphs to find where something went wrong.

When coding agents got good enough to hold context across real multi-step tasks, I realized: Houdini is a visual programming environment built on Python. Give an agent access to that Python layer with enough context about how Houdini works, and it can handle a surprising amount of the execution while I focus on the decisions.

That's what this is. Not a demo — a production tool I use every day.

### Design philosophy

The bridge follows two rules:

1. **If the agent can figure it out, let it.** Coding agents already search docs, manage context, plan multi-step tasks, and recover from errors. Rebuilding any of that inside the bridge is wasted effort that ages poorly. No built-in LLM client, no memory system, no document indexing — the agent brings all of that.
2. **If it takes years of experience to know, write it down.** If you've used Houdini for 5, 10, 15 years, you carry knowledge the docs never teach — which approach actually holds up in production, which "correct" solution falls apart at scale, what to reach for when a scene breaks in ways you've seen before. That kind of experience compresses into a few Markdown files (`context/`), not dozens of specialized tool endpoints. When Houdini changes or a better pattern emerges, you update a text file, not the codebase.

This means the bridge is deliberately small, has zero external dependencies, and keeps only two core write operations (`exec` and `batch`). Everything else is observation, transport, safety, or scheduling infrastructure. The agent writes Python directly against the `hou` module — no preset workflows to constrain it, no specialized tool library to maintain. As agents get smarter, this same thin interface lets them do more, without code changes.

The test for adding a bridge feature is deliberately strict: **would a model ten
times smarter still need it?** The bridge owns interface limits that intelligence
cannot reason away: observation bandwidth, reliable execution, long-running
state, large-result transport, UI visibility, and recoverability. Houdini recipes
and domain workflows stay outside the core.

### Agent-agnostic

The instructions live in `AGENTS.md` — a plain Markdown file that any coding agent can read. Claude Code, Codex, Gemini CLI, or whatever comes next. No SDK integration, no API adapters. Supporting a new agent means pointing it at the same file.

### Built to last

HTTP, JSON, Python, `hou.undos`. No framework dependencies, no abstractions that might not age well. The entire bridge runs on Python's standard library and Houdini's built-in `hou` module. The less there is to break, the longer it lasts.

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

### Option A: Auto-start on launch (recommended)

With the package installed, `scripts/123.py` fires on every Houdini launch and:
- starts the bridge server automatically (no UI click needed)
- registers the Python Panel into the pane tab menu (idempotent)

Launching Houdini from the terminal is enough. Open **New Pane Tab Type > Houdini Agent** to see the green/red status dot, the listening port, and Start/Stop controls. Useful when you run multiple Houdini sessions on different ports — dock the panel in your default desktop and each window self-identifies.

- Disable autostart for one session: `HOUDINI_AGENT_AUTOSTART=0 houdini`
- Use a non-default port: `HOUDINI_AGENT_PORT=8770 houdini`
- Headless (`hython`) is detected and skipped — autostart is GUI-only

### Option B: Manual panel install

If you skipped auto-start but still want the panel:
```python
exec(open(r"C:\path\to\houdini-agent\scripts\install_panel.py").read())
```
Then **New Pane Tab Type > Houdini Agent**.

### Option C: Python Shell

In Houdini's Python Shell:
```python
from bridge.server import start_server
start_server()
```

### Option D: Headless (no GUI)

Run the bridge in a `hython` process — no Houdini window, no viewport, no event loop. The agent drives a fully headless Houdini.

```bash
hython "$HOUDINI_AGENT_ROOT/scripts/serve_headless.py" --port 8765
# Optional: load a .hip file before serving
hython "$HOUDINI_AGENT_ROOT/scripts/serve_headless.py" --hip /path/to/scene.hip
```

Run multiple instances on different ports for parallel agents on one machine. SIGINT/SIGTERM exits cleanly; the server prints its PID on startup so external scripts can target it directly. GUI-only handlers (`/screenshot`, parts of `/ui_state`) return clear errors — everything else (exec, batch, scene_snapshot, parms, geometry, undo) works the same as in GUI mode.

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

# Full report: result + stdout/stderr + timing + mutation receipt
report = h.exec(
    "node.parm('tx').set(5)",
    observe=[{"path": "/obj/geo1", "depth": 1}],
    detailed=True,
)

# Detect bridge edits and manual user edits from actual scene state
before = h.observe_scene("/obj/geo1", depth=1)
after = h.observe_scene("/obj/geo1", depth=1, since=before["token"])

# Large arbitrary values become paged artifacts instead of giant JSON responses
value = h.evaluate("build_a_large_python_value()")
if h.is_artifact(value):
    value = h.read_artifact_all(value)

# Long hou work survives client timeouts and reconnects
job = h.start_job("run_long_cache(); 'done'")
final = h.wait_job(job, timeout=3600)

# Capture the actual Houdini pane, not only the 3D viewport
network_image = h.capture("network_editor")
```

## API

### Core

| Method | Description |
|---|---|
| `status()` | Runtime capabilities plus Houdini/Python/UI/Qt and scene information |
| `exec(code, verify, return_expr, observe, detailed)` | Execute Python and optionally return streams, timing, verification, and mutation diff |
| `raw_exec(...)` | Always return the complete structured execution report |
| `batch(ops, stop_on_error, detailed)` | Multiple snippets in one round-trip and one undo group |
| `query(expression, artifact_threshold)` | Evaluate a Python expression and return the result |
| `evaluate(expression)` | Query with automatic large-result artifact storage |

### Scene & Nodes

| Method | Description |
|---|---|
| `get_node_tree(path, depth)` | Node hierarchy as nested dict |
| `scene_snapshot(path, depth)` | Rich snapshot — nodes, connections, non-default parms, flags, errors |
| `observe_scene(path, depth, since)` | Actual-state token and diff; sees manual edits and recognizes renames by session ID |
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

### Visual observation

| Method | Description |
|---|---|
| `screenshot(output, width, height)` | Capture viewport as PNG — returns file path |
| `capture(target, ...)` | Capture `network_editor`, `parameters`, `pane`, `window`, or `desktop` |

### Artifacts & long jobs

| Method | Description |
|---|---|
| `artifact_info(ref)` | Metadata, size, hash, kind, and path for an opaque result artifact |
| `read_artifact(ref, offset, limit)` | Read one bounded artifact chunk |
| `read_artifact_all(ref)` | Reassemble and decode a complete artifact |
| `start_job(code, ...)` | Queue main-thread Houdini work and immediately return a reconnectable ID |
| `job_status(id)` / `list_jobs()` | Poll one job or discover retained jobs after reconnecting |
| `wait_job(id, timeout)` | Client-side polling; timeout does not discard the Houdini job |
| `cancel_job(id)` | Cancel queued work; running arbitrary cooks use cooperative cancellation only |

### Cross-version behavior

The bridge does not maintain a hand-authored Houdini-version decision table.
`status()` reports Python, UI/Qt availability, and protocol capabilities at
runtime. Features probe the available API and return a structured error or
fallback when unavailable. The contract suite runs in GUI Houdini and disposable
headless `hython`; current coverage includes Houdini 21 / Python 3.11 and Houdini
22 / Python 3.13.

### Undo & Backup

| Method | Description |
|---|---|
| `undo_history(limit)` | Log of agent's mutating operations |
| `backup(directory)` | Save a timestamped .hip backup (default: `$HIP/.agent_backups/`) |
| `list_backups(directory)` | List available .hip backups, newest first |
| `restore_backup(path)` | Load a .hip backup |

## Tests

The contract suite is standard-library `unittest`, so it runs under system
Python and Houdini's bundled Python without installing anything:

```bash
python -m unittest discover -s tests -v
hython -m unittest discover -s tests -v
```

For a real disposable headless bridge, start
`tests/hython_server_runner.py <port>` with any `hython`, then run
`python tests/integration_headless_client.py <port>`. The integration process
uses a new empty scene and never saves it.

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
