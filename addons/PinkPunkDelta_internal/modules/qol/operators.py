"""Quality of life: light color, outline and which layers show - for all set-up objects or the
selected ones - and cleaning up files nothing uses."""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty

from ... import bands
from ... import identity as idn
from ... import material
from . import cleanup

LAYERS = ("BASE", "ALB", "TEX", "NOR", "SHD")


def targets(context):
    objs = idn.objects()
    if context.scene.ppd_qol.scope == 'SELECTED':
        sel = set(context.selected_objects or ())
        active = getattr(context, "active_object", None)
        if active is not None:
            sel.add(active)
        objs = [o for o in objs if o in sel]
    return objs


def _set(node, name, value):
    s = node.inputs.get(name) if node is not None else None
    if s is not None and abs(s.default_value - value) > 1e-6:
        s.default_value = value


def apply(context, what=None):
    """The panel's settings onto the target objects. what: one setting, or all of them."""
    q = context.scene.ppd_qol
    n = 0
    for o in targets(context):
        if bands.outdated(o):
            bands.upgrade(o)
        node = bands.npr_node(o)
        if what in (None, "light"):
            _set(node, "Light Color", 1.0 if q.light_color else 0.0)
            _set(node, "Exposure", q.exposure)
        if what in (None, "layers"):
            for k in LAYERS:
                _set(node, f"Show {k}", 1.0 if getattr(q, "show_" + k.lower()) else 0.0)
            _set(node, "Solo", float(q.solo))
        if what in (None, "outline"):
            for m in o.modifiers:
                if m.type == 'NODES' and m.node_group and m.node_group.name == material.GN:
                    m.show_viewport = m.show_render = q.outline
        n += 1
    return n


def _updater(what):
    def update(self, context):
        apply(context, what)
    return update


def _true_colors(self, context):
    """Standard view: the colors on screen are the ones picked. AgX (Blender's default)
    washes bright colors out on purpose. Off: the view from before comes back."""
    sc = context.scene
    vs = sc.view_settings
    if self.true_colors:
        if vs.view_transform != 'Standard':
            sc["ppd_view_before"] = vs.view_transform
            sc["ppd_look_before"] = vs.look
        vs.view_transform = 'Standard'
        vs.look = 'None'
    else:
        vs.view_transform = sc.get("ppd_view_before", 'AgX')
        try:
            vs.look = sc.get("ppd_look_before", 'None')
        except TypeError:
            pass


class PPD_QOL(bpy.types.PropertyGroup):
    true_colors: BoolProperty(name="True Colors", default=False, update=_true_colors,
                              description="Show the ramp colors exactly (Standard view instead "
                                          "of AgX). Off: the view from before")
    scope: EnumProperty(name="For", items=[
        ('ALL', "All Objects", "Every set-up object of the file"),
        ('SELECTED', "Selected", "Only the selected set-up objects")], default='ALL')
    light_color: BoolProperty(name="Light Color", default=False, update=_updater("light"),
                              description="The lights' colors tint the shading")
    exposure: FloatProperty(name="Exposure", default=1.0, min=0.0, soft_max=2.0, max=16.0,
                            subtype='FACTOR',
                            update=_updater("light"),
                            description="Multiplies the light (every light counts, averaged). "
                                        "1: the ramp's colors where every light reaches")
    outline: BoolProperty(name="Outline", default=True, update=_updater("outline"),
                          description="The outline tubes (GN_SharpTubes), in the viewport and "
                                      "in renders")
    show_base: BoolProperty(name="BASE", default=True, update=_updater("layers"),
                            description="The parts' colors (off: plain clay)")
    show_alb: BoolProperty(name="ALB", default=True, update=_updater("layers"))
    show_tex: BoolProperty(name="TEX", default=True, update=_updater("layers"))
    show_nor: BoolProperty(name="NOR", default=True, update=_updater("layers"))
    show_shd: BoolProperty(name="SHD", default=True, update=_updater("layers"))
    solo: EnumProperty(name="Solo", update=_updater("layers"), items=[
        ('0', "All", "Lit, with every layer that is on"),
        ('1', "BASE", "Only BASE, flat"), ('2', "ALB", "Only ALB, flat"),
        ('3', "TEX", "Only TEX, flat"), ('4', "NOR", "Only NOR, flat"),
        ('5', "SHD", "Only SHD, flat")], default='0')


class PPD_OT_qol_apply(bpy.types.Operator):
    """Set these on the objects again (after the selection changed)"""
    bl_idname = "ppd.qol_apply"
    bl_label = "Apply"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, f"{apply(context)} objects")
        return {'FINISHED'}


def _mb(n):
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


class PPD_OT_clean_files(bpy.types.Operator):
    """Move the files of this .blend that nothing uses any more to the Recycle Bin"""
    bl_idname = "ppd.clean_files"
    bl_label = "Clean Up Files"

    unused: BoolProperty(name="Unused textures", default=True)
    previous: BoolProperty(name="Previous copies", default=True)
    sent: BoolProperty(name="Sent PSDs", default=False)
    temp: BoolProperty(name="LiveLink temp", default=True)

    @classmethod
    def poll(cls, context):
        if not bpy.data.filepath:
            cls.poll_message_set("Save the .blend first")
            return False
        return True

    def invoke(self, context, event):
        self._found = cleanup.collect()
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        found = getattr(self, "_found", None) or cleanup.collect()
        col = self.layout.column()
        for key, label, desc in cleanup.CATEGORIES:
            paths = found[key]
            row = col.row()
            row.enabled = bool(paths)
            row.prop(self, key, text=f"{label}: {len(paths)} ({_mb(cleanup.size(paths))})")
        sub = col.column()
        sub.active = False
        sub.label(text="They go to the Recycle Bin.", icon='INFO')

    def execute(self, context):
        found = cleanup.collect()
        paths = [p for key, _l, _d in cleanup.CATEGORIES if getattr(self, key)
                 for p in found[key]]
        total = cleanup.size(paths)
        gone = cleanup.recycle(paths)
        self.report({'INFO'}, f"{gone} of {len(paths)} moved to the Recycle Bin ({_mb(total)})")
        return {'FINISHED'}


CLASSES = (PPD_QOL, PPD_OT_qol_apply, PPD_OT_clean_files)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.ppd_qol = PointerProperty(type=PPD_QOL)


def unregister():
    del bpy.types.Scene.ppd_qol
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
