"""Main-thread side of the link: which object and texture a received file belongs to."""
import collections
import json
import os
import re
import secrets
import shutil
import time
import traceback
import uuid

import bpy

from ... import identity as idn
from ... import links
from ..bakenlink import bake, operators as bake_ops
from . import psd, server as srv

PORT = 8770
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

server = None
inbox = []              # dicts: id, stem, psd, files {kind or '': path}
log_lines = collections.deque(maxlen=30)
_last = 0.0


def token():
    """One per computer, kept, so the iPad Shortcut is built once."""
    path = os.path.join(bpy.utils.user_resource('CONFIG', create=True), "ppd_livelink.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["token"]
    except (OSError, ValueError, KeyError):
        t = secrets.token_urlsafe(9)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"token": t}, f)
        return t


def address(path=""):
    host = bpy.context.window_manager.ppd_link_host.strip() or srv.local_ips()[0]
    return f"http://{host}:{PORT}/{path}?t={token()}"


def log(msg):
    log_lines.appendleft(time.strftime("%H:%M:%S ") + msg)
    print("[PPD LiveLink]", msg.encode("ascii", "replace").decode())


def norm(name):
    return re.sub(r"[\s_\-.]+", " ", name.casefold()).strip()


def split_kind(stem):
    """'SHD_Tractor.Wheel' -> ('SHD', 'Tractor.Wheel')"""
    m = re.match(r"(SHD|TEX)[\s_\-.]+(.+)", stem, re.I)
    return (m.group(1).upper(), m.group(2)) if m else ("", stem)


def find_object(name):
    objs = idn.objects()
    for o in objs:
        if o.name == name:
            return o
    hits = [o for o in objs if norm(o.name) == norm(name) or
            (o.ppd.canvas and norm(o.ppd.canvas) == norm(name))]
    return hits[0] if len(hits) == 1 else None


def put(obj, kind, path):
    """The received image becomes obj's SHD / TEX: 8K, in the textures folder, linked."""
    tmp = idn.tex_path(obj, kind) + ".part.png"
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    note = ""
    if psd.png_size(path) == (idn.SIZE, idn.SIZE):
        shutil.copyfile(path, tmp)
    else:
        links.scale_file(path, tmp, idn.colorspace(kind))
        note = " (scaled to 8K)"
    bake.install(obj, kind, tmp)
    return kind + note


def deliver(obj, item, kind=""):
    done = [put(obj, k or kind, p) for k, p in item["files"].items()]
    drop(item)
    msg = f"✓ {obj.name}: {', '.join(done)} updated.{item.get('note', '')}"
    log(msg)
    return msg


def drop(item):
    for p in item["files"].values():
        try:
            os.remove(p)
        except OSError:
            pass
    if item in inbox:
        inbox.remove(item)


def receive(item):
    """A file from the iPad. Returns the text the iPad shows."""
    if not bpy.data.filepath:
        drop(item)
        return "⚠ Save the .blend in Blender first"
    kind, name = ("", item["stem"]) if item["psd"] else split_kind(item["stem"])
    obj = find_object(name)
    if obj is not None and (item["psd"] or kind):
        return deliver(obj, item, kind)
    for old in [i for i in inbox if i["stem"] == item["stem"]]:
        drop(old)               # only the newest waits
    item["id"] = uuid.uuid4().hex
    inbox.append(item)
    log(f"'{item['stem']}' waits for its object")
    return f"⏳ '{item['stem']}' is new: pick its object in Blender (03.LiveLink)"


def redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


def publish():
    objs, files = [], {}
    for o in sorted(idn.objects(), key=lambda o: o.name):
        p = idn.psd_path(o)
        ready = bool(bpy.data.filepath) and os.path.isfile(p)
        if ready:
            files[o.name] = p
        objs.append({"name": o.name, "psd": ready,
                     "size": os.path.getsize(p) if ready else 0,
                     "kinds": [k for k in idn.KINDS if idn.image(o, k)]})
    server.psd_files = files
    server.state = {"blend": os.path.basename(bpy.data.filepath) or "(unsaved .blend)",
                    "objects": objs, "waiting": [i["stem"] for i in inbox],
                    "log": list(log_lines)[:10]}


def tick():
    global _last
    if server is None:
        return None
    try:
        if not bake_ops.busy:           # a bake owns Blender: uploads wait their turn
            try:
                job = server.jobs.get_nowait()
            except Exception:
                job = None
            if job is not None:
                if job.cancelled:
                    drop(job.payload)
                else:
                    try:
                        job.result = receive(job.payload)
                    except Exception as e:
                        traceback.print_exc()
                        job.result = f"⚠ {e}"
                        log(job.result)
                    job.done.set()
                redraw()
                _last = 0.0
        if time.time() - _last > 2.0:
            publish()
            _last = time.time()
    except Exception:
        traceback.print_exc()
    return 0.25


def start():
    global server
    if server is not None:
        return
    s = srv.LinkServer(PORT, WEB_DIR, token())
    s.start()
    server = s
    publish()
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.1, persistent=True)
    log(f"Listening on port {PORT}")


def stop():
    global server
    if server is not None:
        server.stop()
        server.cleanup()
        server = None
        inbox.clear()
        log("Stopped")
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
