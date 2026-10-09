"""Preview, Auto Rig (modal with progress) and removal operators."""
from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from ..rig import generator as GEN
from ..rig import ik_fk
from ..utils import logging as log
from ..utils import viewport as VP


class _ModalRunner:
    """Mixin: advance a generator from a timer so the UI can show progress and stays responsive."""
    _timer = None
    _gen = None

    def _start(self, context, mode: str):
        s = context.scene.sar
        s.progress_active = True
        s.progress_value = 0.0
        s.progress_label = "Starting"
        self._mode = mode
        self._gen = GEN.autorig_steps(context, s, mode)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _stop(self, context):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.scene.sar.progress_active = False
        VP.tag_redraw_all()

    def modal(self, context, event):
        s = context.scene.sar
        if event.type == "ESC":
            self._stop(context)
            self._gen = None
            if self._mode == "FULL":
                GEN.remove_generated(context, s, restore_sources=True)
            else:
                GEN.remove_preview(context, s)
            self.report({"WARNING"}, "Cancelled; partial results were removed.")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        try:
            stage, frac, label = next(self._gen)
            GEN._set_progress(s, stage, frac, label)
            VP.tag_redraw_all()
        except StopIteration:
            self._stop(context)
            s.progress_value = 1.0
            self._report_done(context)
            return {"FINISHED"}
        except GEN.GenerationError as exc:
            self._stop(context)
            self._cleanup_failed(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:                       # unexpected: never leave a half-built rig behind
            self._stop(context)
            self._cleanup_failed(context)
            log.error(f"{type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"Rig generation failed ({type(exc).__name__}: {exc}). Partial results removed; "
                                   f"enable Debug mode and check the console.")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _cleanup_failed(self, context):
        s = context.scene.sar
        if self._mode == "FULL":
            GEN.remove_generated(context, s, restore_sources=True)
        else:
            GEN.remove_preview(context, s)

    def cancel(self, context):
        self._stop(context)


class SAR_OT_preview_rig(_ModalRunner, bpy.types.Operator):
    bl_idname = "sar.preview_rig"
    bl_label = "Preview Rig"
    bl_description = ("Create a preview armature (skeleton, control positions, hierarchy) without touching the "
                      "source character")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return self._start(context, "PREVIEW")

    def _report_done(self, context):
        s = context.scene.sar
        warns = [m.text for m in s.messages if m.level == "WARN"]
        self.report({"INFO"}, "Preview ready: inspect the skeleton, then Accept, Edit Guides or Cancel." +
                    (f" ({len(warns)} warning(s))" if warns else ""))


class SAR_OT_accept_preview(bpy.types.Operator):
    bl_idname = "sar.accept_preview"
    bl_label = "Accept"
    bl_description = "Accept the previewed skeleton so Auto Rig can build the final rig from it"

    def execute(self, context):
        s = context.scene.sar
        if s.preview_rig is None:
            self.report({"ERROR"}, "There is no preview to accept. Click 'Preview Rig' first.")
            return {"CANCELLED"}
        s.preview_state = "ACCEPTED"
        self.report({"INFO"}, "Preview accepted. Click 'Auto Rig' to generate controls, IK/FK and weights.")
        return {"FINISHED"}


class SAR_OT_cancel_preview(bpy.types.Operator):
    bl_idname = "sar.cancel_preview"
    bl_label = "Cancel"
    bl_description = "Remove the preview armature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        GEN.remove_preview(context, context.scene.sar)
        return {"FINISHED"}


class SAR_OT_edit_guides_from_preview(bpy.types.Operator):
    bl_idname = "sar.edit_guides"
    bl_label = "Edit Guides"
    bl_description = "Remove the preview and go back to editing the guides"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        GEN.remove_preview(context, context.scene.sar)
        return bpy.ops.sar.guide_editor("INVOKE_DEFAULT", guided=False)


class SAR_OT_auto_rig(_ModalRunner, bpy.types.Operator):
    bl_idname = "sar.auto_rig"
    bl_label = "Auto Rig"
    bl_description = ("Generate the armature, controls, IK/FK, constraints and weights from the guides. "
                      "Press Esc to cancel while it runs")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return self._start(context, "FULL")

    def _report_done(self, context):
        s = context.scene.sar
        errs = [m.text for m in s.validation if m.level == "ERROR"]
        warns = [m.text for m in s.validation if m.level == "WARN"]
        if errs:
            self.report({"WARNING"}, f"Rig built with {len(errs)} problem(s): {errs[0]}")
        else:
            self.report({"INFO"}, "Rig generated" + (f" ({len(warns)} warning(s) - see Validation)" if warns else "") +
                        ". Try 'Test Rig', then pose the controls in Pose Mode.")


class SAR_OT_remove_rig(bpy.types.Operator):
    bl_idname = "sar.remove_rig"
    bl_label = "Remove Rig"
    bl_description = "Delete the generated rig and bound duplicates and show the original character again"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        n = GEN.remove_generated(context, s, restore_sources=True)
        self.report({"INFO"}, f"Removed {n} generated object(s)" if n else "Nothing to remove")
        return {"FINISHED"}


class SAR_OT_set_ik_fk(bpy.types.Operator):
    bl_idname = "sar.set_ik_fk"
    bl_label = "Set IK/FK"
    bl_description = "Switch all arms/legs between IK and FK"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items=[("IK", "IK", ""), ("FK", "FK", "")], default="IK")
    part: EnumProperty(items=[("ALL", "All", ""), ("ARM", "Arms", ""), ("LEG", "Legs", "")], default="ALL")

    def execute(self, context):
        rig = context.scene.sar.rig_object
        if rig is None:
            self.report({"ERROR"}, "No generated rig. Run Auto Rig first.")
            return {"CANCELLED"}
        kinds = ("ARM", "LEG") if self.part == "ALL" else (self.part,)
        n = ik_fk.set_ik_fk(rig, 1.0 if self.mode == "IK" else 0.0, kinds)
        self.report({"INFO"}, f"{n} limb(s) set to {self.mode}")
        return {"FINISHED"}


CLASSES = (SAR_OT_preview_rig, SAR_OT_accept_preview, SAR_OT_cancel_preview, SAR_OT_edit_guides_from_preview,
           SAR_OT_auto_rig, SAR_OT_remove_rig, SAR_OT_set_ik_fk)
