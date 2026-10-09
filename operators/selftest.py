"""Add-on self test: builds temporary test characters in a throw-away scene and exercises everything."""
from __future__ import annotations

import time
import traceback
from typing import Callable, List, Tuple

import bpy

from .. import guides_model as GM
from ..rig import deformation as DF
from ..rig import generator as GEN
from ..utils import validation
from . import analysis as AN
from . import demo, presets
from . import testing


def run_selftest(context) -> List[Tuple[str, str]]:
    """Returns (level, text) lines. Runs in a temporary scene; the user's scene is untouched."""
    results: List[Tuple[str, str]] = []
    window = context.window
    original_scene = context.scene
    use_tmp = window is not None          # background mode has no window: run in the current scene instead
    tmp = bpy.data.scenes.new("SAR_SelfTest") if use_tmp else original_scene
    created_colls = []
    try:
        if use_tmp:
            window.scene = tmp
        ctx = bpy.context
        s = tmp.sar

        def check(name: str, fn: Callable[[], str]):
            t0 = time.perf_counter()
            try:
                msg = fn()
                results.append(("OK", f"{name}{(': ' + msg) if msg else ''}  [{(time.perf_counter() - t0) * 1000:.0f} ms]"))
                return True
            except AssertionError as exc:
                results.append(("ERROR", f"{name}: FAILED - {exc}"))
            except Exception as exc:
                traceback.print_exc()
                results.append(("ERROR", f"{name}: EXCEPTION {type(exc).__name__}: {exc}"))
            return False

        state = {}

        def t_registration():
            for op in ("guide_editor", "analyze", "preview_rig", "auto_rig", "auto_weight", "test_rig",
                       "validate_rig", "save_preset", "create_demo", "self_test"):
                assert hasattr(bpy.ops.sar, op), f"operator sar.{op} missing"
            return "operators registered"
        check("Registration", t_registration)

        def t_props():
            assert hasattr(tmp, "sar"), "scene.sar property missing"
            assert s.rig_type in {"HUMANOID", "CREATURE", "CUSTOM"}
            return "scene properties present"
        check("Properties", t_props)

        def t_guides():
            GM.ensure_core_guides(s)
            assert len(s.chains) == 5, f"expected 5 core chains, got {len(s.chains)}"
            n = len(s.guides)
            GM.set_guide(s, "head", (0.1, 0.2, 0.3))
            g = GM.get_guide(s, "head")
            assert g.placed and abs(g.location[2] - 0.3) < 1e-6, "guide storage failed"
            GM.add_chain(s, "TAIL", "C", "tail", 4)
            assert len(s.guides) == n + 4, "custom chain guides not created"
            s.guides.clear()
            s.chains.clear()
            return f"{n} core guides, storage OK"
        check("Guide creation & storage", t_guides)

        def t_demo():
            coll = bpy.data.collections.new("SAR_Test_Humanoid")
            tmp.collection.children.link(coll)
            created_colls.append(coll)
            objs, guides = demo.create_humanoid(ctx, coll)
            demo.apply_demo_guides(s, guides)
            s.objects.clear()
            for o in objs:
                s.objects.add().obj = o
            s.character_name = "SelfTest"
            state["objs"] = objs
            assert len(objs) == 15, f"expected 15 parts, got {len(objs)}"
            return f"{len(objs)} disconnected objects"
        if not check("Test character", t_demo):
            return results

        def t_analysis():
            res, err = AN.run_analysis(ctx, s)
            assert res is not None, err
            assert res.overall > 60, f"confidence unexpectedly low: {res.overall:.0f}"
            state["conf"] = res.overall
            return f"confidence {res.overall:.0f}% ({', '.join(f'{n} {v:.0f}' for n, v, _ in res.scores)})"
        check("Analysis", t_analysis)

        def t_preview():
            GEN.run_to_completion(ctx, s, "PREVIEW")
            assert s.preview_rig is not None and len(s.preview_rig.data.bones) > 20
            n = len(s.preview_rig.data.bones)
            GEN.remove_preview(ctx, s)
            assert s.preview_rig is None
            return f"{n} preview bones, removed cleanly"
        check("Preview rig", t_preview)

        def t_rig():
            st = GEN.run_to_completion(ctx, s, "FULL")
            rig = s.rig_object
            assert rig is not None, "no rig"
            state["rig"], state["st"] = rig, st
            names = {b.name for b in rig.data.bones}
            for need in ("DEF-pelvis", "DEF-head", "DEF-upper_arm.L", "DEF-forearm.R", "DEF-thigh.L", "DEF-foot.R",
                         "CTRL-root", "CTRL-ik_hand.L", "CTRL-pole_leg.R", "CTRL-ik_foot.L"):
                assert need in names, f"bone {need} missing"
            return f"{len(names)} bones"
        check("Auto rig / bone generation", t_rig)
        rig = state.get("rig")
        if rig is None:
            return results

        def t_constraints():
            n = sum(len(pb.constraints) for pb in rig.pose.bones)
            ik = [c for pb in rig.pose.bones for c in pb.constraints if c.type == "IK"]
            assert n > 20 and len(ik) == 4, f"{n} constraints, {len(ik)} IK"
            for c in ik:
                assert c.target and c.pole_target, "IK target/pole missing"
            return f"{n} constraints, 4 IK with poles"
        check("Constraints & IK", t_constraints)

        def t_drivers():
            fcs = rig.animation_data.drivers
            bad = [f.data_path for f in fcs if not f.driver.is_valid]
            assert fcs and not bad, f"invalid drivers: {bad[:3]}"
            return f"{len(fcs)} drivers valid"
        check("IK/FK & foot-roll drivers", t_drivers)

        def t_weights():
            meshes = DF.bound_meshes(rig, tmp)
            assert len(meshes) == 15, f"{len(meshes)} meshes bound"
            for o in meshes:
                assert any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers), f"{o.name} no modifier"
                rep = DF.weight_report(o, rig)
                assert rep["unweighted"] == 0, f"{o.name} has {rep['unweighted']} unweighted vertices"
            return "15 meshes bound, all vertices weighted"
        check("Binding & weights", t_weights)

        def t_smooth_clean():
            o = DF.bound_meshes(rig, tmp)[0]
            DF.smooth_weights(o, rig, 1, 0.5)
            DF.clean_weights(o, rig, 0.01, 4)
            assert DF.weight_report(o, rig)["unweighted"] == 0
            return "smooth + clean OK"
        check("Weight smooth / clean", t_smooth_clean)

        def t_validate():
            res = validation.validate_rig(rig, s, state["st"].plan, state["st"].meshes)
            errs = [t for l, t in res if l == "ERROR"]
            assert not errs, "; ".join(errs[:3])
            return f"{sum(1 for l, _ in res if l == 'OK')} checks passed"
        check("Validation", t_validate)

        def t_rigtest():
            res = testing.run_rig_test(ctx, rig, DF.bound_meshes(rig, tmp))
            errs = [t for l, t in res if l == "ERROR"]
            assert not errs, "; ".join(errs[:3])
            return f"{sum(1 for l, _ in res if l == 'OK')} pose checks passed, pose restored"
        check("Rig test", t_rigtest)

        def t_preset():
            path = presets.save_preset(s, "_selftest")
            n0 = len([g for g in s.guides if g.placed])
            s.guides[0].placed = False
            presets.load_preset(s, "_selftest")
            n1 = len([g for g in s.guides if g.placed])
            import os
            os.remove(path)
            assert n0 == n1, f"{n0} vs {n1} placed guides after load"
            return f"{n1} guides round-tripped"
        check("Presets", t_preset)

        def t_cleanup():
            n = GEN.remove_generated(ctx, s)
            assert s.rig_object is None
            return f"removed {n} generated objects, sources restored"
        check("Remove rig", t_cleanup)

        # ---- creature with extra limbs
        def t_creature():
            s.guides.clear()
            s.chains.clear()
            s.objects.clear()
            coll = bpy.data.collections.new("SAR_Test_Creature")
            tmp.collection.children.link(coll)
            created_colls.append(coll)
            objs, guides, extra = demo.create_four_arm_creature(ctx, coll)
            demo.apply_demo_guides(s, guides, extra, extra_arms=1)
            for o in objs:
                s.objects.add().obj = o
            s.rig_type = "CREATURE"
            s.character_name = "SelfTestCreature"
            st = GEN.run_to_completion(ctx, s, "FULL")
            names = {b.name for b in s.rig_object.data.bones}
            for need in ("DEF-upper_arm.L", "DEF-upper_arm2.L", "DEF-upper_arm2.R", "DEF-tail_01", "DEF-tail_04"):
                assert need in names, f"{need} missing"
            res = validation.validate_rig(s.rig_object, s, st.plan, st.meshes)
            errs = [t for l, t in res if l == "ERROR"]
            assert not errs, "; ".join(errs[:2])
            r = testing.run_rig_test(ctx, s.rig_object, DF.bound_meshes(s.rig_object, tmp))
            errs = [t for l, t in r if l == "ERROR"]
            assert not errs, "; ".join(errs[:2])
            GEN.remove_generated(ctx, s)
            return "4 arms + tail rigged, validated and tested"
        check("Four-arm creature", t_creature)

        # ---- graceful failures
        def t_missing():
            s.guides.clear()
            s.chains.clear()
            GM.ensure_core_guides(s)
            s.rig_type = "HUMANOID"
            GM.set_guide(s, "pelvis", (0, 0, 1))
            try:
                GEN.run_to_completion(ctx, s, "FULL")
            except GEN.GenerationError as exc:
                return f"clear error: '{str(exc)[:60]}'"
            raise AssertionError("missing guides did not produce an error")
        check("Missing guides fail gracefully", t_missing)

        def t_invalid():
            s.objects.clear()
            try:
                GEN.run_to_completion(ctx, s, "FULL")
            except GEN.GenerationError as exc:
                return f"clear error: '{str(exc)[:60]}'"
            raise AssertionError("empty selection did not produce an error")
        check("Invalid selection fails gracefully", t_invalid)

        def t_cpu():
            from ..utils import compute
            xp, label, _n = compute.get_xp("CPU")
            assert label.startswith("CPU")
            return f"CPU fallback available ({compute.gpu_report()['compute']})"
        check("CPU fallback", t_cpu)
    finally:
        if use_tmp:
            window.scene = original_scene
        try:
            for ob in list(tmp.objects):
                data = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                if data is not None and getattr(data, "users", 1) == 0:
                    (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.armatures).remove(data)
            for c in list(bpy.data.collections):
                if c.name.startswith(("SAR_Test_", "SAR_SelfTest")) and c.users <= 1:
                    bpy.data.collections.remove(c)
            if use_tmp:
                bpy.data.scenes.remove(tmp)
        except Exception:
            traceback.print_exc()
    return results


class SAR_OT_self_test(bpy.types.Operator):
    bl_idname = "sar.self_test"
    bl_label = "Run Add-on Self Test"
    bl_description = ("Builds test characters in a temporary scene and tests registration, guides, analysis, "
                      "rig generation, constraints, weights, validation and error handling")

    def execute(self, context):
        s = context.scene.sar
        results = run_selftest(context)
        s = context.scene.sar          # context scene restored
        s.selftest_results.clear()
        for level, text in results:
            m = s.selftest_results.add()
            m.level, m.text = level, text
        failed = [t for l, t in results if l == "ERROR"]
        self.report({"ERROR" if failed else "INFO"},
                    f"Self test: {len(results) - len(failed)} passed, {len(failed)} failed" +
                    (f" - {failed[0]}" if failed else ""))
        return {"FINISHED"}


CLASSES = (SAR_OT_self_test,)
