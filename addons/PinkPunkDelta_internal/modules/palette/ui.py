"""The Concept Palette lives in the Image Editor's sidebar (N, tab PPD), in every mode: View,
UV and Paint. It reads the picture that editor shows. Drag a swatch from there onto a ramp
block in the 3D view's 04.Split Parts & Ramps."""
import bpy

PER_ROW = 8


class PINKPUNKDELTA_INTERNAL_PT_Palette(bpy.types.Panel):
    bl_label = "Concept Palette"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_palette"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "PPD"

    def draw(self, context):
        layout = self.layout
        pal = context.scene.ppd_palette
        shown = context.space_data.image
        row = layout.row(align=True)
        if shown is None:
            row.label(text="Open a concept picture here", icon='INFO')
        else:
            row.label(text=shown.name, icon='IMAGE_DATA')
        row = layout.row(align=True)
        row.prop(pal, "count")
        row.operator("ppd.palette_pick", text="Pick Colors", icon='EYEDROPPER')
        if pal.image is not None and pal.image != shown:
            sub = layout.row()
            sub.active = False
            sub.label(text=f"These colors are from {pal.image.name}")
        if not len(pal.colors):
            return
        col = layout.column(align=True)
        col.scale_y = 1.5
        colors = list(pal.colors)
        for i in range(0, len(colors), PER_ROW):
            row = col.row(align=True)
            chunk = colors[i:i + PER_ROW]
            for c in chunk:
                row.prop(c, "color", text="")
            for _ in range(PER_ROW - len(chunk)):       # the last row keeps the cell size
                row.label(text="")
        sub = layout.column()
        sub.active = False
        sub.label(text="Drag a color onto a ramp block", icon='INFO')
        sub.label(text="(3D view: PPD > 04.Split Parts)")


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Palette)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Palette)
