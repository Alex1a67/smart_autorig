"""Save / load guide presets as JSON files (the user's mesh is never touched)."""
from __future__ import annotations

import json
import os
import tempfile
from typing import List

import bpy
from bpy.props import StringProperty
from mathutils import Vector

from .. import guides_model as GM
from ..utils import geometry as G

PRESET_OPTIONS = ["rig_type", "fit_mode", "joint_mode", "spine_bones", "neck_bones", "use_clavicles",
                  "generate_controls", "generate_ik", "generate_fk", "foot_roll", "default_ik", "control_scale",
                  "weight_method", "weight_falloff", "weight_max_influences", "weight_smooth_iterations",
                  "weight_smooth_factor", "weight_clean_threshold", "mirror_axis", "forward_axis", "left_axis"]


def preset_dir() -> str:
    try:
        path = bpy.utils.user_resource("CONFIG", path="smart_autorig_presets", create=True)
        if path and os.path.isdir(path):
            return path
    except Exception:
        pass
    path = os.path.join(tempfile.gettempdir(), "smart_autorig_presets")
    os.makedirs(path, exist_ok=True)
    return path


def list_presets() -> List[str]:
    try:
        return sorted(f[:-5] for f in os.listdir(preset_dir()) if f.endswith(".json"))
    except OSError:
        return []


def _bounds(settings):
    objs = [r.obj for r in settings.objects if r.obj is not None]
    if not objs:
        return None
    lo, hi = G.object_bounds(objs)
    if (hi - lo).length < 1e-9:
        return None
    return lo, hi


def serialise(settings) -> dict:
    b = _bounds(settings)
    data = {"version": 1, "normalized": b is not None, "chains": [], "guides": [], "options": {}}
    if b:
        lo, hi = b
        data["bbox"] = [list(lo), list(hi)]
        size = [max(hi[i] - lo[i], 1e-9) for i in range(3)]
    for ch in settings.chains:
        data["chains"].append({"cid": ch.cid, "kind": ch.kind, "side": ch.side, "name": ch.name,
                               "label": ch.label, "point_count": ch.point_count, "parent_chain": ch.parent_chain,
                               "use_ik": ch.use_ik})
    for g in settings.guides:
        loc = list(g.location)
        if b:
            loc = [(loc[i] - lo[i]) / size[i] for i in range(3)]
        data["guides"].append({"key": g.key, "label": g.label, "chain": g.chain, "index": g.index,
                               "location": loc, "placed": g.placed, "required": g.required})
    for name in PRESET_OPTIONS:
        data["options"][name] = getattr(settings, name)
    return data


def apply(settings, data: dict) -> int:
    settings.guides.clear()
    settings.chains.clear()
    for c in data["chains"]:
        ch = settings.chains.add()
        ch.cid, ch.kind, ch.side, ch.name = c["cid"], c["kind"], c["side"], c["name"]
        ch.label, ch.point_count, ch.parent_chain, ch.use_ik = c["label"], c["point_count"], c["parent_chain"], c["use_ik"]
    b = _bounds(settings) if data.get("normalized") else None
    n = 0
    for g in data["guides"]:
        item = settings.guides.add()
        item.key, item.label, item.chain, item.index, item.required = g["key"], g["label"], g["chain"], g["index"], g["required"]
        loc = g["location"]
        if data.get("normalized") and b:
            lo, hi = b
            loc = [lo[i] + loc[i] * (hi[i] - lo[i]) for i in range(3)]
        elif data.get("normalized") and not b and data.get("bbox"):
            lo, hi = data["bbox"]
            loc = [lo[i] + loc[i] * (hi[i] - lo[i]) for i in range(3)]
        item.location = loc
        item.placed = g["placed"]
        n += 1 if g["placed"] else 0
    for k, v in data.get("options", {}).items():
        try:
            setattr(settings, k, v)
        except (TypeError, AttributeError):
            pass
    settings.analysis_done = False
    return n


def save_preset(settings, name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "-_ ").strip() or "preset"
    path = os.path.join(preset_dir(), safe + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(serialise(settings), fh, indent=1)
    return path


def load_preset(settings, name: str) -> int:
    path = os.path.join(preset_dir(), name + ".json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return apply(settings, data)


class SAR_OT_save_preset(bpy.types.Operator):
    bl_idname = "sar.save_preset"
    bl_label = "Save Preset"
    bl_description = "Save guide positions, chains and rig options to a preset file"

    def execute(self, context):
        s = context.scene.sar
        if not len(s.guides):
            self.report({"ERROR"}, "There are no guides to save. Create guides first.")
            return {"CANCELLED"}
        path = save_preset(s, s.preset_name)
        self.report({"INFO"}, f"Preset saved: {path}")
        return {"FINISHED"}


class SAR_OT_load_preset(bpy.types.Operator):
    bl_idname = "sar.load_preset"
    bl_label = "Load Preset"
    bl_description = "Load guides and options from the selected preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        name = s.preset_list
        if not name:
            self.report({"ERROR"}, "No preset selected. Save one first.")
            return {"CANCELLED"}
        try:
            n = load_preset(s, name)
        except (OSError, ValueError, KeyError) as exc:
            self.report({"ERROR"}, f"Could not load preset '{name}': {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Loaded '{name}' ({n} guides placed)")
        return {"FINISHED"}


class SAR_OT_delete_preset(bpy.types.Operator):
    bl_idname = "sar.delete_preset"
    bl_label = "Delete Preset"
    bl_description = "Delete the selected preset file"

    def execute(self, context):
        name = context.scene.sar.preset_list
        path = os.path.join(preset_dir(), name + ".json")
        if name and os.path.exists(path):
            os.remove(path)
            self.report({"INFO"}, f"Deleted '{name}'")
            return {"FINISHED"}
        self.report({"ERROR"}, "No preset selected.")
        return {"CANCELLED"}


class SAR_OT_reset_guides(bpy.types.Operator):
    bl_idname = "sar.reset_guides"
    bl_label = "Reset"
    bl_description = "Remove all guides and extra chains and restore the default humanoid guide set"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.sar
        GM.reset_guides(s, keep_chains=False)
        s.analysis_done = False
        self.report({"INFO"}, "Guides reset")
        return {"FINISHED"}


CLASSES = (SAR_OT_save_preset, SAR_OT_load_preset, SAR_OT_delete_preset, SAR_OT_reset_guides)
