<!-- houdini_version: 21.0 -->
# COPs Python Snippet — Reference

The `cop/pythonsnippet` node (Houdini 21+, Copernicus context) runs Python on
image **layers**. It is **not** the same as the Python COP from the legacy
compositor, **not** the OpenCL COP, and **not** a Python SOP. It has its own
small API and its own surprising failure modes — keep it in its own mental box.

## Snippet contract

```python
# kwargs holds: bound parms (by name) + input layers/geometry (by name)
# Snippet body must return a dict mapping output names to ImageLayer objects.

src = kwargs["src"]          # one of the input names you set on Signature tab
intensity = kwargs["intensity"]   # one of the bindings (already evaluated)
return {"dst": new_layer}    # output names from Signature tab
```

- The **last statement must be `return {...}`** even though the body is
  `exec()`-ed — internally the snippet is wrapped in a function. Forgetting it
  produces a single, unhelpful node error: `Python code did not return a dictionary`.
- The snippet has **no access to `hou.pwd()` or the surrounding network**.
  The doc page calls this out explicitly: "this node can't access the
  currently evaluating node." Everything you need must come through `kwargs`.
- Same `#bind` directive convention as OpenCL COPs (used only by the
  *Create input and spare parameters* button to populate Signature/Bindings
  tabs). Python ignores them — they are pure comments. Editing them does not
  change behavior unless you re-run the button or hand-edit Signature/Bindings.

## Inputs / outputs

Configured on the **Signature** tab. Each input/output has:

- A `name` (the key used in `kwargs` and the return dict).
- A `type` (the menu stores **string tokens**, not ints, even though the menu
  *labels* are "RGBA" etc.). Set with `parm("input1_type").set("float4")`,
  not `.set(6)`. Tokens: `floatn` (Varying), `int` (ID), `float` (Mono),
  `float2` (UV), `float3` (RGB), `float4` (RGBA), `geo` (Geometry),
  `metadata`, `ivdb` / `fvdb` / `vvdb` / `fnvdb`.
- Geometry inputs: not bound as a layer — refer to the input by name from
  inside an attribute or volume binding (rare path, see the doc page).

## Bindings (constant parameters)

Each entry on the **Bindings** tab becomes a key in `kwargs`. Configure with:

```python
ps.parm("bindings").set(N)
ps.parm(f"bindings{i}_name").set("intensity")
ps.parm(f"bindings{i}_type").set("float")          # int / float / float2/3/4 / string / ramp
ps.parm(f"bindings{i}_fval").set(1.0)              # value parm depends on type:
# int    -> bindings{i}_intval
# float  -> bindings{i}_fval
# vec2/3/4 -> bindings{i}_v2val / v3val / v4val
# string -> bindings{i}_sval
# ramp   -> bindings{i}_ramp / bindings{i}_ramp_rgb (no scalar value)
```

The value parms accept **expressions**, so the standard HDA pattern is to
expose user-facing parms at the asset level and forward them in:

```python
ps.parm("bindings1_sval").setExpression('chs("../lut_path")', hou.exprLanguage.Hscript)
ps.parm("bindings2_fval").setExpression('ch("../intensity")', hou.exprLanguage.Hscript)
```

Until the parent's parms exist, the node logs `Bad parameter reference` warnings
— harmless during build, but verify they clear once the wrapper parms are in.

## ImageLayer (the actual data API)

`kwargs["<input>"]` returns a `hou.ImageLayer` for non-geometry inputs.
Layers are **not** numpy arrays and have no `.shape` / `.dtype` — you have to
pull a buffer:

```python
src = kwargs["src"]
w, h = src.bufferResolution()              # (width, height)
ch   = src.channelCount()                  # 4 for RGBA
buf  = src.allBufferElements()             # bytes, length = w*h*ch*sizeof(storage)
img  = np.frombuffer(buf, dtype=np.float32).reshape(h, w, ch).copy()
```

Storage type: `src.storageType()` returns a `hou.imageLayerStorageType` enum
(`Float32`, `Float16`, `UNorm8`, etc.). For `Float32` use `np.float32`;
for `Float16` use `np.float16`; for `UNorm8` use `np.uint8` and divide by 255.

To produce an output, **construct a fresh `hou.ImageLayer()`** — never mutate
`kwargs[...]` and return it (you may corrupt cached upstream data and you cannot
guarantee write permission on the input):

```python
dst = hou.ImageLayer()
dst.setDataWindow(0, 0, w, h)              # NOT setBufferResolution — that doesn't exist
dst.setDisplayWindow(0, 0, w, h)
dst.setChannelCount(ch)
dst.setStorageType(src.storageType())
dst.setTypeInfo(src.typeInfo())
dst.setAllBufferElements(out_array.tobytes())
return {"dst": dst}
```

Window objects (`dataWindow()` / `displayWindow()`) return `hou.BoundingRect`,
which uses `min()` / `max()` / `size()` — not `xmin()` / `xmax()`. Trying the
xmin form fails with `AttributeError: 'BoundingRect' object has no attribute 'xmin'`.

## Maintain State / module-level cache

The **Maintain State** toggle (`options_maintainstate`) keeps the underlying
Python interpreter alive between cooks. With it on, `_LUT_CACHE = {}` style
module-level caches survive — fine for parsed-file caches keyed by `path +
mtime`. With it off (the default and the docs' recommendation), each cook
re-executes the snippet from scratch.

Caching parsed external files is usually still cheap enough to do per-cook
(`_parse_cube` on a 33³ LUT is single-digit ms), so leaving Maintain State off
is the safer default.

## Performance reality check

The doc page warns up front: Python is interpreted, per-pixel loops are slow.
Vectorise with numpy, never iterate `for y in range(h)`. For a 1080p RGBA
buffer a numpy-vectorised LUT lookup runs in tens of ms; a Python `for`-loop
will be many seconds. If numpy can't express it, drop down to OpenCL COP — see
[opencl-patterns.md](opencl-patterns.md).

## Foolproof I/O — accept anything, emit something useful

The Signature tab couples I/O strictly by default (`float4` in → `float4` out
means a Mono layer wired into the input throws a type mismatch). For nodes
intended as drop-in user-facing filters, prefer:

- **Input:** `floatn` (Varying) — accepts Mono / UV / RGB / RGBA without complaint.
- **Output:** the widest type the node can emit (often `float4` RGBA), so
  downstream always sees a known-shaped layer.

Inside the snippet, branch on `src.channelCount()` and **promote** the buffer
to whatever your maths assumes (usually 3-channel RGB):

```python
in_ch = src.channelCount()
img = np.frombuffer(src.allBufferElements(), dtype=np.float32).reshape(h, w, in_ch)

if in_ch == 1:
    rgb = np.repeat(img, 3, axis=2)        # mono: replicate
elif in_ch == 2:
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    rgb[..., 0:2] = img                    # UV-ish: pad blue with zero
else:
    rgb = img[..., :3].copy()              # 3 / 4 / more: take first three
```

Always honour `storageType()` when decoding and re-encoding so you don't
silently change precision (`UNorm8` ↔ `np.uint8` × `1/255`, `Float16` ↔
`np.float16`, etc.). The "obvious" `np.frombuffer(buf, dtype=np.float32)`
crashes loudly on any non-`Float32` layer — always read the storage enum first.

For filters where the *visual effect* matters more than format-fidelity (a
LUT, a colour grade, a film-look), output 4-channel RGBA even when input is
mono — that lets a B&W layer pick up the LUT's colour tint instead of being
collapsed back to luminance. If you want it to stay mono, collapse with
Rec.709 weights `0.2126 R + 0.7152 G + 0.0722 B`.

## Live example in the wild

`motion-cops` repo → `boning::mc_lut_apply::1.0`
(`otls/cop_boning.mc_lut_apply.1.0.hdalc`). Wraps a single `pythonsnippet` in a
subnet, exposes `lut_path` / `intensity` / `input_log`, forwards them to the
snippet via `chs()` / `ch()` expressions on the binding parms. The snippet body
lives at `motion-cops/scripts/lut_cop_snippet.py` — handy as a reference for
the buffer-in / buffer-out pattern with numpy.

## Building HDAs that wrap a snippet — pitfalls

- `createDigitalAsset()` discards any parm template group already set on the
  source subnet. **Set the user-facing parms on `definition.setParmTemplateGroup(...)`
  AFTER the asset is created**, then `definition.save(libraryFilePath())`.
- `hou.hda.definitionsInFile(path)` raises `OperationFailed` if the file does
  not yet exist. Guard with `os.path.exists(path)` before deciding whether to
  uninstall an old version.
- `hou.hda.uninstallFile(path)` raises `OperationFailed` if the file isn't
  currently installed. Wrap in `try/except hou.OperationFailed`.
- After saving, an instance of the new HDA is locked. To edit the inner
  `pythonsnippet` (e.g. to refresh the embedded code) call
  `node.allowEditingOfContents()` first, then `defn.updateFromNode(node)` and
  `defn.save(...)`.

## Doc references

- F1 on the node, or `hfs/houdini/help/nodes.zip` → `cop/pythonsnippet.txt`.
- Compare against `sop/pythonsnippet.txt` for the SOP variant — same `kwargs`
  contract, but the SOP returns `hou.Geometry` instead of a layer dict.
