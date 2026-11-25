"""03.LiveLink > iPad Setup: what this PC still needs, one button that does it, and the address
to type on the iPad."""
import os

import bpy
from bpy.props import EnumProperty

from . import core, pc


class PPD_OT_pc_check(bpy.types.Operator):
    """Check again whether the iPad can reach this PC"""
    bl_idname = "ppd.pc_check"
    bl_label = "Check This PC"

    def execute(self, context):
        core.check_pc()
        return {'FINISHED'}


class PPD_OT_pc_setup(bpy.types.Operator):
    """Share the folder for your Windows account and allow the iPad through the firewall (private network only). Windows asks for permission"""
    bl_idname = "ppd.pc_setup"
    bl_label = "Set Up This PC"

    @classmethod
    def poll(cls, context):
        return pc.supported() and bool(core.monitor.user)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="Windows will ask for permission. Then this PC:", icon='INFO')
        col.label(text=f"shares {core.watch_folder()} for {core.monitor.user} only")
        col.label(text="lets the iPad through the firewall, in your private network only")
        if any(k == "private" and not ok for k, ok, _t in core.monitor.checks):
            col.separator()
            col.label(text="Your network is Public: set it to Private yourself after this")

    def execute(self, context):
        if not pc.elevate(core.pc_script(pc._SETUP)):
            self.report({'WARNING'}, "Not set up: Windows was not given permission")
            return {'CANCELLED'}
        core.check_pc(follow=40)
        return {'FINISHED'}


class PPD_OT_pc_remove(bpy.types.Operator):
    """Stop sharing the folder and remove the firewall rules. The folder itself stays"""
    bl_idname = "ppd.pc_remove"
    bl_label = "Remove PC Setup"

    @classmethod
    def poll(cls, context):
        return pc.supported()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not pc.elevate(core.pc_script(pc._REMOVE)):
            self.report({'WARNING'}, "Windows was not given permission")
            return {'CANCELLED'}
        core.check_pc(follow=15)
        return {'FINISHED'}


class PPD_OT_pc_network(bpy.types.Operator):
    """Open Windows' network settings: choose your connection, then Private network"""
    bl_idname = "ppd.pc_network"
    bl_label = "Network Settings"

    def execute(self, context):
        os.startfile("ms-settings:network")
        return {'FINISHED'}


class PPD_OT_pc_copy(bpy.types.Operator):
    """Copy"""
    bl_idname = "ppd.pc_copy"
    bl_label = "Copy"

    what: EnumProperty(items=[("SMB", "", ""), ("USER", "", "")], options={'HIDDEN'})

    def execute(self, context):
        text = core.smb_address() if self.what == "SMB" else core.monitor.login
        context.window_manager.clipboard = text
        self.report({'INFO'}, "Copied " + text)
        return {'FINISHED'}


class PINKPUNKDELTA_INTERNAL_PT_LivelinkSetup(bpy.types.Panel):
    bl_label = "iPad Setup"
    bl_idname = "PINKPUNKDELTA_INTERNAL_PT_livelink_setup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PPD"
    bl_parent_id = "PINKPUNKDELTA_INTERNAL_PT_livelink"

    def draw_header_preset(self, context):
        m = core.monitor
        if m.checks:
            self.layout.label(text="", icon='CHECKMARK' if m.ready else 'ERROR')

    def draw(self, context):
        layout = self.layout
        m = core.monitor
        if not pc.supported():
            layout.label(text="Windows only: share the folder yourself", icon='INFO')
            return
        if not m.checks and not m.busy:
            layout.operator("ppd.pc_check", icon='VIEWZOOM')
            if m.error:
                layout.label(text=m.error, icon='ERROR')
            return
        col = layout.column(align=True)
        for key, ok, text in m.checks:
            row = col.row(align=True)
            row.alert = not ok
            row.label(text=text, icon='CHECKMARK' if ok else 'X')
            if key == "private" and not ok:
                row.operator("ppd.pc_network", text="", icon='PREFERENCES')
        if m.busy:
            col.label(text="Checking...", icon='SORTTIME')
        if m.error:
            col.label(text=m.error, icon='ERROR')
        row = layout.row(align=True)
        if not m.ready:
            row.operator("ppd.pc_setup", icon='TOOL_SETTINGS')
        row.operator("ppd.pc_check", text="Check" if not m.ready else "Check Again",
                     icon='FILE_REFRESH')
        if m.ready:
            row.operator("ppd.pc_remove", text="", icon='X')
            box = layout.box()
            box.label(text="On the iPad: scan the QR code, it shows every step", icon='INFO')
            for what, text, icon in (("SMB", core.smb_address(), 'URL'),
                                     ("USER", m.login, 'USER')):
                row = box.row(align=True)
                row.label(text=text, icon=icon)
                row.operator("ppd.pc_copy", text="", icon='COPYDOWN').what = what


CLASSES = (PPD_OT_pc_check, PPD_OT_pc_setup, PPD_OT_pc_remove, PPD_OT_pc_network,
           PPD_OT_pc_copy, PINKPUNKDELTA_INTERNAL_PT_LivelinkSetup)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    if bpy.app.timers.is_registered(core._check_tick):
        bpy.app.timers.unregister(core._check_tick)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
