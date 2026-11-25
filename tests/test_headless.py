"""blender -b --factory-startup -P tests/test_headless.py   (works in a temp folder only)"""
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addons"))
import PinkPunkDelta_internal as addon          # noqa: E402

addon.register()
from PinkPunkDelta_internal import identity as idn, links, material     # noqa: E402
from PinkPunkDelta_internal.modules.bakenlink import bake               # noqa: E402
from PinkPunkDelta_internal.modules.livelink import core, prepare, psd, qr  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_test_")
core.token = lambda: "testtoken"
core.PORT = 8799


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        raise AssertionError(what)


def names(o):
    ok(o.ppd.material.name == "MAT_" + o.name, "material " + o.ppd.material.name)
    for k in idn.KINDS:
        img = idn.image(o, k)
        if img:
            ok(os.path.isfile(idn.abspath(img)) and links.same(idn.abspath(img),
               idn.tex_path(o, k)), f"{k} file follows")
            ok(o.ppd.material.node_tree.nodes["PPD_" + k].image == img, f"{k} on its node")


def run():
    first = os.path.join(tmp, "VHC_Test.blend")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.save_as_mainfile(filepath=first)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
    high = bpy.context.object
    m = bpy.data.materials.new("metal")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.8, 0.1, 0.1, 1)
    b.inputs["Metallic"].default_value = 1
    high.data.materials.append(m)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
    low = bpy.context.object
    low.name = "Wheel"
    print("setup")
    bpy.ops.ppd.setup_current()
    ok(low.name == "VHC_Test.Wheel", low.name)
    ok(any(x.type == 'NODES' and x.node_group.name == "GN_SharpTubes" for x in low.modifiers),
       "geometry nodes")
    nt = low.ppd.material.node_tree
    ok(all(n.bl_idname != "NodeUndefined" for n in nt.nodes["NPR"].node_tree.nodes),
       "NPR has no undefined nodes")
    ok(nt.nodes["PPD_ALB"].outputs[0].links[0].to_socket.name == "Base", "ALB in Base")
    ok(not nt.nodes["PPD_SHD"].outputs[0].links, "SHD is left to the user")

    print("bake 8K")
    low.ppd.original, low.ppd.cage = high, 0.1
    high.hide_set(True)
    for k in idn.BAKED:
        print(f"  {k} {bake.bake_kind(bpy.context, low, k):.1f} s")
    names(low)
    ok(tuple(low.ppd.alb.size) == (8192, 8192), "8K")
    ok(low.ppd.nor.colorspace_settings.name == 'Non-Color', "NOR is Non-Color")
    ok(high.hide_get() and low.modifiers[-1].show_render, "scene is as before")
    px = prepare.pixels(low.ppd.alb)
    mid = px[4096, 4096]
    ok(abs(int(mid[0]) - 231) < 4 and mid[1] < 100, f"metal is not black {mid}")
    del px

    print("rename")
    low.name = "Tire"
    ok(links._needs_sync(), "F2 is seen")
    old = idn.abspath(low.ppd.alb)
    links.sync_all()
    ok(low.name == "VHC_Test.Tire" and not os.path.exists(old), "F2 moves the files")
    names(low)
    # what an undo of F2 leaves behind
    low.name = low.ppd.synced = "VHC_Test.Wheel"
    low.ppd.part = "Wheel"
    for k in idn.BAKED:
        idn.image(low, k).filepath = f"//textures/{k}_VHC_Test.Wheel.png"
    ok(links._needs_sync(), "undo is seen")
    links.sync_all()
    names(low)

    print("duplicate")
    dup = low.copy()
    dup.data = low.data.copy()
    bpy.context.collection.objects.link(dup)
    links.sync_all()
    ok(low.name == "VHC_Test.Wheel" and low.ppd.alb is not None, "the first one is untouched")
    ok(dup.ppd.key != low.ppd.key and dup.ppd.alb is None, "own key, no textures")
    ok(dup.ppd.material != low.ppd.material, "own material")
    names(dup)
    inst = low.copy()
    bpy.context.collection.objects.link(inst)
    links.sync_all()
    ok(not inst.ppd.is_setup, "Alt+D stays an instance")
    for o in (dup, inst):
        bpy.data.objects.remove(o)

    print("psd")
    t = time.time()
    path = prepare.prepare(low)
    print(f"  {time.time() - t:.1f} s, {os.path.getsize(path) / 1e6:.0f} MB")
    with open(path, "rb") as f:
        data = f.read()
    got, size, unused = psd.read_layers(data, ("UV layout", "ALB", "NOR", "SHD"))
    ok(size == (8192, 8192) and unused == ["TEX"], "layers")
    ok(got["UV layout"][:, :, 3].any() and got["UV layout"][:, :, 3].max() == 64, "UV 25 %")
    src = prepare.pixels(low.ppd.alb)
    ok((got["ALB"][:, :, :3] == src[:, :, :3]).all(), "ALB is exact")
    del got, src, data

    print("live link")
    core.start()
    url = f"http://127.0.0.1:{core.PORT}"

    def call(u, body=None, headers=None):
        """Request in a thread while this thread plays Blender's timer."""
        res = {}

        def go():
            try:
                r = urllib.request.urlopen(urllib.request.Request(u, body, headers or {}),
                                           timeout=120)
                res.update(code=r.status, body=r.read())
            except urllib.error.HTTPError as e:
                res.update(code=e.code, body=e.read())
        th = threading.Thread(target=go)
        th.start()
        while th.is_alive():
            core.tick()
            time.sleep(0.05)
        return res

    ok(call(url + "/")["code"] == 403, "no token, no entry")
    ok(call(url + "/upload?t=wrong", b"x" * 10)["code"] == 403, "wrong token, no entry")
    ok(b"PPD LiveLink" in call(url + "/?t=testtoken")["body"], "page")
    r = call(url + "/psd/VHC_Test.Wheel.psd?t=testtoken")
    ok(r["body"][:4] == b"8BPS", "PSD download")

    n = 512
    rng = np.random.default_rng(1)
    shd = np.zeros((n, n, 4), np.uint8)
    shd[100:200, 100:300] = rng.integers(1, 255, (100, 200, 4), np.uint8)
    p = os.path.join(tmp, "x.psd")
    psd.write(p, n, [("SHD", shd, 255, True), ("TEX", None, 255, True), ("Sketch", shd, 255, True)],
              shd)
    with open(p, "rb") as f:
        body = f.read()
    ok((psd.read_layers(body, ("SHD",))[0]["SHD"] == shd).all(), "PSD round trip is exact")

    def form(name, data):
        sep = b"----XyZ"
        head = f'\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n' \
               "Content-Type: application/octet-stream\r\n\r\n"
        return (b"--" + sep + head.encode() + data + b"\r\n--" + sep + b"--\r\n",
                {"Content-Type": "multipart/form-data; boundary=" + sep.decode()})

    r = call(url + "/upload?t=testtoken", *form("VHC_Test.Wheel.psd", body))
    print("  ", r["body"].decode().encode("ascii", "replace").decode())
    ok(low.ppd.shd is not None and low.ppd.tex is None, "SHD in, empty TEX left alone")
    ok(tuple(low.ppd.shd.size) == (8192, 8192), "scaled to 8K")
    ok(b"Sketch" in r["body"], "unused layer is named")
    names(low)
    png = os.path.join(tmp, "x.png")
    psd.write_png(png, shd)
    with open(png, "rb") as f:
        r = call(url + "/upload?t=testtoken", *form("TEX_VHC_Test.Wheel.png", f.read()))
    ok(low.ppd.tex is not None, "TEX_ png")
    call(url + "/upload?t=testtoken", *form("Untitled Artwork.psd", body))
    ok(len(core.inbox) == 1, "unknown canvas waits")
    core.drop(core.inbox[0])

    def stream():       # urllib sends an iterable body chunked, as the iPad does
        for i in range(0, len(body), 5000):
            yield body[i:i + 5000]
    r = call(url + "/upload?t=testtoken", stream(), {"Content-Type": "application/octet-stream"})
    ok(r["code"] == 200 and core.inbox[0]["stem"] == "Untitled", "streamed upload")
    core.drop(core.inbox[0])
    r = call(url + "/upload?t=testtoken&object=VHC_Test.Wheel&name=Anything%20(1).psd", body,
             {"Content-Type": "application/octet-stream"})
    ok(b"VHC_Test.Wheel: SHD" in r["body"] and not core.inbox, "Send back goes to its object")
    ok(core.server.requests[-1]["received"] == len(body), "upload is noted")
    r = call(url + "/upload?t=testtoken", b"")
    ok(r["code"] == 400 and b"empty file" in r["body"], "empty upload is named")
    call(url + "/upload?t=testtoken", *form("Untitled Artwork.psd", body))
    bpy.ops.ppd.inbox_assign(item_id=core.inbox[0]["id"], object_name=low.name)
    ok(not core.inbox and core.find_object("Untitled_Artwork") == low, "and is remembered")
    names(low)
    core.stop()
    qr.encode("http://192.168.178.20:8770/?t=abcdefghijkl")

    print("central")
    second = os.path.join(tmp, "VHC_Other.blend")
    old = idn.abspath(low.ppd.alb)
    bpy.ops.wm.save_as_mainfile(filepath=second)
    ok(low.name == "VHC_Other.Wheel" and os.path.isfile(old), "Save As copies")
    names(low)
    ok(os.path.isfile(idn.psd_path(low)), "PSD too")
    bpy.ops.wm.save_mainfile()
    os.remove(second + "1") if os.path.exists(second + "1") else None
    third = os.path.join(tmp, "VHC_Third.blend")
    os.rename(second, third)
    bpy.ops.wm.open_mainfile(filepath=third)
    low = idn.objects()[0]
    ok(low.name == "VHC_Other.Wheel" and links.central_changed(), "opening changes nothing")
    bpy.ops.wm.save_mainfile()
    ok(low.name == "VHC_Third.Wheel", "saving renames")
    names(low)
    ok(not os.path.exists(os.path.join(tmp, "textures", "ALB_VHC_Other.Wheel.png")),
       "moved, the old .blend is gone")

    print("check all links")
    low.ppd.material.name = "Broken"
    low.ppd.material.node_tree.nodes["PPD_NOR"].image = None
    low.ppd.nor = None
    ok(len(links.problems()) >= 2, "problems are seen")
    fixed, left = links.check_and_fix()
    ok(not left, f"all corrected {left}")
    names(low)


code = 0
try:
    run()
    print("ALL OK")
except Exception:
    traceback.print_exc()
    code = 1
finally:
    core.stop()
    try:
        addon.unregister()
    except Exception:
        traceback.print_exc()
        code = 1
    shutil.rmtree(tmp, ignore_errors=True)
sys.stdout.flush()
os._exit(code)
