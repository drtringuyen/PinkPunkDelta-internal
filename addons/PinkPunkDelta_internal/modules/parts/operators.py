"""Split parts: numbers in the face attribute PPD_PART. One number per face, so a face is in
one part at most."""
import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, IntProperty, StringProperty

from ... import bands


def active(context):
    o = context.active_object
    return o if o is not None and o.type == 'MESH' and o.library is None \
        and o.ppd.is_setup else None


def part_of(obj, pid):
    return next((p for p in obj.ppd.parts if p.pid == pid), None)


def layer(obj, create=False):
    """(bmesh, PPD_PART layer) in Edit Mode."""
    bm = bmesh.from_edit_mesh(obj.data)
    lay = bm.faces.layers.int.get(bands.ATTR)
    if lay is None and create:
        lay = bm.faces.layers.int.new(bands.ATTR)
    return bm, lay


def values(me):
    """PPD_PART of every face (Object Mode)."""
    out = np.zeros(len(me.polygons), np.int32)
    a = me.attributes.get(bands.ATTR)
    if a is not None and a.domain == 'FACE' and a.data_type == 'INT' and len(a.data) == len(out):
        a.data.foreach_get("value", out)
    return out


def counts(obj):
    """{pid: faces} ({} for a big mesh in Edit Mode: too slow to count on every redraw)."""
    if obj.mode == 'EDIT':
        bm, lay = layer(obj)
        if len(bm.faces) > 30000:
            return None
        v = [f[lay] for f in bm.faces] if lay is not None else [0] * len(bm.faces)
        v = np.array(v, np.int32)
    else:
        v = values(obj.data)
    pids, n = np.unique(v, return_counts=True)
    return dict(zip(pids.tolist(), n.tolist()))


class _Edit:
    bl_options = {'REGISTER', 'UNDO'}

    pid: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        if active(context) is None or context.mode != 'EDIT_MESH':
            cls.poll_message_set("Edit Mode of a set-up object")
            return False
        return True


class PPD_OT_part_add(bpy.types.Operator):
    """New split part with its own color ramp. In Edit Mode it takes the selected faces"""
    bl_idname = "ppd.part_add"
    bl_label = "Add Split Part"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return active(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj = active(context)
        d = obj.ppd
        name = self.name.strip() or f"Part {len(d.parts) + 1}"
        if any(p.name.casefold() == name.casefold() for p in d.parts):
            self.report({'ERROR'}, f"There is a part {name} already")
            return {'CANCELLED'}
        used = {p.pid for p in d.parts}
        pid = max(used | set((counts(obj) or {}).keys()) | {0}) + 1
        p = d.parts.add()
        p.name, p.pid = name, pid
        try:
            bands.build(obj)
        except RuntimeError as e:
            d.parts.remove(len(d.parts) - 1)
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = 0
        if obj.mode == 'EDIT':
            bm, lay = layer(obj, create=True)
            for f in bm.faces:
                if f.select:
                    f[lay] = pid
                    n += 1
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        elif obj.data.attributes.get(bands.ATTR) is None:
            obj.data.attributes.new(bands.ATTR, 'INT', 'FACE')
        self.report({'INFO'}, f"{name}: {n} faces")
        return {'FINISHED'}


class PPD_OT_part_assign(_Edit, bpy.types.Operator):
    """Put the selected faces into this part"""
    bl_idname = "ppd.part_assign"
    bl_label = "Assign to Part"

    remove: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, props):
        return "Take the selected faces out of this part" if props.remove else cls.__doc__

    def execute(self, context):
        obj = active(context)
        bm, lay = layer(obj, create=True)
        for f in bm.faces:
            if f.select and (not self.remove or f[lay] == self.pid):
                f[lay] = 0 if self.remove else self.pid
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class PPD_OT_part_select(_Edit, bpy.types.Operator):
    """Select this part's faces"""
    bl_idname = "ppd.part_select"
    bl_label = "Select Part"

    deselect: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, props):
        if props.deselect:
            return "Deselect this part's faces"
        return "Select the faces in no part" if props.pid == 0 else cls.__doc__

    def execute(self, context):
        obj = active(context)
        # vertex mode would also select the faces enclosed by this part's corners
        context.tool_settings.mesh_select_mode = (False, False, True)
        bm, lay = layer(obj)
        bm.select_mode = {'FACE'}
        bm.select_flush_mode()
        for f in bm.faces:
            if (f[lay] if lay is not None else 0) == self.pid and not f.hide:
                f.select_set(not self.deselect)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {'FINISHED'}


class PPD_OT_part_delete(bpy.types.Operator):
    """Delete this part and its color ramp. The faces stay, in no part"""
    bl_idname = "ppd.part_delete"
    bl_label = "Delete Split Part"
    bl_options = {'REGISTER', 'UNDO'}

    pid: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return active(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = active(context)
        p = part_of(obj, self.pid)
        if p is None:
            return {'CANCELLED'}
        if obj.mode == 'EDIT':
            bm, lay = layer(obj)
            if lay is not None:
                for f in bm.faces:
                    if f[lay] == self.pid:
                        f[lay] = 0
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        else:
            a = obj.data.attributes.get(bands.ATTR)
            if a is not None:
                v = values(obj.data)
                v[v == self.pid] = 0
                a.data.foreach_set("value", v)
                obj.data.update()
        obj.ppd.parts.remove(list(obj.ppd.parts).index(p))
        try:
            bands.build(obj)
        except RuntimeError as e:
            self.report({'WARNING'}, str(e))
        return {'FINISHED'}


class PPD_OT_part_copy_ramp(bpy.types.Operator):
    """Give this part's color ramp to every other part of the object"""
    bl_idname = "ppd.part_copy_ramp"
    bl_label = "Copy Ramp to All Parts"
    bl_options = {'REGISTER', 'UNDO'}

    pid: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return active(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = active(context)
        src = bands.ramp(obj, self.pid)
        for p in obj.ppd.parts:
            dst = bands.ramp(obj, p.pid)
            if src is not None and dst is not None and p.pid != self.pid:
                bands._copy_ramp(src, dst)
        return {'FINISHED'}


class PPD_OT_part_refresh(bpy.types.Operator):
    """Copy the shared NPR group again into this object's own one (after you changed NPR). The ramps stay"""
    bl_idname = "ppd.part_refresh"
    bl_label = "Update from NPR"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = active(context)
        return o is not None and o.ppd.bands is not None

    def execute(self, context):
        try:
            bands.build(active(context), fresh=True)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (PPD_OT_part_add, PPD_OT_part_assign, PPD_OT_part_select, PPD_OT_part_delete,
           PPD_OT_part_copy_ramp, PPD_OT_part_refresh)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
