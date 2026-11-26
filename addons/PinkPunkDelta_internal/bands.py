"""The shader of a set-up object: its own group NPR_<full name>, built here from its data.

A part is a number in the INT face attribute PPD_PART (0 = no part): one attribute, because
EEVEE refuses a material that reads dozens of them. Every part has a light spectrum
(identity.PPD_Part): 1-3 shades - Shadow, Mid, High - and Gloss.

    COLOR    BASE (the part's Mid, flat) -> ALB over it by alpha -> TEX over that by alpha
             Diffuse Color = that color / Mid, so paint is shaded like its part
    LIGHT    NOR bends the normal -> Light Evaluation -> the part's shade ramp -> Diffuse Light
             (x the light's color when Light Color is on)
             Light Evaluation (Glossy) above the part's Gloss border -> Gloss color
    SHD      gray: 0.5 leaves the light as it is, darker pushes it toward Shadow, lighter
             toward High (where painted: its alpha). Applied to the light before the ramp
    EXPOSURE multiplies the light (every light counts, averaged)
    VIEW     Show BASE / ALB / TEX / NOR / SHD, Solo 1-5 shows one layer flat

The group is rebuilt from the object's data whenever parts come or go; colors and borders
are written straight into its nodes."""
import bpy

from . import identity as idn

ATTR = "PPD_PART"
TAG = "PPD_"
VERSION = 2
NEWEST = "SHD_SHIFT"            # a node only the latest shader has: older ones are rebuilt
CLAY = (0.8, 0.8, 0.8, 1.0)
GRAY = (0.5, 0.5, 0.5, 1.0)
ROUGHNESS = 0.35

INPUTS = (  # name, socket, default, min, max
    ("ALB", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0), None, None),
    ("ALB Alpha", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ("TEX", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0), None, None),
    ("TEX Alpha", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ("NOR", "NodeSocketColor", (0.5, 0.5, 1.0, 1.0), None, None),
    ("SHD", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0), None, None),
    ("SHD Alpha", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ("Light Color", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ("Show BASE", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Show ALB", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Show TEX", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Show NOR", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Show SHD", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Solo", "NodeSocketFloat", 0.0, 0.0, 5.0),
    ("Exposure", "NodeSocketFloat", 1.0, 0.0, 16.0),
)
SHOW = ("BASE", "ALB", "TEX", "NOR", "SHD")     # Solo 1..5
IMAGE_INPUTS = {"ALB": ("ALB", "ALB Alpha"), "TEX": ("TEX", "TEX Alpha"),
                "NOR": ("NOR", None), "SHD": ("SHD", "SHD Alpha")}


def _find(nt, idname):
    return next((n for n in nt.nodes if n.bl_idname == idname), None)


def suits(nt):
    return nt is not None and nt.bl_idname == 'ShaderNodeTree' \
        and _find(nt, "ShaderNodeLightEvaluation") is not None \
        and _find(nt, "ShaderNodeLightAccumulation") is not None


def ours(nt):
    return nt is not None and nt.get("ppd_shader") == VERSION


def npr_node(obj):
    """The group node in obj's material that shades it."""
    mat = obj.ppd.material
    if mat is None or mat.node_tree is None:
        return None
    nodes = [n for n in mat.node_tree.nodes if n.type == 'GROUP']
    for n in nodes:
        if n.node_tree is not None and n.node_tree == obj.ppd.bands:
            return n
    named = [n for n in nodes if n.name == "NPR"]
    nodes = [n for n in nodes if suits(n.node_tree)]
    used = [n for n in nodes if any(o.links for o in n.outputs)]
    return (named or used or nodes or [None])[0]


def ramp(obj, pid):
    nt = obj.ppd.bands
    return nt.nodes.get(f"{TAG}RAMP_{pid}") if nt is not None else None


def group_name(obj):
    return "NPR_" + obj.name


def _part(obj, pid):
    return next((p for p in idn.all_parts(obj) if p.pid == pid), None)


# ------------------------------------------------------------------ values
def _write_ramp(node, part):
    cr = node.color_ramp
    cr.color_mode, cr.interpolation = 'RGB', 'CONSTANT'
    cols = idn.shade_colors(part)
    pos = [0.0, part.border_1, part.border_2][:len(cols)]
    if len(cols) == 2:
        pos = [0.0, part.border_1]
    elif len(cols) == 1:
        pos = [0.0]
    while len(cr.elements) > len(cols):
        cr.elements.remove(cr.elements[-1])
    while len(cr.elements) < len(cols):
        cr.elements.new(1.0)
    # set from the right, so no element passes another on the way
    for e, p, c in reversed(list(zip(cr.elements, pos, cols))):
        e.position, e.color = p, (*c, 1.0)
    for e, p, c in zip(cr.elements, pos, cols):
        e.position, e.color = p, (*c, 1.0)


def write_part(part):
    """A part's colors and borders into the shader (no rebuild)."""
    obj = part.id_data
    nt = obj.ppd.bands if isinstance(obj, bpy.types.Object) else None
    if not ours(nt):
        return
    nodes = nt.nodes
    pid = part.pid
    if nodes.get(f"{TAG}RAMP_{pid}") is None:
        return
    _write_ramp(nodes[f"{TAG}RAMP_{pid}"], part)
    nodes[f"{TAG}MID_{pid}"].outputs[0].default_value = (*part.mid, 1.0)
    nodes[f"{TAG}GLOSS_{pid}"].outputs[0].default_value = (*part.gloss, 1.0)
    nodes[f"{TAG}GLOSSAT_{pid}"].outputs[0].default_value = part.gloss_at


def write_blend(obj):
    nt = obj.ppd.bands
    if not ours(nt):
        return
    d = obj.ppd
    for kind, mode, opacity in (("ALB", d.alb_blend, d.alb_opacity),
                                ("TEX", d.tex_blend, d.tex_opacity)):
        n = nt.nodes.get(f"{TAG}{kind}_MIX")
        if n is not None:
            n.blend_type = mode
        v = nt.nodes.get(f"{TAG}{kind}_OPACITY")
        if v is not None:
            v.outputs[0].default_value = opacity


def copy_bands(src, dst):
    for k in ("shades", "shadow", "mid", "high", "gloss"):
        setattr(dst, k, getattr(src, k))
    # borders: gloss first, so the order checks never push one
    dst.gloss_at, dst.border_2, dst.border_1 = 0.99, 0.98, src.border_1
    dst.border_2, dst.gloss_at = src.border_2, src.gloss_at


# ------------------------------------------------------------------ building
def _interface(nt):
    want = [(n, s) for n, s, *_ in INPUTS]
    have = [(i.name, i.socket_type) for i in nt.interface.items_tree
            if i.item_type == 'SOCKET' and i.in_out == 'INPUT']
    outs = [i.name for i in nt.interface.items_tree
            if i.item_type == 'SOCKET' and i.in_out == 'OUTPUT']
    if have == want and outs == ["Shader"]:
        return
    if outs == ["Shader"] and have == want[:len(have)]:
        for name, sock, default, lo, hi in INPUTS[len(have):]:
            s = nt.interface.new_socket(name, in_out='INPUT', socket_type=sock)
            s.default_value = default
            if lo is not None:
                s.min_value, s.max_value = lo, hi
        return
    nt.interface.clear()
    nt.interface.new_socket("Shader", in_out='OUTPUT', socket_type='NodeSocketShader')
    for name, sock, default, lo, hi in INPUTS:
        s = nt.interface.new_socket(name, in_out='INPUT', socket_type=sock)
        s.default_value = default
        if lo is not None:
            s.min_value, s.max_value = lo, hi
        if name.startswith(("Show", "Light")) or name.endswith("Alpha"):
            s.subtype = 'FACTOR'


class _Graph:
    def __init__(self, nt):
        self.nt, self.nodes, self.links = nt, nt.nodes, nt.links

    def new(self, idname, name=None, at=(0, 0), hide=False, **props):
        n = self.nodes.new(idname)
        if name:
            n.name = n.label = TAG + name
        n.location, n.hide = at, hide
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.links.new(a, b)

    def math(self, op, a, b, at, name=None, c=None):
        n = self.new("ShaderNodeMath", name, at, hide=True, operation=op)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.link(v, n.inputs[i])
        return n.outputs[0]

    def mix(self, fac, a, b, at, name=None, blend='MIX', kind='RGBA'):
        n = self.new("ShaderNodeMix", name, at, hide=True, data_type=kind, blend_type=blend)
        n.clamp_result = False
        sa, sb, out = (6, 7, 2) if kind == 'RGBA' else (2, 3, 0)
        for sock, v in ((0, fac), (sa, a), (sb, b)):
            if isinstance(v, (int, float)):
                n.inputs[sock].default_value = v
            elif isinstance(v, tuple):
                n.inputs[sock].default_value = v
            else:
                self.link(v, n.inputs[sock])
        return n.outputs[out]

    def rgb(self, name, value, at):
        n = self.new("ShaderNodeRGB", name, at)
        n.outputs[0].default_value = value
        return n.outputs[0]

    def value(self, name, v, at):
        n = self.new("ShaderNodeValue", name, at)
        n.outputs[0].default_value = v
        return n.outputs[0]

    def vmath_scale(self, v, scale, at):
        n = self.new("ShaderNodeVectorMath", None, at, hide=True, operation='SCALE')
        self.link(v, n.inputs[0])
        self.link(scale, n.inputs["Scale"])
        return n.outputs[0]

    def vmath(self, op, a, b, at):
        n = self.new("ShaderNodeVectorMath", None, at, hide=True, operation=op)
        for i, v in enumerate((a, b)):
            if isinstance(v, tuple):
                n.inputs[i].default_value = v
            else:
                self.link(v, n.inputs[i])
        return n.outputs[0]


def _graph(obj, nt):
    """Every node of the shader, from scratch."""
    nt.nodes.clear()
    g = _Graph(nt)
    parts = idn.all_parts(obj)
    gi = g.new("NodeGroupInput", None, (-1600, 0))
    gin = gi.outputs
    go = g.new("NodeGroupOutput", None, (1700, 0))

    # which part a face is in
    attr = g.new("ShaderNodeAttribute", "PART", (-1600, 700), attribute_type='GEOMETRY',
                 attribute_name=ATTR)
    is_part = {p.pid: g.math('COMPARE', attr.outputs["Fac"], p.pid, (-1350, 700 - 40 * i),
                             f"IS_{p.pid}", 0.5)
               for i, p in enumerate(parts) if p.pid}

    def pick(outs, at, kind='RGBA'):
        """outs: {pid: socket}; the one of the face's part (no part: pid 0)."""
        cur = outs[0]
        for i, p in enumerate(parts[1:]):
            cur = g.mix(is_part[p.pid], cur, outs[p.pid], (at[0] + 30 * i, at[1] - 30 * i),
                        kind=kind)
        return cur

    # the parts' values
    mids, glosses, gloss_at, ramps = {}, {}, {}, {}
    for i, p in enumerate(parts):
        y = 1500 + 320 * i
        mids[p.pid] = g.rgb(f"MID_{p.pid}", (*p.mid, 1.0), (-1100, y))
        glosses[p.pid] = g.rgb(f"GLOSS_{p.pid}", (*p.gloss, 1.0), (-900, y))
        gloss_at[p.pid] = g.value(f"GLOSSAT_{p.pid}", p.gloss_at, (-700, y))
        r = g.new("ShaderNodeValToRGB", f"RAMP_{p.pid}", (-400, -900 - 280 * i))
        r.label = p.name or "No part"
        _write_ramp(r, p)
        ramps[p.pid] = r
    mid = pick(mids, (-600, 900))
    gloss = pick(glosses, (-600, 600))
    gloss_border = pick(gloss_at, (-600, 300), kind='FLOAT')

    # COLOR: BASE -> ALB -> TEX
    base = g.mix(gin["Show BASE"], CLAY, mid, (-300, 400), "BASE")
    a_op = g.value("ALB_OPACITY", obj.ppd.alb_opacity, (-600, 150))
    t_op = g.value("TEX_OPACITY", obj.ppd.tex_opacity, (-600, -50))
    a_fac = g.math('MULTIPLY', g.math('MULTIPLY', gin["ALB Alpha"], gin["Show ALB"],
                                      (-400, 150)), a_op, (-250, 150))
    t_fac = g.math('MULTIPLY', g.math('MULTIPLY', gin["TEX Alpha"], gin["Show TEX"],
                                      (-400, -50)), t_op, (-250, -50))
    alb = g.mix(a_fac, base, gin["ALB"], (-50, 350), "ALB_MIX", blend=obj.ppd.alb_blend)
    color = g.mix(t_fac, alb, gin["TEX"], (150, 300), "TEX_MIX", blend=obj.ppd.tex_blend)
    safe_mid = g.vmath('MAXIMUM', mid, (0.001, 0.001, 0.001), (150, 700))
    ratio = g.vmath('DIVIDE', color, safe_mid, (350, 500))

    # LIGHT, per light
    geo = g.new("ShaderNodeNewGeometry", "GEOMETRY", (-1100, -300))
    nmap = g.new("ShaderNodeNormalMap", "NOR", (-1100, -450), space='TANGENT',
                 uv_map=idn.bake_uv(obj))
    g.link(gin["NOR"], nmap.inputs["Color"])
    g.link(gin["Show NOR"], nmap.inputs["Strength"])
    diffuse = g.new("ShaderNodeLightEvaluation", "DIFFUSE", (-800, -400), mode='DIFFUSE')
    glossy = g.new("ShaderNodeLightEvaluation", "GLOSSY", (-800, -650), mode='GLOSSY')
    for le in (diffuse, glossy):
        g.link(geo.outputs["Position"], le.inputs["Position"])
        g.link(nmap.outputs["Normal"], le.inputs["Normal"])
    glossy.inputs["Roughness"].default_value = ROUGHNESS
    bw = g.new("ShaderNodeRGBToBW", "SHD_VALUE", (-1100, -1500))
    g.link(gin["SHD"], bw.inputs[0])
    shd_amount = g.math('MULTIPLY', gin["SHD Alpha"], gin["Show SHD"], (-900, -1550))
    shift = g.math('MULTIPLY', g.math('MULTIPLY_ADD', bw.outputs[0], 2.0, (-900, -1500), None,
                                      -1.0), shd_amount, (-750, -1500), "SHD_SHIFT")
    lit_amount = g.math('ADD', diffuse.outputs["Factor"], shift, (-600, -500), "LIGHT_AMOUNT")
    lit_amount.node.use_clamp = True
    for r in ramps.values():
        g.link(lit_amount, r.inputs[0])
    shade = pick({k: r.outputs[0] for k, r in ramps.items()}, (0, -400))
    info = g.new("ShaderNodeLightInfo", "LIGHT", (-800, -900))
    light = g.mix(gin["Light Color"], (1.0, 1.0, 1.0, 1.0), info.outputs["Color"], (300, -700),
                  "LIGHT_COLOR")
    # Light Accumulation adds every light up: four lights, four times the band color. So each
    # light counts 1 / the number of lights: where they all reach, the ramp's color exactly,
    # elsewhere a blend of ramp colors. Exposure scales that.
    count = g.value("LIGHT_COUNT", 1.0, (-800, -1350))
    average = g.math('DIVIDE', 1.0, g.math('MAXIMUM', count, 1.0, (-550, -1350)), (-350, -1350),
                     "LIGHT_WEIGHT")
    weight = g.math('MULTIPLY', average, gin["Exposure"], (0, -1200), "EXPOSURE")
    light = g.vmath_scale(light, weight, (450, -800))
    # the paint's ratio goes on the light: Light Accumulation clamps Diffuse Color to 1, and
    # paint brighter than the part's Mid must stay brighter
    shade = g.vmath('MULTIPLY', shade, ratio, (300, -400))
    diffuse_light = g.mix(1.0, shade, light, (500, -400), "DIFFUSE_LIGHT", blend='MULTIPLY')
    shine = g.math('GREATER_THAN', glossy.outputs["Factor"], gloss_border, (300, -600), "SHINE")
    glossy_light = g.mix(1.0, light, light, (500, -600), "GLOSSY_LIGHT", blend='MULTIPLY')
    g.link(shine, glossy_light.node.inputs[6])
    acc = g.new("ShaderNodeLightAccumulation", "ACCUMULATION", (800, -200))
    g.link(diffuse_light, acc.inputs["Diffuse Light"])
    acc.inputs["Diffuse Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    g.link(glossy_light, acc.inputs["Glossy Light"])
    g.link(gloss, acc.inputs["Glossy Color"])

    lit = acc

    # VIEW: one layer alone, flat
    solo = {1: mid,
            2: g.mix(gin["ALB Alpha"], GRAY, gin["ALB"], (900, 600)),
            3: g.mix(gin["TEX Alpha"], GRAY, gin["TEX"], (900, 550)),
            4: gin["NOR"],
            5: g.mix(gin["SHD Alpha"], GRAY, gin["SHD"], (900, 500))}
    cur = solo[1]
    for i in range(2, 6):
        cur = g.mix(g.math('COMPARE', gin["Solo"], i, (1050, 650 - 30 * i), None, 0.5),
                    cur, solo[i], (1200, 650 - 30 * i))
    solo_emit = g.new("ShaderNodeEmission", "SOLO_EMIT", (1350, 300))
    g.link(cur, solo_emit.inputs["Color"])
    out = g.new("ShaderNodeMixShader", "SOLO", (1500, 0))
    g.link(g.math('GREATER_THAN', gin["Solo"], 0.5, (1350, 450)), out.inputs[0])
    g.link(lit.outputs[0], out.inputs[1])
    g.link(solo_emit.outputs[0], out.inputs[2])
    g.link(out.outputs[0], go.inputs[0])


def edited(part):
    """Whether any color, border or the shade count differs from a new part's."""
    for k in ("shades", "shadow", "mid", "high", "gloss", "border_1", "border_2", "gloss_at"):
        default = part.bl_rna.properties[k].default_array \
            if part.bl_rna.properties[k].is_array else part.bl_rna.properties[k].default
        v = getattr(part, k)
        if hasattr(v, "__len__"):
            if any(abs(a - b) > 1e-4 for a, b in zip(v, default)):
                return True
        elif abs(v - default) > 1e-4:
            return True
    return False


def _adopt(obj, old):
    """A file of the version before: each part's ramp becomes its spectrum - its last three
    stops are Shadow, Mid, High."""
    for p in obj.ppd.parts:
        r = old.nodes.get(f"{TAG}RAMP_{p.pid}")
        if r is None or r.bl_idname != "ShaderNodeValToRGB" or edited(p):
            continue            # colors set in the new bar win over the old ramp
        els = sorted(r.color_ramp.elements, key=lambda e: e.position)[-3:]
        cols = [tuple(e.color[:3]) for e in els]
        pos = [e.position for e in els]
        p.gloss_at, p.border_2 = 0.99, 0.98         # room to place the borders
        p.shades = len(cols)
        if len(cols) == 1:
            p.mid = cols[0]
            continue
        p.shadow, p.mid = cols[0], cols[1]
        p.border_1 = min(max(pos[1], 0.02), 0.9)
        if len(cols) == 3:
            p.high = cols[2]
            p.border_2 = min(max(pos[2], p.border_1 + 0.01), 0.95)
        p.gloss_at = min(p.border_2 + 0.15, 0.97)


def reset_inputs(node):
    """The group node's unlinked inputs at the shader's defaults. Needed when the node gets
    a new group: Blender carries the old group's values over by slot, so an old 'Shade 2
    Position' 0.14 would become 'Light Color' 0.14."""
    for name, _sock, default, _lo, _hi in INPUTS:
        s = node.inputs.get(name)
        if s is not None and not s.links:
            s.default_value = default


def light_count(scene):
    """How many lights the shader averages: the visible ones."""
    return max(1, sum(1 for o in scene.objects if o.type == 'LIGHT' and o.visible_get()))


def write_lights(scene=None, objs=None):
    """The light count into every shader (a value only). Returns whether anything changed.
    A shader from before still has its key-light nodes: switched off here."""
    scene = scene or bpy.context.scene
    count = light_count(scene)
    changed = False
    for o in (objs if objs is not None else idn.objects()):
        nt = o.ppd.bands
        if not ours(nt) or nt.library is not None:
            continue
        n = nt.nodes.get(f"{TAG}LIGHT_COUNT")
        if n is not None and n.outputs[0].default_value != count:
            n.outputs[0].default_value = count
            changed = True
        on = nt.nodes.get(f"{TAG}KEY_ON")
        if on is not None and on.outputs[0].default_value != 0.0:
            on.outputs[0].default_value = 0.0
            changed = True
    return changed


def build(obj):
    """obj's own NPR_<full name> from its data, and its material using it."""
    d = obj.ppd
    old = d.bands
    if old is not None and not ours(old):
        _adopt(obj, old)
    nt = old if ours(old) and old.library is None and old.users <= 2 else None
    if nt is None:
        nt = bpy.data.node_groups.new(group_name(obj), 'ShaderNodeTree')
    nt["ppd_shader"] = VERSION
    _interface(nt)
    _graph(obj, nt)
    d.bands = nt
    node = npr_node(obj)
    if node is not None and node.node_tree != nt:
        node.node_tree = nt
        reset_inputs(node)
    if old is not None and old != nt and old.library is None:
        # never deleted here: deleting data can leave Blender's undo history pointing at it.
        # Unused, it is not saved with the file.
        old.use_fake_user = False
        if not old.name.endswith(" (old)"):
            old.name = old.name[:56] + " (old)"
    sync(obj)
    write_lights(objs=[obj])
    from . import material
    material.show_images(obj)
    return nt


# ------------------------------------------------------------------ following the object
def sync(obj):
    d = obj.ppd
    if d.bands is not None and d.bands.library is None and d.bands.name != group_name(obj):
        d.bands.name = group_name(obj)


def make_own(obj):
    """After a duplicate: its own shader, built from its own (copied) data."""
    obj.ppd.bands = None
    build(obj)


def problems(obj):
    d = obj.ppd
    if d.bands is None:
        return ["no shader group"]
    if not ours(d.bands):
        return ["the shader is from an older version"]
    node = npr_node(obj)
    if node is None or node.node_tree != d.bands:
        return ["the material does not use its shader"]
    if any(ramp(obj, p.pid) is None for p in idn.all_parts(obj)):
        return ["a split part has no ramp"]
    if d.bands.nodes.get(TAG + NEWEST) is None:
        return ["the shader needs an update (lights)"]
    if d.bands.name != group_name(obj):
        return [f"the shader group is named {d.bands.name}"]
    return []


def fix(obj):
    if problems(obj):
        build(obj)


def outdated(obj):
    d = obj.ppd
    node = npr_node(obj)
    return d.material is not None and node is not None and (
        not ours(d.bands) or node.node_tree != d.bands or
        d.bands.nodes.get(TAG + NEWEST) is None)


def upgrade_all():
    """Objects still on the shader of an older version get the new one (their ramp colors
    come along). Returns their names. Only from an operator (it has undo): changing data from
    a timer, outside undo, breaks Blender's undo history - Redo then crashes."""
    done = []
    for o in idn.objects():
        if o.library is None and outdated(o):
            try:
                build(o)
                done.append(o.name)
            except Exception as e:          # never in the way of opening a file
                print("[PPD] shader upgrade:", o.name, e)
    if done:
        print("[PPD] new shader for", ", ".join(done))
    return done
