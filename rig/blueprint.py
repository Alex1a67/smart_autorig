"""Rig blueprint: declarative description of every bone, constraint and driver.

`build_blueprint(plan)` converts a RigPlan into bone definitions. `skeleton.py` and
`constraints.py` then realise the blueprint inside Blender. Rig types differ only in how
the blueprint is assembled, so new rig types can be added without touching Blender code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from mathutils import Vector

from .. import constants as C
from ..utils import geometry as G
from ..utils import naming
from .plan import LimbSpec, RigPlan
from .controls import PALETTE


@dataclass
class BoneDef:
    name: str
    head: Vector
    tail: Vector
    z_hint: Optional[Vector] = None
    parent: Optional[str] = None
    connect: bool = False
    deform: bool = False
    collection: str = ""
    shape: str = ""
    shape_scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    shape_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    shape_bone_size: bool = False
    color: str = ""
    rotation_mode: str = "QUATERNION"
    props: Dict[str, Any] = field(default_factory=dict)       # custom properties
    prop_ui: Dict[str, dict] = field(default_factory=dict)
    lock_scale: bool = False
    radius: float = 0.0                                        # envelope radius for deform bones
    rest_rotation: Optional[Tuple[float, float, float]] = None  # initial pose rotation (euler XYZ, radians)


@dataclass
class ConstraintDef:
    bone: str
    ctype: str
    name: str
    props: Dict[str, Any] = field(default_factory=dict)      # simple property assignments
    target: Optional[str] = None                              # subtarget bone on the same rig
    pole_target: Optional[str] = None
    influence_driver: Optional[Tuple[str, str]] = None        # (bone, custom prop) -> influence


@dataclass
class DriverDef:
    bone: str
    path: str                  # e.g. 'rotation_euler' (relative to pose bone)
    index: int
    expression: str
    variables: List[Tuple[str, str, str]]    # (var name, bone, custom property)


@dataclass
class LimbInfo:
    """What the pole-angle solver and the UI need to know about each IK limb."""
    chain: str
    kind: str
    ik_bone_last: str          # MCH bone carrying the IK constraint
    ik_constraint: str
    ctrl_ik: str
    ctrl_pole: str
    upper_def: str
    switch_bone: str
    switch_prop: str
    pole_dir: Vector
    shoulder: Vector
    end: Vector
    side: str
    has_fk: bool
    has_ik: bool


@dataclass
class Blueprint:
    bones: Dict[str, BoneDef] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    constraints: List[ConstraintDef] = field(default_factory=list)
    drivers: List[DriverDef] = field(default_factory=list)
    limbs: List[LimbInfo] = field(default_factory=list)
    collections: List[Tuple[str, bool]] = field(default_factory=list)   # (name, visible)

    def add(self, bd: BoneDef) -> BoneDef:
        if bd.name in self.bones:
            raise ValueError(f"Duplicate bone definition '{bd.name}'")
        self.bones[bd.name] = bd
        self.order.append(bd.name)
        return bd


def _color_for(side: str) -> str:
    return PALETTE.get(side, PALETTE["C"])


def _connected(parent_tail: Vector, head: Vector, tol: float) -> bool:
    return (parent_tail - head).length <= tol


# ----------------------------------------------------------------------------- main assembly
def build_blueprint(plan: RigPlan) -> Blueprint:
    opts = plan.options
    bp = Blueprint()
    tol = plan.height * 1e-4
    scale = opts.control_scale
    h = plan.height

    colls = [(C.COLL_ROOT, True), (C.COLL_TORSO, True), (C.COLL_HEAD, True), (C.COLL_ARM_FK, True),
             (C.COLL_ARM_IK, True), (C.COLL_LEG_FK, True), (C.COLL_LEG_IK, True), (C.COLL_FINGERS, True),
             (C.COLL_EXTRA, True), (C.COLL_MCH, False), (C.COLL_DEF, not opts.generate_controls)]
    bp.collections = colls

    limb_by_bone: Dict[str, LimbSpec] = {}
    for lim in plan.limbs:
        for b in lim.bones:
            limb_by_bone[b] = lim

    # ------------------------------------------------------------------ DEF bones
    for name in plan.order:
        spec = plan.bones[name]
        parent = naming.deform(spec.parent) if spec.parent else None
        connect = False
        if spec.parent:
            connect = _connected(plan.bones[spec.parent].tail, spec.head, tol) and spec.role not in {"clavicle"}
        bd = BoneDef(naming.deform(name), spec.head, spec.tail, spec.z_hint, parent, connect, True, C.COLL_DEF,
                     props={"sar_std": f"{spec.std}{naming.side_suffix(spec.side)}"} if spec.std else {},
                     radius=spec.radius)
        bp.add(bd)

    if not opts.generate_controls:
        return bp

    # ------------------------------------------------------------------ master / root
    centre = Vector((plan.centre_x, _centre_y(plan), plan.ground_z))
    fwd = opts.forward
    ring = h * 0.35 * scale
    bp.add(BoneDef("CTRL-master", centre, centre + fwd * ring * 0.6, Vector((0, 0, 1)), None, False, False,
                   C.COLL_ROOT, "root", (ring, ring, ring), color=PALETTE["C"]))
    rr = h * 0.2 * scale
    bp.add(BoneDef("CTRL-root", centre, centre + fwd * rr * 0.6, Vector((0, 0, 1)), "CTRL-master", False, False,
                   C.COLL_ROOT, "ring_flat", (rr, rr, rr), color=PALETTE["C"]))

    def ctrl_parent_for(parent_base: Optional[str]) -> str:
        """Control that should drive children of the deform bone `parent_base`."""
        if parent_base is None:
            return "CTRL-root"
        if parent_base in limb_by_bone:
            return naming.deform(parent_base)      # follow the blended result of the limb
        return naming.control(parent_base)

    # ------------------------------------------------------------------ FK style controls for non-limb bones
    for name in plan.order:
        spec = plan.bones[name]
        if name in limb_by_bone:
            continue
        cname = naming.control(name)
        coll = {"spine": C.COLL_TORSO, "pelvis": C.COLL_TORSO, "chest": C.COLL_TORSO, "neck": C.COLL_HEAD,
                "head": C.COLL_HEAD, "clavicle": C.COLL_ARM_FK, "finger": C.COLL_FINGERS}.get(spec.role, C.COLL_EXTRA)
        parent = ctrl_parent_for(spec.parent)
        connect = False
        r = max(spec.radius * 1.2 * scale, h * 0.008)
        if spec.role in {"clavicle"}:
            shape, sscale, offs, bone_size = "bone_box", (1.0, 1.0, 1.0), (0, 0, 0), True
        else:
            shape, sscale = "circle", (r, r, r)
            offs, bone_size = (0.0, spec.length * 0.5, 0.0), False
        bp.add(BoneDef(cname, spec.head, spec.tail, spec.z_hint, parent, connect, False, coll, shape, sscale, offs,
                       bone_size, _color_for(spec.side)))
        bp.constraints.append(ConstraintDef(naming.deform(name), "COPY_TRANSFORMS", "SAR-FK",
                                            props={}, target=cname))

    # ------------------------------------------------------------------ limbs
    for lim in plan.limbs:
        _add_limb(bp, plan, lim, scale, tol)

    return bp


def _centre_y(plan: RigPlan) -> float:
    ys = [plan.bones[n].head.y for n in plan.spine] or [0.0]
    return sum(ys) / len(ys)


# ----------------------------------------------------------------------------- limbs
def _add_limb(bp: Blueprint, plan: RigPlan, lim: LimbSpec, scale: float, tol: float) -> None:
    opts = plan.options
    h = plan.height
    is_leg = lim.kind == "LEG"
    sfx = naming.side_suffix(lim.side)
    specs = [plan.bones[b] for b in lim.bones]
    upper, lower, end = specs[0], specs[1], specs[2]
    toe = specs[3] if is_leg else None
    use_ik = lim.use_ik
    use_fk = opts.generate_fk or not use_ik
    color = _color_for(lim.side)
    c_fk = C.COLL_LEG_FK if is_leg else C.COLL_ARM_FK
    c_ik = C.COLL_LEG_IK if is_leg else C.COLL_ARM_IK

    parent_ctrl = _limb_parent(plan, lim)
    def_names = [naming.deform(b) for b in lim.bones]

    fk_names: List[str] = []
    ik_names: List[str] = []
    # ------------------------------------------------ FK chain
    if use_fk:
        prev = parent_ctrl
        for spec in specs[:3] + ([toe] if toe else []):
            fk = f"CTRL-fk_{spec.name}"
            if spec is toe:
                # toe control hangs off the blended foot
                parent = naming.deform(end.name)
            else:
                parent = prev
            r = max(spec.radius * 1.25 * scale, h * 0.008)
            bp.add(BoneDef(fk, spec.head, spec.tail, spec.z_hint, parent, False, False, c_fk, "circle",
                           (r, r, r), (0.0, spec.length * 0.5, 0.0), False, color))
            fk_names.append(fk)
            if spec is not toe:
                prev = fk

    # ------------------------------------------------ IK chain
    ctrl_ik = pole = ""
    ik_last = ""
    if use_ik:
        prev = parent_ctrl
        mchs = []
        for spec in specs[:2]:
            m = f"MCH-ik_{spec.name}"
            bp.add(BoneDef(m, spec.head, spec.tail, spec.z_hint, prev, False, False, C.COLL_MCH, "", color=PALETTE["MCH"]))
            prev = m
            mchs.append(m)
        ik_names = mchs
        ik_last = mchs[1]
        # Blender's IK solver cannot bend a perfectly straight chain, so the IK helper bones start with a
        # slight bend towards the pole. Local +X rotation swings a bone's tip towards its +Z (= pole) axis.
        bend = math.radians(3.0)
        bp.bones[mchs[0]].rotation_mode = "XYZ"
        bp.bones[mchs[0]].rest_rotation = (bend, 0.0, 0.0)
        bp.bones[mchs[1]].rotation_mode = "XYZ"
        bp.bones[mchs[1]].rest_rotation = (-2.0 * bend, 0.0, 0.0)

        r = max(end.radius * 1.6 * scale, h * 0.02)
        if is_leg:
            ctrl_ik = f"CTRL-ik_foot{lim.name[3:]}{sfx}"
            heel = lim.heel
            tip = Vector((lim.toe_tip.x, lim.toe_tip.y, heel.z))
            foot_dir = G.safe_normalized(tip - heel, lim.forward)
            length = max((lim.toe_tip - heel).length, h * 0.05)
            bp.add(BoneDef(ctrl_ik, heel, heel + foot_dir * length, Vector((0, 0, 1)), "CTRL-root", False, False,
                           c_ik, "foot_box", (1.0, 1.0, 1.0), (0, 0, 0), True, color))
            _add_foot_roll(bp, plan, lim, ctrl_ik, foot_dir, length, tol)
            ik_target = f"MCH-ankle_target{lim.name[3:]}{sfx}"
        else:
            ctrl_ik = f"CTRL-ik_hand{lim.name[3:]}{sfx}"
            rr = max(end.radius * 1.5 * scale, h * 0.02)
            bp.add(BoneDef(ctrl_ik, end.head, end.tail, end.z_hint, "CTRL-root", False, False, c_ik, "cube",
                           (rr, rr * 0.5, rr), (0, end.length * 0.5, 0), False, color))
            ik_target = ctrl_ik

        pole = f"CTRL-pole_{'leg' if is_leg else 'arm'}{lim.name[3:]}{sfx}"
        pr = h * 0.03 * scale
        bp.add(BoneDef(pole, lim.pole_pos, lim.pole_pos + lim.pole_dir * pr * 2.0, Vector((0, 0, 1)), "CTRL-root",
                       False, False, c_ik, "diamond", (pr, pr, pr), (0, pr, 0), False, color))

        # IK foot / hand follows the IK target orientation
        ikend = f"MCH-ik_{end.name}"
        bp.add(BoneDef(ikend, end.head, end.tail, end.z_hint, mchs[1], False, False, C.COLL_MCH, "",
                       color=PALETTE["MCH"]))
        ik_names.append(ikend)
        bp.constraints.append(ConstraintDef(ikend, "COPY_ROTATION", "SAR-IK-Rot",
                                            props={"target_space": "WORLD", "owner_space": "WORLD"}, target=ik_target))
        bp.constraints.append(ConstraintDef(
            mchs[1], "IK", "SAR-IK",
            props={"chain_count": 2, "use_tail": True, "use_stretch": False, "pole_angle": 0.0}, target=ik_target,
            pole_target=pole))

        # switch property lives on the IK control
        bp.bones[ctrl_ik].props["ik_fk"] = float(opts.default_ik) if use_fk else 1.0
        bp.bones[ctrl_ik].prop_ui["ik_fk"] = {"min": 0.0, "max": 1.0, "soft_min": 0.0, "soft_max": 1.0,
                                              "description": "IK/FK blend: 1 = IK, 0 = FK"}

    # ------------------------------------------------ DEF constraints (FK then IK blended over it)
    for i, spec in enumerate(specs[:3]):
        d = naming.deform(spec.name)
        if use_fk:
            bp.constraints.append(ConstraintDef(d, "COPY_TRANSFORMS", "SAR-FK", target=fk_names[i]))
        if use_ik:
            infl = (ctrl_ik, "ik_fk") if use_fk else None
            bp.constraints.append(ConstraintDef(d, "COPY_TRANSFORMS", "SAR-IK", target=ik_names[i],
                                                influence_driver=infl))
    if toe is not None:
        d = naming.deform(toe.name)
        if use_fk:
            bp.constraints.append(ConstraintDef(d, "COPY_TRANSFORMS", "SAR-FK", target=fk_names[3]))
        else:
            # IK-only: toe rigidly follows the foot via its deform parent; add a plain control
            r = max(toe.radius * 1.25 * scale, h * 0.008)
            ctoe = f"CTRL-fk_{toe.name}"
            bp.add(BoneDef(ctoe, toe.head, toe.tail, toe.z_hint, naming.deform(end.name), False, False, c_fk,
                           "circle", (r, r, r), (0, toe.length * 0.5, 0), False, color))
            bp.constraints.append(ConstraintDef(d, "COPY_TRANSFORMS", "SAR-FK", target=ctoe))

    bp.limbs.append(LimbInfo(lim.chain, lim.kind, ik_last, "SAR-IK", ctrl_ik, pole, naming.deform(upper.name),
                             ctrl_ik, "ik_fk", lim.pole_dir, upper.head, end.head, lim.side, use_fk, use_ik))


def _limb_parent(plan: RigPlan, lim: LimbSpec) -> str:
    parent = plan.bones[lim.bones[0]].parent
    if parent is None:
        return "CTRL-root"
    # a parent that belongs to another limb (e.g. extra arm on an arm) follows the deform result
    for other in plan.limbs:
        if parent in other.bones:
            return naming.deform(parent)
    return naming.control(parent)


def _add_foot_roll(bp: Blueprint, plan: RigPlan, lim: LimbSpec, ctrl_ik: str, foot_dir: Vector, length: float,
                   tol: float) -> None:
    """Reverse-foot roll chain: heel -> toe tip -> ball -> ankle target, driven by a 'foot_roll' property."""
    sfx = naming.side_suffix(lim.side)
    tag = f"{lim.name[3:]}{sfx}"
    up = Vector((0, 0, 1))
    h = plan.height
    small = max(length * 0.2, h * 0.01)
    heel = lim.heel
    ball = lim.ball
    toe = lim.toe_tip
    ank = plan.bones[lim.bones[2]].head
    toe_ground = Vector((toe.x, toe.y, lim.heel.z))

    if not plan.options.foot_roll:
        bp.add(BoneDef(f"MCH-ankle_target{tag}", ank, ball, up, ctrl_ik, False, False, C.COLL_MCH, "",
                       color=PALETTE["MCH"]))
        return

    heel_b = f"MCH-roll_heel{tag}"
    toe_b = f"MCH-roll_toe{tag}"
    ball_b = f"MCH-roll_ball{tag}"
    bp.add(BoneDef(heel_b, heel, heel + foot_dir * small, up, ctrl_ik, False, False, C.COLL_MCH, "",
                   color=PALETTE["MCH"], rotation_mode="XYZ"))
    bp.add(BoneDef(toe_b, toe_ground, toe_ground + foot_dir * small, up, heel_b, False, False, C.COLL_MCH, "",
                   color=PALETTE["MCH"], rotation_mode="XYZ"))
    bp.add(BoneDef(ball_b, ball, ball + foot_dir * small, up, toe_b, False, False, C.COLL_MCH, "",
                   color=PALETTE["MCH"], rotation_mode="XYZ"))
    bp.add(BoneDef(f"MCH-ankle_target{tag}", ank, ball, up, ball_b, False, False, C.COLL_MCH, "",
                   color=PALETTE["MCH"]))

    ctrl = bp.bones[ctrl_ik]
    ctrl.props["foot_roll"] = 0.0
    ctrl.prop_ui["foot_roll"] = {"min": -90.0, "max": 150.0, "soft_min": -60.0, "soft_max": 120.0,
                                 "description": "Foot roll in degrees: negative rolls on the heel, positive over the ball and toe"}
    ctrl.props["roll_ball_angle"] = 50.0
    ctrl.prop_ui["roll_ball_angle"] = {"min": 10.0, "max": 90.0, "description": "Angle at which the roll moves from the ball to the toe tip"}
    var_roll = ("roll", ctrl_ik, "foot_roll")
    var_ball = ("ball", ctrl_ik, "roll_ball_angle")
    k = 0.017453292519943295   # degrees -> radians; only min/max/arithmetic so Blender can evaluate it natively
    bp.drivers.append(DriverDef(heel_b, "rotation_euler", 0, f"max(-roll, 0) * {k}", [var_roll]))
    bp.drivers.append(DriverDef(ball_b, "rotation_euler", 0, f"-max(min(roll, ball), 0) * {k}", [var_roll, var_ball]))
    bp.drivers.append(DriverDef(toe_b, "rotation_euler", 0, f"-max(roll - ball, 0) * {k}", [var_roll, var_ball]))
