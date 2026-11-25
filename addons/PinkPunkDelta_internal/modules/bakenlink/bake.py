"""ALB and NOR of a set-up object, baked 8K from its Original (Cycles, Selected to Active)."""
import os
import time
from contextlib import contextmanager

import bpy
import numpy as np

from ... import identity as idn
from ... import links, material

TMP = "PPD_BAKE_TMP"
MARGIN = 32
_RENDER = ("engine",)
_CYCLES = ("device", "samples", "bake_type", "use_denoising", "use_adaptive_sampling")
_BAKE = ("margin", "margin_type", "target", "use_clear", "use_selected_to_active", "use_cage",
         "cage_extrusion", "max_ray_distance", "normal_space", "normal_r", "normal_g",
         "normal_b")


def problem(obj):
    """Why obj cannot be baked ('' = it can)."""
    src = obj.ppd.original
    if not bpy.data.filepath:
        return "Save the .blend first"
    if src is None:
        return "Pick the Original"
    if src == obj or src.type != 'MESH' or not len(src.data.polygons):
        return "The Original has no mesh"
    if not len(obj.data.polygons):
        return "The object has no faces yet"
    if not idn.bake_uv(obj):
        return "No UV map - unwrap it first"
    return ""


@contextmanager
def _state(scene):
    holders = ((scene.render, _RENDER), (scene.cycles, _CYCLES), (scene.render.bake, _BAKE))
    old = [(h, {a: getattr(h, a) for a in attrs if hasattr(h, a)}) for h, attrs in holders]
    try:
        yield
    finally:
        for h, vals in old:
            for a, v in vals.items():
                try:
                    setattr(h, a, v)
                except (AttributeError, TypeError, ValueError):
                    pass


@contextmanager
def _shown(context, objs):
    """Both objects visible, renderable and alone selected - hidden ones and those in an
    excluded collection too. Everything comes back."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    vl, root = context.view_layer, context.scene.collection
    old_sel, old_active = list(context.selected_objects), vl.objects.active
    flags, linked = [], []
    try:
        for o in objs:
            if o.name not in root.objects:
                root.objects.link(o)
                linked.append(o)
        vl.update()
        for o in objs:
            flags.append((o, o.hide_get(), o.hide_viewport, o.hide_render, o.hide_select))
            o.hide_viewport = o.hide_render = o.hide_select = False
            o.hide_set(False)
        for o in old_sel:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        vl.objects.active = objs[0]
        yield
    finally:
        for o in list(context.selected_objects):
            o.select_set(False)
        for o, hidden, hv, hr, hs in flags:
            o.hide_set(hidden)
            o.hide_viewport, o.hide_render, o.hide_select = hv, hr, hs
        for o in linked:
            root.objects.unlink(o)
        vl.update()
        for o in old_sel:
            if o.name in vl.objects:
                o.select_set(True)
        if old_active is not None and old_active.name in vl.objects:
            vl.objects.active = old_active


@contextmanager
def _plain_target(obj):
    """Geometry nodes off while baking: the tubes they add have no UVs."""
    old = [(m, m.show_render, m.show_viewport) for m in obj.modifiers if m.type == 'NODES']
    try:
        for m, _r, _v in old:
            m.show_render = m.show_viewport = False
        yield
    finally:
        for m, r, v in old:
            m.show_render, m.show_viewport = r, v


@contextmanager
def _uv_active(obj, name):
    uvs = obj.data.uv_layers
    prev = uvs.active.name
    uvs.active = uvs[name]
    try:
        yield
    finally:
        if uvs.get(prev):
            uvs.active = uvs[prev]


@contextmanager
def _target_nodes(obj, img):
    """An active image node on every material of the object (a slot without one borrows the
    object's MAT_)."""
    added, filled = [], []
    try:
        for i, s in enumerate(obj.material_slots):
            if s.material is None:
                s.material = obj.ppd.material
                filled.append(i)
        for mat in {s.material for s in obj.material_slots}:
            nt = mat.node_tree
            old = nt.nodes.active
            n = nt.nodes.new("ShaderNodeTexImage")
            n.name, n.image = TMP, img
            nt.nodes.active = n
            added.append((nt, n, old))
        yield
    finally:
        for nt, n, old in added:
            nt.nodes.remove(n)
            nt.nodes.active = old
        for i in filled:
            obj.material_slots[i].material = None


def _color(nt):
    """What a material shows as color: (linked socket, None) or (None, value)."""
    kinds = (('BSDF_PRINCIPLED', "Base Color"), ('EMISSION', "Color"), ('BSDF_DIFFUSE', "Color"))
    for kind, sock in kinds:
        for n in nt.nodes:
            if n.type == kind and n.inputs[sock].links:
                return n.inputs[sock].links[0].from_socket, None
    for n in nt.nodes:          # NPR and other groups: their Base
        if n.type == 'GROUP':
            s = n.inputs.get("Base") or n.inputs.get("Base Color") or n.inputs.get("Color")
            if s is not None and s.type == 'RGBA' and s.links:
                return s.links[0].from_socket, None
    for kind, sock in kinds:
        for n in nt.nodes:
            if n.type == kind:
                return None, tuple(n.inputs[sock].default_value)
    for n in nt.nodes:
        if n.type == 'TEX_IMAGE' and n.image and \
                n.image.colorspace_settings.name != 'Non-Color':
            return n.outputs[0], None
    return None, (0.8, 0.8, 0.8, 1.0)


@contextmanager
def _as_emission(src):
    """The Original's materials show their color unlit: a metal would bake black as Diffuse."""
    done = []
    try:
        for mat in {s.material for s in src.material_slots if s.material}:
            nt = mat.node_tree
            if nt is None:
                continue
            outs = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'
                    and n.target in {'ALL', 'CYCLES'}]
            out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
            if out is None:
                continue
            surf = out.inputs["Surface"]
            old = surf.links[0].from_socket if surf.links else None
            sock, value = _color(nt)
            emit = nt.nodes.new("ShaderNodeEmission")
            if sock is not None:
                nt.links.new(sock, emit.inputs["Color"])
            else:
                emit.inputs["Color"].default_value = value
            nt.links.new(emit.outputs[0], surf)
            done.append((nt, emit, surf, old))
        yield
    finally:
        for nt, emit, surf, old in done:
            nt.nodes.remove(emit)
            if old is not None:
                nt.links.new(old, surf)


def _configure(scene, kind):
    scene.render.engine = 'CYCLES'
    c = scene.cycles
    prefs = bpy.context.preferences.addons.get("cycles")
    gpu = prefs is not None and prefs.preferences.compute_device_type != 'NONE'
    c.device = 'GPU' if gpu else 'CPU'
    c.samples = 4
    c.use_denoising = c.use_adaptive_sampling = False
    c.bake_type = kind
    b = scene.render.bake
    b.normal_space = 'TANGENT'
    b.normal_r, b.normal_g, b.normal_b = 'POS_X', 'POS_Y', 'POS_Z'      # OpenGL, Y+


def _black(img):
    px = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(px)
    return not px.reshape(-1, 4)[:, :3].any()


def install(obj, kind, tmp):
    """The finished file `tmp` becomes obj's texture: on disk, in the .blend, in the material."""
    path = idn.tex_path(obj, kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    links.set_aside(path)
    os.replace(tmp, path)
    img = idn.image(obj, kind)
    if img is None:
        img = bpy.data.images.load(path, check_existing=True)
        idn.set_image(obj, kind, img)
    if img.packed_file:
        img.unpack(method='REMOVE')
    if img.source != 'FILE':
        img.source = 'FILE'
    img.filepath = idn.relpath(path)
    img.name = os.path.basename(path)
    img.reload()
    img.colorspace_settings.name = idn.colorspace(kind)
    material.show_images(obj)
    return img


def bake_kind(context, obj, kind):
    """One 8K texture. The file on disk is only replaced once the bake came out."""
    why = problem(obj)
    if why:
        raise RuntimeError(f"{obj.name}: {why}")
    src = obj.ppd.original
    scene = context.scene
    t0 = time.perf_counter()
    links.adopt_central()
    material.ensure(obj)
    img = bpy.data.images.new(TMP, idn.SIZE, idn.SIZE, alpha=False)
    img.colorspace_settings.name = idn.colorspace(kind)
    path = idn.tex_path(obj, kind) + ".part.png"
    args = dict(use_selected_to_active=True, cage_extrusion=obj.ppd.cage,
                max_ray_distance=0.0, margin=MARGIN, margin_type='EXTEND',
                use_clear=True, target='IMAGE_TEXTURES', save_mode='INTERNAL')
    try:
        with links.paused(), _state(scene), _shown(context, [obj, src]), \
                _plain_target(obj), _uv_active(obj, idn.bake_uv(obj)), _target_nodes(obj, img):
            if kind == "ALB":
                _configure(scene, 'EMIT')
                with _as_emission(src):
                    bpy.ops.object.bake(type='EMIT', **args)
            else:
                _configure(scene, 'NORMAL')
                bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', **args)
        if _black(img):
            raise RuntimeError(f"{obj.name}: {kind} came out black, the file was not touched. "
                               "Check the Original and the Cage")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.filepath_raw, img.file_format = path, 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)
    install(obj, kind, path)
    return time.perf_counter() - t0
