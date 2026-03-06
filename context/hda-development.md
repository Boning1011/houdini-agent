# HDA Development Patterns

Lessons learned from programmatically creating/modifying HDAs via the bridge.

## Parameter Template API Gotchas

- **LabelParmTemplate**: Display text is in `columnLabels`, NOT `defaultValue` (which doesn't exist on this class). Use `setColumnLabels(["text"])`. Use `asCode()` to discover the correct constructor pattern for any parm template.
- **Adding parameters**: Use `ptg.insertAfter("existing_parm_name", new_template)` to position precisely.
- **StringParmTemplate for file paths**: Use `string_type=hou.stringParmType.FileReference` and `file_type=hou.fileType.Any` to get a file chooser widget.

## Modifying HDA Definitions Programmatically

Standard workflow:
```python
defn = node.type().definition()
defn.updateFromNode(node)      # sync any live edits from the node
ptg = defn.parmTemplateGroup()
# ... modify ptg ...
defn.setParmTemplateGroup(ptg)
```

- **Always call `updateFromNode(node)` first** — otherwise you may overwrite changes the user made in the Type Properties dialog.
- **User can clobber your changes**: If they have the Type Properties editor open and click Apply after your programmatic update, their cached version overwrites yours. Warn about this.

## PythonModule & Button Callbacks

- **`hou.phm()` / `node.hdaModule()` cache issue**: After programmatically updating `PythonModule` section contents via `setContents()`, neither `hou.phm()` nor `hdaModule()` refreshes — even after `hou.hda.reloadFile()`. Functions appear invisible.
- **Workaround**: Use `exec()` in the button callback to load the section at runtime:
  ```
  exec(kwargs["node"].type().definition().sections()["PythonModule"].contents());my_function(kwargs)
  ```
- **Writing PythonModule content**: Use `hou.readFile("path/to/file.py")` to load from a temp file, avoids all quoting/escaping issues in exec() calls.

## Rig Pose Node (KineFX)

- **Group naming**: Joint groups follow `@name=joint_1`, `@name=joint_2`, etc.
- **Rotation axes differ per joint**: Do NOT assume all joints rotate on the same axis. Auto-detect by checking which of `rNx/rNy/rNz` has the largest absolute value. Other axes typically have near-zero noise values (~1e-5).
- **Counting groups**: The `configurations` parm is a Folder type (eval() returns 0). Instead, iterate `group0, group1, ...` until `parm("groupN")` returns None.
- **Multiparm offset**: Rig Pose multiparms in this setup use 0-based indexing (`group0`, `r0x`, etc.).

## Bridge Execution Tips

- **`query()` = single expression** (returns value), **`exec()` = multi-line code** (returns None on success).
- **Avoid triple quotes and `\n` in inline code strings** — they cause escaping nightmares across Python→bridge→Houdini. For multi-line Houdini code, write to a temp file and use `hou.readFile()`, or build strings with `chr(10)` for newlines.
- **Testing button callbacks**: Simulate by exec'ing the same code the callback would run, in a bridge `exec()` call. This catches errors before the user clicks.
