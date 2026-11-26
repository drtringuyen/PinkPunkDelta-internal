"""The main colors of a picture. Pure numpy.

Pixels are grouped in OKLab, where a distance is how different two colors look; k-means finds
the groups, each group's mean is a color. The colors are then put in a row where each one sits
next to the ones most like it - by hue first, lightness counting half: a chain from the
darkest, always to the nearest, then improved by reversing stretches (2-opt) while that
shortens the row."""
import numpy as np

SAMPLES = 60000
ITERATIONS = 24
LIGHTNESS = 0.5         # in the row, lightness counts half: dark red sits by light red, not dark blue


def srgb_to_linear(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_oklab(rgb):
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]], np.float32)
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]], np.float32)
    lms = np.cbrt(np.clip(rgb, 0, None) @ m1.T)
    return lms @ m2.T


def _kmeans_pp(lab, k, rng):
    """Starting centers far apart from each other (k-means++)."""
    centers = [lab[rng.integers(len(lab))]]
    d = np.full(len(lab), np.inf, np.float32)
    for _ in range(1, k):
        d = np.minimum(d, ((lab - centers[-1]) ** 2).sum(1))
        total = d.sum()
        if total <= 0:
            break
        centers.append(lab[rng.choice(len(lab), p=d / total)])
    return np.array(centers, np.float32)


def kmeans(lab, k, seed=0):
    """(centers, labels): at most k groups (fewer when the picture has fewer colors)."""
    rng = np.random.default_rng(seed)
    centers = _kmeans_pp(lab, k, rng)
    labels = np.zeros(len(lab), np.int64)
    for _ in range(ITERATIONS):
        d = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(2)
        new = d.argmin(1)
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        for i in range(len(centers)):
            hit = labels == i
            if hit.any():
                centers[i] = lab[hit].mean(0)
    keep = [i for i in range(len(centers)) if (labels == i).any()]
    remap = np.full(len(centers), -1)
    remap[keep] = np.arange(len(keep))
    return centers[keep], remap[labels]


def order(lab):
    """Indices of the colors in a row where neighbors look alike."""
    n = len(lab)
    if n < 3:
        return list(np.argsort(lab[:, 0]))
    w = lab * np.array([LIGHTNESS, 1.0, 1.0], np.float32)  # a hue's shades stay together
    dist = np.sqrt(((w[:, None, :] - w[None, :, :]) ** 2).sum(2))
    path = [int(np.argmin(lab[:, 0]))]          # from the darkest
    left = set(range(n)) - set(path)
    while left:
        nxt = min(left, key=lambda j: dist[path[-1], j])
        path.append(nxt)
        left.remove(nxt)
    better = True
    while better:                               # 2-opt, an open path
        better = False
        for i in range(n - 2):
            for j in range(i + 2, n):
                a, b = path[i], path[i + 1]
                c = path[j]
                d = path[j + 1] if j + 1 < n else None
                old = dist[a, b] + (dist[c, d] if d is not None else 0)
                new = dist[a, c] + (dist[b, d] if d is not None else 0)
                if new < old - 1e-9:
                    path[i + 1:j + 1] = path[i + 1:j + 1][::-1]
                    better = True
    return path


def palette(rgba, k, srgb=True, seed=0):
    """rgba: (N, 4) floats 0-1 of a picture's pixels. Returns [(linear rgb, share)] in a row
    where similar colors are neighbors. Pixels less than half opaque are left out."""
    px = np.asarray(rgba, np.float32).reshape(-1, 4)
    px = px[px[:, 3] >= 0.5][:, :3]
    if not len(px):
        return []
    if len(px) > SAMPLES:
        px = px[np.random.default_rng(seed).choice(len(px), SAMPLES, replace=False)]
    lin = srgb_to_linear(px) if srgb else np.clip(px, 0, None)
    lab = linear_to_oklab(lin)
    centers, labels = kmeans(lab, max(1, min(k, len(lab))), seed)
    share = np.bincount(labels, minlength=len(centers)) / len(labels)
    out = []
    for i in order(centers):
        hit = labels == i
        out.append((tuple(float(v) for v in lin[hit].mean(0)), float(share[i])))
    return out
