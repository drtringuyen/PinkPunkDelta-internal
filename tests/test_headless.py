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
from PinkPunkDelta_internal.modules.livelink import core, pc, prepare, psd, qr  # noqa: E402
from PinkPunkDelta_internal.modules.qol import cleanup                  # noqa: E402
from PinkPunkDelta_internal.modules.unpacking import compose            # noqa: E402

tmp = tempfile.mkdtemp(prefix="ppd_test_")
core.token = lambda: "testtoken"
core.PORT = 8799
drive = os.path.join(tmp, "PPD_Procreate")
os.makedirs(drive)
core.watch_folder = lambda: drive
bpy.utils.user_resource = lambda *a, **k: tmp        # its record stays in the temp folder


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
    ok(nt.nodes["NPR"].node_tree.name == "NPR_VHC_Test.Wheel", "its own shader")
    ok(not nt.nodes["PPD_ALB"].outputs[0].links, "no image yet: not linked (no pink)")

    print("bake 8K")
    low.ppd.original, low.ppd.cage = high, 0.1
    high.hide_set(True)
    for k in idn.BAKED:
        print(f"  {k} {bake.bake_kind(bpy.context, low, k):.1f} s")
    names(low)
    ok({(x.from_socket.name, x.to_socket.name) for x in nt.nodes["PPD_ALB"].outputs[0].links
        + nt.nodes["PPD_ALB"].outputs[1].links} == {("Color", "ALB"), ("Alpha", "ALB Alpha")},
       "ALB linked once baked")
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

    print("send to iPad")
    t = time.time()
    path = core.send(low)
    print(f"  {time.time() - t:.1f} s, {os.path.getsize(path) / 1e6:.0f} MB")
    okey = idn.short_key(low)
    ok(path == os.path.join(drive, "To iPad", f"VHC_Test.Wheel_k{okey}.psd"), path)
    with open(path, "rb") as f:
        data = f.read()
    doc = compose.PSD(data)
    top = [n.name for n in reversed(doc.roots)]
    ok(top == [f"UV layout k{okey}", "SHD", "TEX", "ALB", "BASE", "NOR"], f"order {top}")
    ok(all(n.group for n in doc.roots[:-1]) and not doc.roots[0].visible, "groups; NOR hidden")
    ok(doc.find("SHD").children[0].blend == "over", "SHD shows as Overlay")
    staged = []

    def stage(ext):
        staged.append(os.path.join(tmp, f"st{len(staged)}{ext}"))
        return staged[-1]
    found, unused, size = compose.extract(data, ("ALB", "BASE", "SHD"), stage)
    shd_gray = prepare.pixels(bpy.data.images.load(found["SHD"]["path"]))
    ok(abs(int(shd_gray[100, 100, 0]) - 128) <= 1 and shd_gray[100, 100, 3] == 255,
       "SHD starts as 50 % gray: changes nothing")
    del shd_gray
    ok(size == (8192, 8192) and
       sorted(unused) == ["NOR", "TEX"], f"layers {unused}")
    src = prepare.pixels(low.ppd.alb)
    back = prepare.pixels(bpy.data.images.load(found["ALB"]["path"]))
    shown = back[:, :, 3] > 0
    ok((back[shown][:, :3] == src[shown][:, :3]).all(), "ALB is exact on the islands")
    base_a = prepare.pixels(bpy.data.images.load(found["BASE"]["path"]))[:, :, 3] > 0
    ok(not (shown & ~prepare.grow(base_a)).any() and shown.sum() >= base_a.sum() * 0.99,
       "ALB is transparent outside the UV islands (and a few pixels around them)")
    del base_a, shown
    base = prepare.pixels(bpy.data.images.load(found["BASE"]["path"]))
    want = np.round(prepare._srgb(low.ppd.base.mid) * 255)
    hit = base[base[:, :, 3] > 0]
    ok(len(hit) > 1e6 and np.abs(hit[:, :3] - want).max() <= 1, f"BASE is Mid, flat {hit[0]}")
    del src, back, base, hit, data, doc
    old_name = path
    low.name = "Rim"
    links.sync_all()
    path = core.send(low)
    ok(not os.path.exists(old_name) and os.path.basename(path).startswith("VHC_Test.Rim_k"),
       "after a rename the old PSD goes")
    low.name = "Wheel"
    links.sync_all()
    path = core.send(low)

    print("rebake and send")
    before = os.path.getmtime(path)
    bpy.ops.ppd.bake(object_name=low.name, send=True)
    ok(os.path.getmtime(path) > before, "baked, then the PSD is sent again")
    names(low)

    print("pc setup")
    prog = r"C:\Program Files\Blender.exe"
    good = {"nets": [{"ip": "10.8.0.2", "name": "VPN", "hardware": False, "category": "Public"},
                     {"ip": "192.168.1.5", "name": "Ethernet", "hardware": True,
                      "category": "Private"}],
            "share": r"c:\ppd_procreate", "server": "Running", "user": r"PC\me",
            "rules": [{"name": "a", "program": prog, "port": "8799", "profile": "Private"},
                      {"name": "b", "program": "Any", "port": "445", "profile": "Any"}]}
    checks, ip = pc.evaluate(good, r"C:\PPD_Procreate", prog.upper(), 8799)
    ok(ip == "192.168.1.5" and all(c[1] for c in checks), "ready, the VPN is not picked")
    for key, change in (("share", {"share": r"D:\else"}), ("link", {"rules": []}),
                        ("files", {"rules": []}), ("service", {"server": "Stopped"}),
                        ("net", {"nets": []})):
        c = {k: o for k, o, _t in pc.evaluate({**good, **change}, r"C:\PPD_Procreate", prog, 8799)[0]}
        ok(not c[key], f"{key} missing is seen")
    acc = {"name": "ppdipad", "exists": True, "ours": True, "enabled": True, "access": True}
    c = dict((k, (o, t)) for k, o, t in pc.evaluate({**good, "account": acc},
                                                    r"C:\PPD_Procreate", prog, 8799)[0])
    ok(c["account"][0] and "ppdipad" in c["account"][1], "the iPad account is a check")
    for change, word in (({"exists": False}, "not made"), ({"ours": False}, "did not make"),
                         ({"enabled": False}, "switched off"), ({"access": False}, "may not")):
        c = dict((k, (o, t)) for k, o, t in pc.evaluate(
            {**good, "account": {**acc, **change}}, r"C:\PPD_Procreate", prog, 8799)[0])
        ok(not c["account"][0] and word in c["account"][1], c["account"][1])
    ok(pc.NAME_RE.match("ppdipad") and not pc.NAME_RE.match("a b") and
       not pc.NAME_RE.match("x"), "account names")
    pw = pc.new_password()
    ok(len(pw) == 12 and not set(pw) & set("0O1lI"), "a password easy to read back")
    f = pc.password_file(pw)
    ok(open(f, encoding="utf-8").read() == pw, "the password file")
    os.remove(f)
    s = core.pc_script(pc._ACCOUNT, PWFILE=f)
    ok("%" not in s.replace("%COMPUTERNAME", "") and "iPad access to PPD_Procreate" in s,
       "the account script is filled")
    ok("%" not in core.pc_script(pc._ACCOUNT_REMOVE), "and the remove script")
    ok(pc.test_login("ppd_nobody_here", "wrong-password") != 0, "a wrong login is told")
    ok(core.account() == ("ppdipad", ""), "no password until one is set")
    core.save_config(ipad_user="ppdipad", ipad_password="Secret12345")
    ok(core.account() == ("ppdipad", "Secret12345") and core.token(), "kept with the token")
    one = dict(good, rules=good["rules"][0], nets=good["nets"][1])
    ok(pc.evaluate(one, r"C:\PPD_Procreate", prog, 8799)[1] == "192.168.1.5", "a single entry")
    ok(pc.quote("a'; calc") == "'a" + "'" * 2 + "; calc'", "quoted as text")
    core.monitor.user = r"PC\o'hara"
    for s in (pc._SETUP, pc._REMOVE):
        ok("%" not in core.pc_script(s), "every placeholder is filled")
    core.monitor.user = ""
    import socket
    ok(core.host() == socket.gethostname().removesuffix(".local") + ".local", "the PC by name")
    ok(f"//{core.host()}:" in core.address() and
       core.smb_address() == f"smb://{core.host()}/{pc.SHARE}", "page and folder: one address")
    bpy.context.window_manager.ppd_link_host = "192.168.1.5"
    ok("192.168.1.5" in core.address() and "192.168.1.5" in core.smb_address(), "a typed address wins")
    bpy.context.window_manager.ppd_link_host = ""
    core.check_pc = lambda follow=0.0: None

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
    import json as _json
    st = _json.loads(call(url + "/state?t=testtoken")["body"])
    ok(st["pc"]["user"] == "ppdipad" and st["pc"]["password"] == "Secret12345" and
       st["pc"]["pcname"], "the page shows the iPad account and the PC's name")
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
    found, _u, _s = compose.extract(body, ("SHD",), stage)
    ok((prepare.pixels(bpy.data.images.load(found["SHD"]["path"]), n) == shd).all(),
       "PSD round trip is exact")

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
    r = call(url + f"/upload?t=testtoken", *form(f"Anything_k{okey} (2).psd", body))
    ok(b"VHC_Test.Wheel: SHD" in r["body"], "the key in the name finds it")
    r = call(url + "/upload?t=testtoken", *form("Other_k0123ab.psd", body))
    ok(len(core.inbox) == 1, "a key of another .blend waits")
    core.drop(core.inbox[0])
    keyed = os.path.join(tmp, "uv.psd")
    psd.write(keyed, n, [(f"UV layout k{okey}", shd, 64, True), ("SHD", shd, 255, True)], shd)
    with open(keyed, "rb") as f:
        keyed = f.read()
    r = call(url + "/upload?t=testtoken", *form("Renamed in Procreate.psd", keyed))
    ok(b"VHC_Test.Wheel: SHD" in r["body"], "or the key in the UV layer's name")
    grouped = os.path.join(tmp, "g.psd")
    psd.write(grouped, n, [{"name": "TEX", "opacity": 128, "children": [
        {"name": "a", "px": shd, "blend": "mul "}, {"name": "b", "px": shd}]},
        {"name": "ALB", "children": [{"name": "x", "px": shd, "blend": "scrn"}]}], shd)
    with open(grouped, "rb") as f:
        r = call(url + "/upload?t=testtoken", *form(f"VHC_Test.Wheel_k{okey}.psd", f.read()))
    ok(low.ppd.tex_blend == 'MIX' and abs(low.ppd.tex_opacity - 128 / 255) < 1e-6,
       "TEX: the group's opacity is kept for Blender")
    ok(low.ppd.alb_blend == 'SCREEN' and b"Screen" in r["body"], "ALB: its one layer's Screen")
    names(low)

    print("watched folder")

    def wait(cond, sec=40):
        end = time.time() + sec
        while time.time() < end and not cond():
            core.tick()
            time.sleep(0.05)
        return cond()

    shd_file = idn.abspath(low.ppd.shd)
    for name in ("VHC_Test.Wheel.psd", "VHC_Test_Wheel (1).psd"):
        before = os.path.getmtime(shd_file)
        with open(os.path.join(drive, name), "wb") as f:
            f.write(body)
        ok(wait(lambda: os.path.getmtime(shd_file) != before), name + " is imported")
        ok(wait(lambda: len(core.watcher.done) > 0 and any(name in k for k in core.watcher.done)), "and noted")
        ok(wait(lambda: not os.path.exists(os.path.join(drive, name))), "and removed")
    before = os.path.getmtime(shd_file)
    with open(os.path.join(drive, "Renamed.psd"), "wb") as f:
        f.write(keyed)
    ok(wait(lambda: os.path.getmtime(shd_file) != before), "the UV layer's key, in the folder")
    ok(os.path.isfile(path), "the outbox is not imported")
    with open(os.path.join(drive, "VHC_Test.Nobody.psd"), "wb") as f:
        f.write(body)
    ok(wait(lambda: any("Nobody" in x for x in core.log_lines)), "a stranger is left alone")
    ok(os.path.isfile(os.path.join(drive, "VHC_Test.Nobody.psd")), "and kept")
    name = os.path.join(drive, "VHC_Test.Wheel.psd")    # imported, but could not be removed
    with open(name, "wb") as f:
        f.write(body)
    held = open(name, "rb")
    before = os.path.getmtime(shd_file)
    ok(wait(lambda: os.path.getmtime(shd_file) != before), "imported while it is held open")
    wait(lambda: False, 6)
    held.close()
    ok(os.path.isfile(name), "a file in use stays")
    before = os.path.getmtime(shd_file)
    core.stop()
    core.start()
    wait(lambda: False, 10)
    ok(os.path.getmtime(shd_file) == before and not core.inbox, "nothing is imported twice")
    core.stop()
    qr.encode("http://192.168.178.20:8770/?t=abcdefghijkl")

    print("central")
    second = os.path.join(tmp, "VHC_Other.blend")
    old = idn.abspath(low.ppd.alb)
    bpy.ops.wm.save_as_mainfile(filepath=second)
    ok(low.name == "VHC_Other.Wheel" and os.path.isfile(old), "Save As copies")
    names(low)
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

    print("clean up")
    texdir = idn.tex_dir()
    gone = os.path.join(texdir, "ALB_VHC_Third.Gone.png")
    other = os.path.join(texdir, "ALB_VHC_Else.Gone.png")
    for f in (gone, other):
        with open(f, "wb") as fh:
            fh.write(b"x")
    found = cleanup.collect()
    ok(gone in found["unused"] and other not in found["unused"], "only this .blend's files")
    ok(not any(idn.abspath(idn.image(low, k)) in found["unused"] for k in idn.KINDS
               if idn.image(low, k)), "used files stay")
    ok(not any("VHC_Third" not in os.path.basename(f) for f in found["previous"]),
       "backups of other names stay")
    os.makedirs(os.path.join(texdir, "_previous"), exist_ok=True)
    prev = os.path.join(texdir, "_previous", "SHD_VHC_Third.Wheel.png")
    with open(prev, "wb") as fh:
        fh.write(b"x")
    ok(prev in cleanup.collect()["previous"], "previous copies are found")
    ok(cleanup.recycle([gone]) == 1 and not os.path.exists(gone), "to the Recycle Bin")


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
