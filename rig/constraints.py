"""Pose-mode setup: custom shapes, colours, custom properties, constraints and drivers."""
from __future__ import annotations

import bpy

from .. import constants as C
from ..utils import logging as log
from . import controls
from .blueprint import Blueprint
from .skeleton import set_mode


def _driver_variable(driver, name: str, rig, bone: str, prop: str):
    var = driver.variables.new()
    var.name = name
    var.type = "SINGLE_PROP"
    tgt = var.targets[0]
    tgt.id_type = "OBJECT"
    tgt.id = rig
    tgt.data_path = f'pose.bones["{bone}"]["{prop}"]'


def _clean_fcurve(fc) -> None:
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)


def apply_pose_setup(rig, bp: Blueprint, shape_collection, with_logic: bool = True) -> dict:
    """Shapes, colours, custom props and (optionally) constraints/drivers. Returns statistics."""
    stats = {"constraints": 0, "drivers": 0, "shapes": 0, "errors": []}
    set_mode(rig, "POSE")
    pbones = rig.pose.bones

    for name in bp.order:
        bd = bp.bones[name]
        pb = pbones.get(name)
        if pb is None:
            stats["errors"].append(f"Pose bone '{name}' missing")
            continue
        pb.rotation_mode = bd.rotation_mode if bd.rotation_mode != "QUATERNION" else "QUATERNION"
        if bd.rest_rotation is not None:
            pb.rotation_euler = bd.rest_rotation
        if bd.shape:
            shape = controls.get_shape(bd.shape, shape_collection)
            pb.custom_shape = shape
            pb.use_custom_shape_bone_size = bd.shape_bone_size
            pb.custom_shape_scale_xyz = bd.shape_scale
            pb.custom_shape_translation = bd.shape_offset
            stats["shapes"] += 1
        if bd.color:
            try:
                pb.color.palette = bd.color
            except (TypeError, AttributeError):
                pass
        for key, value in bd.props.items():
            pb[key] = value
            ui = bd.prop_ui.get(key)
            if ui:
                try:
                    pb.id_properties_ui(key).update(**ui)
                except Exception as exc:  # pragma: no cover - UI metadata only
                    log.debug(f"id_properties_ui failed for {name}[{key}]: {exc}")

    if with_logic:
        for cd in bp.constraints:
            pb = pbones.get(cd.bone)
            if pb is None:
                stats["errors"].append(f"Constraint owner '{cd.bone}' missing")
                continue
            con = pb.constraints.new(cd.ctype)
            con.name = cd.name
            for k, v in cd.props.items():
                setattr(con, k, v)
            if cd.target:
                if cd.target not in pbones:
                    stats["errors"].append(f"Constraint target '{cd.target}' missing for '{cd.bone}'")
                    pb.constraints.remove(con)
                    continue
                con.target = rig
                con.subtarget = cd.target
            if cd.pole_target:
                con.pole_target = rig
                con.pole_subtarget = cd.pole_target
            if cd.influence_driver:
                bone, prop = cd.influence_driver
                fc = con.driver_add("influence")
                _clean_fcurve(fc)
                drv = fc.driver
                drv.type = "AVERAGE"
                _driver_variable(drv, "blend", rig, bone, prop)
                stats["drivers"] += 1
            stats["constraints"] += 1

        for dd in bp.drivers:
            path = f'pose.bones["{dd.bone}"].{dd.path}'
            fc = rig.driver_add(path, dd.index)
            _clean_fcurve(fc)
            drv = fc.driver
            drv.type = "SCRIPTED"
            for vname, bone, prop in dd.variables:
                _driver_variable(drv, vname, rig, bone, prop)
            drv.expression = dd.expression
            stats["drivers"] += 1

    bpy.ops.object.mode_set(mode="OBJECT")
    return stats
