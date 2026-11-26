"""Shadow, High and Gloss estimated from a part's main color (Mid), the way a painter would:
the shadow darker, a little more saturated and cooler; the light lighter, a little less
saturated and warmer; the gloss nearly white in the light's hue. Worked out in OKLab, where
lightness and hue behave as they look. Pure numpy."""
import math

import numpy as np

BLUE = math.radians(264)        # OKLab hue of a cool blue
YELLOW = math.radians(100)      # and of a warm yellow
SNAP = 0.06                     # a palette color this close (OKLab) is used instead
WEIGHT = np.array([0.5, 1.0, 1.0])  # picking from the palette: hue counts more than lightness

_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def to_lab(rgb):
    return _M2 @ np.cbrt(_M1 @ np.clip(np.asarray(rgb, float), 0, None))


def to_rgb(lab):
    lms = np.linalg.solve(_M2, np.asarray(lab, float)) ** 3
    return np.linalg.solve(_M1, lms)


def _lch(lab):
    return lab[0], math.hypot(lab[1], lab[2]), math.atan2(lab[2], lab[1])


def _toward(h, target, most):
    d = (target - h + math.pi) % (2 * math.pi) - math.pi
    return h + max(-most, min(most, d))


def _rgb(L, C, h):
    """In gamut: the chroma comes down until every channel is 0-1."""
    L = min(max(L, 0.0), 1.0)
    for _ in range(30):
        rgb = to_rgb((L, C * math.cos(h), C * math.sin(h)))
        if rgb.min() >= -1e-4 and rgb.max() <= 1 + 1e-4:
            break
        C *= 0.9
    return tuple(float(v) for v in np.clip(rgb, 0, 1))


def estimate(mid):
    """{'shadow', 'high', 'gloss'}: linear RGB, from Mid (linear RGB)."""
    L, C, h = _lch(to_lab(mid))
    tinted = C > 0.02           # a gray stays gray
    hs = _toward(h, BLUE, math.radians(14)) if tinted else h
    hh = _toward(h, YELLOW, math.radians(8)) if tinted else h
    return {
        "shadow": _rgb(L * 0.6, C * 1.1, hs),
        "high": _rgb(L + (1 - L) * 0.5, C * 0.85, hh),
        "gloss": _rgb(max(0.95, L + (1 - L) * 0.85), C * 0.25, hh),
    }


def snap(color, palette):
    """The palette color closest to `color` when it is close enough, else `color`. And
    whether it came from the palette."""
    if not palette:
        return color, False
    lab = to_lab(color)
    best = min(palette, key=lambda p: np.linalg.norm(to_lab(p) - lab))
    if np.linalg.norm(to_lab(best) - lab) < SNAP:
        return tuple(best), True
    return color, False


def from_palette(mid, palette, gap=0.03):
    """Every ramp color out of the palette: {'mid', 'shadow', 'high', 'gloss'}.
    Mid is the palette color nearest the main color; Shadow, High and Gloss are the palette
    colors nearest to their estimates, Shadow darker than Mid, High lighter, Gloss at least as
    light as High. A slot with no such palette color keeps its estimate (and is told)."""
    labs = [(tuple(p), to_lab(p)) for p in palette]
    m_rgb, m_lab = min(labs, key=lambda c: np.linalg.norm(c[1] - to_lab(mid)))
    est = estimate(m_rgb)
    out, missing = {"mid": m_rgb}, []

    def nearest(target, ok):
        hits = [c for c in labs if ok(c[1]) and c[0] != m_rgb]
        if not hits:
            return None
        t = to_lab(target) * WEIGHT
        return min(hits, key=lambda c: np.linalg.norm(c[1] * WEIGHT - t))

    L = m_lab[0]
    s = nearest(est["shadow"], lambda lab: lab[0] < L - gap)
    h = nearest(est["high"], lambda lab: lab[0] > L + gap)
    hL = h[1][0] if h else L + gap
    g = nearest(est["gloss"], lambda lab: lab[0] >= hL)
    if g is not None and h is not None and g[0] == h[0]:
        g = nearest(est["gloss"], lambda lab: lab[0] > hL)
    for key, hit in (("shadow", s), ("high", h), ("gloss", g)):
        if hit is None:
            out[key] = est[key]
            missing.append(key)
        else:
            out[key] = hit[0]
    return out, missing
