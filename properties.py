"""Blender property definitions (stored on the Scene as `scene.sar`)."""
from __future__ import annotations

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

from . import constants as C
from .utils import logging as log


def _update_debug(self, _context):
    log.set_debug(self.debug_mode)


class SAR_ObjectRef(PropertyGroup):
    obj: PointerProperty(type=bpy.types.Object)


class SAR_Guide(PropertyGroup):
    key: StringProperty()
    label: StringProperty()
    chain: StringProperty()
    index: IntProperty()
    location: FloatVectorProperty(size=3, subtype="TRANSLATION", unit="LENGTH")
    placed: BoolProperty(default=False)
    suggested: BoolProperty(default=False, description="Position was estimated; confirm or move it")
    required: BoolProperty(default=False)


class SAR_Chain(PropertyGroup):
    cid: StringProperty()
    kind: EnumProperty(items=[(k, n, d) for k, n, d in C.CHAIN_KINDS], default="CUSTOM")
    side: EnumProperty(items=[("C", "Centre", ""), ("L", "Left", ""), ("R", "Right", "")], default="C")
    name: StringProperty(description="Base name used for the generated bones")
    label: StringProperty()
    point_count: IntProperty(default=3, min=2, max=64)
    parent_chain: StringProperty(description="Chain this one attaches to (blank = nearest spine bone)")
    use_ik: BoolProperty(default=True, description="Generate IK for this limb")


class SAR_Score(PropertyGroup):
    name: StringProperty()
    value: FloatProperty(default=0.0)
    detail: StringProperty()


class SAR_Message(PropertyGroup):
    text: StringProperty()
    level: EnumProperty(items=[("OK", "OK", ""), ("INFO", "Info", ""), ("WARN", "Warning", ""), ("ERROR", "Error", "")],
                        default="INFO")


def _preset_items(self, context):
    from .operators import presets as P

    items = [(n, n, "") for n in P.list_presets()]
    return items or [("", "(no presets)", "")]


class SAR_Settings(PropertyGroup):
    # ---------------------------------------------------------------- ui
    ui_mode: EnumProperty(
        name="Mode",
        items=[("BEGINNER", "Beginner", "Only the essentials"), ("ADVANCED", "Advanced", "Expose every setting")],
        default="BEGINNER")
    debug_mode: BoolProperty(name="Debug mode", default=False, update=_update_debug,
                             description="Print detailed information to the system console")

    # ---------------------------------------------------------------- character
    character_name: StringProperty(name="Character", default="Character")
    objects: CollectionProperty(type=SAR_ObjectRef)
    preserve_source: BoolProperty(
        name="Preserve source", default=True,
        description="Bind duplicates (in the 'Deform' collection) and hide the originals instead of modifying them")
    forward_axis: EnumProperty(
        name="Forward", items=[("-Y", "-Y", "Character faces -Y (Blender default)"), ("Y", "+Y", ""),
                               ("-X", "-X", ""), ("X", "+X", "")], default="-Y")
    left_axis: EnumProperty(
        name="Left side", items=[("X", "+X", "Character's left is +X (Blender default)"), ("-X", "-X", "")],
        default="X")

    # ---------------------------------------------------------------- guides
    guides: CollectionProperty(type=SAR_Guide)
    chains: CollectionProperty(type=SAR_Chain)
    active_guide: IntProperty(default=0)
    guided_active: BoolProperty(default=False)
    guided_step: IntProperty(default=0)
    guided_finished: BoolProperty(default=False)
    editor_running: BoolProperty(default=False)
    snap_to_surface: BoolProperty(name="Snap to mesh", default=True,
                                  description="Project dragged guides onto the character surface")
    snap_to_volume_centre: BoolProperty(
        name="Centre in volume", default=True,
        description="Place guides at the middle of the body along the view ray (joints live inside the mesh)")
    guide_size: FloatProperty(name="Guide size", default=1.0, min=0.3, max=4.0)
    show_guides: BoolProperty(name="Show guides", default=True, description="Draw the guides in the 3D viewport")
    mirror_axis: EnumProperty(name="Mirror axis", items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
                              default="X")
    mirror_auto_center: BoolProperty(name="Auto centre", default=True,
                                     description="Use the character bounding-box centre as the mirror plane")
    mirror_center: FloatVectorProperty(name="Mirror plane position", size=3, subtype="TRANSLATION", unit="LENGTH")
    new_chain_name: StringProperty(name="Name", default="chain")
    new_chain_points: IntProperty(name="Points", default=4, min=2, max=64)
    new_chain_side: EnumProperty(name="Side", items=[("C", "Centre", ""), ("L", "Left", ""), ("R", "Right", "")],
                                 default="C")

    # ---------------------------------------------------------------- rig options
    rig_type: EnumProperty(
        name="Rig type",
        items=[("HUMANOID", "Humanoid", "Complete humanoid: spine, head, two arms, two legs required"),
               ("CREATURE", "Creature", "Any combination of chains; spine pieces may be missing"),
               ("CUSTOM", "Custom", "Only the chains you define")],
        default="HUMANOID")
    fit_mode: EnumProperty(
        name="Bone fit",
        items=[("EXACT", "Keep exact guide positions", "Bones are placed exactly where the guides are"),
               ("OPTIMIZE", "Optimize bone fit", "Nudge joints to the centre of the limb cross-section")],
        default="EXACT")
    joint_mode: EnumProperty(
        name="Joints",
        items=[("MANUAL", "Manual joints", "Use only the guides you placed; infer only what is missing"),
               ("AUTO", "Automatic joint detection", "Infer and refine elbows/knees from the mesh")],
        default="MANUAL")
    spine_bones: IntProperty(name="Spine bones", default=0, min=0, max=8,
                             description="Bones between pelvis and chest (0 = choose automatically)")
    neck_bones: IntProperty(name="Neck bones", default=0, min=0, max=4,
                            description="Bones in the neck (0 = choose automatically)")
    use_clavicles: BoolProperty(name="Clavicles", default=True)
    generate_controls: BoolProperty(name="Controls", default=True)
    generate_ik: BoolProperty(name="IK", default=True)
    generate_fk: BoolProperty(name="FK", default=True)
    foot_roll: BoolProperty(name="Foot roll", default=True)
    default_ik: FloatProperty(name="Default IK", default=1.0, min=0.0, max=1.0,
                              description="Initial IK/FK blend (1 = IK, 0 = FK)")
    control_scale: FloatProperty(name="Control scale", default=1.0, min=0.1, max=5.0)
    bind_weights: BoolProperty(name="Generate weights", default=True)
    rig_name: StringProperty(name="Rig name", default="")

    # ---------------------------------------------------------------- weighting
    weight_method: EnumProperty(
        name="Method",
        items=[("AUTO", "Automatic", "Blender bone heat, falling back to smooth distance weights if it fails"),
               ("HEAT", "Bone heat only", "Blender automatic weights"),
               ("ENVELOPE", "Envelopes", "Blender envelope weights (estimated radii)"),
               ("DISTANCE", "Distance (smooth)", "Smooth distance based weights, robust for any mesh"),
               ("RIGID", "Rigid per object", "Each object follows the nearest bone (blocky / disconnected parts)")],
        default="AUTO")
    weight_falloff: FloatProperty(name="Falloff", default=3.0, min=0.5, max=10.0,
                                  description="Higher = tighter influence around each bone")
    weight_max_influences: IntProperty(name="Max influences", default=4, min=1, max=8)
    weight_smooth_iterations: IntProperty(name="Smooth passes", default=2, min=0, max=20)
    weight_smooth_factor: FloatProperty(name="Smooth factor", default=0.5, min=0.0, max=1.0)
    weight_clean_threshold: FloatProperty(name="Clean threshold", default=0.01, min=0.0, max=0.5)

    # ---------------------------------------------------------------- processing
    compute_mode: EnumProperty(name="Compute", items=[("AUTO", "Auto", ""), ("GPU", "GPU", ""), ("CPU", "CPU", "")],
                               default="AUTO")
    analysis_quality: EnumProperty(
        name="Analysis",
        items=[("FAST", "Fast (5k samples)", ""), ("BALANCED", "Balanced (20k)", ""),
               ("DETAILED", "Detailed (60k)", "")], default="BALANCED")

    # ---------------------------------------------------------------- results
    scores: CollectionProperty(type=SAR_Score)
    messages: CollectionProperty(type=SAR_Message)
    validation: CollectionProperty(type=SAR_Message)
    test_results: CollectionProperty(type=SAR_Message)
    selftest_results: CollectionProperty(type=SAR_Message)
    confidence: FloatProperty(default=0.0)
    analysis_done: BoolProperty(default=False)
    analysis_summary: StringProperty()

    # ---------------------------------------------------------------- progress (generation, not analysis)
    progress_active: BoolProperty(default=False)
    progress_label: StringProperty()
    progress_value: FloatProperty(default=0.0, min=0.0, max=1.0)
    stages: CollectionProperty(type=SAR_Score)

    # ---------------------------------------------------------------- generated data
    preview_rig: PointerProperty(type=bpy.types.Object)
    preview_state: EnumProperty(items=[("NONE", "None", ""), ("PENDING", "Pending", ""),
                                       ("ACCEPTED", "Accepted", "")], default="NONE")
    rig_object: PointerProperty(type=bpy.types.Object)

    # ---------------------------------------------------------------- presets
    preset_name: StringProperty(name="Preset name", default="my_character")
    preset_list: EnumProperty(name="Preset", items=_preset_items)


CLASSES = (SAR_ObjectRef, SAR_Guide, SAR_Chain, SAR_Score, SAR_Message, SAR_Settings)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sar = PointerProperty(type=SAR_Settings)


def unregister():
    if hasattr(bpy.types.Scene, "sar"):
        del bpy.types.Scene.sar
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
