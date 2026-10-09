"""Guide / chain data model helpers (operate on `scene.sar`)."""
from __future__ import annotations

from typing import Dict, List, Optional

from mathutils import Vector

from . import constants as C
from .utils import naming


# ----------------------------------------------------------------------------- lookups
def get_chain(settings, cid: str):
    for ch in settings.chains:
        if ch.cid == cid:
            return ch
    return None


def get_guide(settings, key: str):
    for g in settings.guides:
        if g.key == key:
            return g
    return None


def guide_index(settings, key: str) -> int:
    for i, g in enumerate(settings.guides):
        if g.key == key:
            return i
    return -1


def chain_guides(settings, cid: str) -> list:
    gs = [g for g in settings.guides if g.chain == cid]
    gs.sort(key=lambda g: g.index)
    return gs


def placed_positions(settings) -> Dict[str, Vector]:
    return {g.key: Vector(g.location) for g in settings.guides if g.placed}


def chains_of_kind(settings, kind: str) -> list:
    return [c for c in settings.chains if c.kind == kind]


# ----------------------------------------------------------------------------- creation
def _add_guide(settings, key, label, chain, index, required=False):
    if get_guide(settings, key):
        return get_guide(settings, key)
    g = settings.guides.add()
    g.key = key
    g.label = label
    g.chain = chain
    g.index = index
    g.required = required
    g.placed = False
    return g


def chain_number(name: str) -> str:
    """'arm2' -> '2', 'arm' -> ''"""
    digits = ""
    for ch in reversed(name):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    return digits


def _side_label(side: str) -> str:
    return {"L": "Left ", "R": "Right "}.get(side, "")


def make_cid(name: str, side: str) -> str:
    return f"{name}.{side}" if side in {"L", "R"} else name


def unique_chain_name(settings, base: str, side: str) -> str:
    """Return base, base2, base3... so that the chain id is unused."""
    if not get_chain(settings, make_cid(base, side)):
        return base
    n = 2
    while get_chain(settings, make_cid(f"{base}{n}", side)):
        n += 1
    return f"{base}{n}"


def add_chain(settings, kind: str, side: str = "C", name: Optional[str] = None, points: Optional[int] = None,
              parent_chain: str = ""):
    """Create a chain and its (unplaced) guides. Returns the new chain."""
    kind = kind.upper()
    if kind == "SPINE":
        side = "C"
        name = "spine"
    elif kind in {"ARM", "LEG"}:
        name = unique_chain_name(settings, name or kind.lower(), side)
    else:
        base = naming.sanitize(name or kind.lower(), kind.lower())
        name = unique_chain_name(settings, base, side)
    cid = make_cid(name, side)
    if get_chain(settings, cid):
        return get_chain(settings, cid)

    ch = settings.chains.add()
    ch.cid = cid
    ch.kind = kind
    ch.side = side
    ch.name = name
    ch.parent_chain = parent_chain
    pretty = {"SPINE": "Spine", "ARM": "Arm", "LEG": "Leg"}.get(kind, name.replace("_", " ").title())
    num = chain_number(name)
    ch.label = f"{_side_label(side)}{pretty}{(' ' + num) if num and kind in {'ARM', 'LEG'} else ''}".strip()

    if kind == "SPINE":
        ch.point_count = len(C.SPINE_KEYS)
        for i, k in enumerate(C.SPINE_KEYS):
            _add_guide(settings, k, C.SPINE_LABELS[k], cid, i, required=k in C.SPINE_REQUIRED)
    elif kind == "ARM":
        ch.point_count = len(C.ARM_PARTS)
        for i, part in enumerate(C.ARM_PARTS):
            _add_guide(settings, f"{cid}.{part}", f"{ch.label} {C.ARM_LABELS[part]}", cid, i,
                       required=part in C.ARM_REQUIRED)
    elif kind == "LEG":
        ch.point_count = len(C.LEG_PARTS)
        for i, part in enumerate(C.LEG_PARTS):
            _add_guide(settings, f"{cid}.{part}", f"{ch.label} {C.LEG_LABELS[part]}", cid, i,
                       required=part in C.LEG_REQUIRED)
    else:
        n = points or (4 if kind == "FINGER" else 4)
        ch.point_count = n
        for i in range(n):
            _add_guide(settings, f"{cid}.p{i:02d}", f"{ch.label} {i + 1}", cid, i, required=False)
    return ch


def ensure_core_guides(settings) -> None:
    """Create the default humanoid chains if they do not exist."""
    if not get_chain(settings, "spine"):
        add_chain(settings, "SPINE")
    for side in ("L", "R"):
        if not get_chain(settings, f"arm.{side}"):
            add_chain(settings, "ARM", side)
        if not get_chain(settings, f"leg.{side}"):
            add_chain(settings, "LEG", side)


def add_fingers(settings, side: str, arm_cid: str) -> list:
    """Add five finger chains (4 points each) attached to the hand of arm_cid. Returns the chain ids.

    NOTE: never keep references to collection items across `.add()` calls - Blender may reallocate the
    collection and invalidate them. Always re-fetch with get_chain(cid).
    """
    num = chain_number(get_chain(settings, arm_cid).name) if get_chain(settings, arm_cid) else ""
    created = []
    for f in C.FINGER_NAMES:
        base = f"{f}{num}"
        cid = make_cid(base, side)
        if get_chain(settings, cid):
            continue
        add_chain(settings, "FINGER", side, base, 3 if f == "thumb" else 4, parent_chain=arm_cid)
        get_chain(settings, cid).name = base
        created.append(cid)
    return created


def remove_chain(settings, cid: str) -> None:
    for i in reversed(range(len(settings.guides))):
        if settings.guides[i].chain == cid:
            settings.guides.remove(i)
    for i, ch in enumerate(settings.chains):
        if ch.cid == cid:
            settings.chains.remove(i)
            break
    # detach children
    for ch in settings.chains:
        if ch.parent_chain == cid:
            ch.parent_chain = ""
    settings.active_guide = min(settings.active_guide, max(0, len(settings.guides) - 1))


def reset_guides(settings, keep_chains: bool = True) -> None:
    if keep_chains:
        for g in settings.guides:
            g.placed = False
            g.suggested = False
    else:
        settings.guides.clear()
        settings.chains.clear()
        ensure_core_guides(settings)
    settings.guided_step = 0
    settings.guided_finished = False
    settings.analysis_done = False


def set_guide(settings, key: str, location: Vector, suggested: bool = False):
    g = get_guide(settings, key)
    if g is None:
        return None
    g.location = location
    g.placed = True
    g.suggested = suggested
    return g


# ----------------------------------------------------------------------------- mirror
def mirror_centre(settings, character_bounds=None) -> Vector:
    if settings.mirror_auto_center and character_bounds is not None:
        lo, hi = character_bounds
        return (lo + hi) * 0.5
    return Vector(settings.mirror_center)


def duplicate_chain_mirrored(settings, cid: str, centre: Vector, axis: str):
    """Create the opposite-side copy of a sided chain, with mirrored guide positions."""
    from .utils.geometry import mirror_point

    src = get_chain(settings, cid)
    if src is None or src.side not in {"L", "R"}:
        return None
    # copy what we need: `src` may be invalidated when a chain is added below
    kind, side, base, count, parent = src.kind, src.side, src.name, src.point_count, src.parent_chain
    new_side = naming.opposite_side(side)
    new_cid = make_cid(base, new_side)
    if get_chain(settings, new_cid) is None:
        add_chain(settings, kind, new_side, base, count, parent_chain=naming.mirror_cid(parent))
        new_cid = make_cid(unique_name_used(settings, base, new_side), new_side) if get_chain(settings, new_cid) is None else new_cid
    dst_cid = new_cid
    for g in chain_guides(settings, cid):
        if not g.placed:
            continue
        key = g.key.replace(cid, dst_cid, 1)
        tgt = get_guide(settings, key)
        if tgt is None:
            continue
        tgt.location = mirror_point(Vector(g.location), axis, centre)
        tgt.placed = True
        tgt.suggested = g.suggested
    return get_chain(settings, dst_cid)


def unique_name_used(settings, base: str, side: str) -> str:
    """Name of the most recently added chain with this base and side (fallback: base)."""
    for ch in reversed(list(settings.chains)):
        if ch.side == side and ch.name.rstrip("0123456789") == base.rstrip("0123456789"):
            return ch.name
    return base


def mirror_guide(settings, key: str, centre: Vector, axis: str) -> bool:
    from .utils.geometry import mirror_point

    g = get_guide(settings, key)
    if g is None or not g.placed:
        return False
    other = get_guide(settings, naming.mirror_key(key))
    if other is None or other.key == key:
        return False
    other.location = mirror_point(Vector(g.location), axis, centre)
    other.placed = True
    other.suggested = g.suggested
    return True


def mirror_all_sides(settings, centre: Vector, axis: str, source_side: str = "L") -> int:
    """Mirror every placed guide from source_side to the opposite side. Returns count."""
    count = 0
    for g in list(settings.guides):
        if naming.key_side(g.key) == source_side and g.placed:
            if mirror_guide(settings, g.key, centre, axis):
                count += 1
    return count


def guided_next_key(settings) -> Optional[str]:
    """Next unplaced key in the guided order (or None when finished)."""
    for i, (key, _text) in enumerate(C.GUIDED_STEPS):
        g = get_guide(settings, key)
        if g is not None and not g.placed:
            settings.guided_step = i
            return key
    settings.guided_step = len(C.GUIDED_STEPS)
    return None


def guide_status(settings) -> Dict[str, bool]:
    """Quick completion map used by the UI checklist."""
    def done(keys):
        gs = [get_guide(settings, k) for k in keys]
        return all(g is not None and g.placed for g in gs)

    out = {
        "Head": done(["head"]),
        "Neck": done(["neck"]),
        "Spine": done(["pelvis", "chest"]),
        "Pelvis": done(["pelvis"]),
    }
    for side, nm in (("L", "Left"), ("R", "Right")):
        out[f"{nm} Arm"] = done([f"arm.{side}.shoulder", f"arm.{side}.wrist"])
        out[f"{nm} Leg"] = done([f"leg.{side}.hip", f"leg.{side}.ankle"])
    return out
