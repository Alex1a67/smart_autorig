"""Shared constants for Smart Auto Rig."""

ADDON_ID = "smart_autorig"
ADDON_NAME = "Smart Auto Rig"

# Character is assumed to be Z-up, facing -Y (Blender convention). The character's
# left side is therefore +X. Both can be changed in the advanced settings.
UP = (0.0, 0.0, 1.0)

CHAIN_KINDS = [
    ("SPINE", "Spine", "Pelvis, chest, neck and head"),
    ("ARM", "Arm", "Shoulder, elbow, wrist, hand tip (IK/FK)"),
    ("LEG", "Leg", "Hip, knee, ankle, ball, toe (IK/FK + foot roll)"),
    ("FINGER", "Finger", "Finger chain attached to a hand"),
    ("TAIL", "Tail", "FK chain"),
    ("WING", "Wing", "FK chain"),
    ("HORN", "Horn", "FK chain"),
    ("EAR", "Ear", "FK chain"),
    ("TENTACLE", "Tentacle", "FK chain"),
    ("CLAW", "Claw", "FK chain"),
    ("CUSTOM", "Custom chain", "Generic FK chain"),
]

# Kinds that are generic FK chains (variable point count)
GENERIC_KINDS = {"TAIL", "WING", "HORN", "EAR", "TENTACLE", "CLAW", "CUSTOM", "FINGER"}

SPINE_KEYS = ["pelvis", "chest", "neck", "head", "head_top"]
SPINE_LABELS = {
    "pelvis": "Pelvis",
    "chest": "Chest",
    "neck": "Neck (base)",
    "head": "Head",
    "head_top": "Head top",
}
SPINE_REQUIRED = {"pelvis", "chest", "neck", "head"}

ARM_PARTS = ["shoulder", "elbow", "wrist", "hand_tip"]
ARM_LABELS = {"shoulder": "Shoulder", "elbow": "Elbow", "wrist": "Hand (wrist)", "hand_tip": "Hand tip"}
ARM_REQUIRED = {"shoulder", "wrist"}  # elbow can be inferred

LEG_PARTS = ["hip", "knee", "ankle", "ball", "toe"]
LEG_LABELS = {"hip": "Hip", "knee": "Knee", "ankle": "Foot (ankle)", "ball": "Ball of foot", "toe": "Toe tip"}
LEG_REQUIRED = {"hip", "ankle"}  # knee can be inferred

FINGER_NAMES = ["thumb", "index", "middle", "ring", "pinky"]

# Guided setup order: (guide key, instruction)
GUIDED_STEPS = [
    ("head", "HEAD: click the centre of the head where it meets the neck (skull base)."),
    ("neck", "NECK: click the centre of the base of the neck."),
    ("chest", "CHEST: click the centre of the upper chest."),
    ("pelvis", "PELVIS: click the centre of the hips."),
    ("arm.L.shoulder", "LEFT SHOULDER: click the left shoulder joint (character's left)."),
    ("arm.L.elbow", "LEFT ELBOW: click the left elbow."),
    ("arm.L.wrist", "LEFT HAND: click the left wrist / hand."),
    ("arm.R.shoulder", "RIGHT SHOULDER: click the right shoulder joint."),
    ("arm.R.elbow", "RIGHT ELBOW: click the right elbow."),
    ("arm.R.wrist", "RIGHT HAND: click the right wrist / hand."),
    ("leg.L.hip", "LEFT HIP: click the left hip joint."),
    ("leg.L.knee", "LEFT KNEE: click the left knee."),
    ("leg.L.ankle", "LEFT FOOT: click the left ankle."),
    ("leg.R.hip", "RIGHT HIP: click the right hip joint."),
    ("leg.R.knee", "RIGHT KNEE: click the right knee."),
    ("leg.R.ankle", "RIGHT FOOT: click the right ankle."),
]

# Bone collection names
COLL_ROOT = "Root"
COLL_TORSO = "Torso"
COLL_HEAD = "Head"
COLL_ARM_FK = "Arm FK"
COLL_ARM_IK = "Arm IK"
COLL_LEG_FK = "Leg FK"
COLL_LEG_IK = "Leg IK"
COLL_FINGERS = "Fingers"
COLL_EXTRA = "Extra"
COLL_MCH = "Mechanism"
COLL_DEF = "Deform"

# Collections inside the character collection
SUB_SOURCE = "Source"
SUB_RIG = "Rig"
SUB_CONTROLS = "Controls"
SUB_DEFORM = "Deform"

PREFIX_DEF = "DEF-"
PREFIX_CTRL = "CTRL-"
PREFIX_MCH = "MCH-"
PREFIX_ORG = "ORG-"
