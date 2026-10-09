"""Viewport drawing of guides (GPU module, screen space so markers keep a constant size)."""
from __future__ import annotations

import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .. import constants as C
from .. import guides_model as GM
from ..utils import viewport as VP

# Shared with the guide editor modal operator.
STATE = {"hover": -1, "drag": -1, "mouse": None, "hint": "", "warn": ""}

_HANDLE = None
_ERRORED = False

COL_PLACED = (0.25, 0.85, 0.35, 1.0)
COL_SUGGESTED = (1.0, 0.6, 0.1, 1.0)
COL_ACTIVE = (1.0, 0.95, 0.2, 1.0)
COL_HOVER = (1.0, 1.0, 1.0, 1.0)
COL_LINE_L = (0.3, 0.6, 1.0, 0.9)
COL_LINE_R = (1.0, 0.35, 0.3, 0.9)
COL_LINE_C = (0.9, 0.9, 0.9, 0.9)
COL_WARN = (1.0, 0.2, 0.2, 1.0)


def _shader(name):
    try:
        return gpu.shader.from_builtin(name)
    except Exception:
        return None


def _lines(region, segments, color, width=2.0):
    if not segments:
        return
    poly = _shader("POLYLINE_UNIFORM_COLOR")
    pts = [(p[0], p[1], 0.0) for seg in segments for p in seg]
    if poly is not None:
        batch = batch_for_shader(poly, "LINES", {"pos": pts})
        poly.bind()
        poly.uniform_float("viewportSize", (region.width, region.height))
        poly.uniform_float("lineWidth", width)
        poly.uniform_float("color", color)
        batch.draw(poly)
    else:
        flat = _shader("UNIFORM_COLOR")
        batch = batch_for_shader(flat, "LINES", {"pos": pts})
        flat.bind()
        flat.uniform_float("color", color)
        batch.draw(flat)


def _circle(center, radius, color, filled=True, segments=20):
    flat = _shader("UNIFORM_COLOR")
    pts = [(center[0] + math.cos(2 * math.pi * i / segments) * radius,
            center[1] + math.sin(2 * math.pi * i / segments) * radius, 0.0) for i in range(segments)]
    kind = "TRI_FAN" if filled else "LINE_LOOP"
    if filled:
        pts = [(center[0], center[1], 0.0)] + pts + [pts[0]]
    batch = batch_for_shader(flat, kind, {"pos": pts})
    flat.bind()
    flat.uniform_float("color", color)
    batch.draw(flat)


def _text(x, y, text, color=(1, 1, 1, 1), size=13):
    font = 0
    try:
        blf.size(font, size)
    except TypeError:
        blf.size(font, size, 72)
    blf.position(font, x, y, 0)
    blf.color(font, *color)
    blf.draw(font, text)


def screen_positions(context, settings):
    """Map guide index -> (x, y) screen position for placed guides."""
    area, region, rv3d = VP.find_view3d(context)
    out = {}
    if region is None or rv3d is None:
        return out, region
    for i, g in enumerate(settings.guides):
        if g.placed:
            p = VP.world_to_screen(region, rv3d, Vector(g.location))
            if p is not None:
                out[i] = (p.x, p.y)
    return out, region


def draw_callback():
    global _ERRORED
    context = bpy.context
    scene = context.scene
    settings = getattr(scene, "sar", None)
    if settings is None or not settings.show_guides or len(settings.guides) == 0:
        return
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None or context.area is None or context.area.type != "VIEW_3D":
        return
    try:
        _draw(context, settings, region, rv3d)
        _ERRORED = False
    except Exception as exc:  # never break the viewport because of the overlay
        if not _ERRORED:
            print(f"[SmartAutoRig] guide overlay error: {exc}")
            _ERRORED = True
    finally:
        try:
            gpu.state.blend_set("NONE")
        except Exception:
            pass


def _draw(context, settings, region, rv3d):
    gpu.state.blend_set("ALPHA")
    size = 7.0 * settings.guide_size
    pos = {}
    for i, g in enumerate(settings.guides):
        if g.placed:
            p = VP.world_to_screen(region, rv3d, Vector(g.location))
            if p is not None:
                pos[i] = (p.x, p.y)

    # chain polylines with direction arrows
    for ch in settings.chains:
        gs = [(i, g) for i, g in enumerate(settings.guides) if g.chain == ch.cid]
        gs.sort(key=lambda t: t[1].index)
        col = {"L": COL_LINE_L, "R": COL_LINE_R}.get(ch.side, COL_LINE_C)
        segs, arrows = [], []
        prev = None
        for i, g in gs:
            if i in pos:
                if prev is not None:
                    a, b = prev, pos[i]
                    segs.append((a, b))
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    ln = math.hypot(dx, dy)
                    if ln > 30:
                        ux, uy = dx / ln, dy / ln
                        mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
                        arrows.append(((mx, my), (mx - ux * 9 - uy * 5, my - uy * 9 + ux * 5)))
                        arrows.append(((mx, my), (mx - ux * 9 + uy * 5, my - uy * 9 - ux * 5)))
                prev = pos[i]
            else:
                prev = None
        _lines(region, segs, col, 2.5)
        _lines(region, arrows, col, 2.0)

    # markers
    for i, (x, y) in pos.items():
        g = settings.guides[i]
        col = COL_SUGGESTED if g.suggested else COL_PLACED
        _circle((x, y), size + 2.0, (0, 0, 0, 0.7))
        _circle((x, y), size, col)
        if i == settings.active_guide:
            _circle((x, y), size + 5.0, COL_ACTIVE, filled=False, segments=28)
        if i == STATE["hover"] or i == STATE["drag"]:
            _circle((x, y), size + 8.0, COL_HOVER, filled=False, segments=28)
    for i, (x, y) in pos.items():
        g = settings.guides[i]
        if i == settings.active_guide or i == STATE["hover"] or settings.editor_running:
            _text(x + size + 8, y + 4, g.label, (1, 1, 1, 1), 12)

    # prompt for the active (unplaced) guide
    if settings.editor_running:
        lines = []
        if 0 <= settings.active_guide < len(settings.guides):
            g = settings.guides[settings.active_guide]
            lines.append(("Click on the character to place: " + g.label) if not g.placed
                         else f"Drag to move: {g.label}")
        if STATE.get("hint"):
            lines.append(STATE["hint"])
        if STATE.get("warn"):
            lines.append(STATE["warn"])
        y = region.height - 40
        for ln in lines:
            _text(20, y, ln, COL_WARN if ln == STATE.get("warn") else (1, 1, 1, 1), 15)
            y -= 22
        if STATE["mouse"] is not None and 0 <= settings.active_guide < len(settings.guides) \
                and not settings.guides[settings.active_guide].placed:
            mx, my = STATE["mouse"]
            _circle((mx, my), 9.0, COL_ACTIVE, filled=False, segments=24)


def register():
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(draw_callback, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, "WINDOW")
        _HANDLE = None
