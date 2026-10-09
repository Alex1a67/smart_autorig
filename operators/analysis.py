"""Character analysis operator (real measurements; see analysis/confidence.py)."""
from __future__ import annotations

import time

import bpy

from .. import guides_model as GM
from ..analysis import confidence
from ..rig import generator as GEN
from ..rig import plan as PL
from ..utils import logging as log
from ..utils import validation


def run_analysis(context, settings):
    objs = GEN.character_objects(settings)
    problems = validation.validate_character_objects(objs)
    errors = [t for lvl, t in problems if lvl == "ERROR"]
    if errors:
        return None, errors[0]
    positions = GM.placed_positions(settings)
    if not positions:
        return None, "No guides have been placed yet. Click 'Start Guided Setup' and place the guides."
    options = PL.RigOptions.from_settings(settings)
    t0 = time.perf_counter()
    res = confidence.analyze(settings, objs, positions, GEN.collect_chains(settings), options)
    log.debug(f"analysis took {(time.perf_counter() - t0) * 1000:.0f} ms, overall {res.overall:.1f}")
    store_result(settings, res)
    return res, ""


def store_result(settings, res) -> None:
    settings.scores.clear()
    for name, value, detail in res.scores:
        sc = settings.scores.add()
        sc.name, sc.value, sc.detail = name, value, detail
    settings.messages.clear()
    for e in res.errors:
        m = settings.messages.add()
        m.text, m.level = e, "ERROR"
    seen = set()
    for w in res.warnings:
        if w in seen:
            continue
        seen.add(w)
        m = settings.messages.add()
        m.text, m.level = w, "WARN"
    settings.confidence = res.overall
    settings.analysis_done = True
    settings.analysis_summary = res.summary


class SAR_OT_analyze(bpy.types.Operator):
    bl_idname = "sar.analyze"
    bl_label = "Analyze Character"
    bl_description = ("Measure mesh and guide quality and compute a rig confidence score. "
                      "The score is derived from geometry checks, not from a machine-learning model")

    def execute(self, context):
        settings = context.scene.sar
        res, err = run_analysis(context, settings)
        if res is None:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        level = "INFO" if not res.errors else "WARNING"
        self.report({level}, f"Rig confidence {res.overall:.0f}% - " +
                    (res.errors[0] if res.errors else f"{len(res.warnings)} warning(s)"))
        return {"FINISHED"}


CLASSES = (SAR_OT_analyze,)
