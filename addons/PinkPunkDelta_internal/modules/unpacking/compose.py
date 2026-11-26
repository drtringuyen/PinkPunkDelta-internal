"""A PSD from Procreate, unpacked into one image per texture. Pure numpy, no bpy: runs in the
LiveLink server's threads.

Inside a texture's group (ALB, NOR, TEX or SHD) everything is merged so it looks as it did in
Procreate: hidden layers are left out; masks, clipping masks, opacity and blend modes are
applied. The group itself - its blend mode and opacity against what lies below it - is not
applied: the image comes out plain and those two settings are handed back, for Blender to
apply in the shader. A group that only holds one layer hands back that layer's mode and
opacity the same way.

Work goes in bands of rows, so an 8K PSD never needs more than a few hundred MB."""
import struct
import zlib

import numpy as np

BAND = 256
GROUP_OPEN, GROUP_CLOSED, GROUP_END = 1, 2, 3

# PSD blend key -> the mode's name in Blender's Mix node (what the shader can redo)
BLENDER_MODE = {
    "norm": "MIX", "pass": "MIX", "mul ": "MULTIPLY", "scrn": "SCREEN", "over": "OVERLAY",
    "lddg": "ADD", "fsub": "SUBTRACT", "dark": "DARKEN", "lite": "LIGHTEN", "div ": "DODGE",
    "idiv": "BURN", "sLit": "SOFT_LIGHT", "lLit": "LINEAR_LIGHT", "diff": "DIFFERENCE",
    "smud": "EXCLUSION", "fdiv": "DIVIDE", "hue ": "HUE", "sat ": "SATURATION",
    "colr": "COLOR", "lum ": "VALUE",
}
MODE_LABEL = {
    "norm": "Normal", "pass": "Pass Through", "mul ": "Multiply", "scrn": "Screen",
    "over": "Overlay", "lddg": "Add", "fsub": "Subtract", "dark": "Darken", "lite": "Lighten",
    "div ": "Color Dodge", "idiv": "Color Burn", "sLit": "Soft Light", "hLit": "Hard Light",
    "lLit": "Linear Light", "vLit": "Vivid Light", "pLit": "Pin Light", "hMix": "Hard Mix",
    "diff": "Difference", "smud": "Exclusion", "fdiv": "Divide", "hue ": "Hue",
    "sat ": "Saturation", "colr": "Color", "lum ": "Luminosity", "lbrn": "Linear Burn",
    "dkCl": "Darker Color", "lgCl": "Lighter Color", "diss": "Dissolve",
}
FLAT_NORMAL = (128, 128, 255)


# ------------------------------------------------------------------ reading the file
class _Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise ValueError("The PSD is cut off")
        b = self.d[self.p:self.p + n]
        self.p += n
        return bytes(b)

    def get(self, fmt):
        v = struct.unpack(">" + fmt, self.take(struct.calcsize(">" + fmt)))
        return v[0] if len(v) == 1 else v


class Layer:
    group = False

    def __init__(self):
        self.name, self.blend, self.opacity, self.fill = "", "norm", 255, 255
        self.visible, self.clip = True, False
        self.box = (0, 0, 0, 0)             # top, left, bottom, right
        self.chans = {}                     # id -> (offset, length)
        self.mask = None                    # (box, default 0-255) or None
        self.divider = 0


class Group(Layer):
    group = True

    def __init__(self, header, children):
        super().__init__()
        self.__dict__.update({k: v for k, v in header.__dict__.items()})
        self.children = children            # bottom first


class PSD:
    def __init__(self, data):
        self.data = memoryview(data)
        r = _Reader(self.data)
        if r.take(4) != b"8BPS":
            raise ValueError("Not a PSD file")
        ver = r.get("H")
        self.big = ver == 2
        r.take(6)
        _n, self.H, self.W, self.depth, mode = r.get("HIIHH")
        if mode != 3 or self.depth not in (8, 16):
            raise ValueError("Only 8 or 16 bit RGB PSD files can be read")
        r.take(r.get("I"))                  # color mode data
        r.take(r.get("I"))                  # image resources
        L = "Q" if self.big else "I"
        if not r.get(L):
            raise ValueError("The PSD has no layers")
        if not r.get(L):
            raise ValueError("The PSD has no layers")
        records = [self._record(r, L) for _ in range(abs(r.get("h")))]
        for la in records:
            at = {}
            for cid, ln in la.chans:
                at[cid] = (r.p, ln)
                r.p += ln
            la.chans = at
        self.layers = records
        self.roots = self._tree(records)
        self._cache = {}

    def _record(self, r, L):
        la = Layer()
        la.box = r.get("4i")
        nch = r.get("H")
        la.chans = [r.get("h" + L) for _c in range(nch)]
        r.take(4)
        la.blend = r.take(4).decode("latin-1")
        la.opacity, clip, flags, _f = r.get("BBBB")
        la.clip, la.visible = clip == 1, not flags & 2
        elen = r.get("I")
        end = r.p + elen
        mlen = r.get("I")
        mend = r.p + mlen
        if mlen >= 18:
            box = r.get("4i")
            default, mflags = r.get("BB")
            if not mflags & 2 and box[2] > box[0] and box[3] > box[1]:
                la.mask = (box, default)
        r.p = mend
        r.take(r.get("I"))                  # blending ranges
        n = r.get("B")
        la.name = r.take(n).decode("mac_roman", "replace")
        r.take(-(n + 1) % 4)
        while r.p + 12 <= end:
            sig, key = r.take(4), r.take(4)
            if sig not in (b"8BIM", b"8B64"):
                break
            wide = self.big and key in (b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32",
                                        b"Mtrn", b"Alph", b"FMsk", b"lnk2", b"FEid", b"FXid",
                                        b"PxSD")
            ln = r.get("Q" if wide else "I")
            at = r.p
            if key == b"luni" and ln >= 4:
                k = r.get("I")
                la.name = r.take(min(k * 2, ln - 4)).decode("utf-16-be", "replace") or la.name
            elif key in (b"lsct", b"lsdk") and ln >= 4:
                la.divider = r.get("I")
                if ln >= 12:
                    r.take(4)
                    la.blend = r.take(4).decode("latin-1")
            elif key == b"iOpa" and ln >= 1:
                la.fill = r.get("B")
            r.p = min(end, at + ln + (ln % 2))
        r.p = end
        la.name = la.name.strip("\0 ")
        return la

    @staticmethod
    def _tree(records):
        """File order is bottom first: a group's end marker, its layers, then its header."""
        stack = [[]]
        for la in records:
            if la.divider == GROUP_END:
                stack.append([])
            elif la.divider in (GROUP_OPEN, GROUP_CLOSED):
                children = stack.pop() if len(stack) > 1 else []
                stack[-1].append(Group(la, children))
            else:
                stack[-1].append(la)
        while len(stack) > 1:               # a group without its header: keep its layers
            kids = stack.pop()
            stack[-1].extend(kids)
        return stack[0]

    # -------------------------------------------------------------- names
    def walk(self, nodes=None):
        for n in (self.roots if nodes is None else nodes):
            yield n
            if n.group:
                yield from self.walk(n.children)

    def names(self):
        return [n.name for n in self.walk()]

    def find(self, name):
        """The top-level layer or group of that name, else the first one deeper down."""
        want = name.casefold()
        for n in reversed(self.roots):
            if n.name.casefold() == want:
                return n
        for n in self.walk():
            if n.name.casefold() == want:
                return n
        return None

    # -------------------------------------------------------------- channels
    def _rows(self, la, cid, y0, y1, box):
        """Rows y0..y1 (canvas) of channel `cid` as uint8 (h, box width); box = its rect."""
        top, left, bottom, right = box
        w, h = right - left, bottom - top
        a, b = max(y0, top), min(y1, bottom)
        out = np.zeros((y1 - y0, max(w, 0)), np.uint8)
        if b <= a or w <= 0 or cid not in la.chans:
            return out
        off, ln = la.chans[cid]
        comp = struct.unpack(">H", self.data[off:off + 2])[0]
        bpp = self.depth // 8
        body = off + 2
        if comp == 1:
            key = (id(la), cid)
            starts = self._cache.get(key)
            cs = 4 if self.big else 2
            if starts is None:
                counts = np.frombuffer(self.data[body:body + h * cs], '>u4' if self.big else '>u2')
                starts = np.concatenate(([0], np.cumsum(counts, dtype=np.int64))) + body + h * cs
                self._cache[key] = starts
            for y in range(a, b):
                row = _unpack(self.data[starts[y - top]:starts[y - top + 1]], w * bpp)
                out[y - y0] = row[::bpp] if bpp == 2 else row
        elif comp == 0:
            raw = np.frombuffer(self.data[body:body + w * h * bpp], np.uint8).reshape(h, w * bpp)
            out[a - y0:b - y0] = raw[a - top:b - top, ::bpp]
        else:
            key = (id(la), cid, "zip")
            full = self._cache.get(key)
            if full is None:
                raw = np.frombuffer(zlib.decompress(self.data[body:off + ln]), np.uint8)
                if bpp == 1:
                    full = raw[:w * h].reshape(h, w)
                    if comp == 3:
                        full = np.cumsum(full, axis=1, dtype=np.uint8)
                else:
                    v = raw[:w * h * 2].reshape(h, w, 2).copy().view('>u2')[:, :, 0]
                    if comp == 3:
                        v = np.cumsum(v.astype(np.uint16), axis=1, dtype=np.uint16)
                    full = (v >> 8).astype(np.uint8)
                self._cache.clear()         # one big channel at a time
                self._cache[key] = full
            out[a - y0:b - y0] = full[a - top:b - top]
        return out

    def pixels(self, la, y0, y1):
        """Premultiplied float32 (h, W, 4) of a layer in rows y0..y1: its mask applied, not its
        opacity."""
        H, W = y1 - y0, self.W
        out = np.zeros((H, W, 4), np.float32)
        top, left, bottom, right = la.box
        x0, x1 = max(0, left), min(W, right)
        if x1 > x0 and min(y1, bottom) > max(y0, top):
            for cid, ch in ((0, 0), (1, 1), (2, 2), (-1, 3)):
                if cid == -1 and -1 not in la.chans:
                    rows = np.full((H, right - left), 255, np.uint8)
                    rows[:max(0, top - y0)] = 0
                    rows[max(0, bottom - y0):] = 0
                else:
                    rows = self._rows(la, cid, y0, y1, la.box)
                out[:, x0:x1, ch] = rows[:, x0 - left:x1 - left]
            out /= 255.0
        if la.fill < 255:
            out[:, :, 3] *= la.fill / 255.0
        self.apply_mask(la, out, y0, y1, premultiplied=False)
        out[:, :, :3] *= out[:, :, 3:]
        return out

    def apply_mask(self, la, px, y0, y1, premultiplied=True):
        """The layer's mask on its pixels: on alpha, and on a premultiplied color too."""
        if la.mask is None or -2 not in la.chans:
            return
        box, default = la.mask
        top, left, bottom, right = box
        m = np.full((y1 - y0, self.W), default / 255.0, np.float32)
        rows = self._rows(la, -2, y0, y1, box).astype(np.float32) / 255.0
        x0, x1 = max(0, left), min(self.W, right)
        ya, yb = max(y0, top) - y0, min(y1, bottom) - y0
        if x1 > x0 and yb > ya:
            m[ya:yb, x0:x1] = rows[ya:yb, x0 - left:x1 - left]
        if premultiplied:
            px *= m[:, :, None]
        else:
            px[:, :, 3] *= m


def _unpack(src, n):
    """One PackBits row into n bytes."""
    out = bytearray()
    src = bytes(src)
    i, end = 0, len(src)
    while i < end and len(out) < n:
        c = src[i]
        i += 1
        if c < 128:
            out += src[i:i + c + 1]
            i += c + 1
        elif c > 128:
            out += src[i:i + 1] * (257 - c)
            i += 1
    row = np.frombuffer(bytes(out[:n]), np.uint8)
    if len(row) < n:
        row = np.concatenate((row, np.zeros(n - len(row), np.uint8)))
    return row


# ------------------------------------------------------------------ blending
def _lum(c):
    return c[..., 0:1] * 0.3 + c[..., 1:2] * 0.59 + c[..., 2:3] * 0.11


def _clip_color(c):
    lum = _lum(c)
    n = c.min(axis=-1, keepdims=True)
    x = c.max(axis=-1, keepdims=True)
    with np.errstate(divide='ignore', invalid='ignore'):
        c = np.where(n < 0, lum + (c - lum) * lum / np.maximum(lum - n, 1e-6), c)
        c = np.where(x > 1, lum + (c - lum) * (1 - lum) / np.maximum(x - lum, 1e-6), c)
    return c


def _set_lum(c, lum):
    return _clip_color(c + (lum - _lum(c)))


def _sat(c):
    return c.max(axis=-1, keepdims=True) - c.min(axis=-1, keepdims=True)


def _set_sat(c, s):
    n = c.min(axis=-1, keepdims=True)
    x = c.max(axis=-1, keepdims=True)
    rng = x - n
    with np.errstate(divide='ignore', invalid='ignore'):
        out = np.where(rng > 1e-6, (c - n) * s / np.maximum(rng, 1e-6), 0.0)
    return out


def blend(mode, b, s):
    """B(backdrop, source) of straight colors 0-1."""
    if mode in ("mul ",):
        return b * s
    if mode == "scrn":
        return b + s - b * s
    if mode == "over":
        return blend("hLit", s, b)
    if mode == "hLit":
        return np.where(s <= 0.5, b * 2 * s, blend("scrn", b, 2 * s - 1))
    if mode == "dark":
        return np.minimum(b, s)
    if mode == "lite":
        return np.maximum(b, s)
    with np.errstate(divide='ignore', invalid='ignore'):
        if mode == "div ":
            return np.where(b <= 0, 0.0, np.where(s >= 1, 1.0, np.minimum(1.0, b / (1 - s))))
        if mode == "idiv":
            return np.where(b >= 1, 1.0, np.where(s <= 0, 0.0,
                                                  1 - np.minimum(1.0, (1 - b) / s)))
        if mode == "fdiv":
            return np.where(s <= 0, np.where(b > 0, 1.0, 0.0), np.minimum(1.0, b / s))
        if mode == "vLit":
            return np.where(s <= 0.5, blend("idiv", b, 2 * s), blend("div ", b, 2 * s - 1))
    if mode == "sLit":
        d = np.where(b <= 0.25, ((16 * b - 12) * b + 4) * b, np.sqrt(b))
        return np.where(s <= 0.5, b - (1 - 2 * s) * b * (1 - b), b + (2 * s - 1) * (d - b))
    if mode == "diff":
        return np.abs(b - s)
    if mode == "smud":
        return b + s - 2 * b * s
    if mode == "lddg":
        return np.minimum(1.0, b + s)
    if mode == "lbrn":
        return np.maximum(0.0, b + s - 1)
    if mode == "fsub":
        return np.maximum(0.0, b - s)
    if mode == "lLit":
        return np.clip(b + 2 * s - 1, 0, 1)
    if mode == "pLit":
        return np.where(s <= 0.5, np.minimum(b, 2 * s), np.maximum(b, 2 * s - 1))
    if mode == "hMix":
        return np.where(b + s >= 1, 1.0, 0.0)
    if mode == "hue ":
        return _set_lum(_set_sat(s, _sat(b)), _lum(b))
    if mode == "sat ":
        return _set_lum(_set_sat(b, _sat(s)), _lum(b))
    if mode == "colr":
        return _set_lum(s, _lum(b))
    if mode == "lum ":
        return _set_lum(b, _lum(s))
    if mode == "dkCl":
        return np.where(_lum(s) < _lum(b), s, b)
    if mode == "lgCl":
        return np.where(_lum(s) > _lum(b), s, b)
    return s


def _straight(p):
    a = p[..., 3:]
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(a > 0, p[..., :3] / np.maximum(a, 1e-8), 0.0)


def composite(back, src, mode, opacity=1.0, atop=False):
    """`src` onto `back` (both premultiplied), in place on `back`. atop: only where `back` is
    (a clipping mask)."""
    if opacity < 1.0:
        src = src * opacity
    sa, ba = src[..., 3:], back[..., 3:]
    normal = mode in ("norm", "pass", "diss")
    both = None if normal else sa * ba * np.clip(blend(mode, _straight(back), _straight(src)),
                                                  0, 1)
    if atop:
        if normal:
            back[..., :3] = src[..., :3] * ba + back[..., :3] * (1 - sa)
        else:
            back[..., :3] = both + back[..., :3] * (1 - sa)
        return back
    mixed = src[..., :3] if normal else (1 - ba) * src[..., :3] + both
    back[..., :3] = mixed + back[..., :3] * (1 - sa)
    back[..., 3:] = sa + ba * (1 - sa)
    return back


class Merger:
    def __init__(self, psd):
        self.psd = psd

    def node(self, n, y0, y1, plain=False):
        """A layer or a group as premultiplied pixels (a group merged on its own). plain:
        its own opacity is left to the caller."""
        if n.group:
            px = self.children(n.children, y0, y1)
            self.psd.apply_mask(n, px, y0, y1)
            return px
        return self.psd.pixels(n, y0, y1)

    def children(self, items, y0, y1, override=None):
        """Bottom-first layers merged onto transparent. override: {id(node): (mode, opacity)}."""
        out = np.zeros((y1 - y0, self.psd.W, 4), np.float32)
        i = 0
        while i < len(items):
            base = items[i]
            clipped = []
            i += 1
            while i < len(items) and items[i].clip and not items[i].group:
                clipped.append(items[i])
                i += 1
            if not base.visible:
                continue
            px = self.node(base, y0, y1)
            for c in clipped:
                if c.visible:
                    composite(px, self.psd.pixels(c, y0, y1), c.blend, c.opacity / 255, atop=True)
            mode, opacity = (override or {}).get(id(base), (base.blend, base.opacity / 255))
            composite(out, px, mode, opacity)
        return out


# ------------------------------------------------------------------ one texture out
def plan(psd, kind):
    """(node, remembered (blend key, opacity 0-1), override) for a texture, None if absent."""
    root = psd.find(kind)
    if root is None:
        return None
    remember = (root.blend, root.opacity / 255)
    override = {}
    if root.group:
        shown = [c for c in root.children if c.visible]
        if remember[0] in ("norm", "pass") and remember[1] >= 1.0 and len(shown) == 1 \
                and not shown[0].group and not shown[0].clip:
            only = shown[0]
            if only.blend not in ("norm", "pass") or only.opacity < 255:
                remember = (only.blend, only.opacity / 255)
                override[id(only)] = ("norm", 1.0)
    return root, remember, override


def bands_of(psd, root, override, background=None, seen=None):
    """Straight uint8 RGBA rows of the merged texture, BAND rows at a time. seen: a list whose
    first item turns True once a pixel is not transparent (before the background)."""
    m = Merger(psd)
    for y0 in range(0, psd.H, BAND):
        y1 = min(psd.H, y0 + BAND)
        if root.group:
            px = m.children(root.children, y0, y1, override)
            psd.apply_mask(root, px, y0, y1)
        else:
            px = psd.pixels(root, y0, y1)
        if seen is not None and not seen[0]:
            seen[0] = bool((px[..., 3] > 0.5 / 255).any())
        if background is not None:
            bg = np.zeros_like(px)
            bg[..., :3] = np.asarray(background, np.float32) / 255
            bg[..., 3] = 1
            px = composite(bg, px, "norm")
        out = np.empty(px.shape, np.uint8)
        out[..., :3] = np.clip(_straight(px) * 255 + 0.5, 0, 255)
        out[..., 3] = np.clip(px[..., 3] * 255 + 0.5, 0, 255)
        yield out


def extract(data, kinds, stage, ignore=("uv layout", "base", "background", "background color")):
    """Every texture of `kinds` found in the PSD, merged, as a PNG at stage('.png').
    Returns ({kind: {"path": path or '' (empty), "blend": Blender mode, "mode": PSD key,
    "opacity": 0-1}}, unused top-level names, canvas size)."""
    psd = PSD(data)
    found = {}
    for kind in kinds:
        p = plan(psd, kind)
        if p is None:
            continue
        root, (mode, opacity), override = p
        path = stage(".png")
        seen = [False]
        write_png(path, psd.W, psd.H, bands_of(
            psd, root, override, FLAT_NORMAL if kind.upper() == "NOR" else None, seen))
        filled = seen[0]
        found[kind] = {"path": path if filled else "", "mode": mode, "opacity": opacity,
                       "blend": BLENDER_MODE.get(mode, "MIX")}
        psd._cache.clear()
    wanted = {k.casefold() for k in kinds}
    unused = [n.name for n in reversed(psd.roots) if n.name.casefold() not in wanted
              and not n.name.casefold().startswith(ignore)]
    return found, unused, (psd.W, psd.H)


def layer_names(data):
    return PSD(data).names()


# ------------------------------------------------------------------ PNG
def write_png(path, w, h, bands):
    """RGBA PNG from bands of rows."""
    def chunk(f, tag, body):
        f.write(struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body)))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        chunk(f, b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        z = zlib.compressobj(2)
        prev = np.zeros((1, w * 4), np.uint8)
        for px in bands:
            rows = np.ascontiguousarray(px).reshape(-1, w * 4)
            block = np.empty((len(rows), w * 4 + 1), np.uint8)
            block[:, 0] = 2
            block[:, 1:] = rows - np.concatenate((prev, rows[:-1]))
            prev = rows[-1:].copy()
            part = z.compress(block.tobytes())
            if part:
                chunk(f, b"IDAT", part)
        chunk(f, b"IDAT", z.flush())
        chunk(f, b"IEND", b"")
