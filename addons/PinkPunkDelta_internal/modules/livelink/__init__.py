from . import operators, setup_ui, ui


def register():
    operators.register()
    ui.register()
    setup_ui.register()


def unregister():
    setup_ui.unregister()
    ui.unregister()
    operators.unregister()
