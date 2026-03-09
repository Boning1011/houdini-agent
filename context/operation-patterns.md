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

### How to trace with existing API

**Use `scene_snapshot`, not one-by-one queries.** The snapshot returns `inputs` and `outputs` for every node — you already have the full connection graph in one call. Trace client-side:

```python
snap = h.scene_snapshot("/obj/EXAMPLES/risograph", depth=1)
# snap is {node_path: {type, inputs, outputs, parms, ...}}

# To trace upstream from a specific node, just walk the dict:
def trace_upstream(snap, node_path, visited=None):
    if visited is None: visited = set()
    if node_path in visited: return []
    visited.add(node_path)
    chain = [node_path]
    info = snap.get(node_path, {})
    for inp in (info.get("inputs") or []):
        if inp: chain.extend(trace_upstream(snap, inp, visited))
    return chain
```

**Do NOT trace connections with repeated `query()` calls** (e.g., querying `node.input(0).path()` one node at a time). This was the #1 waste pattern in HDA analysis sessions — it took ~8 round-trips for something `scene_snapshot` returns in 1.

For networks with 100+ nodes where you only care about one chain, an `exec_code` trace is more efficient than snapshotting the whole network:

```python
h.exec_code('''
visited = {}
def trace(node, depth=0):
    if depth > 20 or node.path() in visited: return
    inputs = []
    for i in range(min(len(node.inputConnectors()), 10)):
        inp = node.input(i)
        inputs.append(inp.name() if inp else None)
        if inp: trace(inp, depth+1)
    visited[node.path()] = {"type": node.type().name(), "inputs": inputs}
trace(hou.node("/obj/EXAMPLES/risograph/outputs"))
''', 'visited')
```

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

## COP-Specific Patterns

- **Multiparm ordering**: Always set the multiparm count first (e.g., `aovs=1`) before accessing instance parms (`aov1`, `type1`). The instance parms don't exist until the count is set. This applies broadly across Houdini, not just COP file nodes
- **COP constant node signatures**: `signature=f3` → parms are `f3r/f3g/f3b`; `signature=f4` → `f4r/f4g/f4b/f4a`; `signature=f1` → `f1` (scalar). Don't guess — check `signature` parm first
- **OpenCL kernel code**: COP OpenCL nodes store code in `kernelcode` parm, not `source`. The full `get_parms` on these nodes returns ~4KB of binding metadata alongside the actual kernel — if you only want the code, extract `kernelcode` specifically
- **COP switch `maxNumInputs()`**: Returns ~256 slots. Never use it for iteration bounds — use a small fixed range (e.g., `range(10)`) with None filtering
- **COP `inputConnectors()`**: Returns raw tuples in H21, not named objects. `.label()` does not exist. There's no reliable programmatic way to determine if a COP HDA expects mono vs RGB input — check the HDA's documentation or parameter interface instead
- **`cook(force=True)` on untested HDAs**: Some HDAs fail on first programmatic cook but work fine interactively. Safer to skip force_cook or wrap in `try/except` when building example scenes

## HDA Batch Creation

**Never batch-create multiple HDA instances in rapid succession.** HDAs can trigger dependency loading (NAS paths, other HDAs) that blocks Houdini's main thread or crashes it. Create one at a time with verification between each.

## Context Retrieval

- `scene_snapshot(path, depth)` is the primary tool — one call returns nodes, connections, non-default parms, flags, errors
- Only drill into `get_parms()` for a specific node when you need ALL parameters (including defaults)
- `get_attribs()` for geometry attribute inspection (point/prim/vertex/detail)
