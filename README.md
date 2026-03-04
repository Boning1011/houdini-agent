# Houdini Agent

A toolkit that lets AI agents (Claude Code) control SideFX Houdini from the outside via a Python bridge.

## How It Works

```
Claude Code (VS Code terminal)
    ↕ HTTP JSON
bridge/server.py (runs inside Houdini)
    ↕ hou module
Houdini Scene
```

A lightweight HTTP server runs inside Houdini. An external Python client sends commands and queries over JSON. The server marshals all calls to Houdini's main thread for thread safety.

## Quick Start

1. **Start the server in Houdini**

   In Houdini's Python Shell, run:
   ```python
   import sys
   sys.path.insert(0, r"C:\path\to\houdini-agent")  # adjust path
   from bridge.server import start_server
   start_server()
   ```

   Or paste the contents of `scripts/start_server.py`.

2. **Connect from outside**

   ```python
   from bridge.client import HoudiniClient
   h = HoudiniClient()  # localhost:8765
   h.status()            # → hip file, frame, fps
   h.create_node("/obj", "geo", "my_geo")
   h.set_parms("/obj/my_geo/box1", {"sizex": 2.0})
   ```

## Repo Structure

```
├── CLAUDE.md              # Instructions for Claude Code
├── bridge/
│   ├── server.py          # Houdini-side HTTP server
│   └── client.py          # External Python client
├── skills/
│   ├── README.md          # Skill authoring guide
│   └── examples/          # Example skills
├── context/
│   ├── houdini-python.md  # hou module reference
│   ├── usd-patterns.md    # USD/LOPs patterns
│   └── kinefx-patterns.md # KineFX reference
└── scripts/
    └── start_server.py    # Quick-start for Houdini
```

## API

| Client Method | Description |
|---|---|
| `status()` | Health check |
| `exec_code(code)` | Run Python in Houdini |
| `query(expr)` | Evaluate expression, return result |
| `get_node_tree(path, depth)` | Node hierarchy as dict |
| `get_parms(path)` | Read all parameters |
| `set_parms(path, parms)` | Set parameters |
| `get_attribs(path, class)` | Geometry attribute info |
| `create_node(parent, type, name)` | Create node |
| `delete_node(path)` | Delete node |
| `node_exists(path)` | Check if node exists |
