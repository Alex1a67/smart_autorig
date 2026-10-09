"""Rig validation and non-destructive pose test."""
from __future__ import annotations

import json
import math
from typing import List

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

from ..rig import deformation as DF
from ..utils import validation
from ..utils.validation import Result


def _mesh_coords(meshes, depsgraph) -> np.ndarray:
    chunks = []
    for obj in meshes:
        ev = obj.evaluated_get(depsgraph)
        me = ev.to_mesh()
        a = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", a)
        ev.to_mesh_clear()
        chunks.append(a)
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def _snapshot(rig):
    snap = {}
    for pb in rig.pose.bones:
        snap[pb.name] = (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(),
                         pb.scale.copy(), {k: pb[k] for k in ("ik_fk", "foot_roll") if k in pb.keys()})
    return snap


def _restore(rig, snap):
    for pb in rig.pose.bones:
        loc, quat, eul, scl, props = snap[pb.name]
        pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = loc, quat, eul, scl
        for k, v in props.items():
            pb[k] = v
    rig.update_tag()
    bpy.context.view_layer.update()


def run_rig_test(context, rig, meshes) -> List[Result]:
    """Apply safe test poses, measure bones and mesh response, and restore the original pose."""
    out: List[Result] = []
    if rig is None:
        return [("ERROR", "No generated rig to test. Run Auto Rig first.")]
    view_layer = context.view_layer
    pb_all = rig.pose.bones
    height = float(rig.get("sar_height", 1.0))
    limbs = json.loads(rig.get("sar_limbs", "[]"))
    spine = json.loads(rig.get("sar_spine", "[]"))
    meshes = [m for m in (meshes or []) if m.type == "MESH"]
    prev_mode = rig.mode
    snap = _snapshot(rig)

    def update():
        rig.update_tag()
        view_layer.update()

    def head(name):
        return rig.matrix_world @ pb_all[name].head

    def tail(name):
        return rig.matrix_world @ pb_all[name].tail

    def mesh_move():
        return float(np.abs(_mesh_coords(meshes, context.evaluated_depsgraph_get()) - base_mesh).max()) \
            if meshes and base_mesh.size else 0.0

    try:
        update()
        base_mesh = _mesh_coords(meshes, context.evaluated_depsgraph_get()) if meshes else np.zeros(0)

        for lim in limbs:
            label = f"{lim['kind'].title()} {lim['chain']}"
            upper, end = lim["upper_def"], lim["end_def"]
            root = head(upper)
            end_rest = head(end)
            axis = end_rest - root
            L = axis.length
            if lim["has_ik"]:
                ctrl = pb_all[lim["ctrl_ik"]]
                if "ik_fk" in ctrl.keys():
                    ctrl["ik_fk"] = 1.0
                n = axis.normalized()
                world_axis = min((Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))), key=lambda v: abs(v.dot(n)))
                perp = n.cross(world_axis).normalized()
                shift = -axis * 0.3 + perp * L * 0.15
                ctrl.matrix = Matrix.Translation(rig.matrix_world.inverted().to_3x3() @ shift) @ ctrl.matrix
                update()
                err = (head(end) - (end_rest + shift)).length / max(L, 1e-9)   # the IK target moves rigidly with the control
                moved = (head(end) - end_rest).length / height
                if err < 0.12 and moved > 0.005:
                    out.append(("OK", f"{label}: IK reaches its target (error {err * 100:.1f}% of limb)"))
                elif moved <= 0.005:
                    out.append(("ERROR", f"{label}: IK control did not move the limb. Check IK constraint / IK-FK switch."))
                else:
                    out.append(("WARN", f"{label}: IK misses its target by {err * 100:.0f}% of the limb length."))
                if meshes:
                    mm = mesh_move() / height
                    out.append(("OK", f"{label}: mesh follows IK ({mm * 100:.1f}% of height)") if mm > 0.004 else
                               ("WARN", f"{label}: mesh barely moved with IK - check weights for this limb."))
                ctrl.matrix_basis = Matrix.Identity(4)
                update()
            if lim["has_fk"]:
                fk_name = "CTRL-fk_" + upper[4:]
                if fk_name in pb_all:
                    if lim["has_ik"] and "ik_fk" in pb_all[lim["ctrl_ik"]].keys():
                        pb_all[lim["ctrl_ik"]]["ik_fk"] = 0.0
                    fk = pb_all[fk_name]
                    fk.rotation_mode = "XYZ"
                    fk.rotation_euler = Euler((0.5, 0.0, 0.0), "XYZ")
                    update()
                    moved = (head(end) - end_rest).length / height
                    out.append(("OK", f"{label}: FK bend works") if moved > 0.005 else
                               ("ERROR", f"{label}: FK control does not move the limb."))
                    fk.rotation_euler = Euler((0, 0, 0), "XYZ")
                    if lim["has_ik"]:
                        pb_all[lim["ctrl_ik"]]["ik_fk"] = 1.0
                    update()
            if lim["kind"] == "LEG" and lim["has_ik"] and "foot_roll" in pb_all[lim["ctrl_ik"]].keys():
                ctrl = pb_all[lim["ctrl_ik"]]
                before = head(end)
                ctrl["foot_roll"] = 40.0
                update()
                moved = (head(end) - before).length / height
                out.append(("OK", f"{label}: foot roll works") if moved > 0.003 else
                           ("WARN", f"{label}: foot roll had no visible effect."))
                ctrl["foot_roll"] = 0.0
                update()

        if spine:
            mid = f"CTRL-{spine[min(1, len(spine) - 1)]}"
            top_def = "DEF-head" if "DEF-head" in pb_all else f"DEF-{spine[-1]}"
            if mid in pb_all:
                before = tail(top_def)
                pb = pb_all[mid]
                pb.rotation_mode = "XYZ"
                pb.rotation_euler = Euler((math.radians(18), 0, 0), "XYZ")
                update()
                moved = (tail(top_def) - before).length / height
                out.append(("OK", "Spine: rotating the spine control moves the head") if moved > 0.003 else
                           ("ERROR", "Spine: the spine control does not drive the upper body."))
                if meshes:
                    mm = mesh_move() / height
                    out.append(("OK", f"Spine: mesh follows ({mm * 100:.1f}% of height)") if mm > 0.004 else
                               ("WARN", "Spine: mesh did not follow the spine - check weights."))
                pb.rotation_euler = Euler((0, 0, 0), "XYZ")
                update()
        if "CTRL-head" in pb_all:
            before = tail("DEF-head")
            pb = pb_all["CTRL-head"]
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = Euler((0.4, 0, 0), "XYZ")
            update()
            moved = (tail("DEF-head") - before).length / height
            out.append(("OK", "Head: rotation works") if moved > 0.002 else ("ERROR", "Head control does not rotate the head."))
            pb.rotation_euler = Euler((0, 0, 0), "XYZ")
            update()
        if "CTRL-root" in pb_all and meshes:
            pb = pb_all["CTRL-root"]
            pb.location = (0.0, 0.0, 0.0)
            before = base_mesh.copy()
            pb.matrix = Matrix.Translation((0.1 * height, 0, 0)) @ pb.matrix
            update()
            cur = _mesh_coords(meshes, context.evaluated_depsgraph_get())
            frac = float((np.abs(cur - before).reshape(-1, 3)[:, 0] > 0.05 * height).mean())
            out.append(("OK", f"Root: moves {frac * 100:.0f}% of the mesh") if frac > 0.95 else
                       ("WARN", f"Root control moves only {frac * 100:.0f}% of the mesh - some vertices are unweighted."))
    finally:
        _restore(rig, snap)
    out.append(("INFO", "Original pose restored."))
    return out


class SAR_OT_test_rig(bpy.types.Operator):
    bl_idname = "sar.test_rig"
    bl_label = "Test Rig"
    bl_description = ("Pose IK/FK arms and legs, the spine and head automatically, measure the response and "
                      "restore your pose afterwards")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        rig = s.rig_object
        if rig is None:
            self.report({"ERROR"}, "No generated rig to test. Run Auto Rig first.")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        results = run_rig_test(context, rig, DF.bound_meshes(rig, context.scene))
        s.test_results.clear()
        for level, text in results:
            m = s.test_results.add()
            m.level, m.text = level, text
        bad = [t for lvl, t in results if lvl in {"ERROR", "WARN"}]
        self.report({"WARNING" if bad else "INFO"}, f"Rig test: {len(results) - len(bad) - 1} passed, {len(bad)} issue(s)")
        return {"FINISHED"}


class SAR_OT_validate_rig(bpy.types.Operator):
    bl_idname = "sar.validate_rig"
    bl_label = "Validate Rig"
    bl_description = "Check bones, parenting, constraints, IK targets, modifier and weights"

    def execute(self, context):
        s = context.scene.sar
        rig = s.rig_object or context.active_object
        if rig is None or rig.type != "ARMATURE":
            self.report({"ERROR"}, "No rig to validate. Run Auto Rig or select the rig.")
            return {"CANCELLED"}
        results = validation.validate_rig(rig, s, None, None)
        validation.store(s, results)
        bad = sum(1 for lvl, _t in results if lvl in {"ERROR", "WARN"})
        self.report({"WARNING" if bad else "INFO"}, f"Validation: {bad} issue(s)" if bad else "Validation passed")
        return {"FINISHED"}


CLASSES = (SAR_OT_test_rig, SAR_OT_validate_rig)
