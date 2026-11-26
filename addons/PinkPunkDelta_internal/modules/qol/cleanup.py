"""Files the add-on made that nothing uses any more. Only files named after this .blend's
Central are looked at, so other .blend files sharing the textures folder are never touched.
They go to the Recycle Bin, not away for good."""
import ctypes
import os
import re
import shutil
import sys
import tempfile

import bpy

from ... import identity as idn

CATEGORIES = (
    ("unused", "Unused textures", "Texture files of objects that are gone or renamed"),
    ("previous", "Previous copies", "The copies kept in textures/_previous when a file was "
                                    "replaced"),
    ("sent", "Sent PSDs", "PSDs in PPD_Procreate/To iPad of this .blend. Remove them once the "
                          "iPad imported them"),
    ("temp", "LiveLink temp", "Leftover files of LiveLink sessions that ended"),
)


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def _used():
    out = set()
    for img in bpy.data.images:
        p = idn.abspath(img) if img.source == 'FILE' else ""
        if p:
            out.add(_norm(p))
    for o in idn.objects():
        for k in idn.KINDS:
            if idn.image(o, k) is not None:
                out.add(_norm(idn.tex_path(o, k)))
    return out


def _ours(name, central):
    """A file named after this .blend: KIND_<Central>.x.png, <Central>.x.psd, or a half-written
    one of those."""
    c = re.escape(central)
    return re.match(rf"^((ALB|NOR|SHD|TEX|BAS)_)?{c}\..+\.(png|psd)(\.part(\.png)?)?$",
                    name, re.I) is not None


def _files(folder):
    try:
        return [e for e in os.scandir(folder) if e.is_file()]
    except OSError:
        return []


def collect():
    """{category: [paths]}"""
    found = {k: [] for k, _l, _d in CATEGORIES}
    if not bpy.data.filepath:
        return found
    central = idn.central()
    used = _used()
    tex = idn.tex_dir()
    for e in _files(tex):
        if _ours(e.name, central) and _norm(e.path) not in used:
            found["unused"].append(e.path)
    for e in _files(os.path.join(tex, "_previous")):
        if _ours(e.name, central):
            found["previous"].append(e.path)
    try:
        from ..livelink import core
        keys = {idn.short_key(o) for o in idn.objects()}
        for e in _files(core.outbox()):
            if e.name.lower().endswith(".psd") and idn.key_in(e.name) in keys:
                found["sent"].append(e.path)
        staging = core.server.staging if core.server is not None else ""
    except ImportError:
        staging = ""
    # one LiveLink per PC (its port): every other session's folder is a leftover
    for e in os.scandir(tempfile.gettempdir()):
        if e.name.startswith("ppd_livelink_") and e.is_dir() and \
                (not staging or _norm(e.path) != _norm(staging)):
            found["temp"].append(e.path)
    return found


def size(paths):
    total = 0
    for p in paths:
        if os.path.isdir(p):
            for root, _d, files in os.walk(p):
                total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        elif os.path.isfile(p):
            total += os.path.getsize(p)
    return total


def recycle(paths):
    """Into the Recycle Bin (Windows); elsewhere deleted. Returns how many are gone."""
    paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
    if not paths:
        return 0
    if sys.platform == "win32":
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", wintypes.LPCWSTR)]

        op = SHFILEOPSTRUCTW()
        op.wFunc = 3                                    # FO_DELETE
        op.pFrom = "\0".join(paths) + "\0\0"
        op.fFlags = 0x40 | 0x10 | 0x4 | 0x400           # undo, no confirm, silent, no error UI
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    else:
        for p in paths:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
    return sum(not os.path.exists(p) for p in paths)
