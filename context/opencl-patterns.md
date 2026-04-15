<!-- houdini_version: 21.0 -->
# OpenCL Patterns (SOP & COP)

This document is a **harness, not a tutorial**. It records only things that are
inherent to Houdini's OpenCL implementation — hidden behaviors where the error
message is misleading or entirely absent. These traps are **independent of model
capability**: even a much smarter model hitting Houdini OpenCL for the first
time will waste cycles on them, because the cause is Houdini-side state that
cannot be inferred from the error alone.

Everything else (kernel logic, algorithm design, optimization) the model should
discover by writing code, reading errors, and iterating through the bridge.


## SOP vs COP — Know Which Context You're In

Houdini has OpenCL nodes in two contexts: **Sop/opencl** and **Cop/opencl**.
They share the `@KERNEL {}` + `#bind` + `@WRITEBACK {}` framework but bind
**fundamentally different data**. Applying SOP patterns in a COP kernel (or
vice versa) will produce confusing errors. Check which context you're in first.

**What they share:**
- `@KERNEL {}`, `@WRITEBACK {}` blocks
- `#bind parm` for scalar parameters
- `getAt(j)` / `.len` for random access
- `static` helper functions (but see trap #5 re: `getAt()` scope)
- **Iteration / Time built-ins** when the corresponding options are enabled
  (see "Standard built-ins" below) — `@Iteration`, `@Time`, `@TimeInc`, etc.
  These are capital-I / capital-T; lowercase `@iteration` / `@time` are
  undefined and will error with "X is undefined".

**SOP-only** — operates on geometry elements (points, prims, vertices):

| Feature | Syntax |
|---|---|
| Bind point attribute | `#bind point P float3` |
| Bind detail attribute | `#bind detail myattr float` |
| Current element index | `@elemnum` |
| Element count | `@P.len` |

**COP-only** — operates on image pixels, binds **layers** not attributes:

| Feature | Syntax |
|---|---|
| Bind input layer (read) | `#bind layer src? val=0` |
| Bind output layer (write) | `#bind layer !&dst` |
| Bind layer with type | `#bind layer &src float2` |
| Pixel coordinates | `@ix`, `@iy` |
| Resolution | `@xres`, `@yres` |
| Read pixel at position | `@src.bufferIndex((int2)(x,y))` |
| Interpolated pixel read | `@src.bufferSample((float2)(x,y))` |
| Texture-space coords | `@P.texture`, `@P.image` |
| UV-space sample | `@src.textureSample(uv)` |
| Bind ramp parameter | `#bind ramp my_ramp float3` |
| Bind geometry from input | `#bind point Cd name=Cd port=geo float3` |

Note: COP `!&dst` (write-only layer) **does** work without pre-creation —
unlike SOP `!&` which requires an upstream `attribcreate` (see trap #4).


## Standard Built-ins — ALWAYS Know These

These come from the OpenCL node's Options tab toggles. They appear in **every
non-trivial kernel** (solvers, iteration, time-based effects). Do not reinvent
or work around them with sentinel values / dynamic kernel rewrites.

| Built-in       | Requires toggle         | Type  | Meaning |
|----------------|-------------------------|-------|---------|
| `@Iteration`   | `options_iteration` ON  | int   | 0-indexed iteration counter. `== 0` on the first pass. |
| `@Time`        | `options_time` ON       | float | Current simulation time (accumulates `@TimeInc` per iter). |
| `@TimeInc`     | `options_timeinc` ON    | float | Per-iteration time step. |
| `@Frame`       | _(present with Time)_   | float | Current frame number. |

**Capitalization matters.** `@iteration`, `@time`, `@iter` are all **undefined
identifiers** — the error is "@iteration is undefined". Always capital letter:
`@Iteration`, `@Time`, `@TimeInc`.

**Other required toggles for iteration-based CA / solver work:**
- `options_iteration = 1` — enable iteration mode
- `options_iterations = N` — number of iterations (can be an expression like
  `ch("../../res2")` to track canvas height)
- `usewritebackkernel = 1` — enable `@WRITEBACK {}` block (silently ignored
  without this — see trap #2)
- `options_time = 1` — expose `@Time`
- `options_timeinc = 1` — expose `@TimeInc` (auto-advance per iter)
- `options_importprequel = 1` — on iteration 0, initialize output layers from
  matching input layers (the ping-pong pattern depends on this when input and
  output share a name like `state`)

**Use `@Iteration == 0` to initialize** state on the first pass — far cleaner
than a sentinel value in an upstream constant.


## Rebuild Bindings — Every #bind parm Needs This

**CRITICAL**: manually setting `#bind parm X int val=30` in the kernel text is
**not enough** to make `X` a live, user-controllable parameter. The kernel
reads `X` as a runtime kernel argument (`_bound_X` in generated code), but that
argument is supplied by an entry in the `bindings` multiparm on the node.
Without that entry, the kernel uses the `val=` default and any user-created
spare parm named `X` / `X_val` is ignored.

The UI has a small **"Rebuild Bindings"** button at the top of the kernel code
editor. Programmatically, that button calls:

```python
import vexpressionmenu
vexpressionmenu.createSpareParmsFromOCLBindings(opencl_node, 'kernelcode')
```

What it does:
1. Parses the kernel via `hou.text.oclExtractBindings(code)`.
2. For each `#bind parm NAME TYPE val=V`, creates a spare parm in the folder
   `folder_generatedparms_kernelcode` (label "Generated Channel Parameters").
   In **COPs** the spare parm is just `NAME`; in **SOPs / Python snippets**
   it's `NAME_val`.
3. Adds an entry to the `bindings` multiparm pointing at the spare parm via
   expression (`ch("./NAME")` on `bindings{i}_intval` or `_fval`).
4. Also creates input/output entries for `#bind layer` directives.

**Call this after every kernel text change that adds/removes `#bind parm` or
`#bind layer` lines.** Without it, new bindings are dead.

**HDA pattern — top-level control via `ch()` chain:**

For an HDA wrapping an OpenCL node, expose user parms at the HDA level and
link the opencl's spare parms to them with a relative `ch()` expression. The
chain is: HDA parm → (ch expression) → opencl spare parm → (ch expression in
`bindings` multiparm) → kernel `_bound_X`.

```python
# After Rebuild Bindings generates opencl's spare parms:
for pname in ['mode', 'rule', 'seed', 'density']:
    opencl_node.parm(pname).setExpression(f'ch("../{pname}")')
# HDA parm of the same name then drives the kernel live — no kernel rewrite needed.
```

The randomize buttons on the HDA just `.set()` the top-level parms; the
expression cascade takes care of the rest.

**Anti-pattern** (what to NOT do): dynamically rewriting the kernel text to
inject values via `#define` or by mutating `val=`. It works but is fragile,
recompiles the kernel on every parm change, and bypasses Houdini's native
binding infrastructure. Use `#bind parm` + Rebuild Bindings instead.


## Official Documentation

The SideFX online docs cover the OpenCL node's `#bind` directives, built-in
variables, and available functions for each context:

- **SOP OpenCL**: `$HFS/houdini/help/nodes/sop/opencl.txt` or press F1 on the
  node. Documents `@elemnum`, `getAt()`, `#bind point/prim/vertex/detail`,
  volume/VDB bindings, and the `@WRITEBACK` mechanism.
- **COP OpenCL**: `$HFS/houdini/help/nodes/cop/opencl.txt` or press F1.
  Documents `@ix/@iy`, `@xres/@yres`, layer bindings, `bufferIndex()`,
  `bufferSample()`, `textureSample()`, and ramp bindings.

These docs list every available function and built-in variable. **Read the
relevant one before writing a kernel** — it prevents guessing at function names.


## Ground Truth: the SideFX Example HDAs

Both SOP and COP ship with example HDAs containing working snippets. These are
**far more complete than the online docs** for real patterns. Every `#bind` /
`@KERNEL` combination in them is guaranteed to compile.

```python
hfs = hou.getenv("HFS")

# SOP examples (~20 snippets: topology, prim/vertex, VDB, matrix, writeback)
hou.hda.installFile(hfs + "/houdini/help/examples/nodes/sop/opencl/SimpleOpenCLSOPSnippets.hda")

# COP examples (~30 snippets: pixel ops, convolution, sampling, ramps, geo binding)
hou.hda.installFile(hfs + "/houdini/help/examples/nodes/cop/opencl/SimpleOpenCLCOPSnippets.hda")
```

After installing, instantiate under `/obj` and walk children. Each child
`opencl` node's `kernelcode` parm is a self-contained example. **When unsure
about any binding syntax, dump and read the relevant snippet before guessing.**

```python
# Dump every example kernel
hda_node = hou.node("/obj").createNode("SimpleOpenCLSOPSnippets")  # or COP variant
for child in hda_node.allSubChildren():
    if child.type().name() == "opencl":
        print(f"--- {child.path()} ---")
        print(child.parm("kernelcode").eval())
```

**SOP** — key examples to look at first:
- `topo_neighbours` — writeback swap pattern, `getAt()` random access
- `simple_point` — minimal point attribute read/write
- `detail_attrib` — reading detail attributes in a kernel

**COP** — key examples:
- `greyscale` / `invert_color` — minimal layer read/write
- `flip_image` / `Sobel_Filter` — `bufferIndex()` neighbor access
- `opencl19` — `textureSample()` with writeback
- `opencl24` / `opencl33` — binding geometry attributes (`#bind point ... port=geo`)
- `opencl29` — ramp binding (`#bind ramp`)


## SOP @-binding Quick Reference

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

**Cause:** After adding `#bind parm NAME TYPE val=X` to the kernel, the kernel
compiles and runs using `val=X` as a hard-coded default. Without an entry in
the `bindings` multiparm pointing at a spare parm, there is nothing to
override that default — any spare parm you create manually with the right
name is orphaned.

**Fix:** Call Rebuild Bindings — see the **Rebuild Bindings** section above.
Programmatically: `vexpressionmenu.createSpareParmsFromOCLBindings(node, 'kernelcode')`.
Run this after every kernel text change that touches `#bind parm` / `#bind layer`.

**SOP fallback (detail attributes):** If for some reason the Rebuild path is
unavailable, upstream detail attribs also work — an attribwrangle writes
`f@_muK = ch(...)` and the kernel reads `#bind detail _muK float`. Detail
attribs are read fresh every cook with no cache surprises. But prefer the
Rebuild Bindings path for normal cases.

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
