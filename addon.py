"""Registration of every class and handler."""
import bpy

from . import properties
from .operators import (analysis, demo, guide_editor, guides, presets, rig_generation, selftest, testing, weighting)
from .ui import draw, lists, panels

_MODULES_WITH_CLASSES = (guides, guide_editor, presets, analysis, rig_generation, weighting, testing, selftest,
                         demo, lists, panels)
_registered = []


def register():
    properties.register()
    for mod in _MODULES_WITH_CLASSES:
        for cls in mod.CLASSES:
            bpy.utils.register_class(cls)
            _registered.append(cls)
    draw.register()


def unregister():
    draw.unregister()
    for cls in reversed(_registered):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    _registered.clear()
    properties.unregister()
