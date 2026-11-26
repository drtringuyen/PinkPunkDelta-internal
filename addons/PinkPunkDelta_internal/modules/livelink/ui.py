import os

import bpy

from ... import identity as idn
from ... import module_manager
from ..bakenlink import ui as bake_ui
from . import core, operators, pc, setup_ui


def textures_loaded():
    return module_manager.is_loaded("bakenlink")


class PINKPUNKDELTA_INTERNAL_PT_Livelink(bpy.types.Panel):
    bl_label = "03.LiveLink"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_livelink"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        if core.server is None:
            box.operator("ppd.link_start", icon='PLAY')
        else:
            row = box.row()
            row.label(text="Listening", icon='CHECKMARK')
            row.operator("ppd.link_stop", icon='PAUSE')
            box.template_icon(icon_value=operators.qr_icon(), scale=9.0)
            row = box.row(align=True)
            row.operator("ppd.link_qr", icon='FULLSCREEN_ENTER')
            row.operator("ppd.link_copy", text="Copy", icon='COPYDOWN')
            row.operator("ppd.link_guide", icon='HELP')
            col = box.column(align=True)
            col.label(text="Only if the iPad cannot find this PC by name:", icon='INFO')
            try:
                col.prop(context.window_manager, "ppd_link_host", text="PC Address",
                         placeholder=core.pc_name())
            except TypeError:           # a Blender without placeholders
                col.prop(context.window_manager, "ppd_link_host", text="PC Address")
            r = box.row(align=True)
            r.label(text=core.watch_folder(), icon='FILE_FOLDER')
            r.operator("ppd.open_share", text="", icon='FOLDER_REDIRECT')
        if pc.supported():
            setup_ui.draw_account(layout, context)
        if textures_loaded():
            bake_ui.draw_busy(layout)

        if core.inbox:
            box = layout.box()
            box.label(text=f"Received, no object yet ({len(core.inbox)})", icon='IMPORT')
            for it in core.inbox:
                row = box.row(align=True)
                row.label(text=it["stem"])
                row.operator("ppd.inbox_assign", text="Assign", icon='LINKED').item_id = it["id"]
                row.operator("ppd.inbox_drop", text="", icon='X').item_id = it["id"]

        row = layout.row()
        row.operator("ppd.prepare_psd", text="Send Selected to iPad", icon='EXPORT')
        textures = module_manager.is_loaded("bakenlink")
        for o in sorted(idn.objects(), key=lambda o: o.name):
            header, body = layout.panel("PPD_LINK_" + o.ppd.key, default_closed=False)
            header.label(text=o.name, icon='MESH_DATA')
            if body is None:
                continue
            col = body.box().column(align=True)
            for k in idn.KINDS:
                if textures:
                    bake_ui.draw_texture(col, o, k)
                else:
                    img = idn.image(o, k)
                    col.label(text=f"{k}  {img.name if img else '(none yet)'}")
            row = col.row(align=True)
            row.operator("ppd.prepare_psd", icon='EXPORT').object_name = o.name
            if textures:
                sub = row.row(align=True)
                sub.enabled = o.ppd.original is not None
                op = sub.operator("ppd.bake", text="Rebake & Send", icon='RENDER_STILL')
                op.object_name, op.send = o.name, True
            path = core.sent(o)
            if path:
                sub = col.row()
                sub.active = False
                sub.label(text=f"{core.OUTBOX}/{os.path.basename(path)}", icon='CHECKMARK')
            if o.ppd.canvas:
                col.label(text=f"Canvas: {o.ppd.canvas}", icon='BRUSH_DATA')

        if setup_ui.debug(context):
            col = layout.box().column(align=True)
            col.scale_y = 0.75
            col.label(text="Activity", icon='INFO')
            for m in list(core.log_lines)[:6]:
                col.label(text=m)


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Livelink)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Livelink)
