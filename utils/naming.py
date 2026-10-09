"""Bone / object naming helpers."""
import re

from ..constants import PREFIX_CTRL, PREFIX_DEF, PREFIX_MCH, PREFIX_ORG


def sanitize(name: str, fallback: str = "chain") -> str:
    """Make a user supplied string safe for use inside a bone name."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip()).strip("_").lower()
    return name or fallback


def side_suffix(side: str) -> str:
    return {"L": ".L", "R": ".R"}.get(side, "")


def opposite_side(side: str) -> str:
    return {"L": "R", "R": "L"}.get(side, side)


def deform(base: str) -> str:
    return PREFIX_DEF + base


def control(base: str) -> str:
    return PREFIX_CTRL + base


def mechanism(base: str) -> str:
    return PREFIX_MCH + base


def organic(base: str) -> str:
    return PREFIX_ORG + base


def with_side(part: str, side: str) -> str:
    return part + side_suffix(side)


def mirror_key(key: str) -> str:
    """Return the guide key of the opposite side ("arm.L.elbow" -> "arm.R.elbow")."""
    if ".L." in key:
        return key.replace(".L.", ".R.", 1)
    if ".R." in key:
        return key.replace(".R.", ".L.", 1)
    return key


def key_side(key: str) -> str:
    if ".L." in key:
        return "L"
    if ".R." in key:
        return "R"
    return ""


def unique_name(base: str, existing) -> str:
    if base not in existing:
        return base
    i = 1
    while f"{base}.{i:03d}" in existing:
        i += 1
    return f"{base}.{i:03d}"


def mirror_cid(cid: str) -> str:
    """Chain id of the opposite side ("arm.L" -> "arm.R"); unchanged for centre chains."""
    if cid.endswith(".L"):
        return cid[:-2] + ".R"
    if cid.endswith(".R"):
        return cid[:-2] + ".L"
    return cid
