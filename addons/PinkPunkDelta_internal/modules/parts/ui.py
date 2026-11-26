import bpy

from ... import bands
from ... import identity as idn
from . import operators as ops

MIN_BLOCK = 0.08        # a narrow band stays wide enough to click (bar width unknown)
HANDLE = 0.075          # a border handle's share of the bar
GLOSS_SHARE = 0.34      # Gloss color + slider beside the bar
MIN_UNITS = 1.0         # narrowest block or handle in UI units: Blender piles narrower ones up
SIDE_UNITS = 5.0        # panel margins, box padding and the + - beside the bar, in UI units


def spectrum(part):
    """[(property, width)] Shadow, Mid, High as the borders place them. Gloss is not on this
    scale (it follows the highlight's strength, not the light's), so it is apart."""
    b1, b2 = part.border_1, part.border_2
    if part.shades == 3:
        return [("shadow", b1), ("mid", b2 - b1), ("high", 1.0 - b2)]
    if part.shades == 2:
        return [("shadow", b1), ("mid", 1.0 - b1)]
    return [("mid", 1.0)]


def bar_units(context):
    """How many UI units wide the bar is drawn, 0 if unknown."""
    region = getattr(context, "region", None) if context else None
    if region is None or region.width <= 0:
        return 0.0
    unit = 20.0 * context.preferences.system.ui_scale
    return max(0.0, region.width / unit - SIDE_UNITS) * (1.0 - GLOSS_SHARE)


def bar(part, units=0.0):
    """[(property, width, is a handle)]: the color blocks with a border handle between
    each two. Widths add up to 1. With the bar's width in UI units, no block or handle is
    narrower than MIN_UNITS: Blender lays narrower buttons over each other, so a border
    dragged far to one side would hide the blocks and handles next to it."""
    blocks = spectrum(part)
    borders = {"shadow": "border_1", "mid": "border_2"}
    n = len(blocks)
    low = MIN_UNITS / units if units > 0 else MIN_BLOCK
    handle = max(HANDLE, low) if units > 0 else HANDLE
    if n * low + (n - 1) * handle > 1.0:            # too narrow: all the same width
        low = handle = 1.0 / (2 * n - 1)
    spare = 1.0 - (n - 1) * handle - n * low        # shared out as the borders place them
    out = []
    for name, w in blocks:
        out.append((name, low + spare * max(w, 0.0), False))
        if name in borders and name != blocks[-1][0]:
            out.append((borders[name], handle, True))
    return out


def _split_row(layout, items, draw):
    """items laid out left to right at their widths (they add up to 1)."""
    cur = layout
    for i, it in enumerate(items[:-1]):
        rest = sum(x[1] for x in items[i:])
        sp = cur.split(factor=min(1.0, it[1] / rest), align=True)
        draw(sp, it)
        cur = sp.row(align=True)
    draw(cur, items[-1])


def draw_bands(layout, part, context=None):
    """[+][-] [Shadow]|[Mid]|[High]   [Gloss ====][Gloss]
    Click a block for its color, drag a | handle left or right to move that border."""
    row = layout.row(align=True)
    row.scale_y = 1.4                   # + and - as tall as the bar
    sub = row.row(align=True)
    sub.scale_x = 0.9
    o = sub.operator("ppd.part_band", text="", icon='ADD')
    o.pid = part.pid
    o = sub.operator("ppd.part_band", text="", icon='REMOVE')
    o.pid, o.remove = part.pid, True
    sp = row.split(factor=1.0 - GLOSS_SHARE, align=True)
    strip = sp.row(align=True)

    def draw(where, it):
        where.prop(part, it[0], text="")
    _split_row(strip, bar(part, bar_units(context)), draw)
    gloss = sp.row(align=True)
    gloss.prop(part, "gloss_at", text="Gloss", slider=True)
    sw = gloss.row(align=True)          # the Gloss color last, at the bright end
    sw.ui_units_x = 1.3
    sw.prop(part, "gloss", text="")


def draw_header(row, part, auto=True):
    """[main color] name ... : the main color first, then the ramp from the palette."""
    sw = row.row(align=True)
    sw.ui_units_x = 1.6
    sw.prop(part, "mid", text="")
    row.prop(part, "name", text="") if part.pid else row.label(text="No part")
    if auto:
        row.operator("ppd.part_auto", text="", icon='SHADERFX').pid = part.pid


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
        if bands.outdated(obj):
            box = layout.box()
            box.alert = True
            box.label(text="This object has the shader of an older version", icon='ERROR')
            box.operator("ppd.shader_update", icon='FILE_REFRESH')
        row = layout.row(align=True)
        row.label(text=obj.name, icon='MESH_DATA')
        row.operator("ppd.part_refresh", text="", icon='FILE_REFRESH')
        for p in d.parts:
            col = layout.box().column()   # not aligned: Blender would merge the header and bar rows
            row = col.row(align=True)
            draw_header(row, p)
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
            draw_bands(col, p, context)

        col = layout.box().column()   # not aligned: Blender would merge the header and bar rows
        row = col.row(align=True)
        draw_header(row, d.base)
        if len(d.parts):
            sub = row.row(align=True)
            sub.enabled = edit
            sub.operator("ppd.part_select", text="", icon='RESTRICT_SELECT_OFF').pid = 0
        draw_bands(col, d.base, context)

        layout.operator("ppd.part_add", icon='ADD')
        if not edit:
            layout.label(text="Edit Mode: select faces, then Add or +", icon='INFO')


def register():
    bpy.utils.register_class(PINKPUNKDELTA_INTERNAL_PT_Parts)


def unregister():
    bpy.utils.unregister_class(PINKPUNKDELTA_INTERNAL_PT_Parts)
