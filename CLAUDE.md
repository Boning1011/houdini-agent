# Houdini Agent — Instructions for Claude Code

This repo is a toolkit for AI-controlled Houdini operations. You (Claude Code) use the bridge layer to observe, reason about, and act on Houdini scenes.

## Architecture

```
Claude Code (VS Code terminal)
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
h.exec_code("hou.node('/obj').createNode('geo')")
tree = h.get_node_tree("/obj")
parms = h.get_parms("/obj/geo1")
```

## Bridge API

| Method | Description |
|---|---|
| `status()` | Health check — returns server info |
| `exec_code(code)` | Execute arbitrary Python in Houdini's main thread |
| `query(expression)` | Evaluate a Python expression and return the result |
| `get_node_tree(path)` | Get node hierarchy as nested dict |
| `get_parms(node_path)` | Get all parameters of a node |
| `set_parms(node_path, parms)` | Set parameters on a node |
| `get_attribs(node_path, attrib_class)` | Get geometry attributes |
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
- Check node existence before modifying (`h.query(f"hou.node('{path}') is not None")`)
- Wrap risky operations in try/except via exec_code
- Inspect scene state before making changes (observe → reason → act)

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

Consult these before writing Houdini Python code.

## Key Technical Notes

- The `hou` module is **not thread-safe**. All hou calls must run on Houdini's main thread.
- The server uses `hou.ui.addEventLoopCallback` to marshal calls from the HTTP thread to the main thread.
- Default server port: **8765**
- The server returns structured JSON with `{"status": "ok", "result": ...}` or `{"status": "error", "error": ...}`
- All mutating operations are wrapped in `hou.undos` blocks — the user can **Ctrl+Z** to undo agent actions
- Before multi-step operations, use `h.backup()` as a safety net
