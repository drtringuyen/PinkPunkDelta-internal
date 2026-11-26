"""Unpacking: a Procreate PSD into one image per texture (compose.py, used by LiveLink), and
the panel that shows how ALB and TEX were blended in Procreate."""
from . import ui


def register():
    ui.register()


def unregister():
    ui.unregister()
