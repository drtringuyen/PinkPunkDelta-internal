"""Who an object is: the data stored on it, and every name that follows from it.

Object    <Central>.<part>              Central = the .blend's file name
Material  MAT_<Central>.<part>
Textures  ALB_ / NOR_ / SHD_ / TEX_<Central>.<part>.png in //textures
"""
import os
import re
import uuid

import bpy
from bpy.props import (BoolProperty, FloatProperty, FloatVectorProperty, PointerProperty,
                       StringProperty)

KINDS = ("ALB", "NOR", "SHD", "TEX")
BAKED = ("ALB", "NOR")          # SHD / TEX only ever come from files
KIND_LABEL = {"ALB": "Albedo", "NOR": "Normal", "SHD": "Shadow", "TEX": "Texture layer"}
SIZE = 8192                     # every texture is 8K
TEX_FOLDER = "textures"
UV_BAKE = "uv_normal"


def colorspace(kind):
    return 'Non-Color' if kind == "NOR" else 'sRGB'


def _poll_original(self, o):
    return o.type == 'MESH' and o != self.id_data


class PPD_ObjectData(bpy.types.PropertyGroup):
    is_setup: BoolProperty(default=False)
    key: StringProperty()           # never changes: tells a duplicate from its source
    part: StringProperty()          # <object_name>
    synced: StringProperty()        # the full name everything was last named after
    original: PointerProperty(
        name="Original", type=bpy.types.Object, poll=_poll_original,
        description="The mesh ALB and NOR are baked from")
    material: PointerProperty(type=bpy.types.Material)
    alb: PointerProperty(type=bpy.types.Image)
    nor: PointerProperty(type=bpy.types.Image)
    shd: PointerProperty(type=bpy.types.Image)
    tex: PointerProperty(type=bpy.types.Image)
    cage: FloatProperty(name="Cage", default=0.02, min=0.0, soft_max=0.5, subtype='DISTANCE',
                        description="How far outside the surface the bake rays start")
    canvas: StringProperty(description="Procreate canvas linked to this object by hand")


class PPD_SceneData(bpy.types.PropertyGroup):
    central: StringProperty()           # the Central everything is named after
    central_path: StringProperty()      # the .blend that Central was read from
    gizmo_offset: FloatVectorProperty(name="Position", size=2, subtype='XYZ',
                                      unit='LENGTH', default=(0.0, 0.0))


def scene_data():
    """One per file: the first scene's, so several scenes cannot disagree."""
    return bpy.data.scenes[0].ppd


def file_central(path=None):
    path = bpy.data.filepath if path is None else path
    return os.path.splitext(os.path.basename(path))[0] if path else ""


def central():
    return scene_data().central or file_central()


def objects():
    return [o for o in bpy.data.objects
            if o.type == 'MESH' and o.library is None and o.ppd.is_setup]


def safe_part(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "Part"


def part_of(name, *centrals):
    """The part in an object name: 'Tractor.Wheel' -> 'Wheel', 'Wheel' -> 'Wheel'."""
    for c in centrals:
        if c and name.lower().startswith(c.lower() + "."):
            name = name[len(c) + 1:]
            break
    return safe_part(name)


def full_name(part, c=None):
    return f"{c or central()}.{part}"


def image(obj, kind):
    return getattr(obj.ppd, kind.lower())


def set_image(obj, kind, img):
    setattr(obj.ppd, kind.lower(), img)


def tex_dir(blend=None):
    blend = blend or bpy.data.filepath
    return os.path.join(os.path.dirname(blend), TEX_FOLDER) if blend else ""


def tex_path(obj, kind):
    return os.path.join(tex_dir(), f"{kind}_{obj.name}.png")


def psd_path(obj, name=None):
    return os.path.join(tex_dir(), f"{name or obj.name}.psd")


def abspath(img):
    fp = img.filepath_raw or img.filepath
    return os.path.normpath(bpy.path.abspath(fp, library=img.library)) if fp else ""


def relpath(path):
    try:
        return bpy.path.relpath(path)
    except ValueError:          # another drive
        return path


def bake_uv(obj):
    uvs = obj.data.uv_layers
    uv = uvs.get(UV_BAKE) or uvs.active
    return uv.name if uv else ""


def new_key():
    return uuid.uuid4().hex


CLASSES = (PPD_ObjectData, PPD_SceneData)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.ppd = PointerProperty(type=PPD_ObjectData)
    bpy.types.Scene.ppd = PointerProperty(type=PPD_SceneData)


def unregister():
    del bpy.types.Scene.ppd
    del bpy.types.Object.ppd
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
