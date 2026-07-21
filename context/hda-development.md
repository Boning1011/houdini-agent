<!-- houdini_version: 21.0 -->
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
defn.setParmTemplateGroup(ptg)   # ← write back to the TYPE definition
```

- **Always call `updateFromNode(node)` first** — otherwise you may overwrite changes the user made in the Type Properties dialog.
- **User can clobber your changes**: If they have the Type Properties editor open and click Apply after your programmatic update, their cached version overwrites yours. Warn about this.

### ⚠️ Parm-template traps — read this before "shortcuts"

**`node.setParmTemplateGroup(ptg)` is NOT a shortcut for `defn.setParmTemplateGroup(ptg)`.** They do different things:

| Call | Where the parms live | Effect |
|---|---|---|
| `node.setParmTemplateGroup(ptg)` | On the **instance** as spare parms. Persist with the .hip file. | HDA TYPE stays empty. New instances of the type get a blank panel. |
| `defn.setParmTemplateGroup(ptg)` | On the **HDA type definition**, saved into the .hda/.hdalc file. | Every instance (existing + future) inherits these parms. |

**`defn.updateFromNode(node)` does NOT promote node-level spare parms into the type's parm template.** It syncs the contained network and some metadata, but spare parms stay where they were — on the instance.

Symptoms when you've used the wrong call:
- The running instance has all the parms and behaves correctly. Looks like everything works.
- But `defn.parmTemplateGroup().parmTemplates()` returns `[]`.
- And `defn.sections()["DialogScript"].contents()` is ~310 bytes (just the skeleton — a real HDA with parms is several KB).
- Then the user crashes or starts a fresh session and creates a new instance (with `_1` suffix), and that instance has an **empty parm panel**. Any wrangles whose expressions reference parent parms (e.g. `ch("../buffer_in")`) start erroring with "Unable to evaluate expression".

How to verify after any HDA parm work:
```python
defn = node.type().definition()
n_parms = len(defn.parmTemplateGroup().parmTemplates())
ds_size = len(defn.sections()["DialogScript"].contents())
assert n_parms > 0 and ds_size > 500, "parm template not promoted to HDA type"
```

If you DID use `node.setParmTemplateGroup()` and need to recover:
```python
ptg = node.parmTemplateGroup()       # capture from the instance
defn.setParmTemplateGroup(ptg)       # write into the type
defn.save(defn.libraryFilePath())
for inst in node.type().instances():
    inst.matchCurrentDefinition()    # refresh existing instances
```

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

## Auto Git Commit & Push After HDA Save

**Mandatory**: Every time you save/update an HDA definition, immediately commit and push the `.hda`/`.hdalc` file to git. The user's HDA library is git-tracked and may be modified 10+ times per day — each save must be versioned.

Steps after any HDA save (`updateFromNode`, `setParmTemplateGroup`, `setContents`, etc.):

1. **Get the library file path** (in Houdini via bridge):
   ```python
   lib_path = h.query(f"hou.node('{node_path}').type().definition().libraryFilePath()")
   ```

2. **Find the git repo root** (in shell):
   ```bash
   cd "$(dirname "$lib_path")" && git rev-parse --show-toplevel
   ```
   If this fails, the HDA is not in a git repo — skip.

3. **Commit and push**:
   ```bash
   cd "<repo_root>"
   git add "<hda_file>"
   git commit -m "Update <HDA label> (<type_name>): <summary of changes>"
   git pull --rebase origin main
   git push
   ```

- Commit message should summarize what you actually changed (e.g., "Add file path parameter", "Fix rotation axis detection", "Update PythonModule callback").
- If `git pull --rebase` has conflicts, stop and ask the user.
- If the repo has unstaged changes unrelated to the HDA, stash them before rebase and pop after.

## Do NOT uninstall + install + save in one exec batch (H21.0 crash)

**Never** do `hou.hda.uninstallFile(lib)` → `hou.hda.installFile(lib)` → `defn.save(lib)` within the same `exec()` call, or back-to-back without a UI event tick between them. Houdini 21.0.631 segfaults in `UI_Object::isAncestor` when the OTL manager's dialog refresh runs against a freshly torn-down parm template tree. Stack top:

```
UI_Object::isAncestor → UI_Feel::replaceChild → OPUI_Dialog::reloadDialog
  → OP_Operator::updateParmTemplates → OP_OTLManager::refreshLibrary
  → HOMF_HDADefinition::save
```

What to do instead:
- To update an already-loaded HDA, just `defn.save(defn.libraryFilePath())` — Houdini refreshes automatically. No uninstall needed.
- If you truly need to reload from disk, use `hou.hda.reloadFile(lib)` (single call, no unpaired uninstall/install).
- If you botched a createDigitalAsset and the type name is "stuck" in memory, don't fight it with uninstall — bump the version (e.g. `::1.0` → `::1.0.1`) and save to a new library path, or ask the user to restart Houdini.


## More Gotchas From the Trenches

### `updateFromNode` order matters when changing BOTH network and parms

When an edit touches both the internal network AND the parm template:

```python
N.allowEditingOfContents()
# 1. modify the instance's contained network (create/wire/destroy nodes)
# 2. THEN sync the network into the type:
defn.updateFromNode(N)
# 3. THEN apply parm template changes:
ptg = defn.parmTemplateGroup()      # ← read AFTER updateFromNode
# ... modify ptg ...
defn.setParmTemplateGroup(ptg)
# 4. THEN save and refresh instances:
defn.save(defn.libraryFilePath())
for inst in op.instances():
    inst.matchCurrentDefinition()
```

If you call `matchCurrentDefinition()` BEFORE `updateFromNode()`, the
instance reverts to whatever the type currently looks like, throwing
away your new internal nodes.

If you build a fresh ParmTemplateGroup from scratch and call
`defn.setParmTemplateGroup(ptg)` AFTER `updateFromNode` (which already
pulled the current parm template into the definition), you can get
`Parameter name 'X' is invalid or already exists` because the
definition already has those parms. Read the ptg back from the
definition AFTER updateFromNode and modify it in place instead.

### `ptg.replace(name, new_template)` can't rename in one shot

`replace(name, tpl)` uses the FIRST argument as the identifier to
look up. If `tpl.name() != name` it tries to add `tpl` as a new entry
and gets a "Parameter name 'X' already exists" conflict against the
one you intended to replace. To rename a folder, either:

- Keep the internal `name` identical and only change the label
  (`hou.FolderParmTemplate(same_name, "New Label", ...)`), or
- Remove the old by name first, then insert the new with a different
  name at the same position (`ptg.remove("old"); ptg.insertBefore("anchor", new)`).

### VEX `@attrib = ...` PRE-DECLARES the attribute even inside `if(){}`

```vex
// Looks like this only creates volume_in3 when cond is true.
// In reality: volume_in3 gets pre-declared at COMPILE time and
// exists in every cook with default value 0, even when cond=0.
if (cond) {
    f@volume_in3 = some_value;
}
```

Use the function-call form to avoid the pre-declaration:

```vex
if (cond) {
    setdetailattrib(0, "volume_in3", some_value, "set");
    // setpointattrib / setprimattrib / setvertexattrib similarly
}
```

Symptom in the wild: downstream node still sees `volume_in3=0` on every
prim/point when the user expected the attribute to be absent entirely
under the off path.

### Measure SOP: `attribname` cannot be empty

The per-prim output attribute name is required. Setting `attribname=""`
to "disable" it errors with "Could not create primitive attribute ''".
Set it to a junk name with an underscore prefix (e.g. `_per_prim_volume`)
and rely on downstream cleanup if you don't want it in the final output.
The `usetotalattrib` toggle controls the detail-attribute output
independently; that one CAN be turned off.

## Copernicus (Cop) HDA specifics (H22, learned building boning::flow_lenia)

### IO is declared via hub nodes + operator min/max — BOTH matter

- A Cop subnet's ports come from **single hub nodes**: one `input`-type node
  (its output k = asset input k) and one `output`-type node (its input k =
  asset output k). NOT one node per port. Fresh Cop subnets auto-create hubs
  named `inputs`/`outputs`; `collapseIntoSubnet` does **not** — add them.
  Hubs expose 2048 virtual connectors; count comes from what's wired.
- The operator type ALSO declares `minNumInputs/maxNumInputs/maxNumOutputs`.
  **Pass `min_num_inputs`/`max_num_inputs` to `createDigitalAsset()` at
  creation time.** Declaring inputs post-hoc (`defn.setMaxNumInputs` + save +
  reload) makes connectors *appear* and wire without error, but the input hub
  passes NO data — downstream OpenCL errors "Missing layer on input" /
  "@x was not bound" on a fresh instance. Only a clean re-create of the asset
  (copy network to a new subnet with auto-hubs, uninstall + delete file in
  separate exec ticks, `createDigitalAsset` with the right args) fixed it.
- Outputs were more forgiving: creation derived 1 output despite 2 wired hub
  inputs; post-hoc `defn.setMaxNumOutputs(2)` + `defn.save()` produced a
  working second port. If a "working" port carries all-zero data, suspect the
  DATA (e.g. a black colormap) before declaring the port dead — we burned a
  rebuild on that misread.
- `switchifwired` (rule `firstwire`) + input hub is the standard optional-input
  pattern: hub → in0, internal default → in1. Verified working inside a locked
  Cop HDA.

### Building a begin/end sim-block HDA pair (RD/pyro/ripple style, H22)

To split a COP simulation into two HDAs with an open user-editable middle
(like `reactiondiffusion_block_begin/end`), four things must ALL be right —
each failure mode below was hit building `boning::flow_lenia_block_*`:

1. **`hda_type` declaration is the master switch.** The begin/end HDAs'
   DialogScript must contain `hda_type block_begin` / `hda_type block_end`
   (indented line after `label`). Without it the raw `block_end simulate=1`
   inside errors "Cannot do simulate if the block doesn't have a begin node
   at the same level" — the raw block nodes live in different HDAs, and only
   this declaration makes the compiler treat the HDA instances as the
   region boundary. It also registers pairing (`coppairednode("<end>")`
   hscript fn returns the begin path) and turns `blockpath` into a native
   reserved parm on the begin type — adding your own 'blockpath' template
   then fails with "Reserved parameter 'blockpath' already exists".
2. **Pairing wiring**: begin HDA exposes `blockpath` (native, empty default);
   the inner raw block_begin's blockpath is the literal string
   `` `chsop("../blockpath")`/<inner_end_name> `` — chsop expands the
   node reference to an absolute path. Users (or the tab tool) set
   begin.blockpath = '../<end_instance>'. There is NO auto-pairing.
   Bonus: put ALL user parms on the END node (RD convention — one panel)
   and have begin's inner nodes read them through the pairing:
   `ch(chsop("../blockpath")/parmname)` (verbatim official RD pattern;
   "../blockpath" is begin's own parm as seen from the inner node).
   Also expose the raw block_end's native `iterations` parm — it reruns
   the whole begin→middle→end region N times per frame (substeps),
   including any user nodes inserted in the open middle.
3. **Hand-author the DS IO lines.** createDigitalAsset generates
   `input input1 src / output output1 dst / signature default Default
   { RGBA } { RGBA }` — the RGBA boundary signature type-mismatches any
   non-RGBA port ("Type mismatch at input N on <inner node>"). Replace with
   named lines (`input mass mass`, `output flow flow`, ...) and a real
   signature: `signature default Default { Mono Mono UV } { Mono UV ... }`
   (first brace-list = input types in order, second = outputs; type names
   as in the constant COP signature menu: Mono/UV/RGB/RGBA/...).
4. **Every `setParmTemplateGroup` regenerates the DialogScript and wipes
   hda_type + IO + signature lines.** Re-inject them after ANY parm edit
   (keep a fix-headers script; verify with `'hda_type' in ds`).

Also: external references (a set blockpath) block createDigitalAsset —
clear the parm or pass `ignore_external_references=True`. And a converted
master instance stays UNLOCKED; sim-block behavior only engages on locked
instances (`matchCurrentDefinition()`), so always test with a fresh locked
instance, not the conversion leftover.

Paired tab-creation is NOT native: the official pairs' Tools.shelf scripts
are plain genericTool. Write the begin HDA's Tools.shelf script to create
both nodes, wire them, and set blockpath (`coptoolutils.genericTool` for
the begin, `parent.createNode` for the end).

For wires the user adds in the open middle: any data entering the region
from outside must route through extra block_begin ports — expose aux
passthrough ports (begin inputs → raw block_begin ports → begin outputs)
or the user's mid-block graph fails to compile.

### Cop createDigitalAsset input counts: verify, don't trust

`min_num_inputs`/`max_num_inputs` args can be silently overridden by the
number of externally wired inputs at conversion time (observed: passed
max 3, stored max 1). After creation, check `type().maxNumInputs()` and fix
via `defn.setMinNumInputs/setMaxNumInputs` + save — then RE-CREATE instances
(existing ones keep the old connector set and reject `setInput` with
"Invalid input").

### Do NOT promote ramp parms into Cop OpenCL HDAs

Two independent breakages, both silent (kernel reads garbage, usually black):

1. `inner.parm('cmap').set(hda.parm('cmap'))` links only the multiparm COUNT.
   Per-key channels (`cmap2cr`, ...) stay static — `evalAsRamp()` on the parm
   *looks* correct (it follows the top-level reference), but the OpenCL
   binding reads the dead per-key values. Diagnosis that finally caught it:
   compare `parm.evalAsString()` per KEY against `getReferencedParm()`.
2. `hou.copyNodesTo` breaks the multiparm channel refs inside the opencl
   `bindings` entry itself (ramp keys 2..N materialize as static zeros).
   Repair: re-run `vexpressionmenu.createSpareParmsFromOCLBindings` (after
   `parm('bindings').set(0)` to clear the dead entry), which re-links
   binding ramp ↔ spare parm with proper multiparm references.

Robust alternative used in flow_lenia: bake colormaps into the kernel as
polynomial fits (viridis/magma) behind an int `preset` parm — int/float parms
link via plain `ch("../x")` with none of this fragility. Keep real ramps
internal to the HDA.

## Bridge Execution Tips

- **`query()` = single expression** (returns value), **`exec()` = multi-line code** (returns None on success).
- **Avoid triple quotes and `\n` in inline code strings** — they cause escaping nightmares across Python→bridge→Houdini. For multi-line Houdini code, write to a temp file and use `hou.readFile()`, or build strings with `chr(10)` for newlines.
- **Testing button callbacks**: Simulate by exec'ing the same code the callback would run, in a bridge `exec()` call. This catches errors before the user clicks.
- **NEVER define functions inside a bridge `exec()` string.** The bridge runs your code with split globals/locals, so a nested `def` can't see module-level names/builtins reliably — symptoms are bizarre (`parm.set(2)` works at top level but raises the SWIG `map<string,string>` overload error from inside a helper). Build flat: inline the repeated logic, or write a real `.py` file and load it into a Python SOP via `hou.readFile()`.
- **Non-ASCII bytes break `parm.set(str)`.** `HOM_Parm._set` with a string containing any byte >127 (e.g. an em-dash `—` = 0x97 written by Windows `open(f,'w')` in cp1252) fails to bind to `char*` and SWIG falls through to the `std::map<string,string>` overload, raising `TypeError: argument 2 of type 'std::map<...>'`. Keep VEX/PythonModule files pure ASCII; when writing files for Houdini use `open(f,'wb')` with `.encode('ascii')` or pass `encoding='utf-8'` and avoid smart-dashes.
- **AttribWrangle `class` parm is an int menu**, not a string: `0=detail, 1=primitive, 2=point, 3=vertex`. Setting the wrong one silently changes behavior — a per-point setup wrangle left at `class=0` (detail) runs ONCE, so per-point `@orient`/`@variant`/`removepoint` never apply and downstream copy-to-points falls back to defaults (looks like it "works" but every instance is variant 0).

## Memory-Light Instancing: pack-by-name + Copy to Points

To instance a small asset library across thousands of points so geometry is shared in memory:

1. Build each prop once, tag a per-prop int id (e.g. `i@variant`) and a `s@name`.
2. **Pack SOP**: `packbyname=1`, `nameattribute='name'`, and set **`transfer_attributes='variant cat ...'`** — without listing the id attribute here it does NOT survive onto the packed prims (they all read 0, and matching collapses). One packed prim per name.
3. Target points carry the same int id (`i@variant`).
4. **Copy to Points** (this H21 build has no "piece attribute" parm): set **`useidattrib=1`, `idattrib='variant'`, `transform=1`, `pack=1`**. Each target point gets the source piece whose id matches; `pack=1` keeps results as packed instances (shared geometry).

Multi-level: pack props (L1) → copy-to-points packed instances (L2) → optional final Pack of the whole build into one packed prim (L3) for city-scale placement.
