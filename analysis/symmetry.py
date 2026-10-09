"""Guide symmetry measurement."""
from __future__ import annotations

from typing import Dict, List, Tuple

from mathutils import Vector

from ..utils import naming
from ..utils.geometry import mirror_point


def guide_symmetry(positions: Dict[str, Vector], centre: Vector, axis: str, scale: float) -> Tuple[float, List[str]]:
    """Return (score 0..1, notes) comparing L guides against mirrored R guides.

    Error is normalised by `scale` (character height). 0 error = 1.0, error >= 8% of scale = 0.0.
    """
    errs: List[float] = []
    notes: List[str] = []
    for key, p in positions.items():
        if naming.key_side(key) != "L":
            continue
        other = positions.get(naming.mirror_key(key))
        if other is None:
            continue
        err = (mirror_point(p, axis, centre) - other).length / max(scale, 1e-6)
        errs.append(err)
        if err > 0.06:
            notes.append(f"{key} and {naming.mirror_key(key)} are not symmetric ({err * 100:.0f}% of height off).")
    if not errs:
        return 1.0, ["No left/right guide pairs to compare - treated as asymmetrical."]
    mean = sum(errs) / len(errs)
    return max(0.0, 1.0 - mean / 0.08), notes
