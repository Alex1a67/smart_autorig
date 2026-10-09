"""Demo / test characters made from separate (disconnected) mesh objects."""
from __future__ import annotations

from typing import Dict, List, Tuple

import bmesh
import bpy
from bpy.props import EnumProperty
from mathutils import Vector

from .. import guides_model as GM


def _box(name: str, centre: Vector, size: Tuple[float, float, float], collection, material=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = centre
    collection.objects.link(obj)
    if material is not None:
        me.materials.append(material)
    return obj


def _sphere(name: str, centre: Vector, radius: float, collection):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=radius)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = centre
    collection.objects.link(obj)
    return obj


def create_humanoid(context, collection=None, name_prefix: str = "") -> Tuple[List[object], Dict[str, Vector]]:
    """T-pose blocky humanoid, 1.8 m tall, made of 15 disconnected objects."""
    coll = collection or context.scene.collection
    objs = []
    P = name_prefix
    # head, torso
    objs.append(_sphere(P + "Head", Vector((0, 0, 1.64)), 0.12, coll))
    objs.append(_box(P + "Body", Vector((0, 0, 1.20)), (0.36, 0.20, 0.62), coll))
    objs.append(_box(P + "Pelvis", Vector((0, 0, 0.86)), (0.32, 0.20, 0.14), coll))
    for sx, side in ((1, "L"), (-1, "R")):
        # arms along X
        objs.append(_box(f"{P}UpperArm.{side}", Vector((sx * 0.43, 0, 1.43)), (0.26, 0.10, 0.10), coll))
        objs.append(_box(f"{P}Forearm.{side}", Vector((sx * 0.69, 0, 1.43)), (0.26, 0.09, 0.09), coll))
        objs.append(_box(f"{P}Hand.{side}", Vector((sx * 0.89, 0, 1.43)), (0.14, 0.06, 0.10), coll))
        # legs
        objs.append(_box(f"{P}Thigh.{side}", Vector((sx * 0.09, 0, 0.64)), (0.14, 0.15, 0.42), coll))
        objs.append(_box(f"{P}Shin.{side}", Vector((sx * 0.09, 0, 0.23)), (0.12, 0.13, 0.40), coll))
        objs.append(_box(f"{P}Foot.{side}", Vector((sx * 0.09, -0.07, 0.04)), (0.12, 0.28, 0.08), coll))
    guides = {
        "head": Vector((0, 0, 1.52)), "neck": Vector((0, 0, 1.50)) + Vector((0, 0, -0.0)),
        "chest": Vector((0, 0, 1.42)), "pelvis": Vector((0, 0, 0.90)), "head_top": Vector((0, 0, 1.76)),
    }
    guides["neck"] = Vector((0, 0, 1.47))
    guides["chest"] = Vector((0, 0, 1.38))
    guides["head"] = Vector((0, 0, 1.53))
    for sx, side in ((1, "L"), (-1, "R")):
        guides[f"arm.{side}.shoulder"] = Vector((sx * 0.22, 0, 1.43))
        guides[f"arm.{side}.elbow"] = Vector((sx * 0.56, 0, 1.43))
        guides[f"arm.{side}.wrist"] = Vector((sx * 0.82, 0, 1.43))
        guides[f"leg.{side}.hip"] = Vector((sx * 0.09, 0, 0.86))
        guides[f"leg.{side}.knee"] = Vector((sx * 0.09, 0, 0.44))
        guides[f"leg.{side}.ankle"] = Vector((sx * 0.09, 0, 0.09))
    bpy.context.view_layer.update()
    return objs, guides


def create_four_arm_creature(context, collection=None) -> Tuple[List[object], Dict[str, Vector], list]:
    """Creature: torso, head, four arms, two legs and a tail. Returns (objects, guides, extra chain specs)."""
    coll = collection or context.scene.collection
    objs = []
    objs.append(_sphere("C_Head", Vector((0, -0.02, 1.62)), 0.14, coll))
    objs.append(_box("C_Body", Vector((0, 0, 1.2)), (0.34, 0.22, 0.7), coll))
    objs.append(_box("C_Pelvis", Vector((0, 0, 0.82)), (0.3, 0.2, 0.14), coll))
    guides = {"head": Vector((0, 0, 1.52)), "neck": Vector((0, 0, 1.47)), "chest": Vector((0, 0, 1.36)),
              "pelvis": Vector((0, 0, 0.86)), "head_top": Vector((0, 0, 1.78))}
    for sx, side in ((1, "L"), (-1, "R")):
        for row, z in (("", 1.42), ("2", 1.22)):
            tag = f"{side}{row}"
            objs.append(_box(f"C_Arm{row}.{side}.a", Vector((sx * 0.42, 0, z)), (0.28, 0.1, 0.1), coll))
            objs.append(_box(f"C_Arm{row}.{side}.b", Vector((sx * 0.72, 0, z)), (0.3, 0.09, 0.09), coll))
            cid = f"arm{row}.{side}"
            guides[f"{cid}.shoulder"] = Vector((sx * 0.20, 0, z))
            guides[f"{cid}.elbow"] = Vector((sx * 0.57, 0, z))
            guides[f"{cid}.wrist"] = Vector((sx * 0.88, 0, z))
        objs.append(_box(f"C_Thigh.{side}", Vector((sx * 0.09, 0, 0.6)), (0.14, 0.15, 0.5), coll))
        objs.append(_box(f"C_Shin.{side}", Vector((sx * 0.09, 0, 0.2)), (0.12, 0.13, 0.4), coll))
        guides[f"leg.{side}.hip"] = Vector((sx * 0.09, 0, 0.84))
        guides[f"leg.{side}.knee"] = Vector((sx * 0.09, 0, 0.42))
        guides[f"leg.{side}.ankle"] = Vector((sx * 0.09, 0, 0.06))
    tail_pts = []
    for i in range(4):
        objs.append(_box(f"C_Tail{i}", Vector((0, 0.18 + i * 0.2, 0.78 - i * 0.04)), (0.1, 0.2, 0.1), coll))
        tail_pts.append(Vector((0, 0.08 + i * 0.2, 0.8 - i * 0.04)))
    tail_pts.append(Vector((0, 0.9, 0.66)))
    extra = [("TAIL", "C", "tail", tail_pts)]
    bpy.context.view_layer.update()
    return objs, guides, extra


def apply_demo_guides(settings, guides: Dict[str, Vector], extra=None, extra_arms: int = 0) -> None:
    """Create needed chains and fill guide positions."""
    GM.ensure_core_guides(settings)
    if extra_arms:
        for side in ("L", "R"):
            GM.add_chain(settings, "ARM", side)
    for e in extra or []:
        kind, side, name, pts = e
        ch = GM.add_chain(settings, kind, side, name, len(pts))
        for g, p in zip(GM.chain_guides(settings, ch.cid), pts):
            g.location = p
            g.placed = True
    for key, p in guides.items():
        GM.set_guide(settings, key, p)


class SAR_OT_create_demo(bpy.types.Operator):
    bl_idname = "sar.create_demo"
    bl_label = "Create Test Character"
    bl_description = "Create a test character made of separate mesh objects (with guides pre-placed)"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=[("HUMANOID", "Blocky humanoid (15 parts)", ""),
                              ("CREATURE", "Four-arm creature with tail", "")], default="HUMANOID")

    def execute(self, context):
        settings = context.scene.sar
        coll = bpy.data.collections.new(f"Demo_{self.kind.title()}")
        context.scene.collection.children.link(coll)
        settings.guides.clear()
        settings.chains.clear()
        settings.objects.clear()
        if self.kind == "HUMANOID":
            objs, guides = create_humanoid(context, coll)
            apply_demo_guides(settings, guides)
            settings.rig_type = "HUMANOID"
            settings.weight_method = "AUTO"
        else:
            objs, guides, extra = create_four_arm_creature(context, coll)
            apply_demo_guides(settings, guides, extra, extra_arms=1)
            settings.rig_type = "CREATURE"
        settings.character_name = "Demo" if self.kind == "HUMANOID" else "Creature"
        for o in objs:
            r = settings.objects.add()
            r.obj = o
        settings.analysis_done = False
        self.report({"INFO"}, f"Created {len(objs)} test objects. Guides are pre-placed: run Analyze, then Auto Rig.")
        return {"FINISHED"}


CLASSES = (SAR_OT_create_demo,)
