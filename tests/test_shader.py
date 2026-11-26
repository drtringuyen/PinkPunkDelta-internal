"""blender -b --factory-startup -P tests/test_shader.py   (renders with EEVEE, temp folder only)"""
import math
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
from PinkPunkDelta_internal import bands, identity as idn, material   # noqa: E402
from PinkPunkDelta_internal.modules.qol import operators as qol      # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_shader_")


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        raise AssertionError(what)


def srgb(c):
    c = np.clip(np.asarray(c, np.float64), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255


def shot():
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(tmp, "r.png")
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(sc.render.filepath, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[h // 2, w // 2, :3] * 255


def near(a, b, tol=6):
    return np.abs(np.asarray(a) - np.asarray(b)).max() <= tol


def image(color, alpha=1.0):
    img = bpy.data.images.new("t", 4, 4, alpha=True)
    img.colorspace_settings.name = 'Non-Color'      # before the pixels: it resets them
    img.pixels.foreach_set(np.tile([*color, alpha], 16).astype(np.float32))
    img.pack()
    return img


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(tmp, "VHC_Sh.blend"))
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = sc.render.resolution_y = 32
    sc.view_settings.view_transform = 'Standard'
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0, 0, 0)
    bpy.ops.mesh.primitive_plane_add(size=2)
    o = bpy.context.object
    bpy.ops.ppd.setup_current()
    for m in o.modifiers:
        m.show_render = m.show_viewport = False
    bpy.ops.object.camera_add(location=(0, 0, 3))
    sc.camera = bpy.context.object
    sc.camera.data.type = 'ORTHO'
    bpy.ops.object.light_add(type='SUN')
    sun = bpy.context.object
    sun.data.energy = 3.0
    p = o.ppd.base
    p.shadow, p.mid, p.high, p.gloss = (0.05, 0.05, 0.2), (0.2, 0.4, 0.6), (0.6, 0.8, 1.0), (0, 0, 0)
    p.border_1, p.border_2, p.gloss_at = 0.2, 0.5, 0.99
    node = bands.npr_node(o)

    print("solo BASE is the part's Mid, flat")
    node.inputs["Solo"].default_value = 1
    ok(near(shot(), srgb(p.mid)), f"{shot().round()} {srgb(p.mid).round()}")
    node.inputs["Solo"].default_value = 0

    print("SHD decides the shade")
    idn.set_image(o, "SHD", image((1, 1, 1)))
    material.show_images(o)
    ok(near(shot(), srgb(p.high)), "white SHD: High")
    idn.set_image(o, "SHD", image((0, 0, 0)))
    material.show_images(o)
    ok(near(shot(), srgb(p.shadow)), "black SHD: Shadow")

    idn.set_image(o, "SHD", image((0.5, 0.5, 0.5)))
    material.show_images(o)
    lit_ref = shot()
    idn.set_image(o, "SHD", None)
    material.show_images(o)
    ok(near(shot(), lit_ref), "50 % gray SHD changes nothing")
    idn.set_image(o, "SHD", image((0, 0, 0)))
    material.show_images(o)

    print("ALB is shaded like its part")
    idn.set_image(o, "ALB", image((1.0, 0.0, 0.0)))
    material.show_images(o)
    want = np.array([1.0, 0, 0]) * np.array(p.shadow) / np.array(p.mid)
    ok(near(shot(), srgb(want)), f"red ALB in Shadow {shot().round()} {srgb(want).round()}")
    node.inputs["Show ALB"].default_value = 0
    ok(near(shot(), srgb(p.shadow)), "Show ALB off")
    node.inputs["Show ALB"].default_value = 1
    idn.set_image(o, "ALB", None)
    idn.set_image(o, "SHD", None)
    material.show_images(o)
    ok(not o.ppd.material.node_tree.nodes["PPD_SHD"].outputs[0].links, "no image, no link")

    print("light")
    sun.rotation_euler = (0, 0, 0)          # straight onto the plane
    lit = shot()
    sun.rotation_euler = (math.pi, 0, 0)    # from below
    dark = shot()
    print("   lit", lit.round(), "dark", dark.round())
    ok(lit.sum() > dark.sum() + 30, "the lit side is brighter")
    sun.rotation_euler = (0, 0, 0)
    sun.data.color = (1, 0, 0)
    bpy.context.scene.ppd_qol.light_color = True
    ok(node.inputs["Light Color"].default_value == 1.0, "QOL sets Light Color")
    red = shot()
    print("   red light", red.round())
    ok(red[1] < lit[1] - 20 and red[2] < lit[2] - 20, "the light's color counts")
    bpy.context.scene.ppd_qol.light_color = False
    ok(near(shot(), lit), "and goes off again")

    print("exposure")
    node.inputs["Exposure"].default_value = 0.5
    half = shot()
    node.inputs["Exposure"].default_value = 1.0
    ok(half.sum() < lit.sum() - 30, f"Exposure 0.5 is darker {half.round()}")

    print("gloss")
    p.gloss, p.gloss_at = (0.5, 0.0, 0.0), 0.51
    shiny = shot()
    print("   gloss", shiny.round())
    ok(shiny[0] > lit[0] - 1 and shiny[0] > shiny[1] - 20 and not near(shiny, lit, 3),
       "a head-on highlight shows Gloss")
    p.gloss, p.gloss_at = (0, 0, 0), 0.99

    print("QOL")
    q = bpy.context.scene.ppd_qol
    q.outline = False
    gn = [m for m in o.modifiers if m.type == 'NODES']
    ok(gn and not gn[0].show_viewport and not gn[0].show_render, "outline off, render too")
    q.outline = True
    ok(gn[0].show_viewport and gn[0].show_render, "outline on")
    q.solo = '1'
    ok(node.inputs["Solo"].default_value == 1, "solo")
    q.scope = 'SELECTED'
    bpy.ops.object.select_all(action='DESELECT')
    q.solo = '0'
    ok(node.inputs["Solo"].default_value == 1, "Selected: an unselected object is left alone")
    o.select_set(True)
    ok(qol.apply(bpy.context) == 1 and node.inputs["Solo"].default_value == 0, "Apply")


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
