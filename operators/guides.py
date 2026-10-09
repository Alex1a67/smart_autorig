"""Guide management operators (character selection, chains, mirroring, suggestions)."""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from mathutils import Vector

from .. import constants as C
from .. import guides_model as GM
from ..analysis import anatomy
from ..analysis import mesh_analysis as MA
from ..utils import geometry as G
from ..utils import naming
from ..utils import validation


def _character_bounds(settings):
    objs = [r.obj for r in settings.objects if r.obj is not None]
    if not objs:
        return None
    lo, hi = G.object_bounds(objs)
    return lo, hi


def mirror_params(settings):
    b = _character_bounds(settings)
    return GM.mirror_centre(settings, b), settings.mirror_axis


class SAR_OT_use_selected(bpy.types.Operator):
    bl_idname = "sar.use_selected"
    bl_label = "Use Selected Objects"
    bl_description = "Use the selected mesh objects as the character"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        meshes = [o for o in context.selected_objects if o.type == "MESH"]
        other = [o for o in context.selected_objects if o.type != "MESH"]
        if not meshes:
            self.report({"ERROR"}, "No mesh character selected. Select one or more mesh objects first.")
            return {"CANCELLED"}
        s.objects.clear()
        for o in meshes:
            s.objects.add().obj = o
        if context.active_object and context.active_object.type == "MESH" and s.character_name in {"", "Character"}:
            s.character_name = context.active_object.name.split(".")[0]
        GM.ensure_core_guides(s)
        s.analysis_done = False
        msg = f"{len(meshes)} mesh object(s) selected as the character"
        if other:
            msg += f" ({len(other)} non-mesh object(s) ignored)"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class SAR_OT_auto_detect_objects(bpy.types.Operator):
    bl_idname = "sar.auto_detect_objects"
    bl_label = "Auto-Detect Character Objects"
    bl_description = ("Starting from the selected objects, include children and touching/overlapping mesh objects "
                      "(unrelated scene meshes far away are left out)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        seeds = [o for o in context.selected_objects if o.type == "MESH"]
        if context.active_object and context.active_object.type == "MESH" and context.active_object not in seeds:
            seeds.append(context.active_object)
        if not seeds:
            self.report({"ERROR"}, "Select at least one part of the character first (e.g. the body).")
            return {"CANCELLED"}
        candidates = [o for o in context.view_layer.objects
                      if o.type == "MESH" and o.visible_get() and not o.get("sar_source")
                      and not o.name.startswith("WGT-")]
        bounds = {o: G.object_bounds([o]) for o in candidates}
        diag = max((G.object_bounds(seeds)[1] - G.object_bounds(seeds)[0]).length, 0.01)
        gap = diag * 0.05
        group = set(seeds)
        for o in list(group):
            for child in o.children_recursive:
                if child.type == "MESH":
                    group.add(child)
        changed = True
        while changed:
            changed = False
            for o in candidates:
                if o in group:
                    continue
                lo, hi = bounds[o]
                for g in list(group):
                    glo, ghi = G.object_bounds([g])
                    if all(lo[i] - gap <= ghi[i] and hi[i] + gap >= glo[i] for i in range(3)):
                        group.add(o)
                        changed = True
                        break
        s.objects.clear()
        for o in sorted(group, key=lambda x: x.name):
            s.objects.add().obj = o
        GM.ensure_core_guides(s)
        s.analysis_done = False
        self.report({"INFO"}, f"Detected {len(group)} character object(s)")
        return {"FINISHED"}


class SAR_OT_add_chain(bpy.types.Operator):
    bl_idname = "sar.add_chain"
    bl_label = "Add Limb / Chain"
    bl_description = "Add an extra limb or bone chain with its own guides"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=[(k, n, d) for k, n, d in C.CHAIN_KINDS if k not in {"SPINE", "FINGER"}], default="ARM")
    side: EnumProperty(items=[("C", "Centre", ""), ("L", "Left", ""), ("R", "Right", "")], default="L")
    name: StringProperty(default="")
    points: IntProperty(default=4, min=2, max=64)
    mirror: BoolProperty(default=False, name="Also add right side")

    def invoke(self, context, event):
        s = context.scene.sar
        self.name = s.new_chain_name if self.kind in C.GENERIC_KINDS else ""
        self.points = s.new_chain_points
        return self.execute(context)

    def execute(self, context):
        s = context.scene.sar
        side = self.side
        if self.kind in {"ARM", "LEG"} and side == "C":
            side = "L"
        name = self.name or self.kind.lower()
        ch = GM.add_chain(s, self.kind, side, name, self.points)
        cid, label = ch.cid, ch.label              # `ch` becomes invalid when another chain is added
        if self.mirror and side in {"L", "R"}:
            other = naming.opposite_side(side)
            GM.add_chain(s, self.kind, other, name if self.kind in C.GENERIC_KINDS else GM.get_chain(s, cid).name,
                         self.points)
        first = GM.chain_guides(s, cid)[0]
        s.active_guide = GM.guide_index(s, first.key)
        s.analysis_done = False
        self.report({"INFO"}, f"Added '{label}' - open the guide editor and place its guides.")
        return {"FINISHED"}


class SAR_OT_remove_chain(bpy.types.Operator):
    bl_idname = "sar.remove_chain"
    bl_label = "Remove Chain"
    bl_description = "Remove the chain of the active guide (the core spine/arms/legs cannot be removed)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        if not (0 <= s.active_guide < len(s.guides)):
            self.report({"ERROR"}, "Select a guide first.")
            return {"CANCELLED"}
        cid = s.guides[s.active_guide].chain
        if cid in {"spine", "arm.L", "arm.R", "leg.L", "leg.R"}:
            self.report({"ERROR"}, "The core humanoid chains cannot be removed; use 'Clear Guide' instead.")
            return {"CANCELLED"}
        GM.remove_chain(s, cid)
        s.analysis_done = False
        self.report({"INFO"}, f"Removed chain '{cid}'")
        return {"FINISHED"}


class SAR_OT_add_fingers(bpy.types.Operator):
    bl_idname = "sar.add_fingers"
    bl_label = "Add Fingers"
    bl_description = ("Add five finger chains to every hand with starting positions estimated from the wrist and "
                      "hand tip. Drag the finger guides to refine them")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        arm_cids = [c.cid for c in s.chains if c.kind == "ARM"]   # ids only: references die when chains are added
        count = 0
        for arm_cid in arm_cids:
            arm = GM.get_chain(s, arm_cid)
            wr = GM.get_guide(s, f"{arm.cid}.wrist")
            sh = GM.get_guide(s, f"{arm.cid}.shoulder")
            if wr is None or not wr.placed or sh is None or not sh.placed:
                continue
            tip_g = GM.get_guide(s, f"{arm.cid}.hand_tip")
            wrist = Vector(wr.location)
            elbow_g = GM.get_guide(s, f"{arm.cid}.elbow")
            back = Vector(elbow_g.location) if elbow_g and elbow_g.placed else Vector(sh.location)
            d = (wrist - back)
            if d.length < 1e-6:
                continue
            d.normalize()
            hand_len = (Vector(tip_g.location) - wrist).length if tip_g and tip_g.placed else (wrist - back).length * 0.45
            arm_side = arm.side
            made = GM.add_fingers(s, arm_side, arm_cid)
            lateral = d.cross(Vector((0, 0, 1)))
            if lateral.length < 1e-6:
                lateral = Vector((0, 1, 0))
            lateral.normalize()
            # thumb in front (character faces -Y): lateral sign chosen so the thumb is on the forward side
            if lateral.y > 0:
                lateral = -lateral
            width = hand_len * 0.5
            spread = {"thumb": -0.5, "index": -0.33, "middle": -0.08, "ring": 0.16, "pinky": 0.38}
            lens = {"thumb": 0.7, "index": 0.95, "middle": 1.0, "ring": 0.95, "pinky": 0.8}
            for fcid in made:
                ch = GM.get_chain(s, fcid)
                fname = ch.name.rstrip("0123456789")
                guides = GM.chain_guides(s, ch.cid)
                n = len(guides)
                base = wrist + d * hand_len * (0.15 if fname == "thumb" else 0.35) + lateral * width * spread[fname]
                tipp = wrist + d * hand_len * lens[fname] * 1.05 + lateral * width * spread[fname] * (1.5 if fname == "thumb" else 1.0)
                for i, g in enumerate(guides):
                    g.location = base.lerp(tipp, i / (n - 1))
                    g.placed = True
                    g.suggested = True
            count += 1
        if not count:
            self.report({"ERROR"}, "Place the shoulder and hand guides of an arm first, then add fingers.")
            return {"CANCELLED"}
        s.analysis_done = False
        self.report({"INFO"}, f"Fingers added to {count} hand(s). They are marked as suggestions - drag them onto the fingers.")
        return {"FINISHED"}


class SAR_OT_mirror_guides(bpy.types.Operator):
    bl_idname = "sar.mirror_guides"
    bl_label = "Mirror to Right"
    bl_description = "Mirror every placed left-side guide (and chain) to the right side across the mirror plane"
    bl_options = {"REGISTER", "UNDO"}

    source: EnumProperty(items=[("L", "Left to Right", ""), ("R", "Right to Left", "")], default="L")

    def execute(self, context):
        s = context.scene.sar
        centre, axis = mirror_params(s)
        n = 0
        for ch in list(s.chains):
            if ch.side == self.source:
                dst = GM.duplicate_chain_mirrored(s, ch.cid, centre, axis)
                if dst is not None:
                    n += 1
        n += GM.mirror_all_sides(s, centre, axis, self.source)
        if not n:
            self.report({"ERROR"}, f"No placed {'left' if self.source == 'L' else 'right'} guides to mirror.")
            return {"CANCELLED"}
        s.analysis_done = False
        self.report({"INFO"}, "Guides mirrored")
        return {"FINISHED"}


class SAR_OT_clear_guide(bpy.types.Operator):
    bl_idname = "sar.clear_guide"
    bl_label = "Clear Guide"
    bl_description = "Remove the position of the active guide (it can be placed again)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        if not (0 <= s.active_guide < len(s.guides)):
            return {"CANCELLED"}
        g = s.guides[s.active_guide]
        g.placed = False
        g.suggested = False
        s.analysis_done = False
        return {"FINISHED"}


class SAR_OT_select_guide(bpy.types.Operator):
    bl_idname = "sar.select_guide"
    bl_label = "Select Guide"
    bl_options = {"INTERNAL"}

    index: IntProperty()

    def execute(self, context):
        context.scene.sar.active_guide = self.index
        return {"FINISHED"}


class SAR_OT_suggest_guides(bpy.types.Operator):
    bl_idname = "sar.suggest_guides"
    bl_label = "Suggest Guides"
    bl_description = ("Estimate the main humanoid guides from the mesh proportions and extremities. "
                      "Suggestions are shown in orange - confirm or drag them")
    bl_options = {"REGISTER", "UNDO"}

    overwrite: BoolProperty(default=False, name="Overwrite placed guides")

    def execute(self, context):
        s = context.scene.sar
        objs = [r.obj for r in s.objects if r.obj is not None]
        if not objs:
            self.report({"ERROR"}, "No mesh character selected. Click 'Use Selected Objects' first.")
            return {"CANCELLED"}
        cd = MA.gather_character(objs, s.analysis_quality)
        if not cd.objects:
            self.report({"ERROR"}, "The selected objects contain no usable mesh.")
            return {"CANCELLED"}
        GM.ensure_core_guides(s)
        sug = anatomy.suggest_humanoid_guides(cd)
        if not sug:
            self.report({"ERROR"}, "Not enough geometry to estimate guides. Place them manually.")
            return {"CANCELLED"}
        n = 0
        for key, p in sug.items():
            g = GM.get_guide(s, key)
            if g is not None and (self.overwrite or not g.placed):
                GM.set_guide(s, key, p, suggested=True)
                n += 1
        s.analysis_done = False
        self.report({"INFO"}, f"{n} guide(s) suggested (orange). Verify them in the viewport - this is a heuristic, not exact.")
        return {"FINISHED"}


CLASSES = (SAR_OT_use_selected, SAR_OT_auto_detect_objects, SAR_OT_add_chain, SAR_OT_remove_chain,
           SAR_OT_add_fingers, SAR_OT_mirror_guides, SAR_OT_clear_guide, SAR_OT_select_guide,
           SAR_OT_suggest_guides)
