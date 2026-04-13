<!-- houdini_version: 21.0 -->
# OpenCL SOP Patterns

This document is a **harness, not a tutorial**. It records only things that are
inherent to Houdini's OpenCL implementation — hidden behaviors where the error
message is misleading or entirely absent. These traps are **independent of model
capability**: even a much smarter model hitting SOP OpenCL for the first time
will waste cycles on them, because the cause is Houdini-side state that cannot
be inferred from the error alone.

Everything else (kernel logic, algorithm design, optimization) the model should
discover by writing code, reading errors, and iterating through the bridge.

## Ground Truth: the SideFX Example HDA

The single most useful reference for SOP OpenCL is an HDA shipped with Houdini
that contains ~20 working snippets (topology arrays, prim/vertex loops, VDB
sampling, matrix ops, writeback patterns, etc.). It is **far more complete than
the online docs** and every `#bind` / `@KERNEL` pattern in it is guaranteed to
compile.

```python
# Install once per session — creates a new node type you can instantiate
hou.hda.installFile(
    hou.getenv("HFS")
    + "/houdini/help/examples/nodes/sop/opencl/SimpleOpenCLSOPSnippets.hda"
)
```

After installing, instantiate it under `/obj` and walk its children.
Each child `opencl` node's `kernelcode` parm is a self-contained, working
example. **When unsure about any binding syntax, dump and read the relevant
snippet before guessing.**

```python
# Dump every example kernel to stdout
hda_node = hou.node("/obj").createNode("SimpleOpenCLSOPSnippets")
for child in hda_node.allSubChildren():
    if child.type().name() == "opencl":
        print(f"--- {child.path()} ---")
        print(child.parm("kernelcode").eval())
```

Key examples to look at first:
- `topo_neighbours` — writeback swap pattern, `getAt()` random access
- `simple_point` — minimal point attribute read/write
- `detail_attrib` — reading detail attributes in a kernel


## @-binding Quick Reference

The SOP `opencl` node and its COP cousin share the `atbinding=1` + `#bind` +
`@KERNEL {}` framework, but each has functions the other doesn't. SOP-specific:
`@elemnum`, `.getAt(j)`, `.len`. COP-specific: `.bufferIndex()`,
`.worldSample()`, `@ix/@iy`.

| Need | Syntax |
|---|---|
| Current element index | `@elemnum` |
| Total element count | `@P.len` |
| Read another element's value | `@P.getAt(j)` |
| Read-only point attrib | `#bind point P float3` |
| Read+write point attrib | `#bind point &P float3` |
| Write-only (must pre-exist!) | `#bind point !&U float` |
| Detail attribute | `#bind detail myattr float` |
| Writeback block | `@KERNEL { @tmp.set(v); }` `@WRITEBACK { @real.set(@tmp); }` |


## Silent-Failure Traps

These are ordered by how misleading the symptom is. Each follows the pattern:
**symptom you see** → **actual cause** → **diagnostic check**.

### 1. "Binding named '' has invalid name" — but your `#bind` directives are fine

**Cause:** A fresh `opencl` SOP starts with `bindings=1` — one empty entry in
the legacy manual-binding multiparm. Under `atbinding=1` this phantom entry
poisons the parser.

**Check:** `node.parm("bindings").eval()` — if > 0, set it to 0.

### 2. Simulation looks frozen — no error, writeback just does nothing

**Cause:** `@WRITEBACK {}` is silently ignored unless `usewritebackkernel=1`.
The checkbox defaults to off.

**Check:** `node.parm("usewritebackkernel").eval()` — if 0, set it to 1.

### 3. Parm slider changes have no effect on the simulation — no error

**Cause:** `#bind parm name float val=X` sometimes reads the baked-in default
instead of the linked spare parm, depending on compile cache state. This is
intermittent and version-dependent.

**Proven alternative:** Use detail attributes instead of parm bindings for any
value that needs to come from outside the kernel. An upstream detail wrangle
writes the values; the kernel reads them via `#bind detail`. Detail attribs are
read fresh every cook with no caching surprises.

```c
#bind detail _muK float
@KERNEL { float muK = @_muK; ... }
```
```vex
// upstream attribwrangle, Run Over: Detail (class=0)
f@_muK = ch("../../../muK");
```

### 4. `Invalid attribute 'X'` on a `!&` (write-only) binding

**Cause:** `!&` does not auto-create attributes. The error message itself is
clear enough — the real trap is that SideFX's own example snippets use `!&`
and appear to create attributes on the fly, but they silently depend on an
upstream node having already created them. First encounter, you'll trust the
official pattern and be confused when it fails.

**Fix:** Pre-create the attribute with an upstream `attribcreate` node.

### 5. `getAt()` — two constraints not in the docs

`getAt(j)` is the mechanism for random-access reads (reading other points
inside the kernel). Two things break it silently:

- **Scope:** The generated accessor variables (e.g. `_bound_P_length`) only
  exist inside the `@KERNEL {}` main body. Calling `getAt()` from a helper
  function produces "use of undeclared identifier" errors. **Inline the
  logic.**

- **Integer attributes:** Houdini's code generator does not emit the accessor
  for `int` typed point attributes. The symptom is the same undeclared-
  identifier error. **Bind as `float`, cast in the kernel:**
  `(int)@cell_id.getAt(j)`.

### 6. Detail binding `_` prefix — spare parm vs input geometry

`#bind detail _foo float` looks for a **spare parm** named `_foo` on the
OpenCL node itself. `#bind detail foo float` (no prefix) reads the **input
geometry's** detail attribute named `foo`.

If you're passing values via an upstream detail wrangle, the upstream creates
attribs like `f@grid_x`. The kernel binding must match that name exactly —
`#bind detail grid_x float`, not `#bind detail _grid_x float`.

The `_` prefix convention works when you pair it with spare parms that have
`ch()` expressions pulling from elsewhere. Both paths work; just be clear
which one you're using.


## Writeback Swap Pattern

The canonical way to update an attribute that other threads are simultaneously
reading via `getAt()`. Without this, you get race conditions (thread A writes
`@P`, thread B reads stale `@P` via `getAt`).

```c
#bind point  P      float3    // real position (read by other threads)
#bind point &P_new  float3    // temp (read+write, not !&)

@KERNEL
{
    float3 new_pos = /* ... compute from @P.getAt(j) neighbors ... */;
    @P_new.set(new_pos);
}

@WRITEBACK
{
    @P.set(@P_new);
}
```

- `P_new` must be `&` (read+write), not `!&` — the writeback block reads it.
- `P_new` must be pre-created on input geometry (see trap #4).
- `usewritebackkernel` must be enabled (see trap #2).
- Reference: `topo_neighbours` in the Example HDA.


## Node Creation via Bridge

When creating OpenCL SOP nodes programmatically, prefer **copying an existing
working node** (`hou.copyNodesTo`) over `createNode("opencl")`. A fresh node's
default parm template may have stale bindings entries (trap #1) and missing
spare parm structure. Copying a known-good node inherits the correct setup.

When that's not possible (no existing node to copy), create fresh and
immediately clear the legacy binding: `node.parm("bindings").set(0)`.
