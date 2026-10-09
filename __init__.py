bl_info = {
    "name": "Smart Auto Rig",
    "author": "Smart Auto Rig",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Smart Auto Rig",
    "description": "Guided, geometry-driven auto-rigging for any character (humanoid, disconnected parts, creatures)",
    "category": "Rigging",
}


def register():
    from . import addon

    addon.register()


def unregister():
    from . import addon

    addon.unregister()
