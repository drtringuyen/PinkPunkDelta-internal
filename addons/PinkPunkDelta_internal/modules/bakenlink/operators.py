import os
import subprocess
import sys

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ... import identity as idn
from ... import links, material
from . import bake

KIND_ITEMS = [(k, k, idn.KIND_LABEL[k]) for k in idn.KINDS]
busy = ""               # what is baking now, shown by the panel
progress = [0, 0]       # jobs done, jobs in all


class _Texture:
    object_name: StringProperty(options={'HIDDEN'})
    kind: EnumProperty(items=KIND_ITEMS, options={'HIDDEN'})

    def target(self):
        o = bpy.data.objects.get(self.object_name)
        return o, (idn.image(o, self.kind) if o else None)


class PPD_OT_show_image(_Texture, bpy.types.Operator):
    """Show this texture in the UV / Image Editor"""
    bl_idname = "ppd.show_image"
    bl_label = "Show in UV Editor"

    def execute(self, context):
        _obj, img = self.target()
        if img is None:
            self.report({'WARNING'}, "No texture yet")
            return {'CANCELLED'}
        areas = [a for w in context.window_manager.windows for a in w.screen.areas
                 if a.type == 'IMAGE_EDITOR']
        if not areas:
            self.report({'WARNING'}, "Open a UV or Image Editor first")
            return {'CANCELLED'}
        area = max(areas, key=lambda a: a.width * a.height)
        area.spaces.active.image = img
        area.tag_redraw()
        return {'FINISHED'}


class PPD_OT_open_folder(_Texture, bpy.types.Operator):
    """Open the texture's folder"""
    bl_idname = "ppd.open_folder"
    bl_label = "Open Folder"

    def execute(self, context):
        _obj, img = self.target()
        path = idn.abspath(img) if img else ""
        folder = os.path.dirname(path) if path else idn.tex_dir()
        if not folder:
            self.report({'WARNING'}, "Save the .blend first")
            return {'CANCELLED'}
        if sys.platform == "win32" and path and os.path.isfile(path):
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.makedirs(folder, exist_ok=True)
            bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


class PPD_OT_reload_texture(_Texture, bpy.types.Operator):
    """Read the texture's file again (a new file with the right name is linked)"""
    bl_idname = "ppd.reload_texture"
    bl_label = "Reload Texture"

    def execute(self, context):
        obj, _img = self.target()
        if obj is None or not bpy.data.filepath:
            return {'CANCELLED'}
        links.sync_texture(obj, self.kind)
        img = idn.image(obj, self.kind)
        if img is None or not os.path.isfile(idn.abspath(img)):
            self.report({'WARNING'}, f"Not found: {idn.tex_path(obj, self.kind)}")
            return {'CANCELLED'}
        img.reload()
        if img.size[0] and tuple(img.size) != (idn.SIZE, idn.SIZE):
            was = tuple(img.size)
            links.to_8k(img)
            self.report({'INFO'}, f"Scaled {was[0]}x{was[1]} to 8K")
        material.show_images(obj)
        return {'FINISHED'}


class PPD_OT_load_texture(_Texture, bpy.types.Operator):
    """Pick an image file: it is copied into the textures folder under this object's name, as an 8K PNG"""
    bl_idname = "ppd.load_texture"
    bl_label = "Load Texture"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.tga;*.bmp;*.webp",
                                options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj, _img = self.target()
        if obj is None or not os.path.isfile(self.filepath):
            return {'CANCELLED'}
        tmp = idn.tex_path(obj, self.kind) + ".part.png"
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        try:
            links.scale_file(self.filepath, tmp, idn.colorspace(self.kind))
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        bake.install(obj, self.kind, tmp)
        return {'FINISHED'}


class PPD_OT_bake(bpy.types.Operator):
    """Bake ALB and NOR (8K) from the Original into the textures folder. Esc stops after the running one"""
    bl_idname = "ppd.bake"
    bl_label = "Bake ALB + NOR"

    object_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})    # empty = every object
    which: EnumProperty(items=[('BOTH', "Both", ""), ('ALB', "ALB", ""), ('NOR', "NOR", "")],
                        default='BOTH', options={'HIDDEN', 'SKIP_SAVE'})
    send: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})     # then Send to iPad (LiveLink)

    @classmethod
    def description(cls, context, props):
        if props.send:
            return ("Bake ALB and NOR again from the Original (after a new UV or a change), "
                    "then send the fresh PSD to the iPad. Esc stops")
        return cls.__doc__

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath) and not busy

    def _jobs(self):
        if self.object_name:
            objs = [bpy.data.objects[self.object_name]]
        else:
            objs = [o for o in idn.objects() if not bake.problem(o)]
        kinds = idn.BAKED if self.which == 'BOTH' else (self.which,)
        return [(o.name, k) for o in objs for k in kinds]

    def _announce(self, context):
        global busy
        busy = f"Baking {self.jobs[0][1]} of {self.jobs[0][0]}"
        progress[:] = [self.total - len(self.jobs), self.total]
        context.window_manager.progress_update(progress[0])
        self.wait = 2           # lets the panel draw it before Blender blocks
        self._redraw(context)

    @staticmethod
    def _redraw(context):
        for a in context.screen.areas:
            a.tag_redraw()

    def invoke(self, context, event):
        o = bpy.data.objects.get(self.object_name)
        if o is not None and bake.problem(o):
            self.report({'ERROR'}, bake.problem(o))
            return {'CANCELLED'}
        self.jobs = self._jobs()
        if not self.jobs:
            self.report({'WARNING'}, "No object is ready to bake")
            return {'CANCELLED'}
        self.total, self.errors, self.stop, self.seconds = len(self.jobs), [], False, 0.0
        self.failed = set()
        self.timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.progress_begin(0, len(self.jobs))
        context.window_manager.modal_handler_add(self)
        self._announce(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.stop = True
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if self.wait and not self.stop:
            self.wait -= 1
            return {'RUNNING_MODAL'}
        if self.jobs and not self.stop:
            name, kind = self.jobs.pop(0)
            o = bpy.data.objects.get(name)
            try:
                if o is not None:
                    self.seconds += bake.bake_kind(context, o, kind)
            except Exception as e:
                self.errors.append(str(e).strip())
                self.failed.add(name)
            if self.jobs:
                self._announce(context)
                return {'RUNNING_MODAL'}
        self._finish(context)
        return {'FINISHED'}

    def _finish(self, context):
        global busy
        busy = ""
        progress[:] = [0, 0]
        context.window_manager.progress_end()
        context.window_manager.event_timer_remove(self.timer)
        for e in self.errors:
            self.report({'ERROR'}, e)
        done = self.total - len(self.jobs) - len(self.errors)
        self.report({'INFO'}, f"{done} of {self.total} baked in {self.seconds:.0f} s")
        if self.send and not self.stop and not self.jobs:
            names = {n for n, _k in self._jobs()} - self.failed
            self._send(names)
        self._redraw(context)

    def _send(self, names):
        try:
            from ..livelink import core
        except ImportError:
            return
        for n in sorted(names):
            o = bpy.data.objects.get(n)
            try:
                path = core.send(o)
                self.report({'INFO'}, f"Sent {os.path.basename(path)}")
            except (OSError, RuntimeError, MemoryError) as e:
                self.report({'ERROR'}, f"{n}: not sent: {e or 'out of memory'}")
        if core.server is not None:
            core.publish()

    def execute(self, context):         # from a script: blocking
        for name, kind in self._jobs():
            bake.bake_kind(context, bpy.data.objects[name], kind)
        if self.send:
            self.failed = set()
            self._send({n for n, _k in self._jobs()})
        return {'FINISHED'}


CLASSES = (PPD_OT_show_image, PPD_OT_open_folder, PPD_OT_reload_texture, PPD_OT_load_texture,
           PPD_OT_bake)


def register():
    global busy
    busy = ""
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
