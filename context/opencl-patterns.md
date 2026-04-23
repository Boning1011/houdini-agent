<!-- houdini_version: 21.0 -->
# OpenCL Patterns (SOP & COP)

Records only Houdini-side behaviors where the error is misleading or absent —
things you can't infer from the kernel alone. Kernel logic and algorithm design
are discoverable by writing code and reading errors; those are not here.


## SOP vs COP — Know Which Context You're In

Houdini has OpenCL nodes in two contexts: **Sop/opencl** and **Cop/opencl**.
They share the `@KERNEL {}` + `#bind` + `@WRITEBACK {}` framework but bind
**fundamentally different data**. Applying SOP patterns in a COP kernel (or
vice versa) will produce confusing errors. Check which context you're in first.

**What they share:** `@KERNEL {}` / `@WRITEBACK {}` blocks, `#bind parm`,
`getAt(j)` / `.len` random access, `static` helper functions (trap #5),
`@Iteration` / `@Time` built-ins (see Standard Built-ins).

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


## COP OpenCL on VDBs (NanoVDB, H21)

H21 introduced NanoVDB-native 3D volumes in COPs. The `opencl` COP runs
kernels per voxel on active leaves of a VDB. This is a *completely different*
data model from 2D layer kernels — almost every pattern differs.

**Running over a VDB:**

- Set `options_runover = 'vdb'` (First Writeable VDB).
- Input ports must be typed as VDBs — `fvdb` (Float VDB), `vvdb` (Vector
  VDB), or `fnvdb` (Varying VDB). A port typed `geo` (Geometry) **cannot**
  supply a VDB input — you must split with a `geotolayer::2.0` upstream
  (set its `outtype#` to `floatvdb` / `vectorvdb` to keep the VDB 3D, not
  slice into a layer). Enable its **Densify VDBs** toggle — the GPU can't
  just-in-time unpack constant tiles, so random writes require dense leaves.

**Per-voxel built-ins** (replace layer `@P` / `@ix @iy`):

| Built-in | Type | Meaning |
|---|---|---|
| `@ix`, `@iy`, `@iz`, `@ixyz` | `int`, `int3` | Current voxel index |
| `@elemnum` | `int` | Flat voxel counter (topology-dependent) |

**`@P` is NOT defined when running over VDBs** — it exists only for
layers/fields. To get the world-space position of the current voxel:

```c
float3 Pw = @mybind.indexToWorld((float3)((float)@ix, (float)@iy, (float)@iz));
```

Requires `xformtoworld` flag on the binding.

### VDB `#bind` syntax

```c
#bind vdb mysrc float xformtoworld voxelsize        // read-only float VDB
#bind vdb mysrc float3                              // read-only vector VDB
#bind vdb &inout  float3                            // read+write (VDB must pre-exist in input)
#bind vdb !&newout float3                           // write-only — creates new VDB, topology from first input
```

Type tokens are **OpenCL C types** (`float`, `float3`) — **not** `vector`.
Writing `#bind vdb &grad vector` produces the misleading warning "Unknown
token 'vector'" plus a cascade of "@grad.set: unknown method" errors.

Common binding flags:

| Flag | Enables |
|---|---|
| `xformtoworld` | `indexToWorld`, `indexToWorldDir`, and `worldGradient` in some cases |
| `xformtovoxel` | `worldToIndex`, `worldToIndexDir` |
| `voxelsize` | `@name.voxelsize_x/y/z`, `@name.voxelsize` |
| `resolution` | `@name.res` / bounds checks |

### Creating a new VDB from thin air — the `!&` + `metadata=first` pattern

Key insight for HDAs that produce a *different-typed* VDB from the input
(e.g. Gradient: Float → Vector): you do **not** need an upstream SOP to
pre-allocate the output container. Instead:

1. On the opencl COP: `output#_type = vvdb` (desired new type),
   `output#_metadata = first` — topology is inherited from the first
   typed input.
2. In the kernel: `#bind vdb !&out float3` — the **`!&`** (not `&`) prefix
   means "write-only, don't expect it to pre-exist." The runtime creates
   a new VDB with the input's active topology and the bound type.

Using `&out` instead of `!&out` produces "unknown method" errors on
`@out.set(...)` because `&` assumes the target already exists in the input
stream and couldn't be found.

### VDB method reference (on a bound VDB `@name`)

Read methods. The method name is **`getAt`**, not `valueAt` (`valueAt` is
a volume-binding method — using it on a VDB gives "unknown method"):

| Method | Returns | Notes |
|---|---|---|
| `@name` | current voxel value | Float VDB → float; Vector VDB → float3 |
| `@name.getAt(x,y,z)` | value at integer index | Returns background for inactive; clamp-safe |
| `@name.sample(ixyz)` | trilinear at `float3` index coords | |
| `@name.worldSample(xyz)` | trilinear at world-space `float3` | Cheap for stencils |
| `@name.worldGradient(xyz)` | **built-in central-difference gradient** | Float VDB only |
| `@name.worldToIndex(xyz)` | world → index | Requires `xformtovoxel` |
| `@name.indexToWorld(xyz)` | index → world | Requires `xformtoworld` |
| `@name.active` / `@name.activeAt(x,y,z)` | topology test | |
| `@name.voxelsize_x/y/z` | world-space voxel size per axis | Requires `voxelsize` |
| `@name.leafCount`, `@name.leafAt(x,y,z)` | leaf-level access | |

Write methods:

| Method | Notes |
|---|---|
| `@name.set(val)` | Write current voxel (requires matching index) |
| `@name.setAt(x,y,z,val)` | Write arbitrary — **only succeeds on already-active voxels**; writes to inactive voxels silently no-op |

**Topology is immutable inside OpenCL.** To activate new voxels (e.g., wider
stencil support for curvature at band edges), use `vdbactivatefrompoints`
upstream, not the kernel.

### No built-in curvature / Laplacian / divergence / curl

Only `worldGradient` is built-in. Other vector-calc operators must be
hand-rolled from stencils. Canonical SDF mean curvature via divergence of
normalized gradient (7 `worldGradient` calls per voxel):

```c
#bind vdb surface    float xformtoworld voxelsize
#bind vdb !&curvature float

@KERNEL {
    float3 Pw = @surface.indexToWorld((float3)((float)@ix,(float)@iy,(float)@iz));
    float vx = @surface.voxelsize_x, vy = @surface.voxelsize_y, vz = @surface.voxelsize_z;

    float3 gpx = @surface.worldGradient(Pw + (float3)( vx, 0, 0));
    float3 gmx = @surface.worldGradient(Pw + (float3)(-vx, 0, 0));
    // ... 4 more along y, z
    // safe-normalize each (guard length < 1e-8)
    float divN = (npx.x - nmx.x)/(2*vx) + (npy.y - nmy.y)/(2*vy) + (npz.z - nmz.z)/(2*vz);
    @curvature.set(0.5f * divN);
}
```

### Polymorphic-output HDAs: two switches, not one

The `switch` COP's output type is the *highest* of its inputs, and all
inputs must convert to it. Float VDB and Vector VDB are not convertible in
either direction — wiring them into one switch errors. For an HDA with a
mode selector where different modes produce different-typed outputs
(e.g. VDB Analyze), use **two switches** — one for scalar-output modes,
one for vector-output modes — and expose two typed outputs on the HDA.
Setting all opencl outputs to `fnvdb` (Varying VDB) does **not** fix this:
`!&` writes commit at one concrete type, and Varying VDB downstream inputs
still enforce a specific type at cook time.


## Standard Built-ins — ALWAYS Know These

Appear in every non-trivial iteration / solver / time-based kernel. Don't
reinvent them with sentinels or dynamic kernel rewrites.

| Built-in     | Requires toggle       | Type  | Meaning                                                   |
|--------------|-----------------------|-------|-----------------------------------------------------------|
| `@Iteration` | `options_iteration`   | int   | 0-indexed iteration counter. Use `== 0` for first-pass init. |
| `@Time`      | `options_time`        | float | Simulation time (accumulates `@TimeInc`).                 |
| `@TimeInc`   | `options_timeinc`     | float | Per-iteration time step.                                  |
| `@Frame`     | _(with Time)_         | float | Current frame.                                            |

**Capital letters only.** `@iteration` / `@time` / `@iter` → "X is undefined".

Usual companion toggles: `options_iterations = N` (expression like
`ch("../../res2")` works), `usewritebackkernel = 1` (trap #2),
`options_importprequel = 1` (so iter 0 reads matching named input layer when
using ping-pong pattern).


## Rebuild Bindings — Every #bind parm Needs This

**`#bind parm X int val=30` alone does nothing.** The kernel reads `X` as a
runtime argument supplied by the `bindings` multiparm on the node; without a
matching entry there, the `val=` default is used and any manually-named spare
parm is orphaned.

The UI's "Rebuild Bindings" button (top of kernel editor) is just:

```python
import vexpressionmenu
vexpressionmenu.createSpareParmsFromOCLBindings(opencl_node, 'kernelcode')
```

It parses `#bind parm` / `#bind layer`, creates spare parms in
`folder_generatedparms_kernelcode` (COPs: `NAME`, SOPs/Python: `NAME_val`),
and wires them to new `bindings` multiparm entries via `ch("./NAME")`.
**Re-run after any `#bind` edit**, or bindings are dead.

**HDA pattern — top-level control.** Expose parms at the HDA level; link the
opencl's spare parms to them:

```python
for pname in ['mode', 'rule', 'seed', 'density']:
    opencl_node.parm(pname).setExpression(f'ch("../{pname}")')
```

Button callbacks `.set()` the HDA parms; the `ch()` chain cascades to the
kernel live — no kernel rewriting, no recompile per change. **Don't** inject
values via `#define` / dynamic kernel text substitution.


## When Unsure — Two Sources of Truth

- **F1 on the node** or `$HFS/houdini/help/nodes/{sop,cop}/opencl.txt` —
  authoritative list of `#bind` directives, built-ins, and functions per context.
- **SideFX example HDAs** — more complete than docs, guaranteed to compile:

  ```python
  hfs = hou.getenv("HFS")
  hou.hda.installFile(hfs + "/houdini/help/examples/nodes/sop/opencl/SimpleOpenCLSOPSnippets.hda")
  hou.hda.installFile(hfs + "/houdini/help/examples/nodes/cop/opencl/SimpleOpenCLCOPSnippets.hda")
  # Instantiate under /obj, then dump each child opencl's kernelcode parm.
  ```

  Key examples:
  - **SOP**: `topo_neighbours` (writeback + `getAt()`), `simple_point`, `detail_attrib`
  - **COP**: `greyscale` / `invert_color` (minimal), `flip_image` / `Sobel_Filter` (`bufferIndex()`), `opencl19` (`textureSample()`), `opencl24` / `opencl33` (`#bind point ... port=geo`), `opencl29` (ramp)


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

The kernel is using `val=X` as the baked default because the `bindings`
multiparm has no entry for this parm. **Fix:** call Rebuild Bindings (see
above) after any `#bind parm` edit.

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

Requires: `P_new` bound as `&` (not `!&`); pre-created upstream (trap #4);
`usewritebackkernel=1` (trap #2). Reference: `topo_neighbours` example.


## Node Creation via Bridge

When creating OpenCL SOP nodes programmatically, prefer **copying an existing
working node** (`hou.copyNodesTo`) over `createNode("opencl")`. A fresh node's
default parm template may have stale bindings entries (trap #1) and missing
spare parm structure. Copying a known-good node inherits the correct setup.

When that's not possible (no existing node to copy), create fresh and
immediately clear the legacy binding: `node.parm("bindings").set(0)`.
