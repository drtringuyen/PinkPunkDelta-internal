"""A color ramp per split part.

A part is a number in the INT face attribute PPD_PART (0 = no part): one attribute, because
EEVEE refuses a material that reads dozens of them. The ramps replace NPR's shade colors, so
they sit inside NPR behind its Light Evaluation - and ramp colors are the same for every user of
a group, so each object with parts gets its own copy, NPR_<full name>.

In the copy, the links into Light Accumulation's Diffuse Light and Diffuse Color run through
PPD_*_IN -> (a mix per part) -> PPD_*_OUT; everything else is NPR as the user made it."""
import bpy

ATTR = "PPD_PART"
TAG = "PPD_"
RAMP = "PPD_RAMP_"          # + pid
ROUTES = (("LIGHT", "Diffuse Light"), ("COLOR", "Diffuse Color"))


def _find(nt, idname):
    return next((n for n in nt.nodes if n.bl_idname == idname), None)


def suits(nt):
    return nt is not None and nt.bl_idname == 'ShaderNodeTree' \
        and _find(nt, "ShaderNodeLightEvaluation") is not None \
        and _find(nt, "ShaderNodeLightAccumulation") is not None


def npr_node(obj):
    """The group node in obj's material that shades it."""
    mat = obj.ppd.material
    if mat is None or mat.node_tree is None:
        return None
    nodes = [n for n in mat.node_tree.nodes if n.type == 'GROUP' and suits(n.node_tree)]
    for n in nodes:
        if n.node_tree == obj.ppd.bands:
            return n
    named = [n for n in nodes if n.name == "NPR"]
    used = [n for n in nodes if any(o.links for o in n.outputs)]
    return (named or used or nodes or [None])[0]


def ramp(obj, pid):
    nt = obj.ppd.bands
    return nt.nodes.get(RAMP + str(pid)) if nt is not None else None


def group_name(obj):
    return "NPR_" + obj.name


# ------------------------------------------------------------------ building
def _prepare(nt):
    """The fixed ends of the two routes, put into a fresh copy of NPR once."""
    acc = _find(nt, "ShaderNodeLightAccumulation")
    for i, (key, sock) in enumerate(ROUTES):
        s = acc.inputs[sock]
        if s.links and s.links[0].from_node.name == f"{TAG}{key}_OUT":
            continue
        ends = []
        for end in ("IN", "OUT"):
            n = nt.nodes.new("NodeReroute")
            n.name = n.label = f"{TAG}{key}_{end}"
            n.socket_idname = "NodeSocketColor"
            ends.append(n)
        if s.links:
            nt.links.new(s.links[0].from_socket, ends[0].inputs[0])
        else:
            rgb = nt.nodes.new("ShaderNodeRGB")
            rgb.name = f"{TAG}{key}_VALUE"
            v = s.default_value
            rgb.outputs[0].default_value = tuple(v) if len(v) == 4 else (*v, 1.0)
            nt.links.new(rgb.outputs[0], ends[0].inputs[0])
        nt.links.new(ends[1].outputs[0], s)
        x, y = acc.location
        ends[0].location = (x + 250, y - 500 - 60 * i)
        ends[1].location = (x + 1250, y - 500 - 60 * i)


def _copy_ramp(src, dst):
    a, b = src.color_ramp, dst.color_ramp
    b.color_mode, b.interpolation, b.hue_interpolation = \
        a.color_mode, a.interpolation, a.hue_interpolation
    while len(b.elements) > 1:
        b.elements.remove(b.elements[-1])
    for i, e in enumerate(a.elements):
        n = b.elements[0] if i == 0 else b.elements.new(e.position)
        n.position, n.color = e.position, e.color


def _default_ramp(node, group_node):
    """The four shades of NPR as hard bands: a new part looks as before, ready to change."""
    stops = []
    for i in range(1, 5):
        c = group_node.inputs.get(f"Shade {i} Color")
        p = group_node.inputs.get(f"Shade {i} Position")
        if c is not None:
            stops.append((0.0 if i == 1 or p is None else min(1.0, max(0.0, p.default_value)),
                          tuple(c.default_value)))
    cr = node.color_ramp
    cr.interpolation = 'CONSTANT'
    if len(stops) < 2:
        return
    stops.sort(key=lambda s: s[0])
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position, cr.elements[0].color = stops[0]
    for pos, col in stops[1:]:
        cr.elements.new(pos).color = col


def _wire(obj):
    """The mixes between the IN and OUT ends, one per part (the ramps are kept)."""
    nt = obj.ppd.bands
    gnode = npr_node(obj)
    nodes, links = nt.nodes, nt.links
    pids = {str(p.pid) for p in obj.ppd.parts}
    for n in list(nodes):
        if n.name.startswith(TAG + "X_") or (n.name.startswith(RAMP)
                                             and n.name[len(RAMP):] not in pids):
            nodes.remove(n)
    factor = _find(nt, "ShaderNodeLightEvaluation").outputs["Factor"]
    x, y = nodes[TAG + "LIGHT_IN"].location
    attr = nodes.new("ShaderNodeAttribute")
    attr.name, attr.attribute_name, attr.location = TAG + "X_ATTR", ATTR, (x, y - 200)
    light = nodes[TAG + "LIGHT_IN"].outputs[0]
    color = nodes[TAG + "COLOR_IN"].outputs[0]

    def mix(name, fac, a, at):
        m = nodes.new("ShaderNodeMix")
        m.data_type, m.name, m.location, m.hide = 'RGBA', TAG + "X_" + name, at, True
        links.new(fac, m.inputs[0])
        links.new(a, m.inputs[6])
        return m

    for i, p in enumerate(obj.ppd.parts):
        py = y - 450 - 320 * i
        r = nodes.get(RAMP + str(p.pid))
        if r is None:
            r = nodes.new("ShaderNodeValToRGB")
            r.name = RAMP + str(p.pid)
            _default_ramp(r, gnode)
        r.location = (x + 200, py)
        links.new(factor, r.inputs[0])
        c = nodes.new("ShaderNodeMath")
        c.operation, c.name, c.hide = 'COMPARE', f"{TAG}X_IS_{p.pid}", True
        c.inputs[1].default_value, c.inputs[2].default_value = p.pid, 0.5
        c.location = (x, py)
        links.new(attr.outputs["Fac"], c.inputs[0])
        m = mix(f"LIGHT_{p.pid}", c.outputs[0], light, (x + 600, py))
        links.new(r.outputs[0], m.inputs[7])
        light = m.outputs[2]
        ig = nodes.new("ShaderNodeMath")        # inputs[1] is the Ignore ALB switch
        ig.operation, ig.name, ig.hide = 'MULTIPLY', f"{TAG}X_IGNORE_{p.pid}", True
        ig.location = (x + 200, py - 250)
        links.new(c.outputs[0], ig.inputs[0])
        m = mix(f"COLOR_{p.pid}", ig.outputs[0], color, (x + 600, py - 100))
        m.inputs[7].default_value = (1, 1, 1, 1)
        color = m.outputs[2]
    links.new(light, nodes[TAG + "LIGHT_OUT"].inputs[0])
    links.new(color, nodes[TAG + "COLOR_OUT"].inputs[0])
    for p in obj.ppd.parts:
        r = nodes[RAMP + str(p.pid)]
        r.label = p.name
    show_ignore(obj)


def show_ignore(obj):
    nt = obj.ppd.bands
    for p in obj.ppd.parts:
        n = nt.nodes.get(f"{TAG}X_IGNORE_{p.pid}") if nt is not None else None
        if n is not None:
            n.inputs[1].default_value = 1.0 if p.ignore_alb else 0.0


def build(obj, fresh=False):
    """obj's own NPR with a ramp per part. `fresh`: copy NPR again (it was changed), the ramps
    stay. Without parts the material goes back to the shared NPR."""
    d = obj.ppd
    node = npr_node(obj)
    if not len(d.parts):
        if d.bands is not None:
            if node is not None and node.node_tree == d.bands and d.npr_source is not None:
                node.node_tree = d.npr_source
            old, d.bands = d.bands, None
            if old.users == 0:
                bpy.data.node_groups.remove(old)
        return
    if node is None:
        raise RuntimeError(f"{obj.name}: no NPR group (Light Evaluation + Light Accumulation) "
                           "in its material")
    if node.node_tree != d.bands:
        # never a copy of a copy: another object's bands group is not a source
        if not any(n.name == TAG + "LIGHT_IN" for n in node.node_tree.nodes):
            d.npr_source = node.node_tree
        elif d.npr_source is None:
            d.npr_source = bpy.data.node_groups.get("NPR")
    old = d.bands
    if old is None or fresh:
        src = d.npr_source
        if not suits(src):
            raise RuntimeError(f"{obj.name}: the NPR group to copy is gone")
        nt = src.copy()
        nt.use_fake_user = False
        nt.name = group_name(obj)
        _prepare(nt)
        if old is not None:
            for p in d.parts:
                r = old.nodes.get(RAMP + str(p.pid))
                if r is not None:
                    n = nt.nodes.new("ShaderNodeValToRGB")
                    n.name = r.name
                    _copy_ramp(r, n)
        d.bands = nt
    if node.node_tree != d.bands:
        node.node_tree = d.bands
    if old is not None and old != d.bands and old.users == 0:
        bpy.data.node_groups.remove(old)
    sync(obj)
    _wire(obj)


# ------------------------------------------------------------------ following the object
def sync(obj):
    d = obj.ppd
    if d.bands is not None and d.bands.library is None and d.bands.name != group_name(obj):
        d.bands.name = group_name(obj)


def make_own(obj):
    """After a duplicate: its material is its own copy, now its ramps too."""
    d = obj.ppd
    if d.bands is None:
        return
    node = npr_node(obj)
    d.bands = d.bands.copy()
    if node is not None:
        node.node_tree = d.bands
    sync(obj)


def problems(obj):
    d = obj.ppd
    if not len(d.parts):
        return []
    if d.bands is None:
        return ["the split parts' ramps are missing"]
    node = npr_node(obj)
    if node is None or node.node_tree != d.bands:
        return ["the material does not use its ramps"]
    if any(ramp(obj, p.pid) is None for p in d.parts):
        return ["a split part has no ramp"]
    if d.bands.name != group_name(obj):
        return [f"the ramps' group is named {d.bands.name}"]
    return []


def fix(obj):
    if problems(obj):
        build(obj)
