"""Heuristic humanoid landmark suggestion (procedural; no ML involved)."""
from __future__ import annotations

from typing import Dict

import numpy as np
from mathutils import Vector

from . import mesh_analysis as MA


def suggest_humanoid_guides(cd, centre_x: float = None) -> Dict[str, Vector]:
    """Estimate the main humanoid guides from proportions and extremities.

    Results are only starting points (the UI marks them 'suggested' in orange) - the user is expected to
    confirm or drag them. Assumes +Z up and the left side on +X.
    """
    pts = cd.samples
    if len(pts) < 20:
        return {}
    lo, hi = cd.bbox_min, cd.bbox_max
    H = max(hi.z - lo.z, 1e-6)
    cx = centre_x if centre_x is not None else (lo.x + hi.x) * 0.5
    # y centre from the torso band (more stable than the whole bbox for tails / flowing capes)
    band = pts[(pts[:, 2] > lo.z + 0.5 * H) & (pts[:, 2] < lo.z + 0.8 * H) & (np.abs(pts[:, 0] - cx) < 0.2 * H)]
    cy = float(band[:, 1].mean()) if len(band) > 5 else (lo.y + hi.y) * 0.5

    def z(f):  # fraction of height -> world z
        return lo.z + f * H

    out: Dict[str, Vector] = {
        "head_top": Vector((cx, cy, hi.z)),
        "head": Vector((cx, cy, z(0.86))),
        "neck": Vector((cx, cy, z(0.82))),
        "chest": Vector((cx, cy, z(0.72))),
        "pelvis": Vector((cx, cy, z(0.53))),
    }
    # refine the vertical-axis points with the cross-section centre
    for key in ("head", "neck", "chest", "pelvis"):
        c = MA.centroid_in_slab(cd, out[key], Vector((0, 0, 1)), slab=0.03 * H, radius=0.12 * H)
        if c is not None:
            out[key] = Vector((cx, c.y, out[key].z))

    # hands: extreme samples in +/-X within the arm height band
    arm_band = pts[(pts[:, 2] > z(0.35)) & (pts[:, 2] < z(0.95))]
    shoulder_z = z(0.82)
    for side, sign in (("L", 1.0), ("R", -1.0)):
        if len(arm_band):
            xs = (arm_band[:, 0] - cx) * sign
            k = max(3, int(len(xs) * 0.01))
            idx = np.argsort(-xs)[:k]
            tip = arm_band[idx].mean(axis=0)
        else:
            tip = np.array([cx + sign * 0.4 * H, cy, shoulder_z])
        shoulder = Vector((cx + sign * 0.115 * H, cy, shoulder_z))
        tipv = Vector(tip.tolist())
        d = (tipv - shoulder)
        if d.length > 0.2 * H:
            wrist = tipv - d.normalized() * 0.07 * H
            out[f"arm.{side}.shoulder"] = shoulder
            out[f"arm.{side}.wrist"] = wrist
            out[f"arm.{side}.hand_tip"] = tipv
        # legs
        foot = pts[(pts[:, 2] < z(0.1)) & ((pts[:, 0] - cx) * sign > 0.02 * H)]
        if len(foot) > 3:
            fc = foot.mean(axis=0)
            hipx = cx + sign * 0.055 * H
            out[f"leg.{side}.hip"] = Vector((hipx, cy, z(0.52)))
            out[f"leg.{side}.ankle"] = Vector((float(fc[0]), float(cy), z(0.04) if lo.z + 0.04 * H > lo.z else lo.z))
    return out
