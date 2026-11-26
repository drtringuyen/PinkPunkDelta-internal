"""Layered 8-bit RGB PSD out (reading is modules/unpacking/compose.py), and a fast PNG writer.
Pure numpy - no bpy, so it runs in the server's threads. Pixels are top-down uint8 (H, W, 4),
straight alpha."""
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


# ------------------------------------------------------------------ writing
def _item(x):
    if isinstance(x, dict):
        d = {"opacity": 255, "visible": True, "blend": "norm", "px": None, "children": None}
        d.update(x)
        return d
    name, px, opacity, visible = x
    return {"name": name, "px": px, "opacity": opacity, "visible": visible, "blend": "norm",
            "children": None}


def _flat(items):
    """Top-first items (groups have children) as bottom-first layer records."""
    out = []
    for it in map(_item, reversed(items)):
        if it["children"] is not None:
            out.append({"name": "</Layer group>", "divider": 3, "px": None, "empty": True,
                        "opacity": 255, "visible": True, "blend": "norm"})
            out += _flat(it["children"])
            it = dict(it, divider=1, empty=True)
        out.append(it)
    return out


def write(path, size, layers, composite):
    """layers: top first; each (name, rgba or None = empty, opacity 0-255, visible), or a dict
    with name, px, opacity, visible, blend (PSD key), clip, mask (uint8 h x w) and children
    (a list: a group).
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
    for it in _flat(layers):
        name, px = it["name"], it["px"]
        if it.get("empty"):
            chans = [None] * 4
            box = (0, 0, 0, 0)
        elif px is None:
            chans = [constant(0)] * 4
            box = (0, 0, h, w)
        else:
            a = px[:, :, 3]
            chans = [constant(int(a[0, 0])) if (a == a[0, 0]).all() else pack_channel(a)]
            chans += [pack_channel(px[:, :, i]) for i in range(3)]
            packed[id(px)] = chans
            box = (0, 0, h, w)
        ids = [-1, 0, 1, 2]
        mask = it.get("mask")
        if mask is not None and not it.get("empty"):
            ids.append(-2)
            chans = chans + [pack_channel(mask)]
        rec = struct.pack(">4iH", *box, len(ids))
        for cid, ch in zip(ids, chans):
            rec += struct.pack(">hI", cid, 2 if ch is None else 2 + len(ch[0]) + len(ch[1]))
        uni = name.encode("utf-16-be")
        luni = struct.pack(">I", len(uni) // 2) + uni
        luni += b"\0" * (-len(luni) % 4)
        pas = name.encode("ascii", "replace")[:255]
        pas = bytes((len(pas),)) + pas
        pas += b"\0" * (-len(pas) % 4)
        mdata = struct.pack(">4iBB2x", 0, 0, h, w, 0, 0) if len(ids) == 5 else b""
        extra = struct.pack(">I", len(mdata)) + mdata + struct.pack(">I", 0) + pas
        extra += b"8BIMluni" + struct.pack(">I", len(luni)) + luni
        blend = it["blend"].encode("latin-1")
        if it.get("divider"):
            body = struct.pack(">I", it["divider"])
            if it["divider"] != 3:
                body += b"8BIM" + blend
            extra += b"8BIMlsct" + struct.pack(">I", len(body)) + body
        flags = (0 if it["visible"] else 2) | (0x18 if it.get("divider") else 0)
        rec += b"8BIM" + blend + struct.pack(">BBBB", it["opacity"], 1 if it.get("clip") else 0,
                                             flags, 0)
        rec += struct.pack(">I", len(extra)) + extra
        records.append(rec)
        data.append(chans)

    info_len = 2 + sum(map(len, records)) + sum(
        2 + (0 if ch is None else len(ch[0]) + len(ch[1])) for chans in data for ch in chans)
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
            for ch in chans:
                if ch is None:
                    f.write(struct.pack(">H", 0))
                else:
                    f.write(struct.pack(">H", 1) + ch[0] + ch[1])
        f.write(b"\0" * pad + struct.pack(">I", 0))                 # no global mask
        comp = packed.get(id(composite))
        comp = comp[1:] if comp else [pack_channel(composite[:, :, i]) for i in range(3)]
        f.write(struct.pack(">H", 1))
        for counts, _b in comp:
            f.write(counts)
        for _c, body in comp:
            f.write(body)


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
