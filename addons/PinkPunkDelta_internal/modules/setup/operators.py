import sys

import bpy
from bpy.props import StringProperty

from ... import identity as idn
from ... import links, material
from . import gizmo


def saved(cls):
    if not bpy.data.filepath:
        cls.poll_message_set("Save the .blend first: its file name is the Central")
        return False
    return True


def setup_object(obj):
    links.adopt_central()
    d = obj.ppd
    d.is_setup = True
    if not d.key:
        d.key = idn.new_key()
    if obj.data.users > 1:
        obj.data = obj.data.copy()      # its material is its own
    material.ensure_gn(obj)
    links.sync_object(obj)


class PPD_OT_gizmo(bpy.types.Operator):
    """Show a 170 cm figure in the viewport to scale the model against"""
    bl_idname = "ppd.gizmo"
    bl_label = "170 cm Figure"

    def execute(self, context):
        gizmo.turn(not gizmo.is_on())
        return {'FINISHED'}


class PPD_OT_setup_current(bpy.types.Operator):
    """Put the geometry nodes and the MAT_ material on the active mesh and name it after the file"""
    bl_idname = "ppd.setup_current"
    bl_label = "Setup Current"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return saved(cls) and context.mode == 'OBJECT' and o is not None \
            and o.type == 'MESH' and o.library is None

    def execute(self, context):
        try:
            setup_object(context.active_object)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"{context.active_object.name} is set up")
        return {'FINISHED'}


class PPD_OT_setup_create(bpy.types.Operator):
    """Make an empty mesh at the world center, set it up and start RetopoFlow on it. The active mesh becomes its Original"""
    bl_idname = "ppd.setup_create"
    bl_label = "Create Setup Object"
    bl_options = {'REGISTER', 'UNDO'}

    part: StringProperty(name="Name", default="Retopo", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return saved(cls)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        src = context.active_object
        links.adopt_central()
        part = idn.safe_part(self.part)
        obj = bpy.data.objects.new(idn.full_name(part), bpy.data.meshes.new(part))
        context.scene.collection.objects.link(obj)
        setup_object(obj)
        if src is not None and src.type == 'MESH' and not src.ppd.is_setup:
            obj.ppd.original = src
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        self._retopoflow(context)
        return {'FINISHED'}

    def _retopoflow(self, context):
        """RetopoFlow's default tool (its own button would use the 3D cursor)."""
        addon = next((k for k in context.preferences.addons.keys()
                      if k.split(".")[-1] == "retopoflow"), "")
        core = sys.modules.get(addon + ".retopoflow.rfcore") if addon else None
        if core is None:
            self.report({'WARNING'}, "RetopoFlow is not enabled - plain Edit Mode")
            return
        try:
            from bl_ui.space_toolsystem_common import activate_by_id
            activate_by_id(context, 'VIEW_3D', core.RFCore.default_RFTool.bl_idname)
        except Exception as e:
            self.report({'WARNING'}, f"RetopoFlow did not start: {e}")


class PPD_OT_select(bpy.types.Operator):
    """Select this object"""
    bl_idname = "ppd.select"
    bl_label = "Select"
    bl_options = {'UNDO'}

    name: StringProperty()

    def execute(self, context):
        o = context.view_layer.objects.get(self.name)
        if o is None:
            self.report({'WARNING'}, f"{self.name} is not in this view layer")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for s in context.selected_objects:
            s.select_set(False)
        o.hide_set(False)
        o.select_set(True)
        context.view_layer.objects.active = o
        return {'FINISHED'}


class PPD_OT_check_links(bpy.types.Operator):
    """Check every object's name, material and texture files, and correct what is wrong. Textures that are not 8K are scaled to 8K"""
    bl_idname = "ppd.check_links"
    bl_label = "Check All Links"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return saved(cls)

    def execute(self, context):
        fixed, left = links.check_and_fix()
        links.messages[:] = [f"{n}: {t}" if n else t for n, t in left]
        self.report({'WARNING'} if left else {'INFO'},
                    f"{fixed} corrected, {len(left)} left" if left
                    else f"{fixed} corrected, all links are right")
        return {'FINISHED'}


CLASSES = (PPD_OT_gizmo, PPD_OT_setup_current, PPD_OT_setup_create, PPD_OT_select,
           PPD_OT_check_links)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    gizmo.unregister()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
