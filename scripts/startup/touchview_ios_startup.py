import sys

import bpy


def _enable_touchview():
    if sys.platform != "ios":
        return None

    try:
        import addon_utils

        if "touchview" not in {
            mod.__name__ for mod in addon_utils.modules(refresh=False)
        }:
            return 1.0

        is_enabled, _is_loaded = addon_utils.check("touchview")
        if not is_enabled:
            addon_utils.enable("touchview", default_set=False, persistent=True)
    except Exception:
        import traceback

        traceback.print_exc()

    return None


if not bpy.app.timers.is_registered(_enable_touchview):
    bpy.app.timers.register(_enable_touchview, first_interval=1.0, persistent=True)
