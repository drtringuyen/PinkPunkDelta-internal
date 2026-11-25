import bpy

from ... import identity as idn
from ... import links
from . import gizmo


class PINKPUNKDELTA_INTERNAL_PT_Setup(bpy.types.Panel):
    bl_label = "01.Setup"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_setup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.operator("ppd.gizmo", icon='OUTLINER_OB_ARMATURE', depress=gizmo.is_on())
        if gizmo.is_on():
            layout.row(align=True).prop(context.scene.ppd, "gizmo_offset", text="")
        if not bpy.data.filepath:
            r = layout.row()
            r.alert = True
            r.label(text="Save the .blend: its name is the Central", icon='ERROR')
        else:
            layout.label(text=idn.central(), icon='FILE_BLEND')
        if links.central_changed():
            box = layout.box()
            box.alert = True
            box.label(text=f"The file is now {idn.file_central()}", icon='ERROR')
            box.label(text="Save or Check All Links updates every name")

        objs = sorted(idn.objects(), key=lambda o: o.name)
        box = layout.box()
        box.label(text=f"Setup objects ({len(objs)})", icon='OUTLINER_OB_MESH')
        col = box.column(align=True)
        for o in objs:
            row = col.row(align=True)
            row.operator("ppd.select", text="", icon='RESTRICT_SELECT_OFF',
                         depress=o == context.active_object).name = o.name
            row.prop(o, "name", text="")
        row = layout.row(align=True)
        row.operator("ppd.setup_current", icon='CHECKMARK')
        row.operator("ppd.setup_create", text="Create Setup Object", icon='ADD')
        layout.operator("ppd.check_links", icon='LINKED')
        for m in links.messages[:8]:
            r = layout.row()
            r.alert = True
            r.label(text=m, icon='DOT')


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Setup)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Setup)
