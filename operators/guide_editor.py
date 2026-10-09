"""Interactive guide placement in the 3D viewport (modal operator)."""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from mathutils import Vector

from .. import constants as C
from .. import guides_model as GM
from ..ui import draw
from ..utils import geometry as G
from ..utils import naming
from ..utils import viewport as VP
from . import guides as GO

NAV_EVENTS = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE",
              "NDOF_MOTION", "INBETWEEN_MOUSEMOVE"}
PICK_RADIUS = 16.0


def _inside_window_region(area, region, event) -> bool:
    mx, my = event.mouse_x, event.mouse_y
    if not (region.x <= mx < region.x + region.width and region.y <= my < region.y + region.height):
        return False
    for r in area.regions:
        if r.type in {"UI", "TOOLS", "HEADER", "TOOL_HEADER", "ASSET_SHELF", "HUD"} and r.width > 1 and r.height > 1:
            if r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height:
                return False
    return True


class SAR_OT_guide_editor(bpy.types.Operator):
    bl_idname = "sar.guide_editor"
    bl_label = "Edit Guides"
    bl_description = ("Place and drag guides directly on the character in the 3D viewport. "
                      "Click = place / grab, drag = move, X = clear, M = mirror, D = duplicate, S = skip, Enter/Esc = finish")
    bl_options = {"REGISTER", "UNDO"}

    guided: BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    # ------------------------------------------------------------------ helpers
    def _objects(self, settings):
        return [r.obj for r in settings.objects if r.obj is not None and r.obj.type == "MESH"
                and r.obj.visible_get()]

    def _hover_index(self, settings, coord):
        best, best_d = -1, PICK_RADIUS
        for i, g in enumerate(settings.guides):
            if not g.placed:
                continue
            p = VP.world_to_screen(self.region, self.rv3d, Vector(g.location))
            if p is None:
                continue
            d = (p - Vector(coord)).length
            if d < best_d:
                best, best_d = i, d
        return best

    def _world_point(self, context, settings, coord, current: Vector = None):
        origin, direction = VP.mouse_ray(self.region, self.rv3d, coord)
        objs = self._objects(settings)
        if settings.snap_to_surface and objs:
            depsgraph = context.evaluated_depsgraph_get()
            if settings.snap_to_volume_centre:
                r = G.volume_centre_along_ray(objs, origin, direction, depsgraph)
                if r is not None:
                    return r[0]
            else:
                hit, loc, nor, _o = G.raycast_objects(objs, origin, direction, depsgraph)
                if hit:
                    return loc
        depth = current if current is not None else self._depth_anchor(settings)
        return VP.mouse_on_view_plane(self.region, self.rv3d, coord, depth)

    def _depth_anchor(self, settings) -> Vector:
        placed = [Vector(g.location) for g in settings.guides if g.placed]
        if placed:
            return sum(placed, Vector()) / len(placed)
        objs = self._objects(settings)
        if objs:
            lo, hi = G.object_bounds(objs)
            return (lo + hi) * 0.5
        return Vector((0, 0, 0))

    def _advance(self, settings):
        if not self.guided:
            return
        key = GM.guided_next_key(settings)
        if key is None:
            settings.guided_finished = True
            draw.STATE["hint"] = "All guided guides placed - press Enter to finish (fingers, tail, wings: use the panel)"
            return
        settings.active_guide = GM.guide_index(settings, key)
        text = dict(C.GUIDED_STEPS).get(key, "")
        draw.STATE["hint"] = f"Step {settings.guided_step + 1}/{len(C.GUIDED_STEPS)}: {text}"

    def _status(self, context):
        context.workspace.status_text_set(
            "Smart Auto Rig:  LMB place / drag guide   X clear   M mirror   D duplicate   S skip step   "
            "Enter/Esc finish")

    def _finish(self, context):
        settings = context.scene.sar
        settings.editor_running = False
        settings.guided_active = False
        draw.STATE.update({"hover": -1, "drag": -1, "mouse": None, "hint": "", "warn": ""})
        context.workspace.status_text_set(None)
        VP.tag_redraw_all()

    # ------------------------------------------------------------------ operator API
    def invoke(self, context, event):
        settings = context.scene.sar
        if settings.editor_running:
            self.report({"WARNING"}, "The guide editor is already running (press Esc to leave it).")
            return {"CANCELLED"}
        area, region, rv3d = VP.find_view3d(context)
        if region is None:
            self.report({"ERROR"}, "Open a 3D Viewport to place guides.")
            return {"CANCELLED"}
        self.area, self.region, self.rv3d = area, region, rv3d
        GM.ensure_core_guides(settings)
        if not settings.objects:
            self.report({"WARNING"}, "No character selected - guides will be placed on a plane facing the view. "
                                     "Select your character and click 'Use Selected Objects' for surface snapping.")
        self.dragging = -1
        settings.editor_running = True
        settings.guided_active = self.guided
        settings.show_guides = True
        draw.STATE.update({"hover": -1, "drag": -1, "mouse": None, "hint": "", "warn": ""})
        if self.guided:
            settings.guided_finished = False
            self._advance(settings)
        else:
            draw.STATE["hint"] = "Click a guide in the panel list to select it, then click on the character."
        self._status(context)
        context.window_manager.modal_handler_add(self)
        VP.tag_redraw_all()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        settings = context.scene.sar
        if not settings.editor_running:
            self._finish(context)
            return {"FINISHED"}
        if context.area is None:
            self._finish(context)
            return {"CANCELLED"}
        if event.type in NAV_EVENTS or event.type.startswith("NUMPAD") or event.type in {"TIMER", "TIMER_REPORT"}:
            return {"PASS_THROUGH"}

        inside = _inside_window_region(self.area, self.region, event)
        coord = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)

        if event.type == "MOUSEMOVE":
            draw.STATE["mouse"] = coord if inside else None
            if self.dragging >= 0:
                g = settings.guides[self.dragging]
                g.location = self._world_point(context, settings, coord, Vector(g.location))
                g.suggested = False
                settings.analysis_done = False
            else:
                draw.STATE["hover"] = self._hover_index(settings, coord) if inside else -1
            VP.tag_redraw_all()
            return {"RUNNING_MODAL"} if inside or self.dragging >= 0 else {"PASS_THROUGH"}

        if event.type == "LEFTMOUSE":
            if event.value == "PRESS" and inside:
                hover = self._hover_index(settings, coord)
                if hover >= 0:
                    settings.active_guide = hover
                    self.dragging = hover
                    draw.STATE["drag"] = hover
                elif 0 <= settings.active_guide < len(settings.guides):
                    g = settings.guides[settings.active_guide]
                    if not g.placed:
                        g.location = self._world_point(context, settings, coord)
                        g.placed = True
                        g.suggested = False
                        settings.analysis_done = False
                        self.dragging = settings.active_guide      # allow fine-tuning with the button held
                        draw.STATE["drag"] = self.dragging
                VP.tag_redraw_all()
                return {"RUNNING_MODAL"}
            if event.value == "RELEASE" and self.dragging >= 0:
                self.dragging = -1
                draw.STATE["drag"] = -1
                self._warn_if_off_mesh(context, settings)
                self._advance(settings)
                VP.tag_redraw_all()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        if event.value != "PRESS":
            return {"PASS_THROUGH"}

        if event.type in {"RET", "NUMPAD_ENTER", "TAB"}:
            self._finish(context)
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            if self.dragging >= 0:
                self.dragging = -1
                draw.STATE["drag"] = -1
                return {"RUNNING_MODAL"}
            self._finish(context)
            return {"FINISHED"}

        target = draw.STATE["hover"] if draw.STATE["hover"] >= 0 else settings.active_guide
        if not (0 <= target < len(settings.guides)) or not inside:
            return {"PASS_THROUGH"}
        g = settings.guides[target]
        if event.type in {"X", "DEL"}:
            g.placed = False
            g.suggested = False
            settings.active_guide = target
            settings.analysis_done = False
            if self.guided:
                self._advance(settings)
            VP.tag_redraw_all()
            return {"RUNNING_MODAL"}
        if event.type == "M":
            centre, axis = GO.mirror_params(settings)
            if GM.mirror_guide(settings, g.key, centre, axis):
                draw.STATE["warn"] = ""
            else:
                ch = GM.get_chain(settings, g.chain)
                if ch is not None and ch.side in {"L", "R"}:
                    GM.duplicate_chain_mirrored(settings, ch.cid, centre, axis)
                else:
                    draw.STATE["warn"] = "This guide has no left/right counterpart to mirror to."
            settings.analysis_done = False
            VP.tag_redraw_all()
            return {"RUNNING_MODAL"}
        if event.type == "D":
            self._duplicate(settings, g)
            VP.tag_redraw_all()
            return {"RUNNING_MODAL"}
        if event.type == "S" and self.guided:
            gk = settings.guides[settings.active_guide]
            # skipping marks the step as done without placing: just move to the next unplaced key
            keys = [k for k, _t in C.GUIDED_STEPS]
            if gk.key in keys:
                idx = keys.index(gk.key)
                for nk in keys[idx + 1:]:
                    ng = GM.get_guide(settings, nk)
                    if ng is not None and not ng.placed:
                        settings.active_guide = GM.guide_index(settings, nk)
                        draw.STATE["hint"] = f"Step: {dict(C.GUIDED_STEPS)[nk]}"
                        break
            VP.tag_redraw_all()
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def cancel(self, context):
        self._finish(context)

    # ------------------------------------------------------------------ actions
    def _warn_if_off_mesh(self, context, settings):
        draw.STATE["warn"] = ""
        objs = self._objects(settings)
        if not objs or not (0 <= settings.active_guide < len(settings.guides)):
            return
        g = settings.guides[settings.active_guide]
        lo, hi = G.object_bounds(objs)
        height = max(hi.z - lo.z, 1e-6)
        d = G.nearest_surface_distance(objs, Vector(g.location), context.evaluated_depsgraph_get(), height * 0.5)
        inside_box = all(lo[i] - height * 0.02 <= g.location[i] <= hi[i] + height * 0.02 for i in range(3))
        if d > height * 0.12 and not inside_box:
            draw.STATE["warn"] = f"'{g.label}' is far from the character. Drag it onto the mesh."

    def _duplicate(self, settings, g):
        ch = GM.get_chain(settings, g.chain)
        if ch is None or ch.kind in {"SPINE"}:
            draw.STATE["warn"] = "The spine cannot be duplicated."
            return
        objs = self._objects(settings)
        lo, hi = G.object_bounds(objs) if objs else (Vector(), Vector((0, 0, 1)))
        centre, axis = GO.mirror_params(settings)
        if ch.side in {"L", "R"} and not GM.get_chain(settings, naming.mirror_cid(ch.cid)):
            GM.duplicate_chain_mirrored(settings, ch.cid, centre, axis)
            return
        offset = Vector((0.0, 0.0, -(hi.z - lo.z) * 0.08)) if ch.kind in {"ARM", "LEG"} else Vector(((hi.x - lo.x) * 0.06, 0, 0))
        kind, side, name, count, parent, src_cid = ch.kind, ch.side, ch.name, ch.point_count, ch.parent_chain, ch.cid
        new = GM.add_chain(settings, kind, side, name.rstrip("0123456789"), count, parent)
        new_cid = new.cid                      # `ch` / `new` may be invalidated by later additions
        for src, dst in zip(GM.chain_guides(settings, src_cid), GM.chain_guides(settings, new_cid)):
            if src.placed:
                dst.location = Vector(src.location) + offset
                dst.placed = True
        settings.active_guide = GM.guide_index(settings, GM.chain_guides(settings, new_cid)[0].key)


CLASSES = (SAR_OT_guide_editor,)
