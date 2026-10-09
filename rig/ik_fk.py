"""IK/FK helpers: pole angle solving and runtime switching."""
from __future__ import annotations

import math
from typing import List

import bpy
from mathutils import Matrix, Vector

from ..utils import logging as log
from .blueprint import Blueprint, LimbInfo
from .skeleton import set_mode


def solve_pole_angles(rig, bp: Blueprint) -> List[str]:
    """Pick, for every IK limb, the pole angle that makes the limb bend towards its pole control.

    The IK target is pulled towards the root of the limb; the candidate pole angle whose bent
    middle joint ends up closest to the pole direction wins. Returns human readable results.
    """
    results: List[str] = []
    view_layer = bpy.context.view_layer
    set_mode(rig, "POSE")
    pbones = rig.pose.bones
    for li in bp.limbs:
        if not li.has_ik or not li.ik_bone_last:
            continue
        pb_ctrl = pbones[li.ctrl_ik]
        pb_last = pbones[li.ik_bone_last]
        con = pb_last.constraints.get(li.ik_constraint)
        if con is None:
            continue
        view_layer.update()
        rest = pb_ctrl.matrix.copy()
        axis = li.end - li.shoulder
        hinge = axis.cross(li.pole_dir)
        hinge = hinge.normalized() if hinge.length > 1e-9 else Vector((0, 0, 1))
        # pull the target towards the limb root AND sideways, so the limb must bend (a pure axial
        # pull on a straight limb is a singular configuration where the pole angle is undetectable)
        shift = -axis * 0.3 + hinge * axis.length * 0.2
        target_pos = li.end + shift
        mid_ref = (li.shoulder + target_pos) * 0.5
        best_angle, best_score = 0.0, -1e9
        for deg in (0.0, 90.0, 180.0, -90.0):
            con.pole_angle = math.radians(deg)
            m = rest.copy()
            m.translation = rest.translation + shift
            pb_ctrl.matrix = m
            rig.update_tag()
            view_layer.update()
            joint = pb_last.head.copy()
            score = (joint - mid_ref).dot(li.pole_dir)
            if score > best_score:
                best_angle, best_score = deg, score
        con.pole_angle = math.radians(best_angle)
        pb_ctrl.matrix_basis = Matrix.Identity(4)
        view_layer.update()
        log.debug(f"pole angle {li.chain}: {best_angle} deg (score {best_score:.4f})")
        results.append(f"{li.chain}: pole angle {best_angle:.0f}\u00b0")
    bpy.ops.object.mode_set(mode="OBJECT")
    return results


def set_ik_fk(rig, value: float, kinds=("ARM", "LEG")) -> int:
    """Set the IK/FK blend of every limb on the rig. Returns the number of limbs changed."""
    n = 0
    for pb in rig.pose.bones:
        if "ik_fk" in pb.keys():
            name = pb.name
            is_leg = "foot" in name
            if ("LEG" in kinds and is_leg) or ("ARM" in kinds and not is_leg):
                pb["ik_fk"] = float(value)
                n += 1
    rig.update_tag()
    return n


def limb_switch_bones(rig) -> list:
    return [pb for pb in rig.pose.bones if "ik_fk" in pb.keys()]
