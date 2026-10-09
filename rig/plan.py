"""Rig planning: turn guide positions into a bpy-independent description of the skeleton.

The plan is pure data (mathutils vectors + dataclasses). The builders in `skeleton.py`,
`controls.py` and `ik_fk.py` turn it into an armature. Keeping planning separate makes the
fitting logic easy to inspect (debug mode prints the plan) and to extend with new rig types.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from mathutils import Vector

from .. import constants as C
from ..analysis import mesh_analysis as MA
from ..utils import geometry as G
from ..utils import logging as log
from ..utils import naming


# ----------------------------------------------------------------------------- data
@dataclass
class RigOptions:
    rig_type: str = "HUMANOID"
    fit_mode: str = "EXACT"          # EXACT | OPTIMIZE
    joint_mode: str = "MANUAL"       # MANUAL | AUTO
    spine_bones: int = 0
    neck_bones: int = 0
    use_clavicles: bool = True
    generate_controls: bool = True
    generate_ik: bool = True
    generate_fk: bool = True
    foot_roll: bool = True
    default_ik: float = 1.0
    control_scale: float = 1.0
    forward: Vector = field(default_factory=lambda: Vector((0.0, -1.0, 0.0)))
    left: Vector = field(default_factory=lambda: Vector((1.0, 0.0, 0.0)))

    @classmethod
    def from_settings(cls, s) -> "RigOptions":
        fwd = {"-Y": (0, -1, 0), "Y": (0, 1, 0), "-X": (-1, 0, 0), "X": (1, 0, 0)}[s.forward_axis]
        left = (1, 0, 0) if s.left_axis == "X" else (-1, 0, 0)
        return cls(s.rig_type, s.fit_mode, s.joint_mode, s.spine_bones, s.neck_bones, s.use_clavicles,
                   s.generate_controls, s.generate_ik, s.generate_fk, s.foot_roll, s.default_ik,
                   s.control_scale, Vector(fwd), Vector(left))


@dataclass
class ChainDef:
    cid: str
    kind: str
    side: str
    name: str
    parent_chain: str = ""
    use_ik: bool = True
    point_keys: List[str] = field(default_factory=list)


@dataclass
class BoneSpec:
    name: str                       # base name (no DEF-/CTRL- prefix)
    head: Vector
    tail: Vector
    z_hint: Vector
    parent: Optional[str]           # base name of the parent deform bone
    chain: str
    role: str
    side: str = ""
    radius: float = 0.05
    std: str = ""                   # standardised humanoid name (retargeting friendly)
    index: int = 0

    @property
    def length(self) -> float:
        return (self.tail - self.head).length


@dataclass
class LimbSpec:
    chain: str
    kind: str                       # ARM | LEG
    side: str
    name: str                       # chain name e.g. "arm2"
    bones: List[str]                # base names: upper, lower, end[, toe]
    pole_pos: Vector
    pole_dir: Vector
    use_ik: bool
    heel: Optional[Vector] = None
    ball: Optional[Vector] = None
    toe_tip: Optional[Vector] = None
    ground_z: float = 0.0
    forward: Vector = field(default_factory=lambda: Vector((0, -1, 0)))
    parent_bone: Optional[str] = None
    clavicle: Optional[str] = None


@dataclass
class RigPlan:
    options: RigOptions
    height: float
    bones: Dict[str, BoneSpec] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    limbs: List[LimbSpec] = field(default_factory=list)
    spine: List[str] = field(default_factory=list)
    chains: Dict[str, ChainDef] = field(default_factory=dict)
    points: Dict[str, Vector] = field(default_factory=dict)       # resolved incl. inferred
    inferred: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    ground_z: float = 0.0
    centre_x: float = 0.0

    def add(self, spec: BoneSpec) -> BoneSpec:
        if spec.name in self.bones:
            self.warnings.append(f"Duplicate bone name '{spec.name}' - renamed.")
            spec.name = naming.unique_name(spec.name, self.bones)
        self.bones[spec.name] = spec
        self.order.append(spec.name)
        return spec

    def children_of(self, name: str) -> List[str]:
        return [n for n in self.order if self.bones[n].parent == name]


# ----------------------------------------------------------------------------- rig types
class RigType:
    id = "BASE"
    label = "Base"

    def check(self, positions: Dict[str, Vector], chains: List[ChainDef]) -> Tuple[List[str], List[str]]:
        """Return (errors, warnings) about missing guides for this rig type."""
        return [], []


class HumanoidRig(RigType):
    id = "HUMANOID"
    label = "Humanoid"

    def check(self, positions, chains):
        errors, warnings = [], []
        for k in sorted(C.SPINE_REQUIRED):
            if k not in positions:
                errors.append(f"{C.SPINE_LABELS[k]} guide is missing. Place it in Guided Setup.")
        for side, nm in (("L", "left"), ("R", "right")):
            for part in sorted(C.ARM_REQUIRED):
                if f"arm.{side}.{part}" not in positions:
                    errors.append(f"The {nm} {C.ARM_LABELS[part].lower()} guide is missing.")
            for part in sorted(C.LEG_REQUIRED):
                if f"leg.{side}.{part}" not in positions:
                    errors.append(f"The {nm} {C.LEG_LABELS[part].lower()} guide is missing.")
        return errors, warnings


class CreatureRig(RigType):
    id = "CREATURE"
    label = "Creature"

    def check(self, positions, chains):
        errors, warnings = [], []
        usable = 0
        for ch in chains:
            placed = [k for k in ch.point_keys if k in positions]
            if len(placed) >= 2:
                usable += 1
            elif placed:
                warnings.append(f"Chain '{ch.cid}' has only one guide - it will be skipped.")
        if usable == 0:
            errors.append("No chain has two or more placed guides. Place at least a start and an end guide.")
        return errors, warnings


class CustomRig(CreatureRig):
    id = "CUSTOM"
    label = "Custom"


RIG_TYPES: Dict[str, RigType] = {r.id: r for r in (HumanoidRig(), CreatureRig(), CustomRig())}


def register_rig_type(rig_type: RigType) -> None:
    """Extension point: register an additional rig type (e.g. a quadruped)."""
    RIG_TYPES[rig_type.id] = rig_type


# ----------------------------------------------------------------------------- helpers
def _bone_radius(cd, head: Vector, tail: Vector, fallback: float) -> float:
    if cd is None or len(cd.samples) == 0:
        return fallback
    d = tail - head
    if d.length < 1e-6:
        return fallback
    r = MA.local_radius(cd, (head + tail) * 0.5, d, d.length * 0.6)
    return max(r, fallback * 0.25)


def _refine_joint(cd, p: Vector, d: Vector, seg: float, plan: RigPlan, label: str) -> Vector:
    """Move a joint to the centre of the cross-section around it (limited displacement)."""
    if cd is None:
        return p
    radius = max(MA.local_radius(cd, p, d, seg * 0.3) * 1.3, seg * 0.15)
    c = MA.centroid_in_slab(cd, p, d, slab=seg * 0.15, radius=radius)
    if c is None:
        return p
    delta = c - p
    limit = seg * 0.25
    if delta.length > limit:
        delta = delta.normalized() * limit
    log.debug(f"refine {label}: moved {delta.length:.4f}")
    return p + delta


def _nearest_bone(plan: RigPlan, point: Vector, candidates: List[str]) -> Optional[str]:
    best, best_d = None, float("inf")
    for n in candidates:
        b = plan.bones[n]
        q, _t = G.closest_point_on_segment(point, b.head, b.tail)
        d = (q - point).length
        if d < best_d:
            best, best_d = n, d
    return best


def _check_distinct(plan: RigPlan, pts: List[Tuple[str, Vector]], tol: float) -> None:
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if (pts[i][1] - pts[j][1]).length < tol:
                plan.errors.append(f"Two guides are at the same location: '{pts[i][0]}' and '{pts[j][0]}'. "
                                   f"Move one of them.")


# ----------------------------------------------------------------------------- builder
def build_plan(positions: Dict[str, Vector], chains: List[ChainDef], options: RigOptions, cd=None) -> RigPlan:
    """Create a RigPlan. `cd` is an optional CharacterData used for refinement and radii."""
    # --- global measures
    if cd is not None and cd.size.z > 1e-6:
        height = cd.height
        ground_z = cd.bbox_min.z
        centre_x = cd.centre.x
    else:
        zs = [p.z for p in positions.values()] or [0.0, 1.0]
        height = max(max(zs) - min(zs), 1e-3) * 1.15
        ground_z = min(zs)
        centre_x = sum(p.x for p in positions.values()) / max(len(positions), 1)

    plan = RigPlan(options=options, height=height, ground_z=ground_z, centre_x=centre_x)
    plan.chains = {c.cid: c for c in chains}
    pts: Dict[str, Vector] = {k: v.copy() for k, v in positions.items()}
    fwd = options.forward.normalized()
    up = Vector(C.UP)
    back = -fwd

    rt = RIG_TYPES.get(options.rig_type, RIG_TYPES["CREATURE"])
    errs, warns = rt.check(pts, chains)
    plan.errors.extend(errs)
    plan.warnings.extend(warns)
    if plan.errors:
        plan.points = pts
        return plan

    # ------------------------------------------------------------------ spine
    spine_chain = next((c for c in chains if c.kind == "SPINE"), None)
    if spine_chain is not None:
        _plan_spine(plan, pts, cd, options, height, up, fwd)

    # ------------------------------------------------------------------ limbs
    for ch in chains:
        if ch.kind == "ARM":
            _plan_arm(plan, ch, pts, cd, options, height, up, fwd, back)
    for ch in chains:
        if ch.kind == "LEG":
            _plan_leg(plan, ch, pts, cd, options, height, up, fwd, back)

    # ------------------------------------------------------------------ generic chains (fingers, tails ...)
    pending = [c for c in chains if c.kind in C.GENERIC_KINDS]
    progress = True
    built: set = set()
    while pending and progress:
        progress = False
        for ch in list(pending):
            if ch.parent_chain and ch.parent_chain in plan.chains and \
                    plan.chains[ch.parent_chain].kind in C.GENERIC_KINDS and ch.parent_chain not in built:
                continue
            _plan_generic(plan, ch, pts, cd, options, height, up, fwd, back)
            built.add(ch.cid)
            pending.remove(ch)
            progress = True
    for ch in pending:
        plan.warnings.append(f"Chain '{ch.cid}' has an unresolved parent chain '{ch.parent_chain}' - skipped.")

    plan.points = pts
    if not plan.bones:
        plan.errors.append("No bones could be generated from the guides.")
    return plan


# ---------------------------------------------------------------------------- spine
def _plan_spine(plan, pts, cd, options, height, up, fwd):
    order = [k for k in C.SPINE_KEYS if k in pts]
    if "head" in pts and "head_top" not in pts:
        base = pts["head"]
        top = None
        if cd is not None and len(cd.samples):
            near = cd.points_in_radius(base + up * (height * 0.06), height * 0.12)
            near = near[near[:, 2] > base.z] if len(near) else near
            if len(near) > 4:
                zmax = float(near[:, 2].max())
                top = Vector((base.x, base.y, zmax))
        if top is None or top.z - base.z < height * 0.04:
            axis = (pts["head"] - pts["neck"]) if "neck" in pts else up
            axis = G.safe_normalized(axis, up)
            top = base + axis * height * 0.13
        pts["head_top"] = top
        plan.inferred.append("head_top")
        order = [k for k in C.SPINE_KEYS if k in pts]

    if len(order) < 2:
        return
    _check_distinct(plan, [(k, pts[k]) for k in order], height * 0.002)
    if plan.errors:
        return

    hint = -fwd.copy()
    names_by_start = {"pelvis": "spine", "chest": "chest", "neck": "neck", "head": "head"}
    seg_std = {"spine": "spine", "chest": "chest", "neck": "neck", "head": "head"}

    # pelvis bone: short bone pointing down from the pelvis point (hips)
    if "pelvis" in order:
        p = pts["pelvis"]
        tail = p - up * height * 0.07
        plan.add(BoneSpec("pelvis", p.copy(), tail, hint, None, "spine", "pelvis", "",
                          radius=height * 0.09, std="hips"))
        plan.spine.append("pelvis")

    prev_name = "pelvis" if "pelvis" in order else None
    for a, b in zip(order[:-1], order[1:]):
        pa, pb = pts[a], pts[b]
        base_name = names_by_start.get(a, "spine")
        seg_len = (pb - pa).length
        if base_name == "spine":
            n = options.spine_bones or max(1, min(5, round(seg_len / (height * 0.1))))
        elif base_name == "neck":
            n = options.neck_bones or (2 if seg_len > height * 0.11 else 1)
        else:
            n = 1
        for i in range(n):
            h = G.lerp(pa, pb, i / n)
            t = G.lerp(pa, pb, (i + 1) / n)
            if base_name == "spine":
                nm = f"spine_{i + 1:02d}"
            elif base_name == "neck" and n > 1:
                nm = f"neck_{i + 1:02d}"
            else:
                nm = base_name
            r = _bone_radius(cd, h, t, height * 0.07)
            spec = plan.add(BoneSpec(nm, h, t, hint, prev_name, "spine", base_name, "",
                                     radius=r, std=seg_std.get(base_name, "spine"), index=len(plan.spine)))
            plan.spine.append(spec.name)
            prev_name = spec.name


# ---------------------------------------------------------------------------- limbs
def _spine_parent_for(plan: RigPlan, point: Vector, prefer_upper: bool) -> Optional[str]:
    cands = [n for n in plan.spine]
    if not cands:
        return None
    return _nearest_bone(plan, point, cands)


def _pole_direction(a: Vector, b: Vector, c: Vector, default_dir: Vector, limb_len: float) -> Vector:
    """Direction from the midpoint of a-c towards the middle joint b; default when nearly straight."""
    mid = (a + c) * 0.5
    dev = b - mid
    axis = (c - a).normalized() if (c - a).length > 1e-9 else Vector((0, 0, 1))
    dev = dev - axis * dev.dot(axis)
    if dev.length < limb_len * 0.02:
        d = default_dir - axis * default_dir.dot(axis)
        return G.safe_normalized(d, Vector((0, 1, 0)))
    return dev.normalized()


def _plan_arm(plan, ch, pts, cd, options, height, up, fwd, back):
    sh, wr = pts.get(f"{ch.cid}.shoulder"), pts.get(f"{ch.cid}.wrist")
    if sh is None or wr is None:
        if sh is not None or wr is not None or f"{ch.cid}.elbow" in pts:
            plan.warnings.append(f"Arm '{ch.cid}' needs both shoulder and hand guides - skipped.")
        return
    num = _num(ch.name)
    sfx = naming.side_suffix(ch.side)
    elbow_key = f"{ch.cid}.elbow"
    elbow = pts.get(elbow_key)
    arm_len = (wr - sh).length
    _check_distinct(plan, [(f"{ch.cid}.shoulder", sh), (f"{ch.cid}.wrist", wr)], height * 0.002)
    if elbow is None:
        elbow = G.lerp(sh, wr, 0.5)
        pts[elbow_key] = elbow
        plan.inferred.append(elbow_key)
        if cd is not None:
            elbow = _refine_joint(cd, elbow, wr - sh, arm_len * 0.5, plan, elbow_key)
            pts[elbow_key] = elbow
    elif options.joint_mode == "AUTO" or options.fit_mode == "OPTIMIZE":
        pts[elbow_key] = elbow = _refine_joint(cd, elbow, wr - sh, arm_len * 0.5, plan, elbow_key)
    if plan.errors:
        return

    tip = pts.get(f"{ch.cid}.hand_tip")
    if tip is None:
        fdir = G.safe_normalized(wr - elbow, Vector((1, 0, 0)))
        tip = wr + fdir * (wr - elbow).length * 0.45
        pts[f"{ch.cid}.hand_tip"] = tip
        plan.inferred.append(f"{ch.cid}.hand_tip")
    _check_distinct(plan, [(f"{ch.cid}.wrist", wr), (f"{ch.cid}.hand_tip", tip)], height * 0.001)
    ratio = (wr - elbow).length / max((elbow - sh).length, 1e-6)
    if not 0.4 <= ratio <= 2.5:
        plan.warnings.append(f"{ch.cid}: forearm/upper-arm length ratio is {ratio:.2f}; check the elbow guide.")

    hint = _pole_direction(sh, elbow, wr, back, arm_len)
    # roll hint: bend direction for limbs
    parent_spine = _spine_parent_for(plan, sh, True)
    clav_name = None
    upper_parent = parent_spine
    if options.use_clavicles and plan.spine and len(plan.spine) >= 2:
        poly = [plan.bones[n].head for n in plan.spine] + [plan.bones[plan.spine[-1]].tail]
        base, _seg, _t = G.closest_point_on_polyline(sh, poly)
        if (sh - base).length > height * 0.03:
            clav_name = f"clavicle{num}{sfx}"
            plan.add(BoneSpec(clav_name, base, sh.copy(), back, parent_spine, ch.cid, "clavicle", ch.side,
                              radius=height * 0.03, std="shoulder"))
            upper_parent = clav_name
    names = []
    up_n, lo_n, hd_n = f"upper_arm{num}{sfx}", f"forearm{num}{sfx}", f"hand{num}{sfx}"
    plan.add(BoneSpec(up_n, sh.copy(), elbow.copy(), hint, upper_parent, ch.cid, "upper", ch.side,
                      radius=_bone_radius(cd, sh, elbow, arm_len * 0.12), std="upperarm"))
    plan.add(BoneSpec(lo_n, elbow.copy(), wr.copy(), hint, up_n, ch.cid, "lower", ch.side,
                      radius=_bone_radius(cd, elbow, wr, arm_len * 0.1), std="lowerarm"))
    plan.add(BoneSpec(hd_n, wr.copy(), tip.copy(), hint, lo_n, ch.cid, "end", ch.side,
                      radius=_bone_radius(cd, wr, tip, arm_len * 0.08), std="hand"))
    limb_len = (elbow - sh).length + (wr - elbow).length
    pole_pos = elbow + hint * limb_len * 0.6
    plan.limbs.append(LimbSpec(ch.cid, "ARM", ch.side, ch.name, [up_n, lo_n, hd_n], pole_pos, hint,
                               ch.use_ik and options.generate_ik, forward=fwd, parent_bone=upper_parent,
                               clavicle=clav_name))


def _plan_leg(plan, ch, pts, cd, options, height, up, fwd, back):
    hip, ank = pts.get(f"{ch.cid}.hip"), pts.get(f"{ch.cid}.ankle")
    if hip is None or ank is None:
        if hip is not None or ank is not None or f"{ch.cid}.knee" in pts:
            plan.warnings.append(f"Leg '{ch.cid}' needs both hip and foot guides - skipped.")
        return
    num = _num(ch.name)
    sfx = naming.side_suffix(ch.side)
    knee_key = f"{ch.cid}.knee"
    knee = pts.get(knee_key)
    leg_len = (ank - hip).length
    _check_distinct(plan, [(f"{ch.cid}.hip", hip), (f"{ch.cid}.ankle", ank)], height * 0.002)
    if knee is None:
        knee = G.lerp(hip, ank, 0.5)
        pts[knee_key] = knee
        plan.inferred.append(knee_key)
        if cd is not None:
            knee = _refine_joint(cd, knee, ank - hip, leg_len * 0.5, plan, knee_key)
            pts[knee_key] = knee
    elif options.joint_mode == "AUTO" or options.fit_mode == "OPTIMIZE":
        pts[knee_key] = knee = _refine_joint(cd, knee, ank - hip, leg_len * 0.5, plan, knee_key)
    if plan.errors:
        return
    ratio = (ank - knee).length / max((knee - hip).length, 1e-6)
    if not 0.4 <= ratio <= 2.5:
        plan.warnings.append(f"{ch.cid}: shin/thigh length ratio is {ratio:.2f}; check the knee guide.")

    # ----- foot geometry
    f2 = Vector((fwd.x, fwd.y, 0.0))
    f2 = G.safe_normalized(f2, Vector((0, -1, 0)))
    ground = plan.ground_z
    if cd is not None and len(cd.samples):
        near = cd.points_in_radius(Vector((ank.x, ank.y, ground)), max(leg_len * 0.45, height * 0.05))
        if len(near):
            low = near[near[:, 2] < ank.z]
            if len(low) > 4:
                ground = float(low[:, 2].min())
    else:
        ground = min(ground, ank.z - leg_len * 0.1)
    ball = pts.get(f"{ch.cid}.ball")
    toe = pts.get(f"{ch.cid}.toe")
    foot_len = leg_len * 0.32
    if cd is not None and len(cd.samples) and ball is None and toe is None:
        near = cd.points_in_radius(Vector((ank.x, ank.y, ground + (ank.z - ground) * 0.5)), leg_len * 0.55)
        if len(near):
            rel = near - np_vec(ank)
            low = near[:, 2] < ank.z + (ank.z - ground) * 0.2
            if low.sum() > 4:
                fwd_ext = float((rel[low] @ np_vec(f2)).max())
                if fwd_ext > leg_len * 0.1:
                    foot_len = fwd_ext
    height_above = max(ank.z - ground, height * 0.02)
    if toe is None and ball is None:
        toe = Vector((ank.x, ank.y, ground + height_above * 0.12)) + f2 * foot_len
        ball = Vector((ank.x, ank.y, ground + height_above * 0.3)) + f2 * foot_len * 0.72
        plan.inferred += [f"{ch.cid}.ball", f"{ch.cid}.toe"]
    elif toe is None:
        d = ball - ank
        toe = ball + G.safe_normalized(Vector((d.x, d.y, 0)), f2) * max(foot_len * 0.28, 1e-4)
        toe.z = ground + height_above * 0.12
        plan.inferred.append(f"{ch.cid}.toe")
    elif ball is None:
        ball = G.lerp(ank, toe, 0.72)
        plan.inferred.append(f"{ch.cid}.ball")
    pts[f"{ch.cid}.ball"], pts[f"{ch.cid}.toe"] = ball, toe
    _check_distinct(plan, [(f"{ch.cid}.ankle", ank), (f"{ch.cid}.ball", ball), (f"{ch.cid}.toe", toe)],
                    height * 0.001)
    if plan.errors:
        return
    foot_dir = G.safe_normalized(Vector((toe.x - ank.x, toe.y - ank.y, 0)), f2)
    heel = Vector((ank.x, ank.y, ground)) - foot_dir * max((toe - ank).length * 0.3, height * 0.02)

    hint = _pole_direction(hip, knee, ank, fwd, leg_len)
    pelvis = "pelvis" if "pelvis" in plan.bones else _spine_parent_for(plan, hip, False)
    th_n, sh_n, ft_n, to_n = f"thigh{num}{sfx}", f"shin{num}{sfx}", f"foot{num}{sfx}", f"toe{num}{sfx}"
    plan.add(BoneSpec(th_n, hip.copy(), knee.copy(), hint, pelvis, ch.cid, "upper", ch.side,
                      radius=_bone_radius(cd, hip, knee, leg_len * 0.12), std="upleg"))
    plan.add(BoneSpec(sh_n, knee.copy(), ank.copy(), hint, th_n, ch.cid, "lower", ch.side,
                      radius=_bone_radius(cd, knee, ank, leg_len * 0.1), std="leg"))
    plan.add(BoneSpec(ft_n, ank.copy(), ball.copy(), up, sh_n, ch.cid, "end", ch.side,
                      radius=_bone_radius(cd, ank, ball, leg_len * 0.09), std="foot"))
    plan.add(BoneSpec(to_n, ball.copy(), toe.copy(), up, ft_n, ch.cid, "toe", ch.side,
                      radius=_bone_radius(cd, ball, toe, leg_len * 0.07), std="toes"))
    limb_len = (knee - hip).length + (ank - knee).length
    pole_pos = knee + hint * limb_len * 0.6
    plan.limbs.append(LimbSpec(ch.cid, "LEG", ch.side, ch.name, [th_n, sh_n, ft_n, to_n], pole_pos, hint,
                               ch.use_ik and options.generate_ik, heel=heel, ball=ball.copy(), toe_tip=toe.copy(),
                               ground_z=ground, forward=foot_dir, parent_bone=pelvis))


# ---------------------------------------------------------------------------- generic chains
def _plan_generic(plan, ch, pts, cd, options, height, up, fwd, back):
    keys = [k for k in ch.point_keys if k in pts]
    if len(keys) < 2:
        if keys:
            plan.warnings.append(f"Chain '{ch.cid}' needs at least two guides - skipped.")
        return
    seq = [pts[k] for k in keys]
    _check_distinct(plan, list(zip(keys, seq)), height * 0.0008)
    if plan.errors:
        return
    sfx = naming.side_suffix(ch.side)
    # parent resolution
    parent = None
    if ch.parent_chain:
        pc = plan.chains.get(ch.parent_chain)
        if pc is not None:
            if pc.kind == "ARM":
                lim = next((l for l in plan.limbs if l.chain == pc.cid), None)
                parent = lim.bones[2] if lim else None
            elif pc.kind == "LEG":
                lim = next((l for l in plan.limbs if l.chain == pc.cid), None)
                parent = lim.bones[2] if lim else None
            else:
                last = [n for n in plan.order if plan.bones[n].chain == pc.cid]
                parent = last[-1] if last else None
    if parent is None:
        cands = [n for n in plan.order if plan.bones[n].chain != ch.cid]
        parent = _nearest_bone(plan, seq[0], cands) if cands else None
    hint = up if ch.kind == "FINGER" else back
    base = ch.name
    prev = parent
    for i in range(len(seq) - 1):
        nm = f"{base}_{i + 1:02d}{sfx}"
        r = _bone_radius(cd, seq[i], seq[i + 1], height * 0.012)
        plan.add(BoneSpec(nm, seq[i].copy(), seq[i + 1].copy(), hint, prev, ch.cid, ch.kind.lower(), ch.side,
                          radius=r, index=i))
        prev = nm


# ---------------------------------------------------------------------------- utils
def _num(name: str) -> str:
    out = ""
    for c in reversed(name):
        if c.isdigit():
            out = c + out
        else:
            break
    return out


def np_vec(v: Vector):
    import numpy as np

    return np.array((v.x, v.y, v.z), dtype=np.float32)


def describe(plan: RigPlan) -> str:
    lines = [f"RigPlan: {len(plan.bones)} bones, {len(plan.limbs)} limbs, height={plan.height:.3f}"]
    for n in plan.order:
        b = plan.bones[n]
        lines.append(f"  {n:20s} parent={b.parent!s:14s} len={b.length:.3f} role={b.role}")
    for w in plan.warnings:
        lines.append(f"  warning: {w}")
    for e in plan.errors:
        lines.append(f"  ERROR: {e}")
    return "\n".join(lines)
