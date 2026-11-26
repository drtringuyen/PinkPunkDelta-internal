import bpy

from ... import identity as idn


class PINKPUNKDELTA_INTERNAL_PT_Qol(bpy.types.Panel):
    bl_label = "06.Quality of Life"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_qol"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        q = context.scene.ppd_qol
        from ... import bands
        if any(bands.outdated(o) for o in idn.objects()):
            box = layout.box()
            box.alert = True
            box.label(text="Some objects have the older shader", icon='ERROR')
            box.operator("ppd.shader_update", icon='FILE_REFRESH')
        row = layout.row(align=True)
        row.prop(q, "scope", expand=True)
        row.operator("ppd.qol_apply", text="", icon='FILE_REFRESH')
        from .operators import targets
        if not targets(context):
            r = layout.row()
            r.alert = True
            r.label(text="No set-up object selected: these do nothing", icon='ERROR')
        row = layout.row(align=True)
        row.prop(q, "light_color", toggle=True, icon='LIGHT')
        row.prop(q, "outline", toggle=True, icon='MOD_WIREFRAME')
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Exact ramp colors", icon='COLOR')
        r = col.row(align=True)
        r.prop(q, "exposure", slider=True)
        vt = context.scene.view_settings.view_transform
        r.prop(q, "true_colors", toggle=True, text="True Colors" if vt == 'Standard' else vt,
               icon='COLOR')
        sub = col.row()
        sub.active = False
        sub.label(text="Every light counts, averaged; Exposure scales them")
        col = layout.column(align=True)
        col.label(text="Layers")
        row = col.row(align=True)
        row.active = q.solo == '0'
        for k in ("base", "alb", "tex", "nor", "shd"):
            row.prop(q, "show_" + k, toggle=True)
        col.row(align=True).prop(q, "solo", expand=True)
        layout.separator()
        layout.operator("ppd.clean_files", icon='TRASH')


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Qol)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Qol)
