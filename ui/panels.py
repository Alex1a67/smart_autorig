"""Sidebar panels: 3D Viewport > N panel > Smart Auto Rig."""
from __future__ import annotations

import json

import bpy

from .. import constants as C
from .. import guides_model as GM
from ..rig import generator as GEN
from ..utils import compute

ICONS = {"OK": "CHECKMARK", "INFO": "INFO", "WARN": "ERROR", "ERROR": "CANCEL"}


def bar(value: float, width: int = 14) -> str:
    n = int(round(max(0.0, min(1.0, value)) * width))
    return "\u2588" * n + "\u2591" * (width - n)


def advanced(context) -> bool:
    return context.scene.sar.ui_mode == "ADVANCED"


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smart Auto Rig"


class SAR_PT_main(_Base, bpy.types.Panel):
    bl_label = "SMART AUTO RIG"
    bl_idname = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        row = layout.row(align=True)
        row.prop(s, "ui_mode", expand=True)
        layout.label(text="Import \u2192 place guides \u2192 analyze \u2192 auto rig \u2192 pose", icon="ARMATURE_DATA")
        if advanced(context):
            layout.label(text="AI enhancement: not installed (procedural analysis in use)", icon="INFO")


class SAR_PT_character(_Base, bpy.types.Panel):
    bl_label = "CHARACTER"
    bl_idname = "SAR_PT_character"
    bl_parent_id = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.prop(s, "character_name", text="Name")
        col = layout.column(align=True)
        col.operator("sar.use_selected", icon="RESTRICT_SELECT_OFF")
        col.operator("sar.auto_detect_objects", icon="VIEWZOOM")
        objs = [r.obj for r in s.objects if r.obj]
        if objs:
            box = layout.box()
            box.label(text=f"{len(objs)} object(s) selected", icon="MESH_DATA")
            if advanced(context):
                box.template_list("SAR_UL_objects", "", s, "objects", s, "guided_step", rows=3)
            else:
                names = ", ".join(o.name for o in objs[:4]) + ("..." if len(objs) > 4 else "")
                box.label(text=names)
        else:
            layout.label(text="Select your character, then click above", icon="INFO")
        if advanced(context):
            layout.prop(s, "preserve_source")
            row = layout.row(align=True)
            row.prop(s, "forward_axis")
            row.prop(s, "left_axis")


class SAR_PT_guides(_Base, bpy.types.Panel):
    bl_label = "GUIDES"
    bl_idname = "SAR_PT_guides"
    bl_parent_id = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        if s.editor_running:
            box = layout.box()
            box.alert = False
            if s.guided_active and not s.guided_finished and s.guided_step < len(C.GUIDED_STEPS):
                key, text = C.GUIDED_STEPS[s.guided_step]
                box.label(text=f"Step {s.guided_step + 1} of {len(C.GUIDED_STEPS)}", icon="TRACKING")
                for chunk in _wrap(text, 38):
                    box.label(text=chunk)
            elif s.guided_active:
                box.label(text="All guided guides placed.", icon="CHECKMARK")
                box.label(text="Add fingers / tail / wings / extra limbs below,")
                box.label(text="then press Enter in the viewport.")
            else:
                box.label(text="Guide editor running (Esc to finish)", icon="TRACKING")
            layout.label(text="LMB place/drag  X clear  M mirror  D duplicate  S skip", icon="MOUSE_LMB")
        else:
            col = layout.column(align=True)
            col.scale_y = 1.3
            op = col.operator("sar.guide_editor", text="Start Guided Setup", icon="PLAY")
            op.guided = True
            col.scale_y = 1.0
            op = col.operator("sar.guide_editor", text="Edit Guides", icon="TOOL_SETTINGS")
            op.guided = False
        layout.prop(s, "show_guides")

        status = GM.guide_status(s)
        if status:
            box = layout.box()
            col = box.column(align=True)
            for label, ok in status.items():
                row = col.row()
                row.label(text=label, icon="CHECKMARK" if ok else "RADIOBUT_OFF")
        extras = [c for c in s.chains if c.kind not in {"SPINE"} and c.cid not in {"arm.L", "arm.R", "leg.L", "leg.R"}]
        if extras:
            box = layout.box()
            box.label(text="Extra chains")
            for c in extras:
                placed = sum(1 for g in GM.chain_guides(s, c.cid) if g.placed)
                box.label(text=f"{c.label}: {placed}/{c.point_count}",
                          icon="CHECKMARK" if placed == c.point_count else "RADIOBUT_OFF")

        col = layout.column(align=True)
        col.label(text="Add")
        row = col.row(align=True)
        for kind, label in (("ARM", "+ Arm"), ("LEG", "+ Leg")):
            op = row.operator("sar.add_chain", text=label)
            op.kind, op.side = kind, "L"
        row = col.row(align=True)
        for kind, label in (("TAIL", "+ Tail"), ("WING", "+ Wing"), ("TENTACLE", "+ Tentacle")):
            op = row.operator("sar.add_chain", text=label)
            op.kind, op.side = kind, "C" if kind != "WING" else "L"
        row = col.row(align=True)
        for kind, label in (("HORN", "+ Horn"), ("EAR", "+ Ear"), ("CLAW", "+ Claw")):
            op = row.operator("sar.add_chain", text=label)
            op.kind, op.side = kind, "L"
        box = col.box()
        r = box.row(align=True)
        r.prop(s, "new_chain_name", text="")
        r.prop(s, "new_chain_points", text="")
        op = box.operator("sar.add_chain", text="+ Add Custom Chain", icon="ADD")
        op.kind, op.side = "CUSTOM", "C"
        col.operator("sar.add_fingers", text="+ Add Fingers", icon="HAND")

        col = layout.column(align=True)
        row = col.row(align=True)
        op = row.operator("sar.mirror_guides", text="Mirror to Right", icon="MOD_MIRROR")
        op.source = "L"
        op = row.operator("sar.mirror_guides", text="to Left")
        op.source = "R"
        col.operator("sar.suggest_guides", icon="LIGHT")
        if advanced(context):
            layout.template_list("SAR_UL_guides", "", s, "guides", s, "active_guide", rows=6)
            row = layout.row(align=True)
            row.operator("sar.clear_guide", icon="X")
            row.operator("sar.remove_chain", icon="TRASH")
            row = layout.row(align=True)
            row.prop(s, "snap_to_surface")
            row.prop(s, "snap_to_volume_centre")
            layout.prop(s, "guide_size")
            row = layout.row(align=True)
            row.prop(s, "mirror_axis", expand=True)
            row = layout.row()
            row.prop(s, "mirror_auto_center")
            if not s.mirror_auto_center:
                layout.prop(s, "mirror_center")


class SAR_PT_analysis(_Base, bpy.types.Panel):
    bl_label = "ANALYSIS"
    bl_idname = "SAR_PT_analysis"
    bl_parent_id = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.operator("sar.analyze", icon="VIEWZOOM")
        if not s.analysis_done:
            layout.label(text="Not analysed yet (or guides changed)", icon="INFO")
            return
        box = layout.box()
        box.label(text="CHARACTER ANALYSIS (analysis score)")
        col = box.column(align=True)
        for sc in s.scores:
            row = col.row()
            row.label(text=f"{sc.name}")
            row.label(text=f"{bar(sc.value / 100.0, 10)} {sc.value:.0f}%")
        box.separator()
        box.label(text=f"OVERALL RIG CONFIDENCE  {s.confidence:.0f}%", icon="CHECKMARK" if s.confidence >= 75 else "ERROR")
        box.label(text="Derived from geometry/guide checks - no ML model")
        if advanced(context):
            for sc in s.scores:
                box.label(text=f"{sc.name}: {sc.detail}")
        shown = 0
        for m in s.messages:
            if m.level in {"WARN", "ERROR"} and shown < 8:
                for i, chunk in enumerate(_wrap(m.text, 40)):
                    box.label(text=chunk, icon=ICONS[m.level] if i == 0 else "BLANK1")
                shown += 1


class SAR_PT_rig(_Base, bpy.types.Panel):
    bl_label = "RIG"
    bl_idname = "SAR_PT_rig"
    bl_parent_id = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        busy = s.progress_active
        col = layout.column(align=True)
        col.enabled = not busy
        if s.preview_rig is not None:
            box = col.box()
            box.label(text="Preview ready - inspect the skeleton", icon="ARMATURE_DATA")
            row = box.row(align=True)
            row.operator("sar.accept_preview", icon="CHECKMARK")
            row.operator("sar.edit_guides", icon="TOOL_SETTINGS")
            row.operator("sar.cancel_preview", icon="X")
            if s.preview_state == "ACCEPTED":
                box.label(text="Accepted - click Auto Rig", icon="CHECKMARK")
        else:
            col.operator("sar.preview_rig", icon="HIDE_OFF")
        row = col.row()
        row.scale_y = 1.4
        row.operator("sar.auto_rig", icon="ARMATURE_DATA")
        if s.rig_object is not None:
            col.operator("sar.remove_rig", icon="TRASH")

        box = layout.box()
        box.label(text="GENERATION PROGRESS")
        if busy or s.progress_value > 0:
            if len(s.stages):
                col = box.column(align=True)
                for st in s.stages:
                    col.label(text=f"{st.name:<18} {bar(st.value, 14)}")
            box.label(text=f"{s.progress_label}  ({s.progress_value * 100:.0f}%)")
        else:
            box.label(text="Idle")
        if busy:
            box.label(text="Press Esc to cancel", icon="INFO")


class SAR_PT_rig_settings(_Base, bpy.types.Panel):
    bl_label = "RIG SETTINGS"
    bl_idname = "SAR_PT_rig_settings"
    bl_parent_id = "SAR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return advanced(context)

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.prop(s, "rig_type")
        layout.prop(s, "rig_name")
        layout.prop(s, "fit_mode", text="")
        layout.prop(s, "joint_mode", text="")
        col = layout.column(align=True)
        col.prop(s, "spine_bones")
        col.prop(s, "neck_bones")
        layout.prop(s, "use_clavicles")
        box = layout.box()
        box.label(text="CONTROLS")
        row = box.row(align=True)
        row.prop(s, "generate_controls")
        row.prop(s, "generate_ik")
        row.prop(s, "generate_fk")
        box.prop(s, "foot_roll")
        box.prop(s, "default_ik", slider=True)
        box.prop(s, "control_scale")
        box = layout.box()
        box.label(text="PROCESSING")
        rep = compute.gpu_report()
        box.label(text=f"GPU: {'Available' if rep['blender_gpu'] else 'Not detected'}", icon="SHADING_RENDERED")
        box.label(text=f"Backend: {rep['backend']}")
        box.label(text=f"Numeric compute: {rep['compute']}")
        if not rep["cupy"]:
            box.label(text="GPU compute (CuPy) not installed - CPU used", icon="INFO")
        box.prop(s, "compute_mode", expand=True)
        box.prop(s, "analysis_quality", text="")


class SAR_PT_weights(_Base, bpy.types.Panel):
    bl_label = "WEIGHTING"
    bl_idname = "SAR_PT_weights"
    bl_parent_id = "SAR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.prop(s, "bind_weights")
        layout.prop(s, "weight_method", text="")
        col = layout.column(align=True)
        col.operator("sar.auto_weight", icon="MOD_VERTEX_WEIGHT")
        row = col.row(align=True)
        row.operator("sar.smooth_weights", icon="MOD_SMOOTH")
        row.operator("sar.clean_weights", icon="BRUSH_DATA")
        col.operator("sar.rebind", icon="FILE_REFRESH")
        if advanced(context):
            col = layout.column(align=True)
            col.prop(s, "weight_falloff")
            col.prop(s, "weight_max_influences")
            col.prop(s, "weight_smooth_iterations")
            col.prop(s, "weight_smooth_factor")
            col.prop(s, "weight_clean_threshold")


class SAR_PT_controls(_Base, bpy.types.Panel):
    bl_label = "CONTROLS"
    bl_idname = "SAR_PT_controls"
    bl_parent_id = "SAR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        rig = context.scene.sar.rig_object
        return rig is not None and rig.name in bpy.data.objects

    def draw(self, context):
        s = context.scene.sar
        rig = s.rig_object
        layout = self.layout
        row = layout.row(align=True)
        for mode in ("IK", "FK"):
            op = row.operator("sar.set_ik_fk", text=f"All {mode}")
            op.mode, op.part = mode, "ALL"
        for pb in rig.pose.bones:
            if "ik_fk" in pb.keys():
                box = layout.box()
                box.label(text=pb.name.replace("CTRL-ik_", ""))
                box.prop(pb, '["ik_fk"]', text="IK \u2194 FK", slider=True)
                if "foot_roll" in pb.keys():
                    box.prop(pb, '["foot_roll"]', text="Foot roll", slider=True)
        if advanced(context):
            box = layout.box()
            box.label(text="Control visibility")
            for coll in rig.data.collections_all:
                box.prop(coll, "is_visible", text=coll.name, toggle=True)


class SAR_PT_presets(_Base, bpy.types.Panel):
    bl_label = "PRESETS"
    bl_idname = "SAR_PT_presets"
    bl_parent_id = "SAR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return advanced(context)

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        row = layout.row(align=True)
        row.prop(s, "preset_name", text="")
        row.operator("sar.save_preset", text="Save", icon="FILE_TICK")
        row = layout.row(align=True)
        row.prop(s, "preset_list", text="")
        row.operator("sar.load_preset", text="Load", icon="IMPORT")
        row.operator("sar.delete_preset", text="", icon="TRASH")
        layout.operator("sar.reset_guides", icon="LOOP_BACK")


class SAR_PT_validation(_Base, bpy.types.Panel):
    bl_label = "VALIDATION"
    bl_idname = "SAR_PT_validation"
    bl_parent_id = "SAR_PT_main"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return advanced(context) or len(context.scene.sar.validation)

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.operator("sar.validate_rig", icon="CHECKMARK")
        if len(s.validation):
            box = layout.box()
            box.label(text="RIG VALIDATION")
            for m in s.validation:
                for i, chunk in enumerate(_wrap(m.text, 40)):
                    box.label(text=chunk, icon=ICONS[m.level] if i == 0 else "BLANK1")


class SAR_PT_tools(_Base, bpy.types.Panel):
    bl_label = "TEST & TOOLS"
    bl_idname = "SAR_PT_tools"
    bl_parent_id = "SAR_PT_main"

    def draw(self, context):
        s = context.scene.sar
        layout = self.layout
        layout.operator("sar.test_rig", icon="PLAY")
        if len(s.test_results):
            box = layout.box()
            box.label(text="RIG TEST")
            for m in s.test_results:
                for i, chunk in enumerate(_wrap(m.text, 40)):
                    box.label(text=chunk, icon=ICONS[m.level] if i == 0 else "BLANK1")
        layout.separator()
        row = layout.row(align=True)
        op = row.operator("sar.create_demo", text="Test Humanoid")
        op.kind = "HUMANOID"
        op = row.operator("sar.create_demo", text="Test Creature")
        op.kind = "CREATURE"
        if advanced(context):
            layout.operator("sar.self_test", icon="CHECKMARK")
            layout.prop(s, "debug_mode")
        if len(s.selftest_results):
            box = layout.box()
            box.label(text="SELF TEST")
            for m in s.selftest_results:
                for i, chunk in enumerate(_wrap(m.text, 40)):
                    box.label(text=chunk, icon=ICONS[m.level] if i == 0 else "BLANK1")


def _wrap(text: str, width: int):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width and line:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out or [""]


CLASSES = (SAR_PT_main, SAR_PT_character, SAR_PT_guides, SAR_PT_analysis, SAR_PT_rig, SAR_PT_rig_settings,
           SAR_PT_controls, SAR_PT_weights, SAR_PT_presets, SAR_PT_validation, SAR_PT_tools)
