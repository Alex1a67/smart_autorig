"""Tiny logging helper. Debug output only appears when debug mode is enabled."""
import time

_DEBUG = False
_PREFIX = "[SmartAutoRig]"


def set_debug(enabled: bool) -> None:
    global _DEBUG
    _DEBUG = bool(enabled)


def is_debug() -> bool:
    return _DEBUG


def info(msg: str) -> None:
    print(f"{_PREFIX} {msg}")


def debug(msg: str) -> None:
    if _DEBUG:
        print(f"{_PREFIX} [debug] {msg}")


def warn(msg: str) -> None:
    print(f"{_PREFIX} WARNING: {msg}")


def error(msg: str) -> None:
    print(f"{_PREFIX} ERROR: {msg}")


class Timer:
    """Context manager that logs elapsed time in debug mode."""

    def __init__(self, label: str):
        self.label = label
        self.elapsed = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.perf_counter() - self._t0
        debug(f"{self.label}: {self.elapsed * 1000:.1f} ms")
        return False
