"""The concept palette: a picture's main colors, kept on the scene. The swatches are ordinary
color fields, so Blender lets you drag one onto any other color - a ramp block included."""
import bpy
import numpy as np
from bpy.props import (CollectionProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty)

from . import extract

READ_SIZE = 256         # the picture is read at most this big: plenty for its main colors


def pixels(img):
    """(rgba floats, are they sRGB-encoded) of a small copy of the picture."""
    if img.size[0] == 0 or img.size[1] == 0:
        img.reload()
    w, h = img.size
    if not w or not h:
        raise RuntimeError(f"{img.name} has no pixels (file missing?)")
    work = img.copy()
    try:
        s = min(1.0, READ_SIZE / max(w, h))
        if s < 1.0:
            work.scale(max(1, round(w * s)), max(1, round(h * s)))
        buf = np.empty(len(work.pixels), np.float32)
        work.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(work)
    srgb = not img.is_float and img.colorspace_settings.name not in (
        'Non-Color', 'Linear Rec.709', 'Linear', 'Raw')
    return buf.reshape(-1, 4), srgb


def pick(scene):
    """The picture's main colors into the palette. Returns how many."""
    pal = scene.ppd_palette
    if pal.image is None:
        return 0
    rgba, srgb = pixels(pal.image)
    found = extract.palette(rgba, pal.count, srgb)
    pal.colors.clear()
    for rgb, share in found:
        c = pal.colors.add()
        c.color, c.share = rgb, share
    return len(found)


def _count_changed(self, context):
    if self.image is not None:
        try:
            pick(context.scene)
        except RuntimeError:
            pass


def _image_changed(self, context):
    _count_changed(self, context)


class PPD_PaletteColor(bpy.types.PropertyGroup):
    color: FloatVectorProperty(name="Color", subtype='COLOR', size=3, min=0.0, max=1.0,
                               description="Drag it onto a ramp block (or any color)")
    share: FloatProperty()      # how much of the picture it covers


class PPD_Palette(bpy.types.PropertyGroup):
    image: PointerProperty(name="Concept", type=bpy.types.Image, update=_image_changed,
                           description="The picture to take the colors from")
    count: IntProperty(name="Colors", min=2, max=32, default=8, update=_count_changed,
                       description="How many main colors to take")
    colors: CollectionProperty(type=PPD_PaletteColor)


def _shown(context):
    space = context.space_data
    return space.image if space is not None and space.type == 'IMAGE_EDITOR' else None


class PPD_OT_palette_pick(bpy.types.Operator):
    """Take the main colors of the picture this Image Editor shows, similar ones side by side"""
    bl_idname = "ppd.palette_pick"
    bl_label = "Pick Colors"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if _shown(context) is None and context.scene.ppd_palette.image is None:
            cls.poll_message_set("Open a concept picture in the Image Editor")
            return False
        return True

    def execute(self, context):
        pal = context.scene.ppd_palette
        shown = _shown(context)
        if shown is not None and pal.image != shown:
            pal.image = shown           # picks on its own
            if len(pal.colors):
                return {'FINISHED'}
        try:
            n = pick(context.scene)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        if not n:
            self.report({'WARNING'}, "The picture is transparent")
            return {'CANCELLED'}
        return {'FINISHED'}


class PPD_OT_palette_from_editor(bpy.types.Operator):
    """Use the picture shown in an Image Editor as the concept"""
    bl_idname = "ppd.palette_from_editor"
    bl_label = "From Image Editor"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def shown(context):
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'IMAGE_EDITOR' and a.spaces.active.image is not None:
                    return a.spaces.active.image
        return None

    @classmethod
    def poll(cls, context):
        if cls.shown(context) is None:
            cls.poll_message_set("No Image Editor shows a picture")
            return False
        return True

    def execute(self, context):
        context.scene.ppd_palette.image = self.shown(context)
        return {'FINISHED'}


CLASSES = (PPD_PaletteColor, PPD_Palette, PPD_OT_palette_pick, PPD_OT_palette_from_editor)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.ppd_palette = PointerProperty(type=PPD_Palette)


def unregister():
    del bpy.types.Scene.ppd_palette
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
