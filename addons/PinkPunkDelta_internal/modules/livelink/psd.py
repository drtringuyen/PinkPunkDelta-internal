"""Layered 8-bit RGB PSD in and out, and a fast PNG writer. Pure numpy - no bpy, so it runs in
the server's threads. Pixels are top-down uint8 (H, W, 4), straight alpha."""
import struct
import zlib

import numpy as np

BLOCK = 128


# ------------------------------------------------------------------ PackBits
def _pack_row(row):
    """Runs where a 128 px block is one value, literals elsewhere: fast and valid."""
    out = bytearray()
    n = len(row)
    for s in range(0, n, BLOCK):
        b = row[s:s + BLOCK]
        k = len(b)
        if k > 1 and (b == b[0]).all():
            out += bytes((257 - k, int(b[0])))
        else:
            out += bytes((k - 1,))
            out += b.tobytes()
    return bytes(out)


def pack_channel(ch):
    """(row byte counts '>u2', data) of one channel."""
    h, w = ch.shape
    counts = np.empty(h, '>u2')
    rows = []
    full = w // BLOCK * BLOCK
    blocks = ch[:, :full].reshape(h, -1, BLOCK)
    flat = (blocks == blocks[:, :, :1]).all(axis=2)
    same_row = (ch == ch[:, :1]).all(axis=1)
    cache = {}
    lit = np.full((blocks.shape[1], BLOCK + 1), BLOCK - 1, np.uint8)
    for y in range(h):
        if same_row[y]:
            v = int(ch[y, 0])
            r = cache.get(v)
            if r is None:
                r = cache[v] = _pack_row(ch[y])
        elif not flat[y].any() and full == w:
            lit[:, 1:] = blocks[y]
            r = lit.tobytes()
        else:
            r = _pack_row(ch[y])
        counts[y] = len(r)
        rows.append(r)
    return counts.tobytes(), b"".join(rows)


def unpack_channel(data, counts, h, w):
    out = np.zeros((h, w), np.uint8)
    pos = 0
    for y in range(h):
        end = pos + int(counts[y])
        buf = bytearray()
        i = pos
        while i < end and len(buf) < w:
            c = data[i]
            i += 1
            if c < 128:
                buf += data[i:i + c + 1]
                i += c + 1
            elif c > 128:
                buf += bytes((data[i],)) * (257 - c)
                i += 1
        pos = end
        row = np.frombuffer(bytes(buf[:w]), np.uint8)
        out[y, :len(row)] = row
    return out


# ------------------------------------------------------------------ writing
def write(path, size, layers, composite):
    """layers: (name, rgba or None = empty, opacity 0-255, visible), TOP layer first.
    composite: rgba shown as the preview."""
    h = w = size
    records, data = [], []
    blank = {}

    def constant(v):
        if v not in blank:
            row = _pack_row(np.full(w, v, np.uint8))
            blank[v] = (np.full(h, len(row), '>u2').tobytes(), row * h)
        return blank[v]

    packed = {}
    for name, px, opacity, visible in reversed(layers):     # a PSD stores bottom first
        if px is None:
            chans = [constant(0)] * 4
        else:
            a = px[:, :, 3]
            chans = [constant(int(a[0, 0])) if (a == a[0, 0]).all() else pack_channel(a)]
            chans += [pack_channel(px[:, :, i]) for i in range(3)]
            packed[id(px)] = chans
        rec = struct.pack(">4iH", 0, 0, h, w, 4)
        for cid, (counts, body) in zip((-1, 0, 1, 2), chans):
            rec += struct.pack(">hI", cid, 2 + len(counts) + len(body))
        uni = name.encode("utf-16-be")
        luni = struct.pack(">I", len(uni) // 2) + uni
        luni += b"\0" * (-len(luni) % 4)
        pas = name.encode("ascii", "replace")[:255]
        pas = bytes((len(pas),)) + pas
        pas += b"\0" * (-len(pas) % 4)
        extra = struct.pack(">II", 0, 0) + pas
        extra += b"8BIMluni" + struct.pack(">I", len(luni)) + luni
        rec += b"8BIMnorm" + struct.pack(">BBBB", opacity, 0, 0 if visible else 2, 0)
        rec += struct.pack(">I", len(extra)) + extra
        records.append(rec)
        data.append(chans)

    info_len = 2 + sum(map(len, records)) + sum(
        2 + len(c) + len(b) for chans in data for c, b in chans)
    pad = info_len % 2
    info_len += pad
    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3))
        f.write(struct.pack(">I", 0))                               # color mode
        res = b"8BIM" + struct.pack(">HH", 1005, 0) + struct.pack(
            ">IIHHIHH", 16, 300 << 16, 1, 1, 300 << 16, 1, 1)       # 300 dpi
        f.write(struct.pack(">I", len(res)) + res)
        f.write(struct.pack(">II", info_len + 8, info_len))
        f.write(struct.pack(">h", len(records)))
        for r in records:
            f.write(r)
        for chans in data:
            for counts, body in chans:
                f.write(struct.pack(">H", 1) + counts + body)
        f.write(b"\0" * pad + struct.pack(">I", 0))                 # no global mask
        comp = packed.get(id(composite))
        comp = comp[1:] if comp else [pack_channel(composite[:, :, i]) for i in range(3)]
        f.write(struct.pack(">H", 1))
        for counts, _b in comp:
            f.write(counts)
        for _c, body in comp:
            f.write(body)


# ------------------------------------------------------------------ reading
class _Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def take(self, n):
        if self.p + n > len(self.d):
            raise ValueError("The PSD is cut off")
        b = self.d[self.p:self.p + n]
        self.p += n
        return bytes(b)

    def get(self, fmt):
        v = struct.unpack(">" + fmt, self.take(struct.calcsize(">" + fmt)))
        return v[0] if len(v) == 1 else v


def _channel(buf, w, h, depth, big):
    if not w or not h:
        return np.zeros((h, w), np.uint8)
    comp = struct.unpack(">H", buf[:2])[0]
    body = buf[2:]
    bpp = depth // 8
    if comp == 1:
        cs = 4 if big else 2
        counts = np.frombuffer(body[:h * cs], '>u4' if big else '>u2')
        raw = unpack_channel(body[h * cs:], counts, h, w * bpp)
    else:
        if comp in (2, 3):
            body = zlib.decompress(body)
        raw = np.frombuffer(body[:w * h * bpp], np.uint8).reshape(h, w * bpp)
        if comp == 3 and bpp == 1:
            raw = np.cumsum(raw, axis=1, dtype=np.uint8)
        elif comp == 3:
            raw = np.cumsum(raw.reshape(h, w, 2).copy().view('>u2')[:, :, 0].astype(np.uint16),
                            axis=1, dtype=np.uint16)
            return (raw >> 8).astype(np.uint8)
    return raw if bpp == 1 else raw[:, ::2]         # the high byte of 16 bit


def read_layers(data, names):
    """{name: rgba} of the layers or groups called one of `names` (any case), the canvas size,
    and the names of the layers that were not used. A group's layers are merged; hidden layers
    inside a group are left out; a layer's own opacity counts."""
    r = _Reader(memoryview(data))
    if r.take(4) != b"8BPS":
        raise ValueError("Not a PSD file")
    ver = r.get("H")
    big = ver == 2
    r.take(6)
    _n, H, W, depth, mode = r.get("HIIHH")
    if mode != 3 or depth not in (8, 16):
        raise ValueError("Only 8 or 16 bit RGB PSD files can be read")
    r.take(r.get("I"))
    r.take(r.get("I"))
    L = "Q" if big else "I"
    total = r.get(L)
    if not total:
        raise ValueError("The PSD has no layers")
    r.get(L)
    layers = []
    for _ in range(abs(r.get("h"))):
        top, left, bottom, right, nch = r.get("4iH")
        chans = [r.get("h" + L) for _c in range(nch)]
        r.take(4)
        r.take(4)
        opacity, clip, flags, _f = r.get("BBBB")
        elen = r.get("I")
        end = r.p + elen
        r.take(r.get("I"))
        r.take(r.get("I"))
        n = r.get("B")
        name = r.take(n).decode("mac_roman", "replace")
        r.take(-(n + 1) % 4)
        kind = 0
        while r.p + 12 <= end:
            sig, key = r.take(4), r.take(4)
            if sig not in (b"8BIM", b"8B64"):
                break
            wide = big and key in (b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32",
                                   b"Mtrn", b"Alph", b"FMsk", b"lnk2", b"FEid", b"FXid", b"PxSD")
            ln = r.get("Q" if wide else "I")
            at = r.p
            if key == b"luni" and ln >= 4:
                name = r_unicode(r, ln) or name
            elif key == b"lsct" and ln >= 4:
                kind = r.get("I")
            r.p = min(end, at + ln + (ln % 2))
        r.p = end
        layers.append(dict(name=name.strip("\0 "), box=(top, left, bottom, right), chans=chans,
                           opacity=opacity, visible=not flags & 2, kind=kind))
    for la in layers:
        la["at"] = []
        for cid, ln in la["chans"]:
            la["at"].append((cid, r.p, ln))
            r.p += ln

    def pixels(la):
        out = np.zeros((H, W, 4), np.uint8)
        t, l, b, ri = la["box"]
        h, w = max(0, b - t), max(0, ri - l)
        y0, x0, y1, x1 = max(0, t), max(0, l), min(H, b), min(W, ri)
        if y1 <= y0 or x1 <= x0:
            return out
        out[y0:y1, x0:x1, 3] = 255
        for cid, at, ln in la["at"]:
            if cid not in (-1, 0, 1, 2):
                continue
            ch = _channel(r.d[at:at + ln], w, h, depth, big)
            out[y0:y1, x0:x1, 3 if cid == -1 else cid] = ch[y0 - t:y1 - t, x0 - l:x1 - l]
        if la["opacity"] < 255:
            out[:, :, 3] = (out[:, :, 3].astype(np.uint16) * la["opacity"] // 255)
        return out

    wanted = {n.casefold(): n for n in names}
    found, unused = {}, []
    stack = []      # open groups, read top-down: the wanted name they belong to
    for la in reversed(layers):
        if la["kind"] in (1, 2):
            parent = stack[-1][0] if stack else None
            # a hidden SHD / TEX group still counts; a hidden group inside it does not
            vis = parent is None or (la["visible"] and stack[-1][1])
            stack.append((parent or wanted.get(la["name"].casefold()), vis))
            continue
        if la["kind"] == 3:
            if stack:
                stack.pop()
            continue
        group = stack[-1][0] if stack else None
        name = group or wanted.get(la["name"].casefold())
        if name is None:
            unused.append(la["name"])
            continue
        if group and not (la["visible"] and stack[-1][1]):
            continue
        px = pixels(la)
        found[name] = under(found[name], px) if name in found else px
    return found, (W, H), unused


def r_unicode(r, ln):
    n = r.get("I")
    return r.take(min(n * 2, ln - 4)).decode("utf-16-be", "replace")


def under(top, low):
    """`top` over `low`, straight alpha, in bands to keep memory down."""
    out = np.empty_like(top)
    for y in range(0, len(top), 512):
        a, b = top[y:y + 512].astype(np.float32), low[y:y + 512].astype(np.float32)
        aa, ba = a[:, :, 3:] / 255, b[:, :, 3:] / 255
        oa = aa + ba * (1 - aa)
        rgb = (a[:, :, :3] * aa + b[:, :, :3] * ba * (1 - aa)) / np.maximum(oa, 1e-6)
        out[y:y + 512, :, :3] = np.where(oa > 0, rgb + .5, 0)
        out[y:y + 512, :, 3:] = oa * 255 + .5
    return out


# ------------------------------------------------------------------ PNG
def write_png(path, px):
    """RGBA PNG, 'Up' filtered, light compression."""
    h, w = px.shape[:2]

    def chunk(f, tag, body):
        f.write(struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body)))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        chunk(f, b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        z = zlib.compressobj(2)
        prev = np.zeros((1, w * 4), np.uint8)
        for y in range(0, h, 256):
            rows = px[y:y + 256].reshape(-1, w * 4)
            block = np.empty((len(rows), w * 4 + 1), np.uint8)
            block[:, 0] = 2
            block[:, 1:] = rows - np.concatenate((prev, rows[:-1]))
            prev = rows[-1:].copy()
            part = z.compress(block.tobytes())
            if part:
                chunk(f, b"IDAT", part)
        chunk(f, b"IDAT", z.flush())
        chunk(f, b"IEND", b"")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24]) if head[:8] == b"\x89PNG\r\n\x1a\n" else None
