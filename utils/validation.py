"""Object and rig validation."""
from __future__ import annotations

from typing import List, Tuple

import bpy
from mathutils import Vector

from .. import constants as C

Result = Tuple[str, str]   # (level OK|WARN|ERROR|INFO, text)


def validate_character_objects(objects) -> List[Result]:
    out: List[Result] = []
    if not objects:
        return [("ERROR", "No mesh character selected. Select the character mesh(es) and click 'Use Selected Objects'.")]
    for o in objects:
        if o.type != "MESH":
            out.append(("ERROR", f"'{o.name}' is not a mesh object."))
            continue
        if len(o.data.vertices) == 0:
            out.append(("ERROR", f"'{o.name}' has no vertices."))
        s = o.scale
        if abs(s.x - 1) > 1e-3 or abs(s.y - 1) > 1e-3 or abs(s.z - 1) > 1e-3:
            out.append(("INFO", f"'{o.name}' has non-unit scale; this is supported but applying scale (Ctrl+A) is cleaner."))
        if o.parent is not None and o.parent.type == "ARMATURE":
            out.append(("WARN", f"'{o.name}' is already parented to an armature ('{o.parent.name}')."))
    return out


def store(settings, results: List[Result]) -> None:
    settings.validation.clear()
    for level, text in results:
        m = settings.validation.add()
        m.level, m.text = level, text


def validate_rig(rig, settings=None, plan=None, meshes=None) -> List[Result]:
    """Check the generated rig. Returns (level, text) lines; OK lines are the check marks."""
    res: List[Result] = []
    if rig is None or rig.type != "ARMATURE":
        return [("ERROR", "Armature missing: no rig object exists. Run Auto Rig first.")]
    arm = rig.data
    pbones = rig.pose.bones
    res.append(("OK", f"Armature '{rig.name}' ({len(arm.bones)} bones)"))

    # zero-length / suspicious bones
    bad = [b.name for b in arm.bones if b.length < 1e-5]
    if bad:
        res.append(("ERROR", f"Zero-length bones: {', '.join(bad[:6])}. Two guides are probably at the same place."))
    else:
        res.append(("OK", "No zero-length bones"))

    # duplicate-looking names
    dup = [b.name for b in arm.bones if b.name[-4:-3] == "." and b.name[-3:].isdigit()]
    if dup:
        res.append(("WARN", f"Bones with auto-numbered names (possible duplicates): {', '.join(dup[:5])}"))
    else:
        res.append(("OK", "Bone names unique"))

    # required bones
    deform = [b for b in arm.bones if b.use_deform]
    if not deform:
        res.append(("ERROR", "The rig has no deform bones - nothing can deform the mesh."))
    else:
        res.append(("OK", f"{len(deform)} deform bones"))
    if plan is not None:
        missing = [f"DEF-{n}" for n in plan.order if f"DEF-{n}" not in arm.bones]
        if missing:
            res.append(("ERROR", f"Missing required bones: {', '.join(missing[:6])}"))
        else:
            res.append(("OK", "All planned deform bones exist"))
        for group, label in (("spine", "Spine"), ("arm", "Arms"), ("leg", "Legs")):
            have = [n for n in plan.order if plan.bones[n].chain.startswith(group) or
                    (group == "spine" and plan.bones[n].chain == "spine")]
            if have:
                res.append(("OK", label))

    # parenting
    broken = [b.name for b in arm.bones if b.parent is not None and b.parent.name not in arm.bones]
    res.append(("ERROR", f"Invalid parents on: {', '.join(broken)}") if broken else ("OK", "Parenting valid"))

    # direction sanity: connected child pointing back against its parent
    flipped = []
    for b in arm.bones:
        if b.parent is not None and b.use_connect and b.length > 1e-5 and b.parent.length > 1e-5:
            if (b.tail_local - b.head_local).normalized().dot((b.parent.tail_local - b.parent.head_local).normalized()) < -0.2:
                flipped.append(b.name)
    if flipped:
        res.append(("WARN", f"Suspicious bone direction (folds back on parent): {', '.join(flipped[:5])}. "
                            f"Check those guides are ordered root to tip."))
    else:
        res.append(("OK", "Bone directions plausible"))

    # constraints, IK, poles
    n_con = n_bad = 0
    ik_missing: List[str] = []
    for pb in pbones:
        for con in pb.constraints:
            n_con += 1
            tgt = getattr(con, "target", None)
            sub = getattr(con, "subtarget", "")
            if hasattr(con, "target") and (tgt is None or (sub and sub not in arm.bones)):
                n_bad += 1
                ik_missing.append(f"{pb.name}:{con.name}")
            if con.type == "IK":
                pt = getattr(con, "pole_target", None)
                ps = getattr(con, "pole_subtarget", "")
                if pt is None or ps not in arm.bones:
                    ik_missing.append(f"{pb.name}:pole")
                    n_bad += 1
    if n_con == 0:
        res.append(("INFO", "No constraints (controls were disabled)."))
    elif n_bad:
        res.append(("ERROR", f"Broken constraint targets: {', '.join(ik_missing[:5])}"))
    else:
        res.append(("OK", f"{n_con} constraints valid (IK targets and poles exist)"))

    # controls
    if any(b.name.startswith(C.PREFIX_CTRL) for b in arm.bones):
        missing_ctrl = []
        for b in deform:
            pb = pbones[b.name]
            if not any(getattr(c, "subtarget", "") for c in pb.constraints):
                missing_ctrl.append(b.name)
        if missing_ctrl:
            res.append(("WARN", f"Deform bones without a control: {', '.join(missing_ctrl[:5])}"))
        else:
            res.append(("OK", "Controls"))

    # meshes
    if meshes is None:
        from ..rig import deformation as DF

        meshes = DF.bound_meshes(rig)
    if not meshes:
        res.append(("INFO", "No meshes are bound to the rig yet."))
    else:
        from ..rig import deformation as DF

        for obj in meshes:
            mod = next((m for m in obj.modifiers if m.type == "ARMATURE" and m.object == rig), None)
            if mod is None:
                res.append(("ERROR", f"'{obj.name}' has no Armature modifier pointing at the rig. Use Rebind."))
                continue
            names = {v.name for v in obj.vertex_groups}
            if not any(b.name in names for b in deform):
                res.append(("ERROR", f"'{obj.name}' has no vertex groups for the deform bones. Use Auto Weight."))
                continue
            rep = DF.weight_report(obj, rig)
            if rep["unweighted"]:
                res.append(("WARN", f"'{obj.name}': {rep['unweighted']} of {rep['vertices']} vertices have no weights."))
            else:
                res.append(("OK", f"'{obj.name}': modifier + weights ({rep['groups_used']} bones used)"))
    return res
