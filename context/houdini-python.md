<!-- houdini_version: 21.0 -->
# Houdini Python (hou module) — Reference

## Python SOPs — Don't Materialize Full Element Lists

When writing a Python SOP (or any code) that handles geometry whose
size you don't control, avoid `.prims()` / `.points()` / `.vertices()`
in patterns that materialize the full tuple just to count or peek:

```python
# BAD on large inputs — builds a Python tuple of every prim object
geo.prims()[0]              # materializes all N prims to take [0]
len(geo.prims())            # materializes all N prims to call len
for p in geo.prims(): ...   # tuple-built first, then iterated
```

Use the lazy alternatives:

```python
# Count via cheap intrinsic
n = geo.intrinsicValue("primitivecount")
# (also: "pointcount", "vertexcount")

# Fetch just the first element
first = None
for p in geo.iterPrims():
    first = p
    break

# Iterate without front-loading the tuple
for p in geo.iterPrims():
    ...
```

Gotcha: `iterPrims()` returns an *iterable*, not an iterator —
`next(geo.iterPrims())` raises `TypeError`. Wrap with `iter()` or
use the for-loop pattern.

Measured impact: in the `fab::set_cnc_stock` HDA, switching a single
`src.prims()[0]` to the `iterPrims()` pattern dropped a Python SOP's
cook time from ~4.2 s to under 50 ms on a 1.6M-prim input — 80×
faster. The actual attribute-copy work was already microseconds; all
the cost was the tuple build.

Reserve `.prims()` / `.points()` for cases where you genuinely need
the full tuple AND the input is small (e.g. iterating the prims of
an OBB box, 6 elements).

## Thread Safety

**The `hou` module is NOT thread-safe.** All hou calls must happen on Houdini's main thread.

Pattern for background thread → main thread:
```python
import hou
hou.ui.addEventLoopCallback(my_callback)  # runs on main thread each UI tick
```

## Common Node Operations

```python
# Get a node
node = hou.node("/obj/geo1")

# Check existence before operating
if hou.node("/obj/geo1") is not None:
    ...

# Create nodes
obj = hou.node("/obj")
geo = obj.createNode("geo", "my_geo")       # type, optional name
box = geo.createNode("box")
xform = geo.createNode("xform")

# Connect nodes
xform.setInput(0, box)                       # input_index, source_node

# Set display/render flags
xform.setDisplayFlag(True)
xform.setRenderFlag(True)

# Layout nodes nicely
geo.layoutChildren()
```

## Parameters

```python
node = hou.node("/obj/geo1/box1")

# Read
node.parm("sizex").eval()          # evaluated value
node.parm("sizex").rawValue()      # raw (may be expression)
node.evalParm("sizex")             # shorthand

# Write
node.parm("sizex").set(2.0)
node.setParms({"sizex": 2.0, "sizey": 3.0})

# Expressions
node.parm("sizex").setExpression("$F * 0.1")

# Parameter tuples (vector parms)
node.parmTuple("size").eval()      # (1.0, 1.0, 1.0)
node.parmTuple("size").set((2.0, 3.0, 4.0))
```

## Geometry Access (SOPs)

```python
node = hou.node("/obj/geo1/box1")
geo = node.geometry()

# Points
for pt in geo.points():
    pos = pt.position()            # hou.Vector3
    pt.setPosition(hou.Vector3(1, 2, 3))

# Primitives
for prim in geo.prims():
    prim.attribValue("name")

# Attributes
geo.pointAttribs()                 # list of hou.Attrib
geo.primAttribs()
geo.vertexAttribs()
geo.globalAttribs()                # detail attribs

# Read attribute values
geo.pointFloatAttribValues("P")    # flat tuple: (x0,y0,z0, x1,y1,z1, ...)

# Create writable geometry (Python SOP or hou.Geometry())
geo = hou.Geometry()
point = geo.createPoint()
point.setPosition(hou.Vector3(0, 1, 0))
geo.addAttrib(hou.attribType.Point, "Cd", (1.0, 0.0, 0.0))
```

## Scene File Operations

```python
hou.hipFile.save()                 # save current
hou.hipFile.save("/path/to/file.hip")
hou.hipFile.load("/path/to/file.hip")
hou.hipFile.path()                 # current file path
```

## Common Gotchas

1. **String vs numeric parms**: `parm.set("string")` vs `parm.set(1.0)` — type must match
2. **Node references go stale**: If a node is deleted, existing Python references throw `hou.ObjectWasDeleted`
3. **Geometry is a snapshot**: `node.geometry()` gives a read-only snapshot at cook time. For writable geo, use Python SOP context or `hou.Geometry()`
4. **Path separators**: Always use forward slashes in node paths, even on Windows
5. **Keyframes vs values**: `parm.set()` sets a static value and removes keyframes. Use `parm.setKeyframe()` to animate
6. **evalParm shorthand**: `node.evalParm("tx")` is equivalent to `node.parm("tx").eval()`

## Useful Queries

```python
# All children of a node
hou.node("/obj").children()

# Find nodes by type
hou.node("/obj").glob("*", hou.nodeTypeFilter.Sop)

# Selection
hou.selectedNodes()

# Current frame
hou.frame()
hou.setFrame(24)

# Frame range
hou.playbar.frameRange()           # (start, end)
```
