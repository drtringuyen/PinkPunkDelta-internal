"""MAT_<full name>: four tagged image nodes. Only the tagged nodes' images are ever touched
after the material was made - its layout is the user's."""
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
    """ALB -> NPR Base, NOR -> NPR Normal. SHD and TEX wait unconnected: the user wires them."""
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)
    npr = nt.nodes.new("ShaderNodeGroup")
    npr.node_tree = group(NPR)
    npr.name = npr.label = NPR
    npr.location = (200, 0)
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.name, uvn.uv_map, uvn.location = "PPD_UV", uv, (-500, 0)
    for i, kind in enumerate(idn.KINDS):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.name, n.label = node_name(kind), kind
        n.location = (-250, 300 - i * 300)
        nt.links.new(uvn.outputs[0], n.inputs[0])
    nt.links.new(nt.nodes[node_name("ALB")].outputs[0], npr.inputs["Base"])
    nt.links.new(nt.nodes[node_name("NOR")].outputs[0], npr.inputs["Normal"])
    nt.links.new(npr.outputs[0], out.inputs["Surface"])


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


def ensure(obj):
    """obj's own material, made when missing, in slot 1."""
    d = obj.ppd
    if d.material is None:
        d.material = bpy.data.materials.new("MAT_" + obj.name)
        d.material.use_nodes = True
        build(d.material, idn.bake_uv(obj))
    slots = obj.material_slots
    if not slots:
        obj.data.materials.append(d.material)
    elif d.material not in [s.material for s in slots]:
        old = slots[0].material
        slots[0].material = d.material
        if old is not None and old.users == 0:
            old.use_fake_user = True        # replaced, never lost
    show_images(obj)
    return d.material


def ensure_gn(obj):
    if any(m.type == 'NODES' and m.node_group and m.node_group.name == GN
           for m in obj.modifiers):
        return
    mod = obj.modifiers.new(GN, 'NODES')
    mod.node_group = group(GN)
