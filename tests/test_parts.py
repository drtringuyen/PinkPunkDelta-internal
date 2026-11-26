"""blender -b --factory-startup -P tests/test_parts.py   (works in a temp folder only)"""
import os
import shutil
import sys
import tempfile
import traceback

import bmesh
import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "addons"))
import PinkPunkDelta_internal as addon          # noqa: E402

addon.register()
from PinkPunkDelta_internal import bands, identity as idn, links    # noqa: E402
from PinkPunkDelta_internal.modules.parts import operators as ops   # noqa: E402
from PinkPunkDelta_internal.modules.parts import ui as parts_ui     # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_parts_")


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        raise AssertionError(what)


def select(o, first, last):
    bm = bmesh.from_edit_mesh(o.data)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select_set(first <= f.index < last)
    bmesh.update_edit_mesh(o.data)


def stops(o, pid, name="RAMP"):
    r = o.ppd.bands.nodes[f"PPD_{name}_{pid}"].color_ramp
    return [(round(e.position, 3), tuple(round(c, 3) for c in e.color[:3])) for e in r.elements]


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(tmp, "VHC_P.blend"))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
    o = bpy.context.object
    o.name = "Cab"
    bpy.ops.ppd.setup_current()
    d = o.ppd

    print("own shader from the start")
    node = bands.npr_node(o)
    ok(d.bands is not None and d.bands.name == "NPR_VHC_P.Cab" and node.node_tree == d.bands,
       "NPR_<name>")
    ok(not bands.problems(o), "nothing to fix")
    ok(len(stops(o, 0)) == 3, "faces in no part: Shadow, Mid, High")

    print("parts")
    bpy.ops.object.mode_set(mode='EDIT')
    select(o, 0, 10)
    bpy.ops.ppd.part_add(name="Door")
    select(o, 5, 25)
    bpy.ops.ppd.part_add(name="Glass")
    ok([p.pid for p in d.parts] == [1, 2], "two parts")
    n = ops.counts(o)
    ok(n[1] == 5 and n[2] == 20, f"the last part a face was put in wins {n}")
    select(o, 0, 3)
    bpy.ops.ppd.part_assign(pid=2)
    n = ops.counts(o)
    ok(n[1] == 2 and n[2] == 23, f"assigning moves faces from their old part {n}")
    bpy.ops.ppd.part_assign(pid=1, remove=True)
    ok(ops.counts(o)[2] == 23, "- of one part leaves the other alone")
    select(o, 0, 0)
    bpy.ops.ppd.part_select(pid=2)
    ok(sum(f.select for f in bmesh.from_edit_mesh(o.data).faces) == 23, "select")
    bpy.ops.object.mode_set(mode='OBJECT')
    ok(ops.counts(o)[2] == 23, "counts in Object Mode")

    print("colors and borders")
    door = d.parts[0]
    door.shadow, door.mid, door.high, door.gloss = (0.1, 0, 0), (0.5, 0, 0), (1, 0, 0), (1, 1, 0)
    door.border_1, door.border_2, door.gloss_at = 0.2, 0.6, 0.8
    ok(stops(o, 1) == [(0.0, (0.1, 0, 0)), (0.2, (0.5, 0, 0)), (0.6, (1, 0, 0))],
       f"the ramp follows {stops(o, 1)}")
    nodes = d.bands.nodes
    ok(tuple(nodes["PPD_MID_1"].outputs[0].default_value)[:3] == (0.5, 0, 0), "Mid")
    ok(abs(nodes["PPD_GLOSSAT_1"].outputs[0].default_value - 0.8) < 1e-6, "Gloss border")
    bpy.context.view_layer.objects.active = o
    bpy.ops.ppd.part_band(pid=1, remove=True)
    ok(door.shades == 2 and stops(o, 1) == [(0.0, (0.1, 0, 0)), (0.2, (0.5, 0, 0))],
       "- takes High away")
    bpy.ops.ppd.part_band(pid=1, remove=True)
    ok(door.shades == 1 and stops(o, 1) == [(0.0, (0.5, 0, 0))], "then Shadow: Mid stays")
    ok(bpy.ops.ppd.part_band(pid=1, remove=True) == {'CANCELLED'}, "never fewer than one")
    bpy.ops.ppd.part_band(pid=1)
    bpy.ops.ppd.part_band(pid=1)
    ok(door.shades == 3 and len(stops(o, 1)) == 3, "+ brings them back")
    door.border_2 = 0.1
    ok(door.border_1 < door.border_2, "borders stay in order")
    door.gloss_at = 0.05
    ok(abs(door.gloss_at - 0.05) < 1e-6, "Gloss is on its own scale")
    door.border_1, door.border_2, door.gloss_at = 0.2, 0.6, 0.8
    widths = parts_ui.spectrum(door)
    ok([w[0] for w in widths] == ["shadow", "mid", "high"] and
       abs(sum(w[1] for w in widths) - 1) < 1e-6, "the bar's blocks fill it")
    items = parts_ui.bar(door)
    ok([n for n, _w, h in items] == ["shadow", "border_1", "mid", "border_2", "high"] and
       abs(sum(w for _n, w, _h in items) - 1) < 1e-6, "handles sit between the blocks")
    door.border_1, door.border_2 = 0.0, 0.99            # dragged all the way
    items = parts_ui.bar(door, 8.0)
    ok(all(w * 8.0 >= parts_ui.MIN_UNITS - 1e-6 for _n, w, _h in items) and
       abs(sum(w for _n, w, _h in items) - 1) < 1e-6, "no block or handle too narrow to draw")
    items = parts_ui.bar(door, 3.0)
    ok(len({round(w, 6) for _n, w, _h in items}) == 1, "a very narrow bar: all the same width")
    door.border_1, door.border_2 = 0.2, 0.6
    door.shades = 2
    ok([n for n, _w, h in parts_ui.bar(door) if h] == ["border_1"], "2 shades")
    door.shades = 3

    print("shades from the main color")
    door.mid = (0.6, 0.1, 0.05)
    bpy.ops.ppd.part_auto(pid=1)
    lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]    # noqa: E731
    ok(lum(door.shadow) < lum(door.mid) < lum(door.high) < lum(door.gloss),
       "Shadow < Mid < High < Gloss")
    ok(door.shadow[0] > door.shadow[1] and door.high[0] > door.high[2], "still red")
    from PinkPunkDelta_internal.modules.parts import shades
    import math

    def to_blue(c):
        lab = shades.to_lab(c)
        h = math.atan2(lab[2], lab[1])
        return abs((shades.BLUE - h + math.pi) % (2 * math.pi) - math.pi)
    ok(to_blue(door.shadow) < to_blue(door.mid) - math.radians(5), "the shadow leans cooler")
    pal = bpy.context.scene.ppd_palette
    # a palette like a concept's: reds, a beige, grays, a sky blue (linear RGB)
    palette = [(0.18, 0.03, 0.02), (0.55, 0.08, 0.05), (0.72, 0.24, 0.15), (0.63, 0.47, 0.33),
               (0.03, 0.03, 0.03), (0.3, 0.3, 0.3), (0.72, 0.81, 0.89)]
    for col in palette:
        pal.colors.add().color = col
    door.mid = (0.5, 0.1, 0.06)
    bpy.ops.ppd.part_auto(pid=1)
    got = [tuple(round(v, 4) for v in getattr(door, k)) for k in ("shadow", "mid", "high", "gloss")]
    pal_r = [tuple(round(v, 4) for v in c.color) for c in pal.colors]
    ok(all(g in pal_r for g in got), "all four colors come from the palette")
    ok(got[1] == pal_r[1], "the main color snaps to the nearest palette color")
    ok(got[0] == pal_r[0] and got[2] == pal_r[2],
       f"Shadow a darker red, High a lighter red - not the beige {got}")
    ok(lum(door.shadow) < lum(door.mid) < lum(door.high) <= lum(door.gloss), "in order")
    pal.colors.clear()
    door.shadow, door.mid, door.high, door.gloss = (0.1, 0, 0), (0.5, 0, 0), (1, 0, 0), (1, 1, 0)
    bpy.ops.ppd.part_copy_ramp(pid=1)
    ok(stops(o, 2) == stops(o, 1) and tuple(d.parts[1].gloss) == (1, 1, 0), "copy to all parts")

    print("the panel draws")

    class Layout:       # takes every layout call: what fails is the panel's own code
        def __getattr__(self, n):
            return self

        def __call__(self, *a, **k):
            return self

        def __setattr__(self, n, v):
            pass

        def panel(self, *a, **k):
            return self, self
    panel = type("P", (), {"layout": Layout()})()
    from PinkPunkDelta_internal.modules.parts.ui import PINKPUNKDELTA_INTERNAL_PT_Parts as PT
    try:
        PT.draw(panel, bpy.context)
        drew = True
    except Exception:
        traceback.print_exc()
        drew = False
    ok(drew, "04.Split Parts draws without an error")

    print("blending from Procreate")
    d.tex_blend, d.tex_opacity = 'MULTIPLY', 0.5
    ok(nodes["PPD_TEX_MIX"].blend_type == 'MULTIPLY' and
       abs(nodes["PPD_TEX_OPACITY"].outputs[0].default_value - 0.5) < 1e-6, "TEX blend")

    print("rename, duplicate")
    o.name = "Cabin"
    links.sync_all()
    ok(d.bands.name == "NPR_VHC_P.Cabin", d.bands.name)
    dup = o.copy()
    dup.data = o.data.copy()
    bpy.context.collection.objects.link(dup)
    links.sync_all()
    ok(dup.ppd.bands not in (None, d.bands) and bands.npr_node(dup).node_tree == dup.ppd.bands
       and bands.npr_node(o).node_tree == d.bands, "a duplicate has its own shader")
    ok(dup.ppd.bands.name == "NPR_" + dup.name, dup.ppd.bands.name)
    dup.ppd.parts[0].mid = (0, 0, 1)
    ok(tuple(nodes["PPD_MID_1"].outputs[0].default_value)[:3] == (0.5, 0, 0), "independent")
    ok(stops(dup, 1)[1][1] == (0, 0, 1), "with its own colors")

    print("check all links")
    bands.npr_node(o).node_tree = None
    ok(any("shader" in t for _n, t in links.problems()), "seen")
    links.check_and_fix()
    ok(bands.npr_node(o).node_tree == d.bands, "corrected")
    ok(not bands.problems(o), "nothing left")
    d.bands["ppd_shader"] = 1
    ok(bands.problems(o) == ["the shader is from an older version"], "an old shader is seen")
    bands.npr_node(o).inputs["Show ALB"].default_value = 0.43     # what an old slot leaves
    ok(bands.upgrade_all() == [o.name], "and upgraded by itself (on opening a file)")
    ok(not bands.problems(o) and stops(o, 1)[1][1] == (0.5, 0, 0), "rebuilt from the data")
    ok(bands.npr_node(o).inputs["Show ALB"].default_value == 1.0,
       "the new shader's inputs start at their defaults")
    ok(bands.upgrade_all() == [], "only once")
    fresh = d.parts.add()
    fresh.pid = 99
    ok(not bands.edited(fresh) and bands.edited(d.parts[0]), "an untouched part is told apart")
    d.parts.remove(len(d.parts) - 1)
    d.bands["ppd_shader"] = 1
    d.bands.nodes["PPD_RAMP_1"].color_ramp.elements[1].color = (0, 1, 0, 1)
    bands.upgrade_all()
    ok(stops(o, 1)[1][1] == (0.5, 0, 0), "colors set in the bar are not replaced by the old ramp")

    print("reload")
    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
    o = bpy.data.objects["VHC_P.Cabin"]
    d = o.ppd
    ok(len(d.parts) == 2 and ops.counts(o)[2] == 23 and not bands.problems(o), "all there")
    ok(stops(o, 1)[1][1] == (0.5, 0, 0) and d.tex_blend == 'MULTIPLY', "colors and blending")

    print("delete")
    bpy.context.view_layer.objects.active = o
    bpy.ops.ppd.part_delete(pid=1)
    ok(bands.ramp(o, 1) is None and bands.ramp(o, 2) is not None, "one")
    bpy.ops.ppd.part_add(name="New")
    ok(d.parts[1].pid == 3, "a number is not used again")
    bpy.ops.ppd.part_delete(pid=2)
    bpy.ops.ppd.part_delete(pid=3)
    ok(not len(d.parts) and bands.ramp(o, 0) is not None and not bands.problems(o),
       "no parts: the faces in no part keep their colors")
    ok(ops.counts(o) == {0: len(o.data.polygons)}, "every face is in no part")


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
