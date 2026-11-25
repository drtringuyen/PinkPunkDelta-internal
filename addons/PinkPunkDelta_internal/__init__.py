bl_info = {
    "name": "PinkPunkDelta_internal",
    "version": (0, 0, 1),
    "blender": (5, 3, 0),
    "category": "Object",
    "location": "3D View > Sidebar > PPD",
    "description": "Setup, bake and Procreate live link for the Pink Punk Delta production",
    "author": "",
    "license": "GPL-3.0-or-later",
    "doc_url": "",
    "tracker_url": "",
}


def register():
    from . import properties, infos, panels, identity, links, module_manager
    properties.register()
    identity.register()
    links.register()
    infos.register()
    panels.register()
    module_manager.load_all()


def unregister():
    from . import properties, infos, panels, identity, links, module_manager
    module_manager.unload_all()
    panels.unregister()
    infos.unregister()
    links.unregister()
    identity.unregister()
    properties.unregister()
