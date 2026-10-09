"""Geometry helpers: world-space sampling, KD-tree access, ray casting, segment maths."""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

EPS = 1e-6


# --------------------------------------------------------------------------- segments
def closest_point_on_segment(p: Vector, a: Vector, b: Vector) -> Tuple[Vector, float]:
    """Closest point to p on segment a-b and its parameter t in [0, 1]."""
    ab = b - a
    denom = ab.length_squared
    if denom < EPS * EPS:
        return a.copy(), 0.0
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return a + ab * t, t


def closest_point_on_polyline(p: Vector, points: Sequence[Vector]) -> Tuple[Vector, int, float]:
    """Closest point on a polyline. Returns (point, segment_index, t)."""
    best = (None, 0, 0.0)
    best_d = float("inf")
    for i in range(len(points) - 1):
        q, t = closest_point_on_segment(p, points[i], points[i + 1])
        d = (q - p).length_squared
        if d < best_d:
            best_d = d
            best = (q, i, t)
    if best[0] is None and points:
        return points[0].copy(), 0, 0.0
    return best


def segment_distances(points: np.ndarray, a: np.ndarray, b: np.ndarray, xp=np):
    """Distances from N points (N,3) to B segments given as arrays a,b (B,3). Returns (N,B)."""
    ab = b - a  # (B,3)
    denom = xp.maximum((ab * ab).sum(axis=1), 1e-12)  # (B,)
    # (N,B,3) would be big; use the expanded form instead.
    # t = ((p-a).ab)/|ab|^2 = (p.ab - a.ab)/|ab|^2
    pa = points @ ab.T - (a * ab).sum(axis=1)[None, :]
    t = xp.clip(pa / denom[None, :], 0.0, 1.0)  # (N,B)
    # closest = a + t*ab ; dist^2 = |p|^2 - 2 p.c + |c|^2
    # compute per component to avoid (N,B,3)
    d2 = xp.zeros_like(t)
    for k in range(3):
        c = a[None, :, k] + t * ab[None, :, k]
        diff = points[:, k:k + 1] - c
        d2 += diff * diff
    return xp.sqrt(d2)


def lerp(a: Vector, b: Vector, t: float) -> Vector:
    return a + (b - a) * t


def safe_normalized(v: Vector, fallback: Vector) -> Vector:
    if v.length < EPS:
        return fallback.normalized()
    return v.normalized()


def project_to_plane(v: Vector, normal: Vector) -> Vector:
    n = normal.normalized()
    return v - n * v.dot(n)


def mirror_point(p: Vector, axis: str, center: Vector) -> Vector:
    q = p.copy()
    i = {"X": 0, "Y": 1, "Z": 2}[axis]
    q[i] = 2.0 * center[i] - p[i]
    return q


def angle_between(a: Vector, b: Vector) -> float:
    if a.length < EPS or b.length < EPS:
        return 0.0
    return a.angle(b, 0.0)


# --------------------------------------------------------------------------- sampling
def world_vertices(obj, max_points: int = 20000, seed: int = 7) -> np.ndarray:
    """World-space vertex positions of a mesh object, stride-sampled to max_points."""
    me = obj.data
    n = len(me.vertices)
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32)
    arr = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", arr)
    arr = arr.reshape(-1, 3)
    if n > max_points:
        rng = np.random.default_rng(seed)
        idx = rng.choice(n, size=max_points, replace=False)
        arr = arr[idx]
    mw = np.array(obj.matrix_world, dtype=np.float32)
    return arr @ mw[:3, :3].T + mw[:3, 3]


def sample_objects(objects: Iterable, max_points: int = 20000) -> np.ndarray:
    objs = [o for o in objects if o is not None and o.type == "MESH"]
    if not objs:
        return np.zeros((0, 3), dtype=np.float32)
    total = sum(len(o.data.vertices) for o in objs)
    chunks = []
    for o in objs:
        share = max(8, int(max_points * (len(o.data.vertices) / max(total, 1))))
        chunks.append(world_vertices(o, max_points=share))
    return np.vstack(chunks)


def bounds_of(points: np.ndarray) -> Tuple[Vector, Vector]:
    if len(points) == 0:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    lo = points.min(axis=0)
    hi = points.max(axis=0)
    return Vector(lo.tolist()), Vector(hi.tolist())


def object_bounds(objects: Iterable) -> Tuple[Vector, Vector]:
    """Exact world bounding box from object bound_box corners (cheap, no vertex scan)."""
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    any_obj = False
    for o in objects:
        if o is None or o.type != "MESH":
            continue
        any_obj = True
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if not any_obj:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return lo, hi


def build_kdtree(points: np.ndarray) -> KDTree:
    kd = KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert((float(p[0]), float(p[1]), float(p[2])), i)
    kd.balance()
    return kd


# --------------------------------------------------------------------------- ray casting
def raycast_objects(objects, origin: Vector, direction: Vector, depsgraph=None):
    """Cast a world-space ray against a list of mesh objects.

    Returns (hit, location, normal, obj) for the nearest hit.
    """
    best = (False, None, None, None)
    best_d = float("inf")
    direction = direction.normalized()
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        inv = obj.matrix_world.inverted_safe()
        o_local = inv @ origin
        d_local = (inv.to_3x3() @ direction)
        if d_local.length < EPS:
            continue
        d_local.normalize()
        try:
            hit, loc, nor, _idx = obj.ray_cast(o_local, d_local, depsgraph=depsgraph)
        except TypeError:
            hit, loc, nor, _idx = obj.ray_cast(o_local, d_local)
        if not hit:
            continue
        loc_w = obj.matrix_world @ loc
        dist = (loc_w - origin).length
        if dist < best_d:
            best_d = dist
            nor_w = (obj.matrix_world.inverted_safe().transposed().to_3x3() @ nor).normalized()
            best = (True, loc_w, nor_w, obj)
    return best


def volume_centre_along_ray(objects, origin: Vector, direction: Vector, depsgraph=None,
                            max_thickness: float = float("inf")):
    """Cast a ray, then continue through the surface to find the exit point.

    Joints live inside the body, so the centre of the volume along the view ray is a much
    better guide position than the front surface. Returns (point, surface_hit, normal, obj)
    or None if nothing was hit.
    """
    hit, loc, nor, obj = raycast_objects(objects, origin, direction, depsgraph)
    if not hit:
        return None
    direction = direction.normalized()
    # Look for the exit of the same volume: step slightly inside and cast again against all objects.
    eps = 1e-4 * max(1.0, loc.length)
    start = loc + direction * eps
    hit2, loc2, _nor2, _obj2 = raycast_objects(objects, start, direction, depsgraph)
    if hit2:
        thickness = (loc2 - loc).length
        if thickness <= max_thickness:
            return (loc + loc2) * 0.5, loc, nor, obj
    return loc.copy(), loc, nor, obj


def nearest_surface_distance(objects, point: Vector, depsgraph=None, search: float = 1e9) -> float:
    """Distance from point to the nearest surface among objects (0 if no mesh)."""
    best = float("inf")
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        inv = obj.matrix_world.inverted_safe()
        try:
            ok, loc, _n, _i = obj.closest_point_on_mesh(inv @ point, distance=search)
        except Exception:
            continue
        if ok:
            best = min(best, (obj.matrix_world @ loc - point).length)
    return 0.0 if best == float("inf") else best
