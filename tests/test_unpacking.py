"""blender -b --factory-startup -P tests/test_unpacking.py   (works in a temp folder only)"""
import os
import shutil
import sys
import tempfile
import traceback

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "addons"))
from PinkPunkDelta_internal.modules.livelink import psd          # noqa: E402
from PinkPunkDelta_internal.modules.unpacking import compose     # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_unpack_")
N = 64
_n = [0]


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        raise AssertionError(what)


def stage(ext):
    _n[0] += 1
    return os.path.join(tmp, f"out{_n[0]}{ext}")


def flat(rgb, a=255):
    px = np.zeros((N, N, 4), np.uint8)
    px[..., :3], px[..., 3] = rgb, a
    return px


def load(path):
    """Top-down uint8 RGBA of a PNG."""
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = 'Non-Color'
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return np.round(px.reshape(h, w, 4)[::-1] * 255).astype(np.int32)


def near(a, b, tol=2):
    return np.abs(np.asarray(a, np.int32) - np.asarray(b, np.int32)).max() <= tol


def write(layers):
    p = os.path.join(tmp, f"in{_n[0]}.psd")
    _n[0] += 1
    psd.write(p, N, layers, flat((0, 0, 0)))
    with open(p, "rb") as f:
        return f.read()


def run():
    print("blend math")
    b, s = np.array([0.5, 0.2, 0.8]), np.array([0.5, 0.5, 0.25])
    ok(np.allclose(compose.blend("mul ", b, s), b * s), "multiply")
    ok(np.allclose(compose.blend("scrn", b, s), b + s - b * s), "screen")
    ok(np.allclose(compose.blend("over", np.array([0.25]), np.array([0.8])), [0.4]), "overlay")
    ok(np.allclose(compose.blend("lddg", b, s), np.minimum(1, b + s)), "add")
    ok(np.allclose(compose.blend("lum ", np.array([1.0, 0, 0]), np.array([0.5, 0.5, 0.5])).sum(),
                   compose.blend("lum ", np.array([1.0, 0, 0]),
                                 np.array([0.5, 0.5, 0.5])).sum()), "luminosity runs")

    print("groups and modes")
    red, blue = flat((255, 0, 0)), flat((0, 0, 255))
    gray = flat((128, 128, 128))
    half = flat((0, 255, 0))
    half[:, N // 2:, 3] = 0                                  # left half painted
    hidden = flat((255, 255, 0))
    data = write([
        {"name": "UV layout k3f9a2c", "px": flat((0, 0, 0), 64), "opacity": 64},
        {"name": "SHD", "children": [{"name": "SHD", "px": gray, "blend": "mul "}]},
        {"name": "TEX", "opacity": 128, "children": [
            {"name": "Hidden", "px": hidden, "visible": False},
            {"name": "Blue", "px": blue, "opacity": 128},
            {"name": "Red", "px": red}]},
        {"name": "ALB", "children": [{"name": "Paint", "px": red, "blend": "mul ",
                                      "opacity": 153}]},
        {"name": "BASE", "children": [{"name": "BASE", "px": gray}]},
        {"name": "NOR", "visible": False, "children": [{"name": "NOR", "px": half}]},
        {"name": "Sketch", "px": red},
    ])
    names = compose.layer_names(data)
    ok("UV layout k3f9a2c" in names and "Paint" in names, f"names {names}")
    found, unused, size = compose.extract(data, ("ALB", "NOR", "TEX", "SHD"), stage)
    ok(size == (N, N) and unused == ["Sketch"], f"unused {unused}")
    shd = load(found["SHD"]["path"])
    ok(near(shd[5, 5], (128, 128, 128, 255)), f"Multiply on nothing is the layer {shd[5, 5]}")
    tex = load(found["TEX"]["path"])
    ok(near(tex[5, 5], (128, 0, 127, 255)), f"layer opacity is merged {tex[5, 5]}")
    ok(found["TEX"]["blend"] == "MIX" and abs(found["TEX"]["opacity"] - 128 / 255) < 1e-6,
       "the group's opacity is handed back, not merged")
    alb = load(found["ALB"]["path"])
    ok(near(alb[5, 5], (255, 0, 0, 255)), f"a single layer comes out plain {alb[5, 5]}")
    ok(found["ALB"]["blend"] == "MULTIPLY" and abs(found["ALB"]["opacity"] - 0.6) < 1e-6,
       "and hands back its Multiply 60 %")
    nor = load(found["NOR"]["path"])
    ok(near(nor[5, 5], (0, 255, 0, 255)) and near(nor[5, N - 5], (128, 128, 255, 255)),
       "a hidden NOR group still counts; unpainted is a flat normal")

    print("clipping and masks")
    left = flat((255, 255, 255))
    left[:, N // 2:, 3] = 0
    mask = np.zeros((N, N), np.uint8)
    mask[N // 2:] = 255                                      # bottom half shows
    data = write([
        {"name": "TEX", "children": [
            {"name": "Clipped", "px": red, "clip": True},
            {"name": "Base", "px": left}]},
        {"name": "SHD", "children": [{"name": "Masked", "px": blue, "mask": mask}]},
    ])
    found, _u, _s = compose.extract(data, ("TEX", "SHD", "ALB"), stage)
    ok("ALB" not in found, "a missing group is left out")
    tex = load(found["TEX"]["path"])
    ok(near(tex[5, 5], (255, 0, 0, 255)) and tex[5, N - 5][3] == 0,
       f"clipped to the layer below {tex[5, 5]} {tex[5, N - 5]}")
    shd = load(found["SHD"]["path"])
    ok(shd[5, 5][3] == 0 and near(shd[N - 5, 5], (0, 0, 255, 255)), "mask")

    print("blend inside a group")
    data = write([{"name": "TEX", "children": [
        {"name": "Mul", "px": gray, "blend": "mul "},
        {"name": "Red", "px": red}]}])
    found, _u, _s = compose.extract(data, ("TEX",), stage)
    tex = load(found["TEX"]["path"])
    ok(near(tex[5, 5], (128, 0, 0, 255)), f"Multiply over the layer below {tex[5, 5]}")

    print("empty")
    data = write([{"name": "SHD", "children": [{"name": "SHD", "px": None}]}])
    found, _u, _s = compose.extract(data, ("SHD",), stage)
    ok(found["SHD"]["path"] == "", "an empty group gives no file")


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
