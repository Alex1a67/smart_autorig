"""UI lists."""
import bpy


class SAR_UL_guides(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        if item.placed:
            row.label(text="", icon="CHECKMARK" if not item.suggested else "QUESTION")
        else:
            row.label(text="", icon="RADIOBUT_OFF")
        row.label(text=item.label + ("  *" if item.required else ""))

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt = [self.bitflag_filter_item] * len(items)
        return flt, []


class SAR_UL_objects(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.obj:
            layout.label(text=item.obj.name, icon="MESH_DATA")
        else:
            layout.label(text="(deleted)", icon="ERROR")


CLASSES = (SAR_UL_guides, SAR_UL_objects)
