# Smart Auto Rig

Guided, geometry-driven auto-rigging for Blender. Import a character, drop a few guides on the body, analyze, and
generate a complete rig (deform skeleton, FK/IK controls, foot roll, weights) - for humanoids, blocky/disconnected
characters (Minecraft-style), creatures with extra limbs, tails, wings and any custom chain.

Everything runs locally in Blender's Python. No internet, no external server, no paid API, no ML model.

## Requirements / status

* Target: Blender 5.1.x. `bl_info` declares a minimum of 4.2 (bone collections API).
* **Tested headlessly on Blender 5.0.1** (the `bpy` module): the whole pipeline, all operators and the built-in
  self test pass. **Not yet run on 5.1.x** and **the interactive viewport parts (modal guide editor, GPU overlay,
  sidebar drawing) could not be exercised without a display** - see *Limitations*.

## Installation

1. Zip the `smart_autorig` folder (a ready-made `smart_autorig.zip` is provided).
2. Blender > Edit > Preferences > Add-ons > Install from Disk... > pick the ZIP, then enable *Smart Auto Rig*.
3. Open the 3D Viewport, press `N`, tab **Smart Auto Rig**.

## Workflow

1. **Character** - select your mesh object(s) and press *Use Selected Objects* (or *Auto-Detect Character Objects*,
   which adds children and touching parts but ignores unrelated meshes far away).
2. **Guides** - press *Start Guided Setup*. The panel tells you what to click: head, neck, chest, pelvis, left/right
   shoulder, elbow, hand, hip, knee, foot. Click on the character to place the guide; drag to adjust.
   By default guides are placed at the *centre of the volume* along the view ray (joints live inside the body), so
   use front/side views (numpad 1 / 3) for best results. Prefer to start from an estimate? *Suggest Guides* fills
   the main humanoid guides in orange; confirm or drag them.
3. Optional: *+ Add Fingers*, *+ Tail*, *+ Wing*, *+ Arm* (extra arms), *+ Leg*, *+ Add Custom Chain*, then place their
   guides with *Edit Guides*.
4. **Analyze** - computes a *rig confidence* from measurable checks (see below) and lists concrete warnings.
5. **Preview Rig** (optional) - builds a preview armature (skeleton + control positions + hierarchy) without touching
   your character. *Accept*, *Edit Guides* or *Cancel*.
6. **Auto Rig** - builds the armature, controls, IK/FK, constraints, drivers and weights. A progress display shows
   the generation stages (this is separate from the analysis score). Esc cancels and removes partial results.
7. **Test Rig** - poses arms/legs (IK and FK), foot roll, spine, head and root, measures the response, reports
   problems and restores your pose.
8. Switch to Pose Mode and animate. The *Controls* panel has IK/FK sliders and foot roll.

### Guide editor keys (3D viewport)

| Key | Action |
|---|---|
| LMB | place the active guide / grab and drag a guide |
| X / Del | clear the hovered guide |
| M | mirror the hovered guide (or its whole chain) across the mirror plane |
| D | duplicate the chain (mirrored copy for L/R chains) |
| S | skip the current guided step |
| Enter / Esc / RMB | finish |

Colours: green = placed, orange = suggested (unconfirmed), yellow ring = active, white ring = hover.

## Generated rig

Collections: `SAR_<name>` > `Source`, `Rig`, `Controls` (custom shapes), `Deform` (bound duplicates).
By default the original meshes are **never modified**: duplicates are bound and the originals are hidden and kept
in `Source`. *Remove Rig* deletes the generated data and shows the originals again.

Bones: `DEF-*` (deform, hidden), `CTRL-*` (animator controls), `MCH-*` (mechanism, hidden).
Examples: `DEF-upper_arm.L`, `CTRL-fk_forearm.L`, `CTRL-ik_hand.L`, `CTRL-pole_arm.L`, `CTRL-ik_foot.L`, `CTRL-root`,
`CTRL-master`, `CTRL-pelvis`, `CTRL-head`. Extra limbs are numbered (`upper_arm2.L`), tails and custom chains
`tail_01`, `tail_02`, fingers `index_01.L`.

* Arms / legs: FK controls, IK control, pole control, driven IK/FK blend (`ik_fk` property on the IK control,
  1 = IK, 0 = FK). The IK pole angle is solved numerically at generation time.
* Legs: reverse-foot roll (`foot_roll` property in degrees: negative = heel, positive = ball then toe).
* Spine, neck, head, clavicles, tails, wings, fingers, ...: FK control chains.
* Every deform bone carries an `sar_std` custom property with a standard humanoid role (`hips`, `upperarm.L`, ...)
  so retargeting tools can map it. Retargeting itself is not implemented.

## Disconnected meshes

Nothing depends on mesh connectivity: guides live in world space, and each object is bound separately to the one rig.
For blocky parts (a cube per limb) use weighting method **Rigid per object** - each object follows the bone that is
closest to it as a whole. The default **Automatic** uses Blender's bone heat and falls back to smooth distance
weights for failures/uncovered vertices (and for very dense meshes, > 150k vertices).

## Weighting

* *Automatic* (bone heat + fallback), *Bone heat*, *Envelopes*, *Distance (smooth)*, *Rigid per object*.
* *Smooth*, *Clean* (threshold + max influences + normalise) and *Rebind* work on the real vertex groups.

## Analysis score

Six measured checks: mesh validity/orientation, required guides present, guide quality (distance to mesh, order
along chains, separation, bone length ratios), joint plausibility (angles; inferred joints score lower), symmetry
(mesh and guides; asymmetrical characters are not penalised), and mesh compatibility (fraction of the mesh within
reach of a bone). Concrete problems subtract extra points and are listed as warnings. It is a heuristic score of how
safe the generated rig is likely to be, not a guarantee, and not an AI model.

## Presets

*Save Preset* stores chains, guides (normalised to the character bounding box so they transfer between characters)
and rig/weight settings as JSON in the Blender config folder. *Load Preset* / *Reset* restore them. Meshes are never
touched.

## GPU / CPU

The sidebar shows what Blender reports (backend, device). The numeric kernels (distance matrices for weights and
coverage) use NumPy on the CPU. If the optional **CuPy** package is installed and Compute is *Auto/GPU*, they run on the
GPU through CuPy; otherwise it says "CPU fallback". No CUDA/AI acceleration is claimed unless CuPy is actually used.

## Extending

`rig/plan.py` has a `RigType` registry (`register_rig_type`) and a pure-data `RigPlan`; `rig/blueprint.py` turns it into
bone/constraint/driver definitions; `skeleton.py` / `constraints.py` realise them in Blender. `ProceduralAnalyzer`
logic lives in `analysis/`; an ML analyzer could replace `anatomy.suggest_humanoid_guides` without touching the rest.

## Troubleshooting

* *"No mesh character selected"* - select mesh objects, press *Use Selected Objects*.
* *"... guide is missing"* - place the named guide (humanoid needs head, neck, chest, pelvis, shoulders, hands, hips,
  feet). Use rig type **Creature** if your character lacks some parts.
* *"Two guides are at the same location"* - drag one of them.
* Elbows/knees bend the wrong way - move the elbow/knee guide slightly towards the direction it should bend (or place
  it manually instead of letting it be inferred).
* Weights look wrong on blocky characters - set method *Rigid per object*; on organic ones raise *Smooth passes*.
* Enable *Debug mode* (Advanced > Test & Tools) for the plan, timings and weighting details in the system console.

## Limitations (honest list)

* Procedural/geometric inference only; unusual characters need guides. It will not magically rig everything.
* The viewport overlay, modal guide editor and sidebar were written against the documented Blender API but not
  run interactively by the author; first-use rough edges are possible.
* Assumes +Z up; facing -Y and left = +X by default (changeable in Advanced > Character).
* No IK/FK snapping, no retargeting, no twist/corrective bones, no facial rig.
* Bone heat on very dense meshes is slow; > 150k vertices automatically use distance weights.
* Straight (perfectly extended) limbs get a 3-degree start bend on the IK helper bones because Blender's IK solver
  cannot bend a perfectly straight chain.

## Self test

Advanced > Test & Tools > *Run Add-on Self Test* builds test characters in a temporary scene (blocky humanoid, four-arm
creature with tail) and checks registration, properties, guides, analysis, preview, bone generation, constraints, IK,
drivers, binding, weights, validation, rig test, presets, error handling and CPU fallback.
