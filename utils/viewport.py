"""3D viewport helpers: region lookup and mouse -> world projections."""
from __future__ import annotations

from typing import Optional, Tuple

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector


def find_view3d(context) -> Tuple[Optional[object], Optional[object], Optional[object]]:
    """Return (area, window_region, region_3d) of the first 3D viewport available."""
    areas = [context.area] if context.area and context.area.type == "VIEW_3D" else []
    if context.screen:
        areas += [a for a in context.screen.areas if a.type == "VIEW_3D" and a not in areas]
    for area in areas:
        for region in area.regions:
            if region.type == "WINDOW":
                space = area.spaces.active
                return area, region, space.region_3d
    return None, None, None


def world_to_screen(region, rv3d, co: Vector):
    if region is None or rv3d is None:
        return None
    return view3d_utils.location_3d_to_region_2d(region, rv3d, co)


def mouse_ray(region, rv3d, coord) -> Tuple[Vector, Vector]:
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    return origin, direction


def mouse_on_view_plane(region, rv3d, coord, depth_point: Vector) -> Vector:
    """Point under the mouse on the plane through depth_point that faces the viewer."""
    return view3d_utils.region_2d_to_location_3d(region, rv3d, coord, depth_point)


def tag_redraw_all(context=None) -> None:
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES"}:
                area.tag_redraw()
