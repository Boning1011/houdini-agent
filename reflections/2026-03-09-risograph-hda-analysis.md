# Session Reflection — 2026-03-09 — Risograph HDA Internal Analysis

## What Was Done

- Explored the internal structure of the Risograph HDA (~100+ internal nodes) to understand the full pipeline
- Extracted and analyzed 4 OpenCL kernels: `weight_calculation`, `Add_all_layers`, `Add_all_weights`, `offset_order`
- Extracted the `km_converter` HDA's two OpenCL kernels (standard KM and scattering-factor variant)
- Mapped the full data flow: input → KM conversion → weight decomposition → dithering → multiply → sum → KM inverse → composite
- Identified palette system (6 presets × 5 inks from 19 colors), dither modes, and misregistration mechanism

## Critical Path

What would have been sufficient:

1. `h.scene_snapshot("/obj/EXAMPLES/risograph", depth=1)` — all nodes, types, connections in one call
2. `h.get_parms` on the HDA itself — user-facing parameter interface
3. `h.get_parms` on `weight_calculation` → extract `kernelcode` — the core algorithm
4. `h.get_parms` on `Add_all_layers`, `Add_all_weights`, `offset_order` — supporting kernels
5. `h.get_parms` on a few palette constant nodes — check `signature`, then read the matching parm prefix
6. `h.get_parms` on `km_converter` internal OpenCL nodes — KM color science

6 queries. In practice it took ~15.

## Friction Log

| What was attempted | What happened | Cost |
|---|---|---|
| `parm("source").eval()` on OpenCL node | KeyError — parm doesn't exist. Actual parm name is `kernelcode` | 1 round-trip |
| `get_parms` on OpenCL node to get kernel code | Got ~4KB response — mostly binding/option metadata, only ~1KB was actual kernel code | Context waste |
| Read palette colors with `f4r/f4g/f4b` on constant node | All returned 1.0 — wrong parm prefix. Node has `signature=f3`, so parms are `f3r/f3g/f3b` | 1 round-trip |
| `maxNumInputs()` on switch_palette node | Returned ~256 — generated 60KB of output iterating over empty slots | 1 round-trip + context |
| Traced output chain one node at a time via `query()` | Took ~5 separate calls: `outputs` → `switch2` → `rgbatorgb3` → `switch6` → etc. | ~5 round-trips |
| `inputConnectors()[i].label()` on COP node | AttributeError — tuples, not objects. Same mistake as MotionCops session | 1 round-trip |

Note: `scene_snapshot` already existed and returns `inputs`/`outputs` for every node. The connection tracing (~5 round-trips) could have been avoided entirely by snapshotting the network and traversing the dict client-side.

## Observations

- COP OpenCL nodes store kernel code in `kernelcode` parm, not `source`
- COP constant node `signature` determines parm prefix: `f3` → `f3r/f3g/f3b`; `f4` → `f4r/f4g/f4b/f4a`; `f1` → `f1`
- COP switch nodes report `maxNumInputs()` ≈ 256 regardless of actual connected inputs — must use bounded iteration (e.g., `range(10)`)
- `get_parms` on OpenCL nodes returns extensive binding metadata alongside the actual kernel code
- `scene_snapshot` returns `inputs` and `outputs` for every node — sufficient for full connection tracing without additional queries
- H21 COP `inputConnectors()` returns tuples, not objects — this was encountered in both sessions
