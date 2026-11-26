"""blender -b --factory-startup -P tests/test_palette.py"""
import os
import shutil
import sys
import tempfile
import traceback

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "addons"))
import PinkPunkDelta_internal as addon          # noqa: E402

addon.register()
from PinkPunkDelta_internal.modules.palette import extract, operators as pal_ops  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_palette_")
# sRGB patches: dark red, light red, dark blue, light blue
PATCHES = [(0.45, 0.05, 0.05), (0.95, 0.45, 0.40), (0.05, 0.10, 0.45), (0.45, 0.65, 0.95)]


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        raise AssertionError(what)


def picture(path, size=400):
    """Five vertical stripes: the four patches (shuffled, uneven widths) and a transparent one."""
    px = np.zeros((size, size, 4), np.float32)
    stripes = [(0, 60, 2), (60, 160, 0), (160, 200, 3), (200, 280, 1), (280, 400, None)]
    rng = np.random.default_rng(3)
    for a, b, i in stripes:
        if i is None:
            px[:, a:b] = (0.0, 1.0, 0.0, 0.0)     # transparent green: must not count
            continue
        px[:, a:b, :3] = np.clip(np.array(PATCHES[i]) + rng.normal(0, 0.02, (size, b - a, 3)),
                                 0, 1)
        px[:, a:b, 3] = 1
    img = bpy.data.images.new("concept", size, size, alpha=True)
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw, img.file_format = path, 'PNG'
    img.save()
    bpy.data.images.remove(img)


def run():
    path = os.path.join(tmp, "concept.png")
    picture(path)
    img = bpy.data.images.load(path)
    pal = bpy.context.scene.ppd_palette

    print("main colors")
    pal.image = img
    ok(len(pal.colors) == 8, "picked on choosing the picture, 8 by default")
    pal.count = 4
    ok(len(pal.colors) == 4, "the count is followed")
    got = [extract.linear_to_oklab(np.array(c.color)) for c in pal.colors]
    want = [extract.linear_to_oklab(extract.srgb_to_linear(np.array(p))) for p in PATCHES]
    for w in want:
        d = min(np.linalg.norm(w - g) for g in got)
        ok(d < 0.03, f"a patch is found (distance {d:.3f})")
    ok(not any(c.color[1] > 0.5 and c.color[0] < 0.2 for c in pal.colors),
       "transparent pixels do not count")
    shares = sorted(c.share for c in pal.colors)
    ok(np.allclose(shares, [40 / 280, 60 / 280, 80 / 280, 100 / 280], atol=0.015),
       f"how much each covers {np.round(shares, 3)}")

    print("similar colors side by side")
    reds = [c.color[0] > c.color[2] for c in pal.colors]
    ok(reds in ([True, True, False, False], [False, False, True, True]),
       f"reds together, blues together {reds}")
    lab = np.array([[0.2, 0, 0], [0.9, 0, 0], [0.25, 0.01, 0], [0.85, 0, 0.01], [0.5, 0, 0]])
    o = extract.order(lab)
    ok([round(lab[i, 0], 2) for i in o] == [0.2, 0.25, 0.5, 0.85, 0.9], f"a smooth row {o}")

    print("more colors than the picture has")
    pal.count = 32
    ok(4 <= len(pal.colors) <= 32, f"{len(pal.colors)} colors")

    print("palette swatches feed a ramp")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(tmp, "VHC_Pal.blend"))
    bpy.ops.mesh.primitive_plane_add()
    o = bpy.context.object
    bpy.ops.ppd.setup_current()
    o.ppd.base.mid = pal.colors[0].color          # what a drop does
    ok(np.allclose(o.ppd.bands.nodes["PPD_MID_0"].outputs[0].default_value[:3],
                   pal.colors[0].color), "a palette color lands in the shader")
    ok(pal_ops.PPD_PaletteColor.bl_rna.properties["color"].subtype ==
       o.ppd.base.bl_rna.properties["mid"].subtype == 'COLOR', "same kind of color field")


code = 0
try:
    run()
    print("ALL OK")
except Exception:
    traceback.print_exc()
    code = 1
shutil.rmtree(tmp, ignore_errors=True)
sys.stdout.flush()
os._exit(code)
