<!-- houdini_version: 21.0 -->
# Network Layout Patterns

## Layout Workflow

1. **Snapshot** — `scene_snapshot(path, depth=1)` gives you the full connection graph
2. **Analyze** — identify logical blocks by tracing data flow client-side
3. **Compute positions** — assign coordinates per block, no Houdini calls needed
4. **Apply** — set all positions in one `hou.undos.group` so the user can Ctrl+Z the whole layout

```python
# Step 4: apply in one undo group
code = 'with hou.undos.group("Agent: layout network"):\n'
for name, (x, y) in positions.items():
    code += f'    n = parent.node("{name}")\n'
    code += f'    if n: n.setPosition(hou.Vector2({x}, {y}))\n'
h.exec(code)
```

## Positioning API

| Method | Use |
|---|---|
| `node.position()` → `hou.Vector2` | Read current XY |
| `node.setPosition(hou.Vector2(x, y))` | Set absolute position |
| `node.move(hou.Vector2(dx, dy))` | Relative offset — good for shifting a group |
| `parent.layoutChildren(items=[nodes])` | Auto-layout a subset of nodes only |

- Houdini's Y axis goes **negative downward** (top of network = higher Y)
- A node tile is roughly **2 units wide, 0.8 units tall**
- Comfortable vertical spacing between connected nodes: **1.2–1.5 units**
- Comfortable horizontal spacing between parallel columns: **10–14 units**

## Network Boxes

```python
parent = hou.node("/obj/geo1")
box = parent.createNetworkBox("block_name")
box.setComment("Human-readable label")
box.setColor(hou.Color(0.3, 0.3, 0.35))
for name in node_names:
    n = parent.node(name)
    if n: box.addNode(n)
box.fitAroundContents()  # auto-size to wrap all nodes with padding
```

- **Remove existing boxes before recreating**: `for box in parent.networkBoxes(): box.destroy()`
- `fitAroundContents()` adds padding automatically — call it after adding all nodes
- Use distinct muted colors per block (avoid bright/saturated — they distract from node colors)

## Block Identification Strategy

From a `scene_snapshot`, identify blocks by data flow structure:

1. **Shared inputs** — nodes that fan out to multiple consumers (e.g., FBX import → GEO/REST_POSE/ANIM_POSE)
2. **Parallel chains** — repeated patterns with the same node types (e.g., 4 identical robot arm pipelines)
3. **Convergence points** — merges that collect parallel chains back together
4. **Side branches** — isolated subgraphs connected at one point (e.g., rig controls branch)
5. **Orphans** — nodes with no connections to any output chain (experimental/abandoned)

## Node Placement — Follow the Data, Not a Grid

### 1. Main spine LEFT, side processing RIGHT

The primary data flow forms the **left spine** of the layout. Secondary/processing branches (e.g., a parametric curve chain that computes IK targets) sit to the **right** and merge back in.

This matches Houdini's input connector order: input 0 (left connector) = main flow, input 1+ (right connectors) = secondary inputs. When side-chain wires merge from the right, they naturally connect to the correct input side.

```
# Main spine (LEFT)         Side chain (RIGHT)
#
#       null8                    ParametricCurve
#      /     \                        |
#   blast6   blast5              transform
#     |        \                      |
#     |      attribcopy ←----  attribwrangle
#     |         |
#     |    apply_param
#      \      /
#       merge2
#         |
#     fullbodyik
```

### 2. Gradual diagonal convergence, not column jumps

When a side branch merges back into the main spine, **don't jump horizontally**. Instead, each node in the merge path shifts 1–3 units toward the main column, creating a smooth diagonal:

```
# BAD — sharp jump:              GOOD — gradual convergence:
#   attribcopy (x-3)               attribcopy  (x+5)
#        |                              |
#   apply_param (x-3)             apply_param  (x+3)    ← shift 2 toward spine
#        |                              |
#     merge (x)  ← 3-unit jump      merge      (x+1)    ← shift 2 more
#        |                              |
#    fullbodyik (x)               fullbodyik    (x)      ← back on spine
```

### 3. Main column floats with its inputs

The main column is NOT a rigid straight line. It shifts slightly left/right to stay aligned with the dominant input of each node:

- `bonedeform` sits closer to `characterunpack` (its mesh source) than to `rigpose`
- `merge` nodes sit between their two inputs, biased toward the heavier branch
- Bypass/dead nodes (e.g., `blast4`) go **far to the opposite side** of the active area — they're not part of the flow and shouldn't compete for visual attention

## Avoiding Wire Overlap

**Stagger branches** so wires route around vertical chains. The passthrough branch (e.g., `blast6` → `merge2`) should be nearly vertical — align it with the merge node's X coordinate. The processing branch merges in diagonally from the side.

**Dots as last resort:** `hou.NetworkDot` (Alt+click on a wire in the UI) can redirect wire routing, but:
- Dots persist even after deleting the wire they belong to — they become orphan clutter
- Don't create dots programmatically unless the user specifically asks for wire routing cleanup
- Use only for important long-distance connections from far upstream that would otherwise be hidden behind dense node clusters. Place the dot at the **target column's X** so the final segment drops straight down

## Layout Principles

- **Main spine LEFT, side chains RIGHT** — matches Houdini's input connector order (input 0 = left)
- **Gradual diagonal convergence** — merge paths shift 1–3 units per step, no sharp jumps
- **Float the main column** — align each node toward its dominant input source, not a rigid X
- **Bypass/dead nodes far away** — opposite side of the active flow, clearly separated
- **Parallel chains in columns** — same vertical structure, horizontal offset
- **Orphans far to the side** — in their own network box labeled "Unused"
- **Don't touch nodes you didn't analyze** — if a node isn't in your position map, leave it
- **Never call `layoutChildren()` on the whole network** — only on specific node subsets
