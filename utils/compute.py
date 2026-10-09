"""Numeric backend selection.

The heavy numeric kernels (distance matrices for weighting / coverage checks) are written
against an `xp` array module. NumPy (CPU) is always available inside Blender. If the user
selects GPU and the optional CuPy package is importable, CuPy is used. Nothing here claims
GPU use unless CuPy is actually active.
"""
from __future__ import annotations

import numpy as np

_CUPY = None
_CUPY_CHECKED = False


def _try_cupy():
    global _CUPY, _CUPY_CHECKED
    if _CUPY_CHECKED:
        return _CUPY
    _CUPY_CHECKED = True
    try:
        import cupy  # type: ignore

        cupy.cuda.runtime.getDeviceCount()
        _CUPY = cupy
    except Exception:
        _CUPY = None
    return _CUPY


def gpu_report() -> dict:
    """Describe what Blender's GPU module reports and whether a GPU compute path exists."""
    info = {"blender_gpu": False, "backend": "unknown", "device": "unknown", "compute": "CPU (NumPy)", "cupy": False}
    try:
        import gpu

        info["backend"] = str(gpu.platform.backend_type_get())
        info["device"] = str(gpu.platform.renderer_get())
        info["blender_gpu"] = info["backend"].upper() not in {"", "UNKNOWN", "NONE"}
    except Exception:
        pass
    info["cupy"] = _try_cupy() is not None
    if info["cupy"]:
        info["compute"] = "CuPy (CUDA) available"
    return info


def get_xp(mode: str = "AUTO"):
    """Return (array_module, label, note). mode in AUTO / GPU / CPU."""
    mode = (mode or "AUTO").upper()
    if mode in {"AUTO", "GPU"}:
        cp = _try_cupy()
        if cp is not None:
            return cp, "GPU (CuPy)", ""
        if mode == "GPU":
            return np, "CPU (NumPy)", "GPU compute requested but CuPy is not installed - using CPU fallback."
    return np, "CPU (NumPy)", ""


def to_numpy(arr):
    try:
        return arr.get()  # cupy array
    except AttributeError:
        return np.asarray(arr)
