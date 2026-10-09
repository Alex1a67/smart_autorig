"""Controller shape library (edge-only mesh objects used as bone custom shapes)."""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import bpy

from .. import constants as C

SHAPE_PREFIX = "WGT-SAR-"


def _circle(n: int = 32, plane: str = "XZ", radius: float = 1.0):
    pts, edges = [], []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        c, s = math.cos(a) * radius, math.sin(a) * radius
        if plane == "XZ":
            pts.append((c, 0.0, s))
        elif plane == "XY":
            pts.append((c, s, 0.0))
        else:
            pts.append((0.0, c, s))
        edges.append((i, (i + 1) % n))
    return pts, edges


def _merge(*parts):
    pts, edges = [], []
    for p, e in parts:
        off = len(pts)
        pts += p
        edges += [(a + off, b + off) for a, b in e]
    return pts, edges


def _box(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
    return v, e


def _shape_geometry(key: str):
    if key == "circle":          # ring around a bone (perpendicular to its Y axis)
        return _circle(32, "XZ")
    if key == "ring_flat":       # ring in the bone's XY plane (flat when Z is up)
        return _circle(48, "XY")
    if key == "cube":
        return _box(-1, 1, -1, 1, -1, 1)
    if key == "sphere":
        return _merge(_circle(24, "XZ"), _circle(24, "XY"), _circle(24, "YZ"))
    if key == "diamond":
        v = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        e = [(0, 2), (2, 1), (1, 3), (3, 0), (0, 4), (4, 1), (1, 5), (5, 0), (2, 4), (4, 3), (3, 5), (5, 2)]
        return v, e
    if key == "bone_box":        # elongated box along Y 0..1
        return _box(-0.12, 0.12, 0.0, 1.0, -0.12, 0.12)
    if key == "foot_box":        # flat long box along Y 0..1
        return _box(-0.28, 0.28, 0.0, 1.0, -0.05, 0.05)
    if key == "cross":
        v = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
        return v, [(0, 1), (2, 3), (4, 5)]
    if key == "arrow":           # flat arrow pointing +Y
        v = [(0, 1.0, 0), (-0.6, 0.3, 0), (-0.25, 0.3, 0), (-0.25, -0.8, 0),
             (0.25, -0.8, 0), (0.25, 0.3, 0), (0.6, 0.3, 0)]
        e = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 0)]
        return v, e
    if key == "root":            # ring + arrow heads, used for the master control
        ring = _circle(48, "XY", 1.0)
        arrows = []
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            ca, sa = math.cos(a), math.sin(a)

            def rot(p):
                return (p[0] * ca - p[1] * sa, p[0] * sa + p[1] * ca, 0.0)
            tri = [(-0.12, 1.0, 0), (0.12, 1.0, 0), (0.0, 1.28, 0)]
            arrows.append(([rot(p) for p in tri], [(0, 1), (1, 2), (2, 0)]))
        return _merge(ring, *arrows)
    raise KeyError(key)


def get_shape(key: str, collection: bpy.types.Collection) -> bpy.types.Object:
    """Return (creating if needed) the shape object for `key`, stored in `collection`."""
    name = f"{SHAPE_PREFIX}{key}"
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "MESH":
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        return obj
    pts, edges = _shape_geometry(key)
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, edges, [])
    me.update()
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    obj.display_type = "WIRE"
    obj.hide_render = True
    obj.hide_select = True
    obj.use_fake_user = False
    return obj


def hide_shapes(collection: bpy.types.Collection, context) -> None:
    for o in collection.objects:
        try:
            o.hide_set(True)
        except RuntimeError:
            pass
        o.hide_viewport = False  # must stay enabled for custom shape drawing


# colour palettes (Blender theme colour sets)
PALETTE = {"L": "THEME04", "R": "THEME01", "C": "THEME09", "": "THEME09", "MCH": "THEME14"}
