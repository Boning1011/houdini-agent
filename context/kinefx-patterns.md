# KineFX Patterns — Reference

## Overview

KineFX is Houdini's SOP-level character rigging and animation framework. Unlike the older CHOP-based system, KineFX represents skeletons as SOP geometry (points = joints, polylines = bones).

## Key Concepts

- **Skeleton**: Point geometry where each point is a joint. Has `name` and `transform` attributes.
- **Joint transforms**: Stored as `localtransform` (4x4 matrix) point attribute.
- **Bone hierarchy**: Encoded as polyline primitives connecting parent → child joints.
- **Rig**: Built by chaining SOP nodes that manipulate the skeleton geometry.

## Essential Attributes

| Attribute | Class | Type | Description |
|---|---|---|---|
| `name` | point | string | Joint name (e.g., "Hips", "LeftArm") |
| `localtransform` | point | 4x4 matrix | Local space transform |
| `transform` | point | 4x4 matrix | World space transform (computed) |

## Common Nodes

| Node | Purpose |
|---|---|
| `skeleton` | Create a skeleton from scratch |
| `rig_doctor` | Diagnose skeleton issues |
| `joint_capture_biharmonic` | Skin geometry to skeleton |
| `bone_deform` | Apply skeleton transforms to skinned geo |
| `rig_pose` | Manually pose joints |
| `rig_stash_pose` | Store a rest/reference pose |
| `ik_chains` | Set up IK solvers |
| `full_body_ik` | Full-body IK solve |
| `configure_joints` | Set joint limits and properties |
| `skeleton_blend` | Blend between two poses/animations |
| `motion_clip` | Work with animation clips |

## Python Patterns

```python
# Access skeleton points (joints)
skel_node = hou.node("/obj/geo1/skeleton1")
geo = skel_node.geometry()

for pt in geo.points():
    name = pt.attribValue("name")
    xform = pt.attribValue("localtransform")  # 16 floats (4x4 matrix)
    print(f"Joint: {name}")

# Find joint by name
for pt in geo.points():
    if pt.attribValue("name") == "Hips":
        hips_point = pt
        break

# Read world transform
import hou
world_xform = pt.attribValue("transform")  # 16 floats
m = hou.Matrix4(world_xform)
translate = m.extractTranslates()
rotate = m.extractRotates()
```

## Common Workflows

### Build a Skeleton
```
Skeleton SOP → Configure Joints → Rig Stash Pose (rest pose)
```

### Skin Geometry
```
[Character Geo] → Joint Capture Biharmonic ← [Skeleton rest pose]
                        ↓
                   Bone Deform ← [Animated skeleton]
```

### IK Setup
```
Skeleton → IK Chains (select root/tip, set solver) → Rig Pose (set IK targets)
```

## Gotchas

1. **Matrix ordering**: Houdini uses row-major matrices. `localtransform` is 16 floats in row-major order.
2. **Rest vs animated pose**: Always stash the rest pose before animating. Bone Deform needs both rest and animated skeletons.
3. **Point order matters**: The skeleton hierarchy relies on point numbers and polyline connectivity. Don't sort or shuffle points.
4. **Name attribute**: Joint names must be unique for proper capture/deform.
5. **Transform vs localtransform**: `transform` is world-space (computed from hierarchy), `localtransform` is parent-relative (what you typically edit).
