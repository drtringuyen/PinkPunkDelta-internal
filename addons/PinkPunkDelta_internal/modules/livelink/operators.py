import os
import tempfile

import bpy
import bpy.utils.previews
from bpy.props import EnumProperty, StringProperty

from ... import identity as idn
from ..bakenlink import operators as bake_ops
from . import core, prepare, qr

_previews = None
_shown = {"url": "", "key": "", "full": ""}


def qr_icon():
    """The preview icon of the QR code for the link's address."""
    url = core.address()
    if _shown["url"] != url:
        d = os.path.join(tempfile.gettempdir(), "ppd_livelink_qr")
        os.makedirs(d, exist_ok=True)
        m = qr.encode(url)
        key = f"qr_{abs(hash(url))}"
        small = os.path.join(d, key + ".png")
        qr.write_png(small, m, scale=max(1, 256 // (len(m) + 4)), border=2)
        full = os.path.join(d, "big.png")
        qr.write_png(full, m, scale=14, border=4)
        if key not in _previews:
            _previews.load(key, small, 'IMAGE')
        _shown.update(url=url, key=key, full=full)
    return _previews[_shown["key"]].icon_id


class PPD_OT_link_start(bpy.types.Operator):
    """Listen on the local Wi-Fi for files from the iPad"""
    bl_idname = "ppd.link_start"
    bl_label = "Start LiveLink"

    def execute(self, context):
        try:
            core.start()
        except OSError as e:
            self.report({'ERROR'}, f"Port {core.PORT} is taken ({e}). "
                                   "Is the link running in another Blender?")
            return {'CANCELLED'}
        return {'FINISHED'}


class PPD_OT_link_stop(bpy.types.Operator):
    """Stop listening"""
    bl_idname = "ppd.link_stop"
    bl_label = "Stop"

    def execute(self, context):
        core.stop()
        return {'FINISHED'}


class PPD_OT_link_qr(bpy.types.Operator):
    """Open the QR code full size"""
    bl_idname = "ppd.link_qr"
    bl_label = "Big QR"

    def execute(self, context):
        qr_icon()
        bpy.ops.wm.path_open(filepath=_shown["full"])
        return {'FINISHED'}


class PPD_OT_link_copy(bpy.types.Operator):
    """Copy the address of the page the QR code opens"""
    bl_idname = "ppd.link_copy"
    bl_label = "Copy Address"

    def execute(self, context):
        context.window_manager.clipboard = core.address()
        self.report({'INFO'}, "Copied")
        return {'FINISHED'}


class PPD_OT_link_guide(bpy.types.Operator):
    """Open the same page the iPad shows after scanning the QR code: setup guide and status"""
    bl_idname = "ppd.link_guide"
    bl_label = "Setup Guide"

    @classmethod
    def poll(cls, context):
        return core.server is not None

    def execute(self, context):
        bpy.ops.wm.url_open(url=core.address())
        return {'FINISHED'}


class PPD_OT_prepare_psd(bpy.types.Operator):
    """Write the 8K PSD for Procreate next to the textures: UV layout at 25 %, TEX, SHD, ALB, NOR"""
    bl_idname = "ppd.prepare_psd"
    bl_label = "Prepare PSD"

    object_name: StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath) and not bake_ops.busy

    def execute(self, context):
        o = bpy.data.objects.get(self.object_name)
        if o is None:
            return {'CANCELLED'}
        if context.window:
            context.window.cursor_set('WAIT')
        try:
            path = prepare.prepare(o)
        except (OSError, RuntimeError, MemoryError) as e:
            self.report({'ERROR'}, str(e) or "Out of memory")
            return {'CANCELLED'}
        finally:
            if context.window:
                context.window.cursor_set('DEFAULT')
        if core.server is not None:
            core.publish()
        self.report({'INFO'}, f"{os.path.basename(path)}, "
                              f"{os.path.getsize(path) / 1e6:.0f} MB")
        return {'FINISHED'}


_items = []         # Blender needs the strings kept alive


def _object_items(self, context):
    _items[:] = [(o.name, o.name, "") for o in sorted(idn.objects(), key=lambda o: o.name)] \
        or [("", "(no setup objects)", "")]
    return _items


class PPD_OT_inbox_assign(bpy.types.Operator):
    """Pick the object this file belongs to. A PSD's name is remembered"""
    bl_idname = "ppd.inbox_assign"
    bl_label = "Assign"

    item_id: StringProperty(options={'HIDDEN'})
    object_name: EnumProperty(name="Object", items=_object_items)
    kind: EnumProperty(name="Texture", items=[("SHD", "SHD", ""), ("TEX", "TEX", "")])

    def _item(self):
        return next((i for i in core.inbox if i["id"] == self.item_id), None)

    def invoke(self, context, event):
        item = self._item()
        if item is None:
            return {'CANCELLED'}
        k = core.split_kind(item["stem"])[0]
        if k:
            self.kind = k
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "object_name")
        item = self._item()
        if item is not None and not item["psd"]:
            self.layout.prop(self, "kind")

    def execute(self, context):
        item, o = self._item(), bpy.data.objects.get(self.object_name)
        if item is None or o is None:
            return {'CANCELLED'}
        if item["psd"]:
            for other in idn.objects():
                if other.ppd.canvas == item["stem"]:
                    other.ppd.canvas = ""
            o.ppd.canvas = item["stem"]
        self.report({'INFO'}, core.deliver(o, item, self.kind))
        return {'FINISHED'}


class PPD_OT_inbox_drop(bpy.types.Operator):
    """Throw this received file away"""
    bl_idname = "ppd.inbox_drop"
    bl_label = "Discard"

    item_id: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        for i in [i for i in core.inbox if i["id"] == self.item_id]:
            core.drop(i)
        return {'FINISHED'}


CLASSES = (PPD_OT_link_start, PPD_OT_link_stop, PPD_OT_link_qr, PPD_OT_link_copy, PPD_OT_link_guide,
           PPD_OT_prepare_psd, PPD_OT_inbox_assign, PPD_OT_inbox_drop)


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    bpy.types.WindowManager.ppd_link_host = StringProperty(
        name="Address", description="Empty: this PC's Wi-Fi address. Set it when the QR code "
                                    "shows the wrong network (VPN, virtual adapter)")
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    global _previews
    core.stop()
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.ppd_link_host
    bpy.utils.previews.remove(_previews)
    _previews = None
    _shown.update(url="", key="", full="")
