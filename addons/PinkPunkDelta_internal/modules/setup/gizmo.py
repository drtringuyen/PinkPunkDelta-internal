"""A 170 cm figure with a ruler, drawn over the viewport only (never rendered or exported)."""
import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

COLOR = (1.0, 0.25, 0.65, 0.9)
HEIGHT = 1.70
_handles = []

# rings per body part, metres: (center x, z, half width x, half depth y)
_LEG = ((.10, 0, .05, .11), (.10, .09, .045, .05), (.10, .48, .06, .06), (.09, .86, .085, .09))
_ARM = ((.31, .68, .035, .04), (.30, .85, .035, .035), (.26, 1.12, .045, .045),
        (.21, 1.40, .05, .05))
_PARTS = (
    ((0, 1.48, .05, .05), (0, 1.52, .075, .09), (0, 1.60, .08, .10), (0, 1.67, .06, .075),
     (0, 1.70, .01, .01)),
    ((0, .86, .16, .10), (0, 1.05, .14, .09), (0, 1.25, .18, .11), (0, 1.40, .19, .09),
     (0, 1.46, .06, .05)),
    _LEG, tuple((-r[0],) + r[1:] for r in _LEG),
    _ARM, tuple((-r[0],) + r[1:] for r in _ARM),
)


def _lines():
    out = []
    n = 12
    for part in _PARTS:
        rings = [[(cx + rx * math.cos(a * 2 * math.pi / n), ry * math.sin(a * 2 * math.pi / n), z)
                  for a in range(n)] for cx, z, rx, ry in part]
        for r in rings:
            for i in range(n):
                out += [r[i], r[(i + 1) % n]]
        for a, b in zip(rings, rings[1:]):
            for i in range(0, n, 2):
                out += [a[i], b[i]]
    x = .5                                  # ruler, a tick every 10 cm
    out += [(x, 0, 0), (x, 0, HEIGHT)]
    for i in range(18):
        w = .08 if i % 5 == 0 or i == 17 else .04
        out += [(x - w, 0, i / 10), (x, 0, i / 10)]
    out += [(x, 0, HEIGHT), (-.12, 0, HEIGHT)]
    return out


_LINES = _lines()


def _base(scene):
    k = 1.0 / (scene.unit_settings.scale_length or 1.0)
    o = scene.ppd.gizmo_offset
    return k, Vector((o[0], o[1], 0.0))


def _draw():
    k, o = _base(bpy.context.scene)
    sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    b = batch_for_shader(sh, 'LINES', {"pos": [Vector(p) * k + o for p in _LINES]})
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    sh.bind()
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", 1.5)
    sh.uniform_float("color", COLOR)
    b.draw(sh)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _draw_text():
    ctx = bpy.context
    k, o = _base(ctx.scene)
    p = location_3d_to_region_2d(ctx.region, ctx.region_data,
                                 Vector((.52, 0, HEIGHT)) * k + o)
    if p is None:
        return
    blf.size(0, 14 * ctx.preferences.system.ui_scale)
    blf.color(0, *COLOR)
    blf.position(0, p.x + 4, p.y - 5, 0)
    blf.draw(0, "170 cm")


def is_on():
    return bool(_handles)


def turn(on):
    view = bpy.types.SpaceView3D
    if on and not _handles:
        _handles.append(view.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW'))
        _handles.append(view.draw_handler_add(_draw_text, (), 'WINDOW', 'POST_PIXEL'))
    elif not on:
        unregister()
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                a.tag_redraw()


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), 'WINDOW')
