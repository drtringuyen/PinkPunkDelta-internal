"""Main-thread side of the link: which object and texture a received file belongs to."""
import collections
import json
import os
import re
import secrets
import shutil
import socket
import time
import traceback
import uuid

import bpy

from ... import identity as idn
from ... import links
from ..bakenlink import bake, operators as bake_ops
from . import pc, prepare, psd, server as srv, watch

PORT = 8770
OUTBOX = "To iPad"
WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

server = None
watcher = None
monitor = pc.Monitor()
watch_folder = watch.folder        # the tests put their own here
inbox = []              # dicts: id, stem, psd, files {kind or '': path}
log_lines = collections.deque(maxlen=30)
_last = 0.0


def _config_path():
    return os.path.join(bpy.utils.user_resource('CONFIG', create=True), "ppd_livelink.json")


def config():
    """This computer's LiveLink settings (Blender's config folder, never in a .blend)."""
    try:
        with open(_config_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(**values):
    d = config()
    d.update(values)
    tmp = _config_path() + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, _config_path())


def token():
    """One per computer, kept, so the iPad's bookmark of the page keeps working."""
    t = config().get("token")
    if not t:
        t = secrets.token_urlsafe(9)
        save_config(token=t)
    return t


def account():
    """(name, password) of the iPad account; password '' until one was set here. Kept in
    plain text in Blender's config folder: it only opens PPD_Procreate."""
    d = config()
    return d.get("ipad_user") or pc.ACCOUNT, d.get("ipad_password", "")


def pc_name():
    """This PC by name: it stays when the number changes."""
    name = socket.gethostname()
    return name if name.lower().endswith(".local") else name + ".local"


def host():
    """The one address the iPad uses, for the page and the shared folder alike: typed, else the
    PC's name."""
    return bpy.context.window_manager.ppd_link_host.strip() or pc_name()


def number():
    """The same PC as a number, for a network that does not know its name."""
    return monitor.ip or srv.local_ips()[0]


def address(path=""):
    return f"http://{host()}:{PORT}/{path}?t={token()}"


def smb_address(name=""):
    return f"smb://{name or host()}/{pc.SHARE}"


def check_pc(follow=0.0):
    monitor.account = account()[0]
    monitor.start(watch_folder(), bpy.app.binary_path, PORT,
                  bpy.context.window_manager.ppd_link_host.strip(), follow)
    if not bpy.app.timers.is_registered(_check_tick):
        bpy.app.timers.register(_check_tick, first_interval=0.5)


def _check_tick():
    """The panel follows the check, link on or off."""
    if monitor.changed:
        monitor.changed = False
        redraw()
    return 0.5 if monitor.busy or monitor.changed else None


def pc_script(script, **extra):
    v = "{}.{}".format(*bpy.app.version[:2])
    return pc.fill(script, FOLDER=watch_folder(), SHARE=pc.SHARE, USER=monitor.user,
                   RULE=pc.rule_name(v), RULE_FILES=pc.RULE_FILES, PORT=str(PORT),
                   PROGRAM=bpy.app.binary_path, ACCOUNT=account()[0], NOTE=pc.ACCOUNT_NOTE,
                   **extra)


def log(msg):
    log_lines.appendleft(time.strftime("%H:%M:%S ") + msg)
    print("[PPD LiveLink]", msg.encode("ascii", "replace").decode())


def norm(name):
    return re.sub(r"[\s_\-.]+", " ", name.casefold()).strip()


def split_kind(stem):
    """'SHD_Tractor.Wheel' -> ('SHD', 'Tractor.Wheel')"""
    m = re.match(r"(ALB|NOR|SHD|TEX)[\s_\-.]+(.+)", stem, re.I)
    return (m.group(1).upper(), m.group(2)) if m else ("", stem)


def outbox():
    """Where Send to iPad puts the PSDs: inside the shared folder, so the iPad opens them."""
    return os.path.join(watch_folder(), OUTBOX)


def outbox_path(obj):
    return os.path.join(outbox(), idn.canvas_name(obj) + ".psd")


def sent(obj):
    """The PSD this object last sent, '' when none waits in the outbox."""
    p = outbox_path(obj)
    return p if bpy.data.filepath and os.path.isfile(p) else ""


def send(obj):
    """The object's latest textures, UV layout and BASE as one PSD in the outbox. Older PSDs
    of the same object (before a rename) go."""
    path = prepare.prepare(obj, outbox_path(obj))
    short = idn.short_key(obj)
    for e in os.scandir(outbox()):
        if e.name.lower().endswith(".psd") and idn.key_in(e.name) == short \
                and not links.same(e.path, path):
            try:
                os.remove(e.path)
            except OSError:
                pass
    log(f"Sent {os.path.basename(path)} ({os.path.getsize(path) / 1e6:.0f} MB)")
    return path


def find_object(name, key=""):
    """The object a file is for: the key in its name (or `key`, from its UV layer), else its
    name. A key of another .blend finds nothing here."""
    short = idn.key_in(name) or key
    if short:
        return idn.by_key(short)
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
    note = ""
    for k, (mode, opacity, label) in item.get("blend", {}).items():
        if k not in item["files"]:
            continue
        d = obj.ppd
        setattr(d, k.lower() + "_blend", mode)
        setattr(d, k.lower() + "_opacity", opacity)
        if mode != 'MIX' or opacity < 1:
            note += f" {k} keeps {label} {opacity * 100:.0f} % in Blender."
    drop(item)
    msg = f"✓ {obj.name}: {', '.join(done)} updated.{note}{item.get('note', '')}"
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
    obj = find_object(name, item.get("key", ""))
    if obj is not None and (item["psd"] or kind):
        return deliver(obj, item, kind)
    for old in [i for i in inbox if i["stem"] == item["stem"]]:
        drop(old)               # only the newest waits
    item["id"] = uuid.uuid4().hex
    inbox.append(item)
    log(f"'{item['stem']}' waits for its object")
    return f"⏳ '{item['stem']}' is new: pick its object in Blender (03.LiveLink)"


def match(link, stem, key=""):
    """For the watcher's thread: the full name of the object a file is for, '' when none.
    Reads only what publish() left on the server."""
    short = idn.key_in(stem) or key
    if short:
        hits = [n for k, n in link.keys.items() if k.startswith(short)]
        return hits[0] if len(hits) == 1 else ""
    return link.names.get(norm(stem), "")


def redraw():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


def publish():
    objs, files, names, taken = [], {}, {}, set()
    server.keys = {o.ppd.key: o.name for o in idn.objects() if o.ppd.key}
    for o in idn.objects():
        for n in {norm(o.name), norm(o.ppd.canvas) if o.ppd.canvas else ""} - {""}:
            if n in names:
                taken.add(n)
            names[n] = o.name
    for n in taken:             # two objects answer to it: neither does
        del names[n]
    server.names = names
    for o in sorted(idn.objects(), key=lambda o: o.name):
        p = sent(o)
        ready = bool(p)
        if ready:
            files[o.name] = p
        objs.append({"name": o.name, "psd": ready,
                     "size": os.path.getsize(p) if ready else 0,
                     "kinds": [k for k in idn.KINDS if idn.image(o, k)]})
    server.psd_files = files
    name, password = account()
    info = {"ready": monitor.ready, "smb": smb_address(), "user": name, "password": password,
            "pcname": host().removesuffix(".local"),
            "smbnumber": smb_address(number()),
            "checks": [{"ok": ok, "text": text} for _k, ok, text in monitor.checks]}
    server.state = {"pc": info, "blend": os.path.basename(bpy.data.filepath) or "(unsaved .blend)",
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
                        if job.result.startswith("✓"):
                            links.undo_push("PPD: textures from the iPad")
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
    global server, watcher
    if server is not None:
        return
    s = srv.LinkServer(PORT, WEB_DIR, token())
    s.start()
    server = s
    check_pc()
    publish()
    record = os.path.join(bpy.utils.user_resource('CONFIG', create=True), "ppd_watch.json")
    watcher = watch.Watcher(s, lambda n, key="": match(s, n, key), log, record,
                            lambda: watch_folder())
    watcher.start()
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=0.1, persistent=True)
    log(f"Listening on port {PORT}")


def stop():
    global server, watcher
    if watcher is not None:
        watcher.stop()
        watcher = None
    if server is not None:
        server.stop()
        server.cleanup()
        server = None
        inbox.clear()
        log("Stopped")
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
