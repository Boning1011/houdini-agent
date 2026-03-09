<!-- houdini_version: 21.0 -->
# Houdini Operation Patterns

## Reading Complex Houdini Scenes — Reverse Tracing

Professional approach to understanding unfamiliar/complex .hip files:

**Always trace backwards from outputs, never forwards from inputs.**

1. Find all final render outputs (ROP Image, USD Render, filecache marked as final, etc.)
2. Trace each output's input chain upstream — only what's connected matters
3. Everything not in the dependency chain of an actual output is either deprecated, experimental, or abandoned
4. This is especially critical for files with many iterations — most nodes may be historical dead ends

This is the Houdini equivalent of "follow the money" — follow the render.

## Scene Building

- **Atomic operations**: Put node creation + wiring + flag setting in a single `exec()` call to avoid partial state (e.g. duplicate nodes when first call succeeds but second fails)
- **VEX snippets**: Set via `set_parms()` separately after node creation — avoids Python string escaping nightmares with VEX's backslashes and quotes
- **Verify after build**: Use `scene_snapshot()` to confirm the network is correct and error-free in one call
- **Idempotency**: Check `node_exists()` before `create_node()` to avoid duplicates on retry

## VEX Gotchas

- `vector(x, y, z)` does NOT work in VEX — use `set(x, y, z)` instead
- Always use raw strings (`r"""..."""`) for VEX code in Python to avoid escape issues

## Undo API (Houdini 21.0)

- Use `hou.undos.group(label)` as a **context manager**, NOT `beginBlock/endBlock` (that's an older API)
- `hou.undos` module members: `group`, `disabler`, `areEnabled`, `performUndo`, `performRedo`, `undoLabels`, `redoLabels`, `clear`, `memoryUsage`
- Empty undo groups (no mutations inside) are harmless — Houdini ignores them

## Context Retrieval

- `scene_snapshot(path, depth)` is the primary tool — one call returns nodes, connections, non-default parms, flags, errors
- Only drill into `get_parms()` for a specific node when you need ALL parameters (including defaults)
- `get_attribs()` for geometry attribute inspection (point/prim/vertex/detail)
