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

### Connection Tracing — MANDATORY Rule

> **NEVER trace connections one node at a time with repeated `query()` calls.**
> `scene_snapshot` already returns the full connection graph (`inputs`/`outputs` per node) in a single call. Trace client-side — zero extra round-trips.

This was the #1 waste pattern across multiple sessions (8+ unnecessary round-trips each time). If you find yourself calling `node.input(0).path()` or `node.outputs()` in a loop, you are doing it wrong.

```python
# ONE call — gets the entire connection graph
snap = h.scene_snapshot("/obj/EXAMPLES/risograph", depth=1)
# snap is {node_path: {type, inputs, outputs, parms, ...}}

# Trace upstream client-side — no additional Houdini calls
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

**Exception — very large networks (100+ nodes):** If you only need one chain and the network is huge, an `exec` trace on the server side is more efficient than snapshotting the whole network:

```python
h.exec('''
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
- **Stick to ASCII in any code-bearing parm sent through the bridge** (VEX snippets, OpenCL `kernelcode`, Python sops). Non-ASCII characters (em-dash, smart quotes, CJK) can become `\ufffd` mojibake in transit and break parsing silently — the symptom is an opaque error like `Binding named '' has invalid name` from a single bad byte in a comment. ASCII-only comments are the safe default.

## SOP Solver / DOPnet Cooking — Critical Gotcha

**`hou.setFrame(N)` alone does NOT make a SOP Solver advance the simulation when you read it programmatically.** The DOPnet caches its last-cooked state and `cook(force=True)` on a downstream SOP only re-runs *that SOP*, not the upstream DOPnet. Reading `attrib_stats` / `attrib_values` after `setFrame` will silently return the same data for every frame, making it look like your VEX update is broken when it isn't.

**The fix:** explicitly cook the dopnet at the new frame before reading any downstream node:

```python
h.exec(f'hou.setFrame({f})')
h.exec('hou.node("/obj/geo1/my_solver/d").cook(force=True)')   # ← required
h.exec('hou.node("/obj/geo1/OUT").cook(force=True)')
stats = h.attrib_stats('/obj/geo1/OUT', ['my_attr'])
```

The DOPnet sits at `<solver_sop>/d` (a `dopnet` child of the Solver SOP wrapper). Inside it the actual SOP Solver DOP is `<solver_sop>/d/s`, and the user-edited SOP context (with your wrangle) is the children of `s`.

A second symptom: if you call `resimulate.pressButton()` to reset, you must *also* `cook(force=True)` the dopnet — pressing the button alone just marks it dirty.

When the user plays the timeline interactively (playbar ▶), this isn't a problem — playbar drives the dopnet's cook signal. The gotcha only bites when an agent is scrubbing programmatically.

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

## OpenCL SOP @-binding — Critical Gotchas

The SOP `opencl` node and its COP cousin share the modern `atbinding=1` + `#bind` directive + `@KERNEL { }` framework, but each has functions the other doesn't (COPs: `.bufferIndex()`, `.worldSample()`, `@ix/@iy`; SOPs: `@elemnum`, `.getAt(j)`, `.len`). The `kernelcode` parm convention noted under "COP-Specific Patterns" applies to SOP OpenCL nodes too.

**The four silent-failure traps to check first when an OpenCL SOP misbehaves:**

1. **`bindings = 1` legacy default poisons parsing.** A fresh `opencl` SOP starts with one empty entry in the legacy `bindings` multiparm (the manual binding UI). Under `atbinding=1` that empty entry errors at cook time with `Binding named '' has invalid name` even though your `#bind` directives in the kernel are perfectly fine. **Always `node.parm("bindings").set(0)` after creating the node.** Working SideFX example nodes confirm `bindings=0`.

2. **`@WRITEBACK { }` requires `usewritebackkernel = 1`.** The block is silently ignored without the checkbox — no error, the simulation just looks frozen because the writeback never runs and the real attribute never gets updated from the temp. Always set the parm explicitly when using a writeback block:
   ```python
   node.parm("usewritebackkernel").set(1)
   ```

3. **`!&` write-only attributes do NOT auto-create**, despite what the official examples imply. The kernel will error with `Invalid attribute 'X'`. Pre-create the attribute with an upstream `attribcreate::2.0` (set `numattr`, then `name1`, `class1=2` for point, `type1=0` for float, `size1` 1 for scalar / 3 for vector). Even Houdini's own `opencl1` example (`#bind point !&foo float`) errors when run standalone — it relies on an unseen upstream node creating `foo`.

4. **`#bind parm name float val=4.0` does NOT reliably link to a spare parm.** Adding a spare parm with the same name and a `ch("…")` expression looks like it should work, but the kernel may use the baked-in `val=` default depending on compile cache state. The failure mode is silent: parm changes have no effect on the simulation. **For any parameter that needs to come from outside the OpenCL node, use the detail-attribute pattern instead:**
   ```c
   // in kernel
   #bind detail _muK float
   @KERNEL { float muK = @_muK; ... }
   ```
   ```vex
   // upstream attribwrangle, "Run Over: Detail"
   f@_muK = ch("../../../muK");
   ```
   Detail attribs are read fresh every cook with no caching surprises. This is the only pattern verified to work for live parameter linking.

**Two more traps for the writeback swap pattern (read-neighbors-write-self):**
- The temp attribute used in writeback must be `&` (read+write), not `!&`. `@WRITEBACK` reads the temp to copy it back to the real attribute, so write-only fails with `Attribute 'X' must be readable.`
- The two-pass swap (`@KERNEL` writes `@P_new`, `@WRITEBACK { @P.set(@P_new); }`) is the canonical race-free way to update an attribute that other threads are reading via `getAt(j)`. See `topo_neighbours` example.

**SOP @-binding quick reference** (verified against `houdini/help/examples/nodes/sop/opencl/SimpleOpenCLSOPSnippets.hda`):

| Need | Syntax |
|---|---|
| Current element index | `@elemnum` |
| Total element count | `@P.len` |
| Read another element's value | `@P.getAt(j)` (returns the bound type) |
| Read-only point attrib | `#bind point P float3` |
| Read+write point attrib | `#bind point &P float3` |
| Write-only (must pre-create!) | `#bind point !&U float` |
| Detail attribute | `#bind detail _muK float` |
| Run-once detail attribwrangle | `attribwrangle.parm("class").set(0)` (0=detail, 2=points) |
| Writeback swap | `@KERNEL { @temp.set(...) }` + `@WRITEBACK { @real.set(@temp); }` |

To explore more patterns (topology arrays, prim/vertex loops, vdb sampling, matrix ops), install the example HDA and dump `kernelcode` from each `opencl` child:

```python
hou.hda.installFile(r"C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/examples/nodes/sop/opencl/SimpleOpenCLSOPSnippets.hda")
# then instantiate the resulting nodetype under /obj and walk allSubChildren()
```

This is the canonical SideFX reference for SOP OpenCL — far more complete than the online docs.

## HDA Batch Creation

**Never batch-create multiple HDA instances in rapid succession.** HDAs can trigger dependency loading (NAS paths, other HDAs) that blocks Houdini's main thread or crashes it. Create one at a time with verification between each.

## Context Retrieval

- `scene_snapshot(path, depth)` is the primary tool — one call returns nodes, connections, non-default parms, flags, errors
- Only drill into `get_parms()` for a specific node when you need ALL parameters (including defaults)
- `get_attribs()` for geometry attribute inspection (point/prim/vertex/detail)
