import os

import bpy

from ... import identity as idn
from . import bake, operators

ICON = {"ALB": 'IMAGE_RGB', "NOR": 'NORMALS_FACE', "SHD": 'SHADING_RENDERED',
        "TEX": 'TEXTURE'}


def draw_texture(layout, obj, kind):
    """[name: shows it in the UV editor] [path] [load] [folder] [refresh]"""
    img = idn.image(obj, kind)
    path = idn.abspath(img) if img else ""
    missing = img is not None and not os.path.isfile(path)
    split = layout.split(factor=0.3, align=True)
    left = split.row(align=True)
    left.alignment = 'LEFT'

    def op(row, idname, icon, text="", **kw):
        o = row.operator(idname, text=text, icon=icon, **kw)
        o.object_name, o.kind = obj.name, kind

    if img is not None:
        op(left, "ppd.show_image", ICON[kind], text=kind, emboss=False)
    else:
        left.label(text=kind, icon=ICON[kind])
    row = split.row(align=True)
    name = row.row(align=True)
    name.alert = missing
    if img is None:
        name.active = False
        name.label(text="(none yet)")
    else:
        folder = os.path.basename(os.path.dirname(path))
        name.label(text=f"{folder}/{os.path.basename(path)}" + (" not found" if missing else ""))
    op(row, "ppd.load_texture", 'IMPORT')
    op(row, "ppd.open_folder", 'FILE_FOLDER')
    op(row, "ppd.reload_texture", 'FILE_REFRESH')


class PINKPUNKDELTA_INTERNAL_PT_Bakenlink(bpy.types.Panel):
    bl_label = "02.Bake & Link Texture"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_bakenlink"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_main"
    bl_order = 1

    def draw(self, context):
        layout = self.layout
        objs = sorted(idn.objects(), key=lambda o: o.name)
        if operators.busy:
            layout.label(text=operators.busy + " - Esc stops", icon='RENDER_STILL')
        if not objs:
            layout.label(text="Set up an object in 01 first", icon='INFO')
            return
        for o in objs:
            header, body = layout.panel("PPD_BAKE_" + o.ppd.key, default_closed=False)
            header.label(text=o.name, icon='MESH_DATA')
            if body is None:
                continue
            box = body.box()
            row = box.row(align=True)
            row.prop(o.ppd, "original", text="")
            sub = row.row(align=True)
            sub.ui_units_x = 5
            sub.prop(o.ppd, "cage")
            col = box.column(align=True)
            for k in idn.KINDS:
                draw_texture(col, o, k)
            why = bake.problem(o)
            row = box.row(align=True)
            row.enabled = not why
            op = row.operator("ppd.bake", text=why or "Bake ALB + NOR", icon='RENDER_STILL')
            op.object_name = o.name
            if not why:
                for k in idn.BAKED:
                    op = row.operator("ppd.bake", text=k)
                    op.object_name, op.which = o.name, k
        if len(objs) > 1:
            layout.operator("ppd.bake", text="Bake All", icon='RENDER_STILL').object_name = ""


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Bakenlink)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Bakenlink)
