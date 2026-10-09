"""Real, measurable rig-confidence analysis.

Every score is computed from geometry and guide placement - nothing is random and no ML model is
involved. The result is an ANALYSIS SCORE and is deliberately separate from generation progress.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
from mathutils import Vector

from .. import constants as C
from ..rig import plan as PL
from ..utils import compute
from ..utils import geometry as G
from ..utils import naming
from . import mesh_analysis as MA
from . import symmetry as SY


@dataclass
class AnalysisResult:
    scores: List[Tuple[str, float, str]] = field(default_factory=list)   # (name, 0..100, detail)
    overall: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    cd: object = None
    plan: object = None
    summary: str = ""
    checklist: Dict[str, bool] = field(default_factory=dict)
    backend: str = "CPU (NumPy)"


def analyze(settings, objects, positions: Dict[str, Vector], chains, options) -> AnalysisResult:
    from ..rig import generator as GEN  # noqa: F401  (avoid circular import at module load)

    res = AnalysisResult()
    cd = MA.gather_character(objects, settings.analysis_quality)
    res.cd = cd
    selected = len([o for o in objects if o is not None])

    # ------------------------------------------------------------- 1. mesh analysis
    if not cd.objects:
        res.errors.append("No mesh character selected. Select the character mesh(es) and click 'Use Selected Objects'.")
        res.scores.append(("Mesh Analysis", 0.0, "no usable meshes"))
        res.overall = 0.0
        return res
    valid_frac = len(cd.objects) / max(selected, 1)
    orient = MA.orientation_report(cd)
    size_ok = 1.0 if cd.height > 1e-3 and cd.vertex_count >= 8 else 0.3
    mesh_score = 0.5 * valid_frac + 0.3 * (1.0 if orient["upright"] else 0.2) + 0.2 * size_ok
    res.warnings += cd.invalid + orient["notes"]
    detail = f"{len(cd.objects)} object(s), {cd.vertex_count} vertices, height {cd.height:.3f}"
    res.scores.append(("Mesh Analysis", mesh_score * 100, detail))

    # ------------------------------------------------------------- plan (also infers missing joints)
    plan = PL.build_plan(positions, chains, options, cd)
    res.plan = plan
    res.errors += plan.errors
    res.warnings += plan.warnings

    # ------------------------------------------------------------- 2. completeness
    rt = PL.RIG_TYPES.get(options.rig_type, PL.RIG_TYPES["CREATURE"])
    errs, _w = rt.check(positions, chains)
    if options.rig_type == "HUMANOID":
        required = (len(C.SPINE_REQUIRED) + 2 * len(C.ARM_REQUIRED) + 2 * len(C.LEG_REQUIRED))
        completeness = max(0.0, 1.0 - len(errs) / required)
    else:
        usable = sum(1 for c in chains if sum(1 for k in c.point_keys if k in positions) >= 2)
        completeness = usable / max(len(chains), 1) if not errs else 0.0
    res.scores.append(("Required Guides", completeness * 100,
                       "all present" if not errs else f"{len(errs)} missing"))
    res.checklist = _checklist(positions, chains)

    # ------------------------------------------------------------- 3. guide quality
    H = cd.height
    near_ok = []
    if cd.kd is not None:
        for key, p in positions.items():
            _co, _i, d = cd.kd.find(p)
            near_ok.append(d <= 0.12 * H)
    far_fraction = 1.0 - (float(np.mean(near_ok)) if near_ok else 0.0)
    near_score = max(0.0, 1.0 - 3.0 * far_fraction) if near_ok else 0.0
    outside = [k for k, ok in zip(positions.keys(), near_ok) if not ok]
    if outside:
        res.warnings.append(f"Guide(s) far from the mesh: {', '.join(outside[:4])}"
                            f"{'...' if len(outside) > 4 else ''}. Drag them onto the character.")

    order_ok, order_total = 0, 0
    for ch in chains:
        keys = [k for k in ch.point_keys if k in positions]
        if len(keys) < 3 or ch.kind not in {"ARM", "LEG", "SPINE"} | C.GENERIC_KINDS:
            continue
        pts = [positions[k] for k in keys]
        axis = pts[-1] - pts[0]
        if axis.length < 1e-6:
            continue
        axis.normalize()
        proj = [(p - pts[0]).dot(axis) for p in pts]
        for a, b in zip(proj[:-1], proj[1:]):
            order_total += 1
            order_ok += 1 if b > a else 0
    order_score = order_ok / order_total if order_total else 1.0
    if order_total and order_ok < order_total:
        res.warnings.append("Some guides are out of order along their chain (root to tip). Check joint order.")

    keys = list(positions.keys())
    close = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if (positions[keys[i]] - positions[keys[j]]).length < H * 0.004:
                close += 1
                res.warnings.append(f"Two guides are at the same location: {keys[i]} and {keys[j]}.")
    sep_score = 1.0 if close == 0 else max(0.0, 1.0 - 0.25 * close)
    ratio_pen = sum(1 for w in plan.warnings if "ratio" in w)
    quality = (0.4 * near_score + 0.3 * order_score + 0.2 * sep_score + 0.1 * max(0.0, 1.0 - 0.5 * ratio_pen)) \
        if positions else 0.0
    res.scores.append(("Guide Quality", quality * 100, f"{sum(near_ok)}/{len(near_ok)} guides on the mesh"))

    # ------------------------------------------------------------- 4. joints
    joint_scores: List[float] = []
    for lim in plan.limbs:
        mid_key = f"{lim.chain}.elbow" if lim.kind == "ARM" else f"{lim.chain}.knee"
        a = plan.bones[lim.bones[0]]
        b = plan.bones[lim.bones[1]]
        u, l = (a.tail - a.head), (b.tail - b.head)
        if u.length < 1e-9 or l.length < 1e-9:
            joint_scores.append(0.0)
            continue
        interior = math.degrees(math.pi - u.angle(l))     # 180 = straight
        plausible = 1.0 if 20.0 <= interior <= 180.0 else 0.2
        if mid_key in plan.inferred:
            joint_scores.append(0.85 * plausible if options.joint_mode == "AUTO" else 0.7 * plausible)
        else:
            mid = positions.get(mid_key)
            on_mesh = 1.0
            if mid is not None and cd.kd is not None:
                on_mesh = 1.0 if cd.kd.find(mid)[2] <= 0.1 * H else 0.5
            joint_scores.append(plausible * on_mesh)
    joint_score = float(np.mean(joint_scores)) if joint_scores else (1.0 if positions else 0.0)
    res.scores.append(("Joint Detection", joint_score * 100,
                       f"{len(plan.inferred)} joint/point(s) inferred" if plan.inferred else "all joints placed"))

    # ------------------------------------------------------------- 5. symmetry
    mesh_sym = MA.symmetry_score(cd, options_axis(settings), cd.centre)
    guide_sym, notes = SY.guide_symmetry(positions, cd.centre, options_axis(settings), H)
    if mesh_sym >= 0.6:
        sym = 0.5 * guide_sym + 0.5 * mesh_sym
        res.warnings += notes[:3]
        sd = f"mesh {mesh_sym * 100:.0f}%, guides {guide_sym * 100:.0f}%"
    else:
        sym = max(0.7, mesh_sym)    # an asymmetrical character is fine; guides may differ
        sd = f"asymmetrical character (mesh {mesh_sym * 100:.0f}%)"
    res.scores.append(("Symmetry", sym * 100, sd))

    # ------------------------------------------------------------- 6. mesh compatibility (bone coverage)
    compat = 0.0
    if plan.bones and len(cd.samples):
        xp, label, _n = compute.get_xp(settings.compute_mode)
        res.backend = label
        a = np.array([tuple(plan.bones[n].head) for n in plan.order], dtype=np.float32)
        b = np.array([tuple(plan.bones[n].tail) for n in plan.order], dtype=np.float32)
        pts = cd.samples[:: max(1, len(cd.samples) // 6000)]
        D = compute.to_numpy(G.segment_distances(xp.asarray(pts), xp.asarray(a), xp.asarray(b), xp)).min(axis=1)
        covered = float((D <= 0.15 * H).mean())
        compat = covered
        if covered < 0.9:
            res.warnings.append(f"{(1 - covered) * 100:.0f}% of the mesh is far from any bone "
                                f"(missing chains such as arms, tail or wings?).")
    res.scores.append(("Mesh Compatibility", compat * 100, f"bone coverage ({res.backend})"))

    # ------------------------------------------------------------- overall
    weights = {"Mesh Analysis": 0.12, "Required Guides": 0.25, "Guide Quality": 0.2, "Joint Detection": 0.13,
               "Symmetry": 0.1, "Mesh Compatibility": 0.2}
    total = sum(weights[n] * v for n, v, _d in res.scores)
    # explicit penalties for concrete, fixable problems (each one is also listed as a warning)
    penalty = 6.0 * len(outside) + (5.0 if order_total and order_ok < order_total else 0.0) + 5.0 * close
    overall = total - penalty
    if res.errors:
        overall = min(overall, completeness * 70.0)
    res.overall = max(0.0, min(100.0, overall))
    res.summary = f"{len(plan.bones)} bones planned" if plan.bones else "nothing to build yet"
    return res


def options_axis(settings) -> str:
    return settings.mirror_axis


def _checklist(positions, chains) -> Dict[str, bool]:
    def has(*keys):
        return all(k in positions for k in keys)

    out = {"Head": has("head"), "Neck": has("neck"), "Spine": has("pelvis", "chest"), "Pelvis": has("pelvis")}
    for c in chains:
        if c.kind == "ARM":
            out[_label(c)] = has(f"{c.cid}.shoulder", f"{c.cid}.wrist")
        elif c.kind == "LEG":
            out[_label(c)] = has(f"{c.cid}.hip", f"{c.cid}.ankle")
        elif c.kind in C.GENERIC_KINDS:
            out[_label(c)] = sum(1 for k in c.point_keys if k in positions) >= 2
    return out


def _label(c) -> str:
    side = {"L": "Left ", "R": "Right "}.get(c.side, "")
    return f"{side}{c.name.replace('_', ' ').title()}"
