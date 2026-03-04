# Scene Inspect

## When to Use
When you need to understand the current state of a Houdini scene before making changes. This should typically be the first thing you do when connecting to an unfamiliar scene.

## What It Does
1. Gets basic scene info (hip file, frame, fps)
2. Reads the full node tree under /obj and /stage
3. Summarizes what's in the scene

## Parameters
None — works on any scene.

## Example
```python
from skills.examples.scene_inspect.run import run
from bridge.client import HoudiniClient

h = HoudiniClient()
report = run(h)
print(report)
```
