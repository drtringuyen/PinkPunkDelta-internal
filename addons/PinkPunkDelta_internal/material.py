"""MAT_<full name>: four tagged image nodes and the object's shader group (bands.py). After
the material was made only the tagged nodes are touched: their images, and their links into the
shader (linked only while they have an image - an empty image node would show pink)."""
import os

import bpy

from . import identity as idn

ASSETS = os.path.join(os.path.dirname(__file__), "assets", "ppd_assets.blend")
GN = "GN_SharpTubes"
NPR = "NPR"


def node_name(kind):
    return "PPD_" + kind


def group(name):
    """The file's own group, else the shipped one."""
    g = bpy.data.node_groups.get(name)
    if g is not None:
        return g
    with bpy.data.libraries.load(ASSETS, link=False) as (src, dst):
        if name not in src.node_groups:
            raise RuntimeError(f"{name} is not in ppd_assets.blend")
        dst.node_groups = [name]
    return dst.node_groups[0]


def build(mat, uv):
    """Image nodes, the shader's group node (its group comes from bands.build) and the output."""
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)
    npr = nt.nodes.new("ShaderNodeGroup")
    npr.name = npr.label = NPR
    npr.location = (200, 0)
    npr.width = 220
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.name, uvn.uv_map, uvn.location = "PPD_UV", uv, (-500, 0)
    for i, kind in enumerate(idn.KINDS):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.name, n.label = node_name(kind), kind
        n.location = (-250, 300 - i * 300)
        nt.links.new(uvn.outputs[0], n.inputs[0])


def _wire(obj):
    from . import bands
    mat = obj.ppd.material
    npr = bands.npr_node(obj)
    if mat is None or npr is None or not bands.ours(npr.node_tree):
        return
    nt = mat.node_tree
    if not any(o.links for o in npr.outputs):
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is not None and not out.inputs["Surface"].links:
            nt.links.new(npr.outputs[0], out.inputs["Surface"])
    for kind, (color, alpha) in bands.IMAGE_INPUTS.items():
        n = nt.nodes.get(node_name(kind))
        if n is None or n.type != 'TEX_IMAGE':
            continue
        want = {(color, "Color")} | ({(alpha, "Alpha")} if alpha else set())
        has = n.image is not None
        for link in list(nt.links):
            if link.from_node == n and link.to_node == npr:
                if not has or (link.to_socket.name, link.from_socket.name) not in want:
                    nt.links.remove(link)
        if not has:
            continue
        for to, frm in want:
            sock = npr.inputs.get(to)
            if sock is not None and not sock.links:
                nt.links.new(n.outputs[frm], sock)


def show_images(obj):
    """The object's four textures on the tagged nodes."""
    mat = obj.ppd.material
    if mat is None or mat.node_tree is None:
        return
    nodes = mat.node_tree.nodes
    for kind in idn.KINDS:
        n = nodes.get(node_name(kind))
        img = idn.image(obj, kind)
        if n is not None and n.type == 'TEX_IMAGE' and n.image != img:
            n.image = img
    uvn = nodes.get("PPD_UV")       # set up before it was unwrapped
    if uvn is not None and not uvn.uv_map:
        uvn.uv_map = idn.bake_uv(obj)
    _wire(obj)


def ensure(obj):
    """obj's own material, made when missing, in slot 1."""
    d = obj.ppd
    if d.material is None:
        d.material = bpy.data.materials.new("MAT_" + obj.name)
        d.material.use_nodes = True
        build(d.material, idn.bake_uv(obj))
        d.bands = None
    slots = obj.material_slots
    if not slots:
        obj.data.materials.append(d.material)
    elif d.material not in [s.material for s in slots]:
        old = slots[0].material
        slots[0].material = d.material
        if old is not None and old.users == 0:
            old.use_fake_user = True        # replaced, never lost
    from . import bands
    bands.sync(obj)
    # only a missing shader is built here (this also runs from the rename timer): an older
    # one is replaced by Update Shader / Check All Links, which have undo
    if obj.ppd.bands is None or bands.npr_node(obj) is None or \
            (bands.ours(obj.ppd.bands) and bands.problems(obj)):
        bands.build(obj)
    show_images(obj)
    return d.material


def ensure_gn(obj):
    if any(m.type == 'NODES' and m.node_group and m.node_group.name == GN
           for m in obj.modifiers):
        return
    mod = obj.modifiers.new(GN, 'NODES')
    mod.node_group = group(GN)
