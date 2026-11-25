"""The Procreate file of an object: <full name>.psd next to its textures, 8K, layers from the top:
UV layout (25 %), TEX, SHD, ALB, NOR. SHD / TEX hold what is painted so far, else are empty."""
import os

import bpy
import numpy as np

from ... import identity as idn
from ... import links
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


def prepare(obj, size=idn.SIZE):
    """Writes the PSD; returns its path. A PSD that is already there is kept in _previous."""
    if obj.mode == 'EDIT':
        obj.update_from_editmode()
    px = {}
    for k in idn.KINDS:
        img = idn.image(obj, k)
        px[k] = pixels(img, size) if img and os.path.isfile(idn.abspath(img)) else None
    white = None
    if px["ALB"] is None:
        white = np.full((size, size, 4), 255, np.uint8)
    layers = [("UV layout", uv_layout(obj, size), UV_OPACITY, True),
              ("TEX", px["TEX"], 255, True),
              ("SHD", px["SHD"], 255, True),
              ("ALB", px["ALB"], 255, True),
              ("NOR", px["NOR"], 255, True)]
    path = idn.psd_path(obj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    psd.write(tmp, size, layers, px["ALB"] if white is None else white)
    links.set_aside(path)
    os.replace(tmp, path)
    return path
