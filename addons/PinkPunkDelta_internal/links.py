"""Keeps names, files and links together.

A 1 s timer sees F2 renames and Shift+D duplicates; a save under a new file name changes the
Central. Files are moved on a rename and copied when the old .blend still needs them; nothing
on disk is overwritten by a rename (a file in the way goes to textures/_previous)."""
import os
import shutil
import traceback

import bpy
from bpy.app.handlers import persistent

from . import identity as idn
from . import material

INTERVAL = 1.0
_moved = {}             # new path -> old path, this session: an undone F2 finds its file
_paused = 0
messages = []           # last sync's problems, shown by 01.Setup


class paused:
    """with links.paused(): no renaming while a bake or a file swap runs."""
    def __enter__(self):
        global _paused
        _paused += 1

    def __exit__(self, *a):
        global _paused
        _paused -= 1


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def set_aside(path):
    """Keep one previous copy before `path` is replaced."""
    if not os.path.isfile(path):
        return
    d = os.path.join(os.path.dirname(path), "_previous")
    os.makedirs(d, exist_ok=True)
    os.replace(path, os.path.join(d, os.path.basename(path)))


def _shared(path, but):
    """Another set-up object's texture uses this file."""
    for o in idn.objects():
        for k in idn.KINDS:
            img = idn.image(o, k)
            if img and (o, k) != but and idn.abspath(img) and same(idn.abspath(img), path):
                return True
    return False


def _bring(old, new, copy):
    """File `old` becomes `new`. A case-only rename works too."""
    if same(old, new):
        if os.path.basename(old) != os.path.basename(new):
            os.rename(old, new)
        return
    os.makedirs(os.path.dirname(new), exist_ok=True)
    set_aside(new)
    if copy:
        shutil.copy2(old, new)
    else:
        shutil.move(old, new)
        _moved[new] = old


def find_file(obj, kind, img):
    """Where the texture's file is now ('' = nowhere): its own path, the place this session
    moved it to before an undo, or the name it should have."""
    cur = idn.abspath(img) if img else ""
    if cur and os.path.isfile(cur):
        return cur
    if cur:
        for new, old in reversed(list(_moved.items())):
            if same(old, cur) and os.path.isfile(new):
                return new
    want = idn.tex_path(obj, kind)
    return want if os.path.isfile(want) else ""


def sync_texture(obj, kind, copy=False):
    img = idn.image(obj, kind)
    want = idn.tex_path(obj, kind)
    src = find_file(obj, kind, img)
    if img is None:
        if not src:             # only a file with exactly this object's name is picked up
            return
        img = bpy.data.images.load(want, check_existing=True)
        img.colorspace_settings.name = idn.colorspace(kind)
        idn.set_image(obj, kind, img)
    if img.library is not None:
        return
    if src:
        exact = same(src, want) and os.path.basename(src) == os.path.basename(want)
        if not exact:
            owned = same(os.path.dirname(src), idn.tex_dir()) or \
                same(os.path.dirname(src), _old_dir() or src)
            _bring(src, want, copy or not owned or _shared(src, (obj, kind)))
        cur = idn.abspath(img)
        if not cur or not same(cur, want) or os.path.basename(cur) != os.path.basename(want):
            img.filepath = idn.relpath(want)
    name = os.path.basename(want)
    if img.name != name:
        img.name = name


def _old_dir():
    p = idn.scene_data().central_path
    return os.path.join(os.path.dirname(p), idn.TEX_FOLDER) if p else ""


def sync_object(obj, old_central="", copy=False):
    d = obj.ppd
    c = idn.central()
    old = d.synced
    if old and obj.name == old and d.part:
        part = d.part
    else:
        part = idn.part_of(obj.name, c, old_central)
    want = idn.full_name(part, c)
    if obj.name != want:
        obj.name = want
    d.part = idn.part_of(obj.name, c)       # Blender adds .001 when the name is taken
    d.synced = obj.name
    for kind in idn.KINDS:
        try:
            sync_texture(obj, kind, copy)
        except OSError as e:
            messages.append(f"{kind}_{obj.name}: {e}")
    if old and old != obj.name:
        for base in (idn.tex_dir(), _old_dir()):
            src = os.path.join(base, old + ".psd") if base else ""
            if src and os.path.isfile(src):
                try:
                    _bring(src, idn.psd_path(obj), copy)
                except OSError as e:
                    messages.append(f"{obj.name}.psd: {e}")
                break
    mat = material.ensure(obj)
    name = "MAT_" + obj.name
    if mat.name != name and mat.library is None:
        mat.name = name


def split_duplicates():
    """A Shift+D copy becomes its own object: new key, own material, no textures yet.
    An Alt+D copy (same mesh) stays a plain instance of the first one."""
    by_key = {}
    for o in idn.objects():
        by_key.setdefault(o.ppd.key, []).append(o)
    for key, objs in by_key.items():
        if len(objs) < 2 and key:
            continue
        objs.sort(key=lambda o: (o.name != o.ppd.synced, o.name))
        first = objs[0]
        if not first.ppd.key:
            first.ppd.key = idn.new_key()
        for o in objs[1:]:
            d = o.ppd
            if o.data == first.data:
                d.is_setup = False
                continue
            d.key = idn.new_key()
            d.synced = d.part = d.canvas = ""
            for k in idn.KINDS:
                idn.set_image(o, k, None)
            own_material(o)


def own_material(obj):
    """A copy of the material this object shares with another one."""
    old = obj.ppd.material
    if old is None:
        return
    obj.ppd.material = old.copy()
    for s in obj.material_slots:
        if s.material == old:
            s.material = obj.ppd.material


def sync_all(old_central="", copy=False):
    if not bpy.data.filepath:
        return
    messages.clear()
    split_duplicates()
    for o in idn.objects():
        sync_object(o, old_central, copy)


def central_changed():
    s = idn.scene_data()
    return bool(bpy.data.filepath and s.central and (
        s.central != idn.file_central() or not same(s.central_path, bpy.data.filepath)))


def update_central():
    """The .blend has a new name or place: everything follows. Textures are copied while the
    old .blend still exists, moved when it is gone."""
    s = idn.scene_data()
    old, old_path = s.central, s.central_path
    copy = bool(old_path) and os.path.isfile(old_path) and not same(old_path, bpy.data.filepath)
    s.central = idn.file_central()
    sync_all(old, copy)
    s.central_path = bpy.data.filepath


def adopt_central():
    s = idn.scene_data()
    if not s.central:
        s.central, s.central_path = idn.file_central(), bpy.data.filepath


def problems():
    """(object name or '', text) of everything Check All Links corrects or reports."""
    out = []
    if central_changed():
        out.append(("", f"Central is '{idn.scene_data().central}', the file is "
                        f"'{idn.file_central()}'"))
    seen = {}
    for o in idn.objects():
        d = o.ppd
        if o.name != idn.full_name(d.part):
            out.append((o.name, "object name"))
        if d.material is None:
            out.append((o.name, "no material"))
        else:
            if d.material.name != "MAT_" + o.name:
                out.append((o.name, f"material is named {d.material.name}"))
            if d.material in seen:
                out.append((o.name, f"shares its material with {seen[d.material]}"))
            seen[d.material] = o.name
            if d.material not in [s.material for s in o.material_slots]:
                out.append((o.name, "its material is not on the object"))
            for k in idn.KINDS:
                n = d.material.node_tree.nodes.get(material.node_name(k))
                if n is None:
                    out.append((o.name, f"no PPD_{k} node in the material"))
                elif n.image != idn.image(o, k):
                    out.append((o.name, f"{k} is not on its material node"))
        for k in idn.KINDS:
            img = idn.image(o, k)
            if img is None:
                if os.path.isfile(idn.tex_path(o, k)):
                    out.append((o.name, f"{k} file is not linked"))
                continue
            p = idn.abspath(img)
            if not p or not os.path.isfile(p):
                out.append((o.name, f"{k} file is missing"))
            elif not same(p, idn.tex_path(o, k)):
                out.append((o.name, f"{k} file is elsewhere"))
            elif tuple(img.size) != (idn.SIZE, idn.SIZE):
                out.append((o.name, f"{k} is {img.size[0]}x{img.size[1]}, not 8K"))
        if d.original is None and len(o.data.polygons):
            out.append((o.name, "no Original picked"))
    return out


def check_and_fix():
    """Returns (number corrected, what is left)."""
    before = problems()
    seen = set()
    for o in idn.objects():
        if o.ppd.material in seen:
            own_material(o)
        if o.ppd.material is not None:
            seen.add(o.ppd.material)
    if central_changed():
        update_central()
    else:
        sync_all()
    for o in idn.objects():
        for k in idn.KINDS:
            img = idn.image(o, k)
            if img is not None and os.path.isfile(idn.abspath(img)):
                img.reload()
                if tuple(img.size) != (idn.SIZE, idn.SIZE) and img.size[0]:
                    to_8k(img)
    left = problems()
    return max(0, len(before) - len(left)), left


def to_8k(img):
    """The image and its file, scaled to 8192 x 8192 (one previous copy kept)."""
    path = idn.abspath(img)
    scale_file(path, path + ".part.png", img.colorspace_settings.name)
    set_aside(path)
    os.replace(path + ".part.png", path)
    img.reload()


def scale_file(src, dst, space):
    """`src` as an 8K PNG at `dst`."""
    work = bpy.data.images.load(src, check_existing=False)
    try:
        work.colorspace_settings.name = space
        work.scale(idn.SIZE, idn.SIZE)
        work.filepath_raw, work.file_format = dst, 'PNG'
        work.save()
    finally:
        bpy.data.images.remove(work)


# ------------------------------------------------------------------ watching
def _needs_sync():
    keys = set()
    lost = {os.path.normcase(os.path.abspath(p)) for p in _moved.values()}
    for o in idn.objects():
        d = o.ppd
        if d.synced != o.name or d.key in keys:
            return True
        keys.add(d.key)
        if lost:                # an undo of F2 put the old paths back
            for k in idn.KINDS:
                img = idn.image(o, k)
                p = idn.abspath(img) if img else ""
                if p and os.path.normcase(os.path.abspath(p)) in lost \
                        and not os.path.isfile(p) and find_file(o, k, img):
                    return True
    return False


def _busy():
    wm = bpy.context.window_manager
    return wm is None or any(
        m.bl_idname.startswith(("TRANSFORM_OT", "SCULPT_OT", "PAINT_OT", "OBJECT_OT"))
        for w in wm.windows for m in w.modal_operators)


def _tick():
    try:
        if _paused or not bpy.data.filepath or central_changed() or _busy():
            return INTERVAL
        if _needs_sync():
            sync_all()
    except Exception:
        traceback.print_exc()
    return INTERVAL


def _save_again():
    """The names changed right after a save: save them too."""
    if bpy.data.filepath and bpy.data.is_dirty:
        bpy.ops.wm.save_mainfile()
    return None


@persistent
def _on_save(*_):
    if _paused or not central_changed() or not idn.objects():
        return
    try:
        update_central()
        bpy.app.timers.register(_save_again, first_interval=0.2)
    except Exception:
        traceback.print_exc()


@persistent
def _on_load(*_):
    _moved.clear()
    messages.clear()


def register():
    bpy.app.handlers.save_post.append(_on_save)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_tick, first_interval=INTERVAL, persistent=True)


def unregister():
    for h, f in ((bpy.app.handlers.save_post, _on_save), (bpy.app.handlers.load_post, _on_load)):
        if f in h:
            h.remove(f)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
