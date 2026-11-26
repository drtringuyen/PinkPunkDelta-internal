"""Concept palette: the main colors of a picture, to drag onto the split parts' ramps."""
from . import operators, ui


def register():
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
