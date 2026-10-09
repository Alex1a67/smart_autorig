"""Armature creation and edit-mode bone construction from a Blueprint."""
from __future__ import annotations

from typing import Dict, Optional

import bpy
from mathutils import Vector

from .. import constants as C
from ..utils import logging as log
from .blueprint import Blueprint


def set_mode(obj, mode: str) -> None:
    """Make `obj` active and switch to `mode`, leaving any other object's mode first."""
    ctx = bpy.context
    active = ctx.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError:
            pass
    try:
        obj.hide_set(False)
    except RuntimeError:
        pass
    obj.hide_viewport = False
    for o in ctx.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    ctx.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.mode != mode:
        bpy.ops.object.mode_set(mode=mode)


def create_armature_object(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    collection.objects.link(rig)
    rig.show_in_front = True
    arm.display_type = "OCTAHEDRAL"
    return rig


def _make_collections(arm, bp: Blueprint) -> Dict[str, object]:
    out = {}
    for name, visible in bp.collections:
        coll = arm.collections.get(name) if hasattr(arm.collections, "get") else None
        if coll is None:
            coll = arm.collections.new(name)
        coll.is_visible = visible
        out[name] = coll
    return out


def apply_bone_defs(rig: bpy.types.Object, bp: Blueprint, height: float) -> int:
    """Create every bone of the blueprint in edit mode. Returns the number of bones created."""
    arm = rig.data
    set_mode(rig, "EDIT")
    ebones = arm.edit_bones
    colls = _make_collections(arm, bp)
    eps = max(height * 1e-4, 1e-6)

    for name in bp.order:
        bd = bp.bones[name]
        eb = ebones.new(name)
        eb.head = bd.head
        tail = bd.tail.copy()
        if (tail - bd.head).length < eps:
            tail = bd.head + Vector((0.0, 0.0, max(height * 0.01, 1e-3)))
            log.warn(f"Bone '{name}' had zero length; extended slightly.")
        eb.tail = tail
        eb.use_deform = bd.deform
        if bd.radius > 0.0:
            eb.head_radius = bd.radius * 0.8
            eb.tail_radius = bd.radius * 0.8
            eb.envelope_distance = bd.radius * 0.6

    for name in bp.order:
        bd = bp.bones[name]
        eb = ebones[name]
        if bd.z_hint is not None:
            d = (eb.tail - eb.head).normalized()
            hint = bd.z_hint.copy()
            hint = hint - d * hint.dot(d)
            if hint.length < 1e-4:
                # hint parallel to the bone: pick a perpendicular alternative
                hint = d.cross(Vector((0, 0, 1)))
                if hint.length < 1e-4:
                    hint = d.cross(Vector((0, 1, 0)))
            eb.align_roll(hint)
        if bd.collection and bd.collection in colls:
            colls[bd.collection].assign(eb)

    for name in bp.order:
        bd = bp.bones[name]
        if bd.parent:
            parent = ebones.get(bd.parent)
            if parent is None:
                raise KeyError(f"Parent '{bd.parent}' of bone '{name}' does not exist")
            eb = ebones[name]
            eb.parent = parent
            if bd.connect:
                eb.use_connect = True
    count = len(ebones)
    bpy.ops.object.mode_set(mode="OBJECT")
    return count
