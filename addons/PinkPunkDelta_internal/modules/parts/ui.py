import bpy

from ... import bands
from . import operators as ops


class PINKPUNKDELTA_INTERNAL_PT_Parts(bpy.types.Panel):
    bl_label = "04.Split Parts & Ramps"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_parts"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 3

    def draw(self, context):
        layout = self.layout
        obj = ops.active(context)
        if obj is None:
            layout.label(text="Select a set-up object", icon='INFO')
            return
        d = obj.ppd
        edit = context.mode == 'EDIT_MESH'
        layout.label(text=obj.name, icon='MESH_DATA')
        n = ops.counts(obj)
        for p in d.parts:
            header, body = layout.panel(f"PPD_PART_{d.key}_{p.pid}", default_closed=False)
            row = header.row(align=True)
            row.prop(p, "name", text="")
            sub = row.row(align=True)
            sub.enabled = edit
            o = sub.operator("ppd.part_assign", text="", icon='ADD')
            o.pid = p.pid
            o = sub.operator("ppd.part_assign", text="", icon='REMOVE')
            o.pid, o.remove = p.pid, True
            o = sub.operator("ppd.part_select", text="", icon='RESTRICT_SELECT_OFF')
            o.pid = p.pid
            o = sub.operator("ppd.part_select", text="", icon='RESTRICT_SELECT_ON')
            o.pid, o.deselect = p.pid, True
            row.operator("ppd.part_delete", text="", icon='X').pid = p.pid
            if body is None:
                continue
            col = body.column()
            r = bands.ramp(obj, p.pid)
            if r is None:
                col.alert = True
                col.label(text="No ramp: Check All Links in 01", icon='ERROR')
                continue
            col.template_color_ramp(r, "color_ramp", expand=False)
            row = col.row(align=True)
            row.label(text="" if n is None else f"{n.get(p.pid, 0)} faces")
            row.prop(p, "ignore_alb", toggle=True)
            if len(d.parts) > 1:
                row.operator("ppd.part_copy_ramp", text="", icon='COPYDOWN').pid = p.pid
        row = layout.row(align=True)
        row.operator("ppd.part_add", icon='ADD')
        if d.bands is not None:
            row.operator("ppd.part_refresh", text="", icon='FILE_REFRESH')
        if len(d.parts) and n is not None:
            row = layout.row(align=True)
            row.label(text=f"{n.get(0, 0)} faces in no part: plain NPR")
            sub = row.row(align=True)
            sub.enabled = edit
            sub.operator("ppd.part_select", text="", icon='RESTRICT_SELECT_OFF').pid = 0
        if not edit:
            layout.label(text="Edit Mode: select faces, then Add or +", icon='INFO')


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Parts)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Parts)
