#!/usr/bin/env python3
"""Repair the key-map on iOS at startup.

Symptom (v17 device log): `[IOSPROBE] WM LMB ... a=1 r=0 act=0` for every tap in
the 3D view, plus a flood of `WARNING empty keymap '3D View'` / `'Window'` /
`'Screen'`.  `act=0` means no handler consumed the event, i.e. the key-map had no
items at all, so nothing key-map driven worked: no select, no orbit, no shortcut.

Cause: `WM_keyconfig_init()` only runs its populate block

    if (CTX_py_init_get(C) && (wm->init_flag & WM_INIT_FLAG_KEYCONFIG) == 0)

and the iOS port creates its window (-> `WM_check` -> `WM_keyconfig_init`) before
Python is up.  Every later call finds `WM_INIT_FLAG_KEYCONFIG` handled or Python
still late, so the key-configuration stays the one `WM_keyconfig_new()` made:
all 106 key-maps present but with zero items.

Fix: after startup, from Python (so no C API is involved), check the 3D View
key-map.  If it is empty, call `bpy.utils.keyconfig_init()` once, which re-reads
`presets/keyconfig/Blender.py` and fills every key-map.  The window manager
rebuilds its handlers on the next event pass, so the viewport starts reacting
immediately.

Idempotent: guarded by the ``IOS-KEYMAP-GUARD`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-KEYMAP-GUARD"

DEFAULT_TARGET = "scripts/startup/bl_ui/__init__.py"

GUARD = '''

# --------------------------------------------------------------------------
# @MARK@ (patch_ios_keymap.py) - see .github/scripts/patch_ios_keymap.py
# The iOS port initialises the key-configuration before Python is ready, which
# leaves every key-map with zero items: clicks and middle-mouse drags in the
# viewport do nothing.  Repair it once, as soon as the UI is up.
# --------------------------------------------------------------------------
def _ios_keymap_guard():
    import bpy

    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.active or wm.keyconfigs.default
        km = kc.keymaps.get("3D View") if kc else None
        items = len(km.keymap_items) if km else -1
        print("[IOSKM] keyconfig=%r 3DView=%d" % (kc.name if kc else None, items))

        if items == 0:
            bpy.utils.keyconfig_init()
            kc = wm.keyconfigs.active or wm.keyconfigs.default
            km = kc.keymaps.get("3D View") if kc else None
            print("[IOSKM] repaired keyconfig=%r 3DView=%d"
                  % (kc.name if kc else None, len(km.keymap_items) if km else -1))
    except Exception as ex:  # never break startup over this
        print("[IOSKM] guard failed:", ex)

    # Run once: returning None unregisters the timer.
    return None


if not globals().get("_ios_keymap_guard_registered"):
    _ios_keymap_guard_registered = True
    try:
        import bpy as _bpy
        _bpy.app.timers.register(_ios_keymap_guard, first_interval=0.5)
    except Exception:
        pass
'''.replace("@MARK@", MARK)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {target}")
        return 0

    target.write_text(text + GUARD, encoding="utf-8")
    print(f"  patched  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
