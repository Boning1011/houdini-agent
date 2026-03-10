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

## Layout Principles

- **Don't touch nodes you didn't analyze** — if a node isn't in your position map, leave it where it is
- **Parallel chains in columns** — same vertical structure, horizontal offset
- **Orphans far to the side** — visually separated, in their own network box labeled "Unused"
- **Never call `layoutChildren()` on the whole network** — it destroys the user's intentional layout. Only use it on specific node subsets, or compute positions yourself
