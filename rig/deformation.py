"""Binding and weight generation / smoothing / cleanup (operates on real vertex groups)."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import bpy
import numpy as np
from mathutils import Matrix, Vector

from .. import constants as C
from ..utils import compute
from ..utils import geometry as G
from ..utils import logging as log
from .skeleton import set_mode


HEAT_VERTEX_LIMIT = 150000


# ----------------------------------------------------------------------------- helpers
def deform_bone_names(rig) -> List[str]:
    return [b.name for b in rig.data.bones if b.use_deform]


def bound_meshes(rig, scene=None) -> list:
    scene = scene or bpy.context.scene
    return [o for o in scene.objects if o.type == "MESH" and o.get("sar_bound_to") == rig.name]


def _world_coords(obj, indices: Optional[np.ndarray] = None) -> np.ndarray:
    me = obj.data
    n = len(me.vertices)
    arr = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", arr)
    arr = arr.reshape(-1, 3)
    if indices is not None:
        arr = arr[indices]
    mw = np.array(obj.matrix_world, dtype=np.float32)
    return arr @ mw[:3, :3].T + mw[:3, 3]


def _bone_segments(rig, names: List[str]) -> Tuple[np.ndarray, np.ndarray]:
    mw = rig.matrix_world
    a = np.array([tuple(mw @ rig.data.bones[n].head_local) for n in names], dtype=np.float32)
    b = np.array([tuple(mw @ rig.data.bones[n].tail_local) for n in names], dtype=np.float32)
    return a, b


def clear_deform_groups(obj, names: Iterable[str]) -> None:
    for n in names:
        vg = obj.vertex_groups.get(n)
        if vg is not None:
            obj.vertex_groups.remove(vg)


def ensure_groups(obj, names: List[str]) -> Dict[str, int]:
    out = {}
    for n in names:
        vg = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
        out[n] = vg.index
    return out


def parent_to_rig(obj, rig) -> None:
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()


def ensure_armature_modifier(obj, rig):
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None)
    if mod is None:
        mod = obj.modifiers.new("Armature", "ARMATURE")
        try:
            obj.modifiers.move(len(obj.modifiers) - 1, 0)
        except Exception:
            pass
    mod.object = rig
    mod.use_vertex_groups = True
    return mod


# ----------------------------------------------------------------------------- distance weights
def distance_weights(points: np.ndarray, a: np.ndarray, b: np.ndarray, falloff: float, max_inf: int,
                     xp=np, eps: float = 1e-3, chunk: int = 30000) -> Tuple[np.ndarray, np.ndarray]:
    """Per point: indices and normalised weights of the `max_inf` closest bones.

    weight_i = ((d_min + eps) / (d_i + eps)) ** falloff, i.e. the nearest bone always scores 1 and
    farther bones fall off smoothly, which blends nicely across joints.
    """
    B = a.shape[0]
    k = max(1, min(max_inf, B))
    N = points.shape[0]
    out_idx = np.zeros((N, k), dtype=np.int32)
    out_w = np.zeros((N, k), dtype=np.float32)
    a_x, b_x = xp.asarray(a), xp.asarray(b)
    for s in range(0, N, chunk):
        e = min(N, s + chunk)
        P = xp.asarray(points[s:e])
        D = compute.to_numpy(G.segment_distances(P, a_x, b_x, xp)).astype(np.float32)
        dmin = D.min(axis=1, keepdims=True)
        ratio = (dmin + eps) / (D + eps)
        W = ratio ** falloff
        if k < B:
            part = np.argpartition(-W, k - 1, axis=1)[:, :k]
        else:
            part = np.tile(np.arange(B), (e - s, 1))
        wk = np.take_along_axis(W, part, axis=1)
        sums = wk.sum(axis=1, keepdims=True)
        wk = wk / np.maximum(sums, 1e-9)
        out_idx[s:e] = part
        out_w[s:e] = wk
    return out_idx, out_w


def write_sparse_weights(obj, names: List[str], vert_index: np.ndarray, idx: np.ndarray, w: np.ndarray,
                         replace: bool = True) -> None:
    """Write (N,k) bone indices/weights to the vertex groups of obj (weights quantised to 1/255)."""
    groups = ensure_groups(obj, names)
    q = np.rint(np.clip(w, 0.0, 1.0) * 255.0).astype(np.int32)
    for j, name in enumerate(names):
        vg = obj.vertex_groups[name]
        rows, cols = np.nonzero((idx == j) & (q > 0))
        if len(rows) == 0:
            continue
        verts = vert_index[rows]
        weights = q[rows, cols]
        for level in np.unique(weights):
            sel = verts[weights == level]
            vg.add(sel.tolist(), float(level) / 255.0, "REPLACE")


def apply_distance_bind(obj, rig, settings, only: Optional[np.ndarray] = None) -> int:
    names = deform_bone_names(rig)
    if not names:
        raise RuntimeError("The rig has no deform bones.")
    xp, label, note = compute.get_xp(settings.compute_mode)
    if note:
        log.warn(note)
    a, b = _bone_segments(rig, names)
    co = _world_coords(obj, only)
    diag = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) if len(co) else 1.0
    idx, w = distance_weights(co, a, b, settings.weight_falloff, settings.weight_max_influences, xp,
                              eps=max(diag * 0.002, 1e-5))
    vert_index = np.arange(len(obj.data.vertices)) if only is None else only
    write_sparse_weights(obj, names, vert_index, idx, w)
    log.debug(f"distance weights on '{obj.name}' via {label}: {len(vert_index)} vertices")
    return len(vert_index)


def apply_rigid_bind(obj, rig, settings) -> str:
    names = deform_bone_names(rig)
    a, b = _bone_segments(rig, names)
    co = _world_coords(obj)
    xp, _l, _n = compute.get_xp(settings.compute_mode)
    sums = np.zeros(len(names), dtype=np.float64)
    for s0 in range(0, len(co), 30000):
        D = compute.to_numpy(G.segment_distances(xp.asarray(co[s0:s0 + 30000]), xp.asarray(a), xp.asarray(b), xp))
        sums += D.sum(axis=0)
    # the bone that is closest to the object as a whole (lowest mean vertex distance) wins
    winner = int(sums.argmin())
    idx = np.full((len(co), 1), winner, dtype=np.int32)
    w = np.ones((len(co), 1), dtype=np.float32)
    write_sparse_weights(obj, names, np.arange(len(co)), idx, w)
    return names[winner]


# ----------------------------------------------------------------------------- bind entry point
def bind_object(context, obj, rig, settings, method: Optional[str] = None) -> str:
    """Bind one mesh object to the rig. Returns a description of what was done."""
    method = method or settings.weight_method
    if method == "AUTO" and len(obj.data.vertices) > HEAT_VERTEX_LIMIT:
        # Blender's bone heat solver needs a lot of time/memory on very dense meshes
        log.info(f"'{obj.name}' has {len(obj.data.vertices)} vertices: using smooth distance weights instead of bone heat")
        method = "DISTANCE"
    names = deform_bone_names(rig)
    clear_deform_groups(obj, names)
    for m in [m for m in obj.modifiers if m.type == "ARMATURE"]:
        obj.modifiers.remove(m)
    obj["sar_bound_to"] = rig.name

    if method == "RIGID":
        parent_to_rig(obj, rig)
        ensure_armature_modifier(obj, rig)
        bone = apply_rigid_bind(obj, rig, settings)
        return f"rigid -> {bone}"
    if method == "DISTANCE":
        parent_to_rig(obj, rig)
        ensure_armature_modifier(obj, rig)
        apply_distance_bind(obj, rig, settings)
        return "distance weights"

    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.view_layer.objects:
        if o.select_get():
            o.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    rig.select_set(True)
    context.view_layer.objects.active = rig
    kind = "ARMATURE_ENVELOPE" if method == "ENVELOPE" else "ARMATURE_AUTO"
    desc = "bone heat" if kind == "ARMATURE_AUTO" else "envelopes"
    try:
        bpy.ops.object.parent_set(type=kind, keep_transform=True)
    except RuntimeError as exc:
        log.warn(f"Blender automatic weights failed for '{obj.name}': {exc}")
        parent_to_rig(obj, rig)
        ensure_armature_modifier(obj, rig)
        apply_distance_bind(obj, rig, settings)
        return "distance weights (automatic weights failed)"
    obj["sar_bound_to"] = rig.name
    if obj.parent != rig:
        parent_to_rig(obj, rig)
    ensure_armature_modifier(obj, rig)

    # coverage check: vertices that received no weight at all
    me = obj.data
    n = len(me.vertices)
    step = 1 if n <= 200000 else 7
    empty = [v.index for v in me.vertices if v.index % step == 0 and not v.groups]
    if step > 1:
        empty = []
    if empty:
        apply_distance_bind(obj, rig, settings, only=np.array(empty, dtype=np.int64))
        return f"{desc} + distance fill for {len(empty)} uncovered vertices"
    return desc


# ----------------------------------------------------------------------------- read / write dense
def read_weights(obj, names: List[str]) -> np.ndarray:
    gi = {}
    for j, n in enumerate(names):
        vg = obj.vertex_groups.get(n)
        if vg is not None:
            gi[vg.index] = j
    V = len(obj.data.vertices)
    W = np.zeros((V, len(names)), dtype=np.float32)
    for v in obj.data.vertices:
        for g in v.groups:
            j = gi.get(g.group)
            if j is not None:
                W[v.index, j] = g.weight
    return W


def write_dense_weights(obj, names: List[str], W: np.ndarray) -> None:
    V = W.shape[0]
    all_idx = list(range(V))
    groups = ensure_groups(obj, names)
    for j, n in enumerate(names):
        vg = obj.vertex_groups[n]
        vg.remove(all_idx)
    q = np.rint(np.clip(W, 0.0, 1.0) * 255.0).astype(np.int32)
    for j, n in enumerate(names):
        col = q[:, j]
        nz = np.nonzero(col > 0)[0]
        if len(nz) == 0:
            continue
        vg = obj.vertex_groups[n]
        vals = col[nz]
        for level in np.unique(vals):
            vg.add(nz[vals == level].tolist(), float(level) / 255.0, "REPLACE")


def normalize(W: np.ndarray) -> np.ndarray:
    s = W.sum(axis=1, keepdims=True)
    return np.where(s > 1e-9, W / np.maximum(s, 1e-9), W)


def smooth_weights(obj, rig, iterations: int, factor: float) -> int:
    names = deform_bone_names(rig)
    W = read_weights(obj, names)
    if W.size == 0 or iterations <= 0:
        return 0
    me = obj.data
    E = len(me.edges)
    if E == 0:
        return 0
    ev = np.empty(E * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    a, b = ev[0::2], ev[1::2]
    V = W.shape[0]
    cnt = np.bincount(a, minlength=V) + np.bincount(b, minlength=V)
    has = cnt > 0
    for _ in range(iterations):
        S = np.zeros_like(W)
        for j in range(W.shape[1]):
            col = W[:, j]
            S[:, j] = np.bincount(a, weights=col[b], minlength=V) + np.bincount(b, weights=col[a], minlength=V)
        avg = S / np.maximum(cnt, 1)[:, None]
        W = np.where(has[:, None], (1.0 - factor) * W + factor * avg, W)
    W = normalize(W)
    write_dense_weights(obj, names, W)
    return V


def clean_weights(obj, rig, threshold: float, max_inf: int) -> Tuple[int, int]:
    """Remove tiny weights, cap influences per vertex and normalise. Returns (vertices, changed)."""
    names = deform_bone_names(rig)
    W = read_weights(obj, names)
    if W.size == 0:
        return 0, 0
    orig = W.copy()
    W[W < threshold] = 0.0
    k = max(1, min(max_inf, W.shape[1]))
    if k < W.shape[1]:
        part = np.argpartition(-W, k - 1, axis=1)[:, :k]
        mask = np.zeros_like(W, dtype=bool)
        np.put_along_axis(mask, part, True, axis=1)
        W = np.where(mask, W, 0.0)
    dead = W.sum(axis=1) < 1e-9
    if dead.any():
        arg = orig[dead].argmax(axis=1)
        rows = np.nonzero(dead)[0]
        has_any = orig[dead].sum(axis=1) > 0
        W[rows[has_any], arg[has_any]] = 1.0
    W = normalize(W)
    changed = int((np.abs(W - orig).sum(axis=1) > 1e-4).sum())
    write_dense_weights(obj, names, W)
    return W.shape[0], changed


def weight_report(obj, rig) -> dict:
    """Stats used by validation: unweighted vertices and number of used groups."""
    names = deform_bone_names(rig)
    W = read_weights(obj, names)
    if W.size == 0:
        return {"vertices": 0, "unweighted": 0, "groups_used": 0, "bad_sum": 0}
    sums = W.sum(axis=1)
    return {"vertices": W.shape[0], "unweighted": int((sums < 1e-6).sum()),
            "groups_used": int((W.max(axis=0) > 0).sum()), "bad_sum": int((np.abs(sums - 1.0) > 0.02).sum())}


def unbind_object(obj, rig) -> None:
    names = deform_bone_names(rig)
    clear_deform_groups(obj, names)
    for m in [m for m in obj.modifiers if m.type == "ARMATURE"]:
        obj.modifiers.remove(m)
    if "sar_bound_to" in obj:
        del obj["sar_bound_to"]
