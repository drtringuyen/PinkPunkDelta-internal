"""Who an object is: the data stored on it, and every name that follows from it.

Object    <Central>.<part>              Central = the .blend's file name
Material  MAT_<Central>.<part>
Textures  ALB_ / NOR_ / SHD_ / TEX_<Central>.<part>.png in //textures
"""
import os
import re
import uuid

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty,
                       FloatVectorProperty, PointerProperty, StringProperty)

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


def _bands_changed(self, context):
    from . import bands
    bands.write_part(self)


def _order(self, context):
    """The borders stay in order: Shadow | Mid | High. Gloss is a highlight on its own scale,
    its border independent of these."""
    b1 = min(self.border_1, 0.98)
    b2 = min(max(self.border_2, b1 + 0.01), 0.99)
    for name, v in (("border_1", b1), ("border_2", b2)):
        if abs(getattr(self, name) - v) > 1e-6:
            setattr(self, name, v)
    _bands_changed(self, context)


def _color(name, default):
    return FloatVectorProperty(name=name, subtype='COLOR', size=3, min=0.0, max=1.0,
                               default=default, update=_bands_changed)


def _border(name, default, description):
    return FloatProperty(name=name, min=0.0, max=1.0, default=default, update=_order,
                         description=description + ". Drag left or right", step=1,
                         precision=2)


class PPD_Part(bpy.types.PropertyGroup):
    """A split part: the faces whose PPD_PART is `pid` (0 = the faces in no part). `name` is
    only a label. Its light spectrum: 1-3 shades (Shadow, Mid, High), then Gloss."""
    pid: IntProperty()
    shades: IntProperty(name="Shades", min=1, max=3, default=3, update=_bands_changed,
                        description="1 = Mid; 2 = Shadow, Mid; 3 = Shadow, Mid, High")
    shadow: _color("Shadow", (0.22, 0.22, 0.24))
    mid: _color("Mid", (0.70, 0.70, 0.70))
    high: _color("High", (0.92, 0.92, 0.90))
    gloss: _color("Gloss", (1.0, 1.0, 1.0))
    border_1: _border("Shadow | Mid", 0.30, "Where Shadow ends and Mid begins in the light")
    border_2: _border("Mid | High", 0.70, "Where Mid ends and High begins in the light")
    gloss_at: _border("Gloss starts", 0.90, "Where the highlight starts: higher is a smaller "
                      "Gloss spot, lower a bigger one")


BLEND_ITEMS = [(k, k.replace("_", " ").title(), "") for k in (
    "MIX", "MULTIPLY", "SCREEN", "OVERLAY", "ADD", "SUBTRACT", "DARKEN", "LIGHTEN", "DODGE",
    "BURN", "SOFT_LIGHT", "LINEAR_LIGHT", "DIFFERENCE", "EXCLUSION", "DIVIDE", "HUE",
    "SATURATION", "COLOR", "VALUE")]


def _blend_changed(self, context):
    from . import bands
    bands.write_blend(self.id_data)


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
    parts: CollectionProperty(type=PPD_Part)
    base: PointerProperty(type=PPD_Part)                    # the faces in no part
    bands: PointerProperty(type=bpy.types.NodeTree)         # its own NPR_<full name>
    npr_source: PointerProperty(type=bpy.types.NodeTree)    # unused since the shader v2
    # how ALB / TEX were blended in Procreate (the group's mode and opacity), applied here
    alb_blend: EnumProperty(name="ALB Blend", items=BLEND_ITEMS, default='MIX',
                            update=_blend_changed)
    alb_opacity: FloatProperty(name="ALB Opacity", min=0.0, max=1.0, default=1.0,
                               subtype='FACTOR', update=_blend_changed)
    tex_blend: EnumProperty(name="TEX Blend", items=BLEND_ITEMS, default='MIX',
                            update=_blend_changed)
    tex_opacity: FloatProperty(name="TEX Opacity", min=0.0, max=1.0, default=1.0,
                               subtype='FACTOR', update=_blend_changed)
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


KEY_LEN = 6


def short_key(obj):
    return obj.ppd.key[:KEY_LEN]


def canvas_name(obj):
    """The Procreate canvas: the object's name to read, its key to find it again after a
    rename: 'Tractor.Wheel_k3f9a2c'."""
    return f"{obj.name}_k{short_key(obj)}"


KEY_RE = re.compile(r"_k([0-9a-f]{%d,32})(?![0-9a-f])" % KEY_LEN, re.I)
UV_KEY_RE = re.compile(r"(?<![0-9a-z])k([0-9a-f]{%d,32})(?![0-9a-z])" % KEY_LEN, re.I)


def key_in(text, layer=False):
    m = (UV_KEY_RE if layer else KEY_RE).search(text or "")
    return m.group(1).lower() if m else ""


def by_key(short):
    """The set-up object whose key starts with `short`, None when none or several do."""
    hits = [o for o in objects() if short and o.ppd.key.startswith(short)]
    return hits[0] if len(hits) == 1 else None


def all_parts(obj):
    """The faces in no part first (pid 0), then the split parts."""
    d = obj.ppd
    return [d.base, *d.parts]


def mid_index(part):
    return 0 if part.shades == 1 else 1


def shade_colors(part):
    if part.shades == 1:
        return [part.mid]
    return [part.shadow, part.mid] + ([part.high] if part.shades == 3 else [])


CLASSES = (PPD_Part, PPD_ObjectData, PPD_SceneData)


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
