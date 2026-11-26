"""03.LiveLink > iPad Setup: what this PC still needs, one button that does it, and the address
to type on the iPad."""
import os

import bpy
from bpy.props import EnumProperty, StringProperty

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

    what: EnumProperty(items=[("SMB", "", ""), ("USER", "", ""), ("PASSWORD", "", "")],
                       options={'HIDDEN'})

    def execute(self, context):
        name, password = core.account()
        text = {"SMB": core.smb_address(), "USER": name, "PASSWORD": password}[self.what]
        context.window_manager.clipboard = text
        self.report({'INFO'}, "Copied" if self.what == "PASSWORD" else "Copied " + text)
        return {'FINISHED'}


def _forget(path):
    def go():
        try:
            os.remove(path)
        except OSError:
            pass
        return None
    return go


class PPD_OT_ipad_account(bpy.types.Operator):
    """Make the iPad's own Windows account, or give it a new password. It can only open PPD_Procreate and cannot sign in at the PC. Windows asks for permission"""
    bl_idname = "ppd.ipad_account"
    bl_label = "iPad Account"

    name: StringProperty(name="Name", description="3 to 20 letters, digits, - or _")
    password: StringProperty(name="Password", description="10 or more characters. The iPad "
                             "asks for it once; this panel and the LiveLink page show it")

    @classmethod
    def poll(cls, context):
        if not pc.supported():
            return False
        if not any(k == "share" and ok for k, ok, _t in core.monitor.checks):
            cls.poll_message_set("Press Set Up This PC first")
            return False
        return True

    def invoke(self, context, event):
        self.name, old = core.account()
        self.password = old or pc.new_password()
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "name")
        col.prop(self, "password")
        sub = col.column(align=True)
        sub.active = False
        sub.label(text="Windows asks for permission once.", icon='INFO')
        sub.label(text="The account only opens PPD_Procreate.")

    def execute(self, context):
        name, password = self.name.strip(), self.password
        if not pc.NAME_RE.match(name):
            self.report({'ERROR'}, "Name: 3 to 20 letters, digits, - or _, a letter first")
            return {'CANCELLED'}
        if name.casefold() == core.monitor.login.casefold():
            self.report({'ERROR'}, "That is your own Windows account: pick another name")
            return {'CANCELLED'}
        if len(password) < 10:
            self.report({'ERROR'}, "The password needs 10 or more characters")
            return {'CANCELLED'}
        core.save_config(ipad_user=name, ipad_password=password)
        path = pc.password_file(password)
        bpy.app.timers.register(_forget(path), first_interval=120)
        if not pc.elevate(core.pc_script(pc._ACCOUNT, PWFILE=path)):
            _forget(path)()
            self.report({'WARNING'}, "Not made: Windows was not given permission")
            return {'CANCELLED'}
        core.check_pc(follow=30)
        if core.server is not None:
            core.publish()
        self.report({'INFO'}, f"{name}: on the iPad use Registered User, this name and password")
        return {'FINISHED'}


_waiting = {"path": "", "until": 0.0}


def _pick_up():
    """The terminal wrote the password it set: keep it for the page, delete the file. Only
    files and LiveLink's settings - nothing in the .blend."""
    import time
    path = _waiting["path"]
    if not path or time.time() > _waiting["until"]:
        _forget(path)()
        _waiting["path"] = ""
        return None
    if not os.path.isfile(path):
        return 1.0
    try:
        with open(path, encoding="utf-8-sig") as f:
            password = f.read().strip()
    except OSError:
        return 1.0
    _forget(path)()
    _waiting["path"] = ""
    if password:
        core.save_config(ipad_password=password)
        core.check_pc(follow=15)
        if core.server is not None:
            core.publish()
        core.log(f"iPad account {core.account()[0]}: password set")
    return None


class PPD_OT_ipad_terminal(bpy.types.Operator):
    """Make the iPad account (or give it a new password) in a PowerShell window: you type the password there twice. Windows asks for permission. Then the LiveLink page shows the name and password to copy"""
    bl_idname = "ppd.ipad_terminal"
    bl_label = "Set Password in Terminal"

    @classmethod
    def poll(cls, context):
        if not pc.supported():
            return False
        if not any(k == "share" and ok for k, ok, _t in core.monitor.checks):
            cls.poll_message_set("Press Set Up This PC first")
            return False
        return True

    def execute(self, context):
        import tempfile
        import time
        name = core.account()[0]
        if not pc.NAME_RE.match(name):
            self.report({'ERROR'}, "Name: 3 to 20 letters, digits, - or _, a letter first")
            return {'CANCELLED'}
        if name.casefold() == core.monitor.login.casefold():
            self.report({'ERROR'}, "That is your own Windows account: pick another name")
            return {'CANCELLED'}
        path = os.path.join(tempfile.gettempdir(), f"ppd_ipad_{os.getpid()}_{int(time.time())}.txt")
        if not pc.elevate(core.pc_script(pc._ACCOUNT_TERMINAL, RESULT=path)):
            self.report({'WARNING'}, "Windows was not given permission")
            return {'CANCELLED'}
        _waiting.update(path=path, until=time.time() + 900)
        if not bpy.app.timers.is_registered(_pick_up):
            bpy.app.timers.register(_pick_up, first_interval=1.0)
        self.report({'INFO'}, "Type the password in the PowerShell window")
        return {'FINISHED'}


class PPD_OT_ipad_test(bpy.types.Operator):
    """Check on this PC that the iPad account's name and password are right (a wrong try counts toward a lock)"""
    bl_idname = "ppd.ipad_test"
    bl_label = "Test Password"

    @classmethod
    def poll(cls, context):
        return pc.supported() and bool(core.account()[1])

    def execute(self, context):
        name, password = core.account()
        code = pc.test_login(name, password)
        if code:
            self.report({'ERROR'}, f"{name}: {pc.LOGIN_ERRORS.get(code, f'Windows error {code}')}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{name} and its password are right on this PC")
        return {'FINISHED'}


class PPD_OT_ipad_remove(bpy.types.Operator):
    """Delete the iPad account from this PC (only one PPD made). Windows asks for permission"""
    bl_idname = "ppd.ipad_remove"
    bl_label = "Remove iPad Account"

    @classmethod
    def poll(cls, context):
        return pc.supported()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not pc.elevate(core.pc_script(pc._ACCOUNT_REMOVE)):
            self.report({'WARNING'}, "Windows was not given permission")
            return {'CANCELLED'}
        core.save_config(ipad_password="")
        core.check_pc(follow=15)
        return {'FINISHED'}


class PPD_OT_open_share(bpy.types.Operator):
    """Open the shared folder: the iPad saves here, Send to iPad puts PSDs in To iPad"""
    bl_idname = "ppd.open_share"
    bl_label = "Open Shared Folder"

    def execute(self, context):
        os.startfile(core.watch_folder())
        return {'FINISHED'}


def _get_user(self):
    return core.account()[0]


def _set_user(self, value):
    value = value.strip()
    if value and value != core.account()[0]:
        core.save_config(ipad_user=value, ipad_password="")    # another account: its own password
        core.check_pc()


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
        shown = m.checks if debug(context) else [c for c in m.checks if not c[1]][:1]
        if not shown and not debug(context):
            col.label(text="This PC is ready for the iPad", icon='CHECKMARK')
        for key, ok, text in shown:
            row = col.row(align=True)
            row.alert = not ok
            row.label(text=text, icon='CHECKMARK' if ok else 'X')
            if key == "private" and not ok:
                row.operator("ppd.pc_network", text="", icon='PREFERENCES')
        if m.busy:
            col.label(text="Checking...", icon='SORTTIME')
        if m.error:
            col.label(text=m.error, icon='ERROR')
        pc_ok = all(ok for k, ok, _t in m.checks if k != "account")
        row = layout.row(align=True)
        if not pc_ok:
            row.operator("ppd.pc_setup", icon='TOOL_SETTINGS')
        row.operator("ppd.pc_check", text="Check" if not m.ready else "Check Again",
                     icon='FILE_REFRESH')
        if pc_ok:
            row.operator("ppd.pc_remove", text="", icon='X')
        if debug(context) and m.ready:
            box = layout.box()
            box.label(text="On the iPad: scan the QR code, it shows every step", icon='INFO')
            r = box.row(align=True)
            r.label(text=core.smb_address(), icon='URL')
            r.operator("ppd.pc_copy", text="", icon='COPYDOWN').what = "SMB"


def debug(context):
    """The Infos panel's debug switch (i): the details show only then."""
    props = getattr(context.scene, "pinkpunkdelta_internal_props", None)
    return bool(props is not None and props.debug_mode)


def draw_account(layout, context):
    """The iPad account: name, password, and the buttons that make it."""
    m = core.monitor
    name, password = core.account()
    box = layout.box()
    box.label(text="iPad account (Registered User on the iPad)", icon='USER')
    r = box.row(align=True)
    r.prop(context.window_manager, "ppd_ipad_user", text="Name", icon='USER')
    r.operator("ppd.pc_copy", text="", icon='COPYDOWN').what = "USER"
    r = box.row(align=True)
    r.label(text=password or "No password yet", icon='LOCKED')
    if password:
        r.operator("ppd.pc_copy", text="", icon='COPYDOWN').what = "PASSWORD"
    r = box.row(align=True)
    r.scale_y = 1.3
    made = any(k == "account" and ok for k, ok, _t in m.checks)
    r.operator("ppd.ipad_terminal", icon='CONSOLE',
               text="New Password in Terminal" if made else "Make Account in Terminal")
    r = box.row(align=True)
    r.operator("ppd.ipad_account", text="Generated Password", icon='LOCKED')
    r.operator("ppd.ipad_test", text="Test", icon='CHECKMARK')
    r.operator("ppd.ipad_remove", text="", icon='X')
    if _waiting["path"]:
        r = box.row()
        r.label(text="Waiting for the PowerShell window...", icon='SORTTIME')


CLASSES = (PPD_OT_pc_check, PPD_OT_pc_setup, PPD_OT_pc_remove, PPD_OT_pc_network,
           PPD_OT_pc_copy, PPD_OT_ipad_account, PPD_OT_ipad_terminal, PPD_OT_ipad_test,
           PPD_OT_ipad_remove, PPD_OT_open_share,
           PINKPUNKDELTA_INTERNAL_PT_LivelinkSetup)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.ppd_ipad_user = StringProperty(
        name="iPad account", get=_get_user, set=_set_user,
        description="The Windows account the iPad logs in with. Kept for this PC")


def unregister():
    del bpy.types.WindowManager.ppd_ipad_user
    if bpy.app.timers.is_registered(_pick_up):
        bpy.app.timers.unregister(_pick_up)
    if bpy.app.timers.is_registered(core._check_tick):
        bpy.app.timers.unregister(core._check_tick)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
