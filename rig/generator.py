"""High level rig generation pipeline (shared by the UI operators, self test and headless use).

`autorig_steps` is a Python generator: every `yield` is a good moment for the UI to redraw
(the modal operator advances it from a timer), and tests simply exhaust it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import bpy
from mathutils import Vector

from .. import constants as C
from .. import guides_model as GM
from ..analysis import mesh_analysis as MA
from ..utils import logging as log
from . import blueprint as BP
from . import constraints as CN
from . import deformation as DF
from . import ik_fk
from . import plan as PL
from . import skeleton as SK

STAGE_NAMES = ["Analyze mesh", "Fit skeleton", "Generate skeleton", "Generate controls", "Solve IK / FK",
               "Generate weights", "Validate"]
STAGE_SHARE = [0.08, 0.07, 0.15, 0.2, 0.1, 0.35, 0.05]


class GenerationError(Exception):
    """A user-facing failure (message explains the problem and a fix)."""


@dataclass
class BuildState:
    cd: object = None
    plan: object = None
    blueprint: object = None
    rig: object = None
    meshes: list = field(default_factory=list)
    log_lines: List[str] = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)


# ----------------------------------------------------------------------------- scene helpers
def character_objects(settings) -> list:
    return [r.obj for r in settings.objects if r.obj is not None and r.obj.name in bpy.data.objects]


def collect_chains(settings) -> List[PL.ChainDef]:
    out = []
    for ch in settings.chains:
        guides = GM.chain_guides(settings, ch.cid)
        keys = [g.key for g in guides]
        out.append(PL.ChainDef(ch.cid, ch.kind, ch.side, ch.name, ch.parent_chain, ch.use_ik, keys))
    return out


def get_collections(context, settings) -> Dict[str, bpy.types.Collection]:
    """Create / fetch the Character > Source / Rig / Controls / Deform collection structure."""
    root_name = f"SAR_{settings.character_name or 'Character'}"
    root = bpy.data.collections.get(root_name)
    if root is None:
        root = bpy.data.collections.new(root_name)
        context.scene.collection.children.link(root)
    elif root.name not in {c.name for c in context.scene.collection.children_recursive}:
        context.scene.collection.children.link(root)
    out = {"root": root}
    for key, sub in (("source", C.SUB_SOURCE), ("rig", C.SUB_RIG), ("controls", C.SUB_CONTROLS),
                     ("deform", C.SUB_DEFORM)):
        name = f"{root_name}.{sub}"
        coll = bpy.data.collections.get(name)
        if coll is None:
            coll = bpy.data.collections.new(name)
        if coll.name not in {c.name for c in root.children}:
            root.children.link(coll)
        out[key] = coll
    return out


def _set_progress(settings, idx: int, frac: float, label: str) -> None:
    while len(settings.stages) < len(STAGE_NAMES):
        settings.stages.add()
    for i, name in enumerate(STAGE_NAMES):
        st = settings.stages[i]
        st.name = name
        if i < idx:
            st.value = 1.0
        elif i == idx:
            st.value = max(0.0, min(1.0, frac))
        else:
            st.value = 0.0
    overall = sum(STAGE_SHARE[:idx]) + STAGE_SHARE[idx] * max(0.0, min(1.0, frac))
    settings.progress_value = overall
    settings.progress_label = label


def _check_guides_ready(settings, positions) -> None:
    if not settings.chains:
        raise GenerationError("No guides exist yet. Click 'Start Guided Setup' and place the guides first.")
    if not positions:
        raise GenerationError("No guides have been placed. Use Guided Setup to place at least the main guides.")


# ----------------------------------------------------------------------------- cleanup
def remove_preview(context, settings) -> None:
    rig = settings.preview_rig
    settings.preview_rig = None
    settings.preview_state = "NONE"
    if rig is not None and rig.name in bpy.data.objects:
        data = rig.data
        bpy.data.objects.remove(rig, do_unlink=True)
        if data and data.users == 0:
            bpy.data.armatures.remove(data)


def remove_generated(context, settings, restore_sources: bool = True) -> int:
    """Remove the rig, the preview and the bound duplicates; unhide the source objects."""
    removed = 0
    remove_preview(context, settings)
    rig = settings.rig_object
    if rig is not None and rig.name in bpy.data.objects:
        for obj in list(DF.bound_meshes(rig, context.scene)):
            if obj.get("sar_source"):
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data.users == 0:
                    bpy.data.meshes.remove(data)
                removed += 1
            else:
                DF.unbind_object(obj, rig)
        data = rig.data
        bpy.data.objects.remove(rig, do_unlink=True)
        if data and data.users == 0:
            bpy.data.armatures.remove(data)
        removed += 1
    settings.rig_object = None
    if restore_sources:
        for ref in settings.objects:
            if ref.obj is not None and ref.obj.name in bpy.data.objects:
                try:
                    ref.obj.hide_set(False)
                except RuntimeError:
                    pass
    for obj in [o for o in bpy.data.objects if o.name.startswith("WGT-SAR-") and o.users <= 1]:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0:
            bpy.data.meshes.remove(data)
    return removed


def duplicate_sources(context, settings, colls) -> list:
    """Duplicate character meshes into the Deform collection and hide the originals."""
    out = []
    for src in character_objects(settings):
        if src.type != "MESH":
            continue
        if src.name not in colls["source"].objects:
            colls["source"].objects.link(src)
        dup = src.copy()
        dup.data = src.data.copy()
        dup.name = f"{src.name}.rig"
        dup["sar_source"] = src.name
        colls["deform"].objects.link(dup)
        src.hide_set(True)
        out.append(dup)
    return out


# ----------------------------------------------------------------------------- pipeline
def autorig_steps(context, settings, mode: str = "FULL") -> Iterator[Tuple[int, float, str]]:
    """Generator performing the whole job. mode: 'FULL' or 'PREVIEW'. Yields (stage, fraction, label)."""
    state = BuildState()
    scene = context.scene
    log.set_debug(settings.debug_mode)
    t_all = time.perf_counter()

    # ---------------------------------------------------------------- analyze
    yield 0, 0.0, "Collecting character meshes"
    objs = character_objects(settings)
    if not objs:
        raise GenerationError("No character selected. Select your character mesh(es) and click 'Use Selected Objects'.")
    cd = MA.gather_character(objs, settings.analysis_quality)
    for msg in cd.invalid:
        log.warn(msg)
    if not cd.objects:
        raise GenerationError("None of the selected objects is a usable mesh. Select a mesh object and try again.")
    state.cd = cd
    yield 0, 1.0, "Mesh analysed"

    # ---------------------------------------------------------------- plan
    yield 1, 0.0, "Fitting skeleton to guides"
    positions = GM.placed_positions(settings)
    _check_guides_ready(settings, positions)
    options = PL.RigOptions.from_settings(settings)
    plan = PL.build_plan(positions, collect_chains(settings), options, cd)
    log.debug(PL.describe(plan))
    state.plan = plan
    if plan.errors:
        raise GenerationError(plan.errors[0] + (f" (+{len(plan.errors) - 1} more problems)" if len(plan.errors) > 1 else ""))
    bp = BP.build_blueprint(plan)
    state.blueprint = bp
    yield 1, 1.0, f"{len(plan.bones)} bones planned"

    colls = get_collections(context, settings)

    if mode == "PREVIEW":
        remove_preview(context, settings)
        name = f"SAR_Preview_{settings.character_name}"
        yield 2, 0.0, "Creating preview skeleton"
        rig = SK.create_armature_object(name, colls["rig"])
        SK.apply_bone_defs(rig, bp, plan.height)
        yield 2, 0.7, "Styling preview"
        CN.apply_pose_setup(rig, bp, _controls_collection(colls, context), with_logic=False)
        rig.data.display_type = "STICK"
        settings.preview_rig = rig
        settings.preview_state = "PENDING"
        _store_plan_summary(settings, plan)
        state.rig = rig
        yield 2, 1.0, "Preview ready"
        _finish(settings, state)
        return

    # ---------------------------------------------------------------- generate
    remove_preview(context, settings)
    if settings.rig_object is not None:
        remove_generated(context, settings, restore_sources=False)
    name = settings.rig_name or f"RIG-{settings.character_name}"
    yield 2, 0.0, "Creating armature"
    rig = SK.create_armature_object(name, colls["rig"])
    n = SK.apply_bone_defs(rig, bp, plan.height)
    rig["sar_rig"] = True
    rig["sar_character"] = settings.character_name
    store_rig_metadata(rig, plan, bp)
    state.rig = rig
    settings.rig_object = rig
    yield 2, 1.0, f"{n} bones created"

    yield 3, 0.0, "Adding controls, constraints and drivers"
    stats = CN.apply_pose_setup(rig, bp, _controls_collection(colls, context), with_logic=options.generate_controls)
    rig.data.display_type = "OCTAHEDRAL" if not options.generate_controls else "STICK"
    for e in stats["errors"]:
        plan.warnings.append(e)
    shapes = _controls_collection(colls, context)
    for o in shapes.objects:
        try:
            o.hide_set(True)
        except RuntimeError:
            pass
    yield 3, 1.0, f"{stats['constraints']} constraints, {stats['drivers']} drivers"

    yield 4, 0.0, "Solving pole angles"
    if options.generate_controls and options.generate_ik:
        for line in ik_fk.solve_pole_angles(rig, bp):
            log.debug(line)
    yield 4, 1.0, "IK/FK ready"

    # ---------------------------------------------------------------- weights
    if options.generate_controls:
        _apply_rest_pose_flush(rig)
    meshes = duplicate_sources(context, settings, colls) if settings.preserve_source else \
        [o for o in character_objects(settings) if o.type == "MESH"]
    state.meshes = meshes
    if settings.bind_weights and meshes:
        total = len(meshes)
        for i, obj in enumerate(meshes):
            yield 5, i / total, f"Weights: {obj.name}"
            desc = DF.bind_object(context, obj, rig, settings)
            state.log_lines.append(f"{obj.name}: {desc}")
            log.debug(f"{obj.name}: {desc}")
            if settings.weight_smooth_iterations > 0 and settings.weight_method not in {"RIGID"}:
                DF.smooth_weights(obj, rig, settings.weight_smooth_iterations, settings.weight_smooth_factor)
            if settings.weight_method != "RIGID":
                DF.clean_weights(obj, rig, settings.weight_clean_threshold, settings.weight_max_influences)
        yield 5, 1.0, "Weights generated"
    else:
        yield 5, 1.0, "Weights skipped"

    # ---------------------------------------------------------------- validate
    yield 6, 0.0, "Validating rig"
    from ..utils import validation

    results = validation.validate_rig(rig, settings, plan, meshes)
    validation.store(settings, results)
    _store_plan_summary(settings, plan)
    rig.select_set(False)
    context.view_layer.objects.active = rig
    rig.select_set(True)
    yield 6, 1.0, "Done"
    state.timings["total"] = time.perf_counter() - t_all
    log.debug(f"auto rig finished in {state.timings['total']:.2f}s")
    _finish(settings, state)


def store_rig_metadata(rig, plan, bp) -> None:
    """Information the test / UI code needs later (kept on the rig object so it survives file save)."""
    import json

    limbs = []
    for li in bp.limbs:
        limbs.append({"chain": li.chain, "kind": li.kind, "side": li.side, "ctrl_ik": li.ctrl_ik,
                      "upper_def": li.upper_def, "end_def": "DEF-" + [l for l in plan.limbs if l.chain == li.chain][0].bones[2],
                      "has_ik": li.has_ik, "has_fk": li.has_fk})
    rig["sar_limbs"] = json.dumps(limbs)
    rig["sar_spine"] = json.dumps([n for n in plan.spine])
    rig["sar_height"] = plan.height


def _controls_collection(colls, context):
    return colls["controls"]


def _apply_rest_pose_flush(rig) -> None:
    bpy.context.view_layer.update()


def _store_plan_summary(settings, plan) -> None:
    settings.messages.clear()
    for w in plan.warnings:
        m = settings.messages.add()
        m.text, m.level = w, "WARN"
    if plan.inferred:
        m = settings.messages.add()
        m.text = "Inferred: " + ", ".join(sorted(set(plan.inferred)))
        m.level = "INFO"


def _finish(settings, state: BuildState) -> None:
    settings.progress_active = False
    settings.progress_label = "Finished"
    settings.progress_value = 1.0
    global LAST_STATE
    LAST_STATE = state


LAST_STATE: Optional[BuildState] = None


def run_to_completion(context, settings, mode: str = "FULL") -> BuildState:
    for stage, frac, label in autorig_steps(context, settings, mode):
        _set_progress(settings, stage, frac, label)
    return LAST_STATE
