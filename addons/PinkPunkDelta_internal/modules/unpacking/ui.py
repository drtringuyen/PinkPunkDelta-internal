import bpy

from ... import identity as idn


def _active(context):
    o = context.active_object
    return o if o is not None and o in idn.objects() else None


class PPD_OT_blend_reset(bpy.types.Operator):
    """ALB and TEX back to Normal at 100 %"""
    bl_idname = "ppd.blend_reset"
    bl_label = "Reset Blending"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        d = _active(context).ppd
        d.alb_blend = d.tex_blend = 'MIX'
        d.alb_opacity = d.tex_opacity = 1.0
        return {'FINISHED'}


class PINKPUNKDELTA_INTERNAL_PT_Unpacking(bpy.types.Panel):
    bl_label = "05.Unpacking"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_unpacking"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        o = _active(context)
        if o is None:
            layout.label(text="Select a set-up object", icon='INFO')
            return
        d = o.ppd
        col = layout.column(align=True)
        col.label(text="How the groups blend, as in Procreate:")
        for k in ("alb", "tex"):
            row = col.row(align=True)
            row.label(text=k.upper())
            row.prop(d, k + "_blend", text="")
            row.prop(d, k + "_opacity", text="")
        layout.operator("ppd.blend_reset", icon='LOOP_BACK')
        sub = layout.column()
        sub.active = False
        sub.label(text="Inside a group, layers, masks and")
        sub.label(text="clipping are merged when it arrives.")


CLASSES = (PPD_OT_blend_reset, PINKPUNKDELTA_INTERNAL_PT_Unpacking)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
