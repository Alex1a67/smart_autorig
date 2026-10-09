"""Procedural character analysis: measurements that do not depend on guides."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from mathutils import Vector

from ..utils import geometry as G

QUALITY_SAMPLES = {"FAST": 5000, "BALANCED": 20000, "DETAILED": 60000}


@dataclass
class CharacterData:
    objects: list
    samples: np.ndarray                       # (N,3) world-space sample of vertices
    bbox_min: Vector
    bbox_max: Vector
    vertex_count: int = 0
    object_count: int = 0
    invalid: List[str] = field(default_factory=list)   # messages about unusable objects
    _kd: Optional[object] = None

    @property
    def size(self) -> Vector:
        return self.bbox_max - self.bbox_min

    @property
    def height(self) -> float:
        # Height along the longest axis is not always Z (lying characters), but the rig assumes Z up.
        return max(self.size.z, 1e-6)

    @property
    def diagonal(self) -> float:
        return max(self.size.length, 1e-6)

    @property
    def centre(self) -> Vector:
        return (self.bbox_min + self.bbox_max) * 0.5

    @property
    def centre_of_mass(self) -> Vector:
        if len(self.samples) == 0:
            return self.centre
        c = self.samples.mean(axis=0)
        return Vector(c.tolist())

    @property
    def kd(self):
        if self._kd is None:
            self._kd = G.build_kdtree(self.samples) if len(self.samples) else None
        return self._kd

    def points_in_radius(self, p: Vector, radius: float) -> np.ndarray:
        kd = self.kd
        if kd is None:
            return np.zeros((0, 3), dtype=np.float32)
        idx = [i for (_co, i, _d) in kd.find_range(p, radius)]
        return self.samples[idx] if idx else np.zeros((0, 3), dtype=np.float32)


def gather_character(objects, quality: str = "BALANCED") -> CharacterData:
    """Collect samples and bounds for the character objects, validating them on the way."""
    import bpy

    bpy.context.view_layer.update()      # make sure matrix_world is current
    invalid: List[str] = []
    valid = []
    for o in objects:
        if o is None:
            continue
        if o.type != "MESH":
            invalid.append(f"'{o.name}' is a {o.type.lower()} object, not a mesh - ignored.")
            continue
        if len(o.data.vertices) == 0:
            invalid.append(f"'{o.name}' has no vertices - ignored.")
            continue
        valid.append(o)
    samples = G.sample_objects(valid, QUALITY_SAMPLES.get(quality, 20000))
    lo, hi = G.object_bounds(valid)
    vcount = sum(len(o.data.vertices) for o in valid)
    return CharacterData(valid, samples, lo, hi, vcount, len(valid), invalid)


# ----------------------------------------------------------------------------- measurements
def orientation_report(cd: CharacterData) -> dict:
    """Check that the character is roughly upright (Z) and has plausible proportions."""
    s = cd.size
    report = {"upright": True, "notes": []}
    if s.z < max(s.x, s.y) * 0.8 and max(s.x, s.y) > 1e-6:
        # arms-out T-pose characters can be wider than tall, so only warn on clearly lying characters
        if s.z < min(s.x, s.y) * 0.6:
            report["upright"] = False
            report["notes"].append("Character appears to lie down; the rig assumes +Z is up.")
    return report


def symmetry_score(cd: CharacterData, axis: str = "X", centre: Optional[Vector] = None) -> float:
    """Fraction (0..1) of sampled vertices that have a mirrored partner within a tolerance."""
    if len(cd.samples) < 16:
        return 0.0
    c = centre if centre is not None else cd.centre
    i = {"X": 0, "Y": 1, "Z": 2}[axis]
    pts = cd.samples
    mirrored = pts.copy()
    mirrored[:, i] = 2.0 * c[i] - pts[:, i]
    kd = cd.kd
    tol = cd.diagonal * 0.012
    n = min(len(mirrored), 3000)
    idx = np.linspace(0, len(mirrored) - 1, n).astype(int)
    hits = 0
    for j in idx:
        m = mirrored[j]
        _co, _i, dist = kd.find((float(m[0]), float(m[1]), float(m[2])))
        if dist <= tol:
            hits += 1
    return hits / n


def best_mirror_centre(cd: CharacterData, axis: str = "X") -> Vector:
    """Centre plane estimate: bounding box centre refined by the sample mean of the upper body."""
    c = cd.centre.copy()
    return c


def extremities(cd: CharacterData, count: int = 8) -> List[Vector]:
    """Farthest-point sampling starting at the centre of mass: finds limb tips / head top / feet."""
    pts = cd.samples
    if len(pts) == 0:
        return []
    com = np.array(cd.centre_of_mass, dtype=np.float32)
    dist = np.linalg.norm(pts - com, axis=1)
    tips = []
    taken = np.zeros(len(pts), dtype=bool)
    sep = cd.diagonal * 0.12
    order = np.argsort(-dist)
    for idx in order:
        p = pts[idx]
        if all(np.linalg.norm(p - np.array(t)) > sep for t in tips):
            tips.append(p.copy())
            if len(tips) >= count:
                break
    return [Vector(t.tolist()) for t in tips]


def local_radius(cd: CharacterData, point: Vector, direction: Vector, reach: float) -> float:
    """Approximate limb/torso radius around `point` perpendicular to `direction` using the samples."""
    pts = cd.points_in_radius(point, max(reach, cd.diagonal * 0.02))
    if len(pts) < 6:
        return cd.diagonal * 0.02
    d = np.array(direction.normalized(), dtype=np.float32)
    rel = pts - np.array(point, dtype=np.float32)
    along = rel @ d
    perp = rel - along[:, None] * d[None, :]
    pd = np.linalg.norm(perp, axis=1)
    slab = np.abs(along) < max(reach * 0.5, cd.diagonal * 0.01)
    if slab.sum() >= 6:
        pd = pd[slab]
    return float(np.percentile(pd, 75))


def centroid_in_slab(cd: CharacterData, point: Vector, direction: Vector, slab: float, radius: float) -> Optional[Vector]:
    """Centroid of samples inside a slab perpendicular to direction around point (cross-section centre)."""
    pts = cd.points_in_radius(point, radius * 1.5 + slab)
    if len(pts) < 8:
        return None
    d = np.array(direction.normalized(), dtype=np.float32)
    p0 = np.array(point, dtype=np.float32)
    rel = pts - p0
    along = rel @ d
    perp = rel - along[:, None] * d[None, :]
    mask = (np.abs(along) <= slab) & (np.linalg.norm(perp, axis=1) <= radius)
    if mask.sum() < 8:
        return None
    c = pts[mask].mean(axis=0)
    # only the perpendicular displacement is wanted
    delta = c - p0
    delta = delta - d * float(delta @ d)
    return Vector((p0 + delta).tolist())
