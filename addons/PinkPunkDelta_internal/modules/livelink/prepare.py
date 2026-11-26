"""The Procreate file of an object, 8K, named <full name>_k<key>.psd. From the top: UV layout
(25 %, its name carries the key too), then a group per texture, in the order the shader stacks
them - SHD (50 % gray, shown Overlay), TEX, ALB, BASE (the parts' Mid, a guide), NOR (hidden). Each group
holds the texture as it is now; the artist adds layers inside the groups."""
import os

import bpy
import numpy as np

from ... import bands
from ... import identity as idn
from . import psd

UV_OPACITY = 64         # 25 %


def pixels(img, size=idn.SIZE):
    """The image's file as top-down uint8 RGBA, scaled to `size` when it is not."""
    path = idn.abspath(img)
    work = bpy.data.images.load(path, check_existing=False)
    try:
        work.colorspace_settings.name = img.colorspace_settings.name
        if tuple(work.size) != (size, size):
            work.scale(size, size)
        buf = np.empty(size * size * 4, np.float32)
        work.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(work)
    np.multiply(buf, 255, out=buf)
    np.add(buf, .5, out=buf)
    np.clip(buf, 0, 255, out=buf)
    return np.ascontiguousarray(buf.astype(np.uint8).reshape(size, size, 4)[::-1])


def uv_layout(obj, size=idn.SIZE, width=3):
    """The UV edges of obj as lines on a transparent layer (black, readable on any ALB)."""
    out = np.zeros((size, size, 4), np.uint8)
    me = obj.data
    uv = me.uv_layers.get(idn.bake_uv(obj))
    n = len(me.loops)
    if uv is None or not n:
        return out
    co = np.empty(n * 2, np.float32)
    uv.uv.foreach_get("vector", co)
    co = co.reshape(-1, 2)
    start = np.empty(len(me.polygons), np.int32)
    total = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    nxt = np.arange(1, n + 1)
    nxt[start + total - 1] = start
    seg = np.concatenate((co, co[nxt]), axis=1)
    flip = (seg[:, 0] > seg[:, 2]) | ((seg[:, 0] == seg[:, 2]) & (seg[:, 1] > seg[:, 3]))
    seg[flip] = seg[flip][:, [2, 3, 0, 1]]
    seg = np.unique(seg, axis=0)            # an edge inside an island is there twice
    p0, p1 = seg[:, :2] * size, seg[:, 2:] * size
    alpha = out[:, :, 3]
    for s in range(0, len(seg), 20000):
        a, d = p0[s:s + 20000], (p1 - p0)[s:s + 20000]
        steps = np.ceil(np.abs(d).max(axis=1)).astype(np.int64) + 1
        steps = np.minimum(steps, size * 4)
        idx = np.repeat(np.arange(len(a)), steps)
        first = np.repeat(np.cumsum(steps) - steps, steps)
        t = (np.arange(steps.sum()) - first) / np.maximum(steps[idx] - 1, 1)
        p = a[idx] + d[idx] * t[:, None]
        x, y = p[:, 0].astype(np.int64), size - 1 - p[:, 1].astype(np.int64)
        for dx in range(width):
            for dy in range(width):
                xx, yy = x + dx - width // 2, y + dy - width // 2
                ok = (xx >= 0) & (xx < size) & (yy >= 0) & (yy < size)
                alpha[yy[ok], xx[ok]] = 255
    return out




def _srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _offscreen(size):
    import gpu
    try:
        return gpu.types.GPUOffScreen(size, size, format='RGBA8')
    except SystemError:             # Blender without a window: start the GPU first
        gpu.init()
        return gpu.types.GPUOffScreen(size, size, format='RGBA8')


def base_layer(obj, size=idn.SIZE):
    """BASE: every part flat in its Mid color, drawn over the UV layout. Only a guide in
    Procreate - Blender colors these parts from the ramps."""
    import gpu
    from gpu_extras.batch import batch_for_shader
    from mathutils import Matrix
    me = obj.data
    uv = me.uv_layers.get(idn.bake_uv(obj))
    if uv is None or not len(me.polygons):
        return np.zeros((size, size, 4), np.uint8)
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    loops = np.empty(nt * 3, np.int32)
    me.loop_triangles.foreach_get("loops", loops)
    poly = np.empty(nt, np.int32)
    me.loop_triangles.foreach_get("polygon_index", poly)
    co = np.empty(len(me.loops) * 2, np.float32)
    uv.uv.foreach_get("vector", co)
    pos = co.reshape(-1, 2)[loops] * 2 - 1
    pids = np.zeros(len(me.polygons), np.int32)
    a = me.attributes.get(bands.ATTR)
    if a is not None and a.domain == 'FACE' and a.data_type == 'INT':
        a.data.foreach_get("value", pids)
    lookup = {p.pid: (*_srgb(p.mid), 1.0) for p in idn.all_parts(obj)}
    colors = np.array([lookup.get(int(v), lookup[0]) for v in pids], np.float32)
    col = np.repeat(colors[poly], 3, axis=0)
    off = _offscreen(size)
    try:
        shader = gpu.shader.from_builtin('FLAT_COLOR')
        batch = batch_for_shader(shader, 'TRIS', {"pos": pos.tolist(), "color": col.tolist()})
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(Matrix.Identity(4))
                batch.draw(shader)
            buf = fb.read_color(0, 0, size, size, 4, 0, 'UBYTE')
        buf.dimensions = size * size * 4
        out = np.array(buf, np.uint8).reshape(size, size, 4)
    finally:
        off.free()
    return np.ascontiguousarray(out[::-1])


ISLAND_GROW = 8         # px kept around the UV islands: sampling at an edge stays clean


def grow(mask, px=ISLAND_GROW):
    """The mask grown by px pixels (a square around each pixel)."""
    out = mask.copy()
    for _ in range(px):
        g = out.copy()
        g[1:] |= out[:-1]
        g[:-1] |= out[1:]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def clear_outside(px, islands):
    """The baked ALB is opaque everywhere - black outside the UV islands, plus the bake's
    margin. Outside the islands (grown a little) it becomes transparent: in Procreate only
    the islands show, and that is what comes back."""
    px[..., 3] = np.where(islands, px[..., 3], 0)
    return px


def _gray(size):
    """SHD's neutral start: 50 % gray changes nothing. Overlay shows it while painting."""
    out = np.empty((size, size, 4), np.uint8)
    out[..., :3], out[..., 3] = 128, 255
    return out


def stack(obj, size=idn.SIZE):
    """The layers of the PSD, top first, as Procreate shows them; and its preview."""
    if obj.mode == 'EDIT':
        obj.update_from_editmode()
    px = {}
    for k in idn.KINDS:
        img = idn.image(obj, k)
        px[k] = pixels(img, size) if img and os.path.isfile(idn.abspath(img)) else None
    base = base_layer(obj, size)
    if px["ALB"] is not None and base[..., 3].any():
        clear_outside(px["ALB"], grow(base[..., 3] > 0))

    def group(name, layer, blend="norm", visible=True):
        return {"name": name, "visible": visible,
                "children": [{"name": name, "px": layer, "blend": blend}]}

    layers = [{"name": f"UV layout k{idn.short_key(obj)}", "px": uv_layout(obj, size),
               "opacity": UV_OPACITY},
              group("SHD", px["SHD"] if px["SHD"] is not None else _gray(size), "over"),
              group("TEX", px["TEX"]),
              group("ALB", px["ALB"]),
              group("BASE", base),
              group("NOR", px["NOR"], visible=False)]
    preview = base
    for k in ("ALB", "TEX"):
        if px[k] is not None:
            preview = psd.under(px[k], preview)
    return layers, preview


def prepare(obj, path, size=idn.SIZE):
    """Writes the PSD for Procreate to `path`; returns it."""
    layers, preview = stack(obj, size)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    psd.write(tmp, size, layers, preview)
    os.replace(tmp, path)
    return path
