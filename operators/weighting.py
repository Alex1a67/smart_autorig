"""Weight operators: auto weight, smooth, clean, rebind."""
from __future__ import annotations

import bpy

from ..rig import deformation as DF
from ..rig import generator as GEN
from ..utils import validation


def target_meshes(context, settings):
    rig = settings.rig_object
    if rig is None or rig.name not in bpy.data.objects:
        return None, []
    bound = DF.bound_meshes(rig, context.scene)
    sel = [o for o in context.selected_objects if o in bound]
    if sel:
        return rig, sel
    if bound:
        return rig, bound
    # nothing bound yet: use the duplicates created by Auto Rig, else the selected meshes
    dups = [o for o in context.scene.objects if o.type == "MESH" and o.get("sar_source")]
    if dups:
        return rig, dups
    return rig, [o for o in context.selected_objects if o.type == "MESH"]


class _WeightBase:
    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def _targets(self, context):
        s = context.scene.sar
        rig, meshes = target_meshes(context, s)
        if rig is None:
            self.report({"ERROR"}, "There is no generated rig. Run Auto Rig first.")
            return None, None, s
        if not meshes:
            self.report({"ERROR"}, "No meshes to weight. Select the character mesh(es) or run Auto Rig with 'Generate weights'.")
            return None, None, s
        return rig, meshes, s


class SAR_OT_auto_weight(_WeightBase, bpy.types.Operator):
    bl_idname = "sar.auto_weight"
    bl_label = "Auto Weight"
    bl_description = "Bind the meshes to the rig and generate weights with the selected method"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig, meshes, s = self._targets(context)
        if rig is None:
            return {"CANCELLED"}
        lines = []
        for obj in meshes:
            lines.append(f"{obj.name}: {DF.bind_object(context, obj, rig, s)}")
            if s.weight_smooth_iterations and s.weight_method != "RIGID":
                DF.smooth_weights(obj, rig, s.weight_smooth_iterations, s.weight_smooth_factor)
            if s.weight_method != "RIGID":
                DF.clean_weights(obj, rig, s.weight_clean_threshold, s.weight_max_influences)
        validation.store(s, validation.validate_rig(rig, s, None, meshes))
        self.report({"INFO"}, "; ".join(lines[:3]) + (" ..." if len(lines) > 3 else ""))
        return {"FINISHED"}


class SAR_OT_smooth_weights(_WeightBase, bpy.types.Operator):
    bl_idname = "sar.smooth_weights"
    bl_label = "Smooth Weights"
    bl_description = "Smooth vertex weights over the mesh edges and renormalise"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig, meshes, s = self._targets(context)
        if rig is None:
            return {"CANCELLED"}
        total = 0
        for obj in meshes:
            total += DF.smooth_weights(obj, rig, max(1, s.weight_smooth_iterations), s.weight_smooth_factor)
        self.report({"INFO"}, f"Smoothed {total} vertices on {len(meshes)} object(s)")
        return {"FINISHED"}


class SAR_OT_clean_weights(_WeightBase, bpy.types.Operator):
    bl_idname = "sar.clean_weights"
    bl_label = "Clean Weights"
    bl_description = "Remove tiny weights, limit influences per vertex and normalise"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig, meshes, s = self._targets(context)
        if rig is None:
            return {"CANCELLED"}
        changed = 0
        for obj in meshes:
            _n, c = DF.clean_weights(obj, rig, s.weight_clean_threshold, s.weight_max_influences)
            changed += c
        self.report({"INFO"}, f"Cleaned weights: {changed} vertices changed")
        return {"FINISHED"}


class SAR_OT_rebind(_WeightBase, bpy.types.Operator):
    bl_idname = "sar.rebind"
    bl_label = "Rebind"
    bl_description = "Remove the existing deform weights and bind again from scratch"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        rig, meshes, s = self._targets(context)
        if rig is None:
            return {"CANCELLED"}
        for obj in meshes:
            DF.unbind_object(obj, rig)
        return bpy.ops.sar.auto_weight()


CLASSES = (SAR_OT_auto_weight, SAR_OT_smooth_weights, SAR_OT_clean_weights, SAR_OT_rebind)
