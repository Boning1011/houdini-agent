<!-- houdini_version: 21.0 -->
# USD / LOPs Patterns — Reference

## Overview

LOPs (Lighting Operators) is Houdini's USD-based context for scene description, layout, lighting, and rendering.

## Key Concepts

- **Stage**: The USD scene graph. In LOPs, each node outputs a stage.
- **Prim**: A USD primitive — can be geometry, xform, material, light, etc.
- **Layer**: USD's composable file format. LOPs uses layers for non-destructive editing.
- **Purpose**: render, proxy, guide — controls visibility per context.

## Common LOP Nodes

| Node | Purpose |
|---|---|
| `sopimport` | Import SOP geometry into LOPs |
| `configure_layer` | Set layer metadata (default prim, etc.) |
| `sublayer` | Combine layers |
| `reference` | Add USD references |
| `xform` | Transform prims |
| `material_library` | Create/manage materials |
| `assign_material` | Assign materials to prims |
| `edit_properties` | Edit prim properties |
| `prune` | Hide or deactivate prims |
| `usd_rop` | Export USD files |

## Stage Access in Python

```python
# Get the stage from a LOP node
lop_node = hou.node("/stage/my_lop")
stage = lop_node.stage()

# Traverse prims
for prim in stage.Traverse():
    print(prim.GetPath(), prim.GetTypeName())

# Get a specific prim
prim = stage.GetPrimAtPath("/World/Geometry/mesh")

# Read attributes
attr = prim.GetAttribute("xformOp:translate")
attr.Get()  # returns value at default time

# Check prim type
from pxr import UsdGeom
if prim.IsA(UsdGeom.Mesh):
    mesh = UsdGeom.Mesh(prim)
    points = mesh.GetPointsAttr().Get()
```

## Common Workflows

### Import SOP to LOPs
```
SOP Import → Configure Layer → (further LOPs processing)
```
Set the SOP path on the sopimport node to pull geometry into the USD stage.

### Material Assignment
```
Material Library → Assign Material → Merge with geometry branch
```

### Export
```
... → USD ROP (set output path, frame range)
```

## Gotchas

1. **Stage is read-only from Python in LOPs**: You can read the stage via `node.stage()`, but writing should be done through LOP nodes or `node.editableStage()` in a Python LOP.
2. **Time-dependent values**: Use `Usd.TimeCode(frame)` when getting animated values.
3. **Composition order matters**: Sublayer order, reference order — later opinions win (LIVRPS: Local, Inherits, Variants, References, Payload, Specializes).
4. **Default prim**: Set via Configure Layer — required for proper referencing.
