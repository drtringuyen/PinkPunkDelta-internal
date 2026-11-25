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


def run():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(tmp, "VHC_P.blend"))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
    o = bpy.context.object
    o.name = "Cab"
    bpy.ops.ppd.setup_current()
    d = o.ppd
    npr = bpy.data.node_groups["NPR"]
    before = len(npr.nodes)
    node = d.material.node_tree.nodes["NPR"]
    node.inputs["Shade 2 Color"].default_value = (0, 1, 0, 1)
    bpy.ops.object.mode_set(mode='EDIT')
    select(o, 0, 10)
    bpy.ops.ppd.part_add(name="Door")
    select(o, 5, 25)
    bpy.ops.ppd.part_add(name="Glass")
    ok([p.pid for p in d.parts] == [1, 2], "two parts")
    n = ops.counts(o)
    ok(n[1] == 5 and n[2] == 20, f"a face is in one part only {n}")
    bpy.ops.ppd.part_assign(pid=1, remove=True)
    ok(ops.counts(o)[2] == 20, "- of one part leaves the other alone")
    select(o, 0, 0)
    bpy.ops.ppd.part_select(pid=2)
    ok(sum(f.select for f in bmesh.from_edit_mesh(o.data).faces) == 20, "select")
    bpy.ops.object.mode_set(mode='OBJECT')
    ok(ops.counts(o)[2] == 20, "counts in Object Mode")

    print("group")
    ok(node.node_tree == d.bands and d.bands.name == "NPR_VHC_P.Cab", d.bands.name)
    ok(len(npr.nodes) == before and node.node_tree != npr, "the shared NPR is untouched")
    ok(node.inputs["Base"].links and node.inputs["Normal"].links and node.outputs[0].links,
       "links stay")
    ok(tuple(node.inputs["Shade 2 Color"].default_value) == (0, 1, 0, 1), "values stay")
    r = bands.ramp(o, 1)
    ok(len(r.color_ramp.elements) >= 4 and r.color_ramp.interpolation == 'CONSTANT',
       "the ramp starts as NPR's shades")
    ok(any(tuple(e.color)[:3] == (0, 1, 0) for e in r.color_ramp.elements), "with its colors")
    acc = next(x for x in d.bands.nodes if x.bl_idname == "ShaderNodeLightAccumulation")
    ok(acc.inputs["Diffuse Light"].links[0].from_node.name == "PPD_LIGHT_OUT", "wired")
    d.parts[0].ignore_alb = True
    ok(d.bands.nodes["PPD_X_IGNORE_1"].inputs[1].default_value == 1, "Ignore ALB")
    r.color_ramp.elements[0].color = (1, 0, 1, 1)

    print("update from NPR")
    npr.nodes.new("NodeReroute").name = "MINE"
    bpy.ops.ppd.part_refresh()
    ok("MINE" in d.bands.nodes and d.bands.name == "NPR_VHC_P.Cab", "the change is in")
    ok(tuple(bands.ramp(o, 1).color_ramp.elements[0].color) == (1, 0, 1, 1), "ramps stay")
    ok(d.bands.nodes["PPD_X_IGNORE_1"].inputs[1].default_value == 1, "Ignore ALB stays")
    ok(not [g for g in bpy.data.node_groups if g.name.startswith("NPR_") and g != d.bands],
       "no leftover group")

    print("rename, duplicate")
    o.name = "Cabin"
    links.sync_all()
    ok(d.bands.name == "NPR_VHC_P.Cabin", d.bands.name)
    dup = o.copy()
    dup.data = o.data.copy()
    bpy.context.collection.objects.link(dup)
    links.sync_all()
    ok(dup.ppd.bands not in (None, d.bands) and bands.npr_node(dup).node_tree == dup.ppd.bands
       and bands.npr_node(o).node_tree == d.bands, "a duplicate has its own ramps")
    ok(dup.ppd.bands.name == "NPR_" + dup.name, dup.ppd.bands.name)
    bands.ramp(dup, 1).color_ramp.elements[0].color = (0, 0, 1, 1)
    ok(tuple(bands.ramp(o, 1).color_ramp.elements[0].color) == (1, 0, 1, 1), "independent")

    print("check all links")
    bands.npr_node(o).node_tree = npr
    ok(any("ramps" in t for _n, t in links.problems()), "seen")
    links.check_and_fix()
    ok(bands.npr_node(o).node_tree == d.bands, "corrected")
    ok(not bands.problems(o), "nothing left")

    print("reload")
    bpy.ops.wm.save_mainfile()
    bpy.ops.wm.open_mainfile(filepath=bpy.data.filepath)
    o = bpy.data.objects["VHC_P.Cabin"]
    d = o.ppd
    ok(len(d.parts) == 2 and ops.counts(o)[2] == 20 and not bands.problems(o), "all there")

    print("delete")
    bpy.context.view_layer.objects.active = o
    bpy.ops.ppd.part_delete(pid=1)
    ok(bands.ramp(o, 1) is None and bands.ramp(o, 2) is not None, "one")
    bpy.ops.ppd.part_add(name="New")
    ok(d.parts[1].pid == 3, "a number is not used again")
    bpy.ops.ppd.part_delete(pid=2)
    bpy.ops.ppd.part_delete(pid=3)
    ok(d.bands is None and bands.npr_node(o).node_tree.name == "NPR", "back on the shared NPR")


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
