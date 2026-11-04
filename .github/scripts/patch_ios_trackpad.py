#!/usr/bin/env python3
"""Make the iOS trackpad events land on event types the key map actually binds.

Why this exists
---------------
``GHOST_SystemIOS`` pushes ``GHOST_kTrackpadEventScroll`` / ``..._Magnify``.
``wm_event_add_ghostevent`` turns those into ``MOUSEPAN`` / ``MOUSEZOOM`` - and
neither name appears even once in ``keymap_data/blender_default.py``:

    TRACKPADPAN   18 bindings      MOUSEPAN    0 bindings
    TRACKPADZOOM   1 binding       MOUSEZOOM   0 bindings

The 3D view binds its whole navigation block to the TRACKPAD names:

    view3d.rotate <- TRACKPADPAN            (plain)
    view3d.move   <- TRACKPADPAN + shift
    view3d.zoom   <- TRACKPADPAN + ctrl
    view3d.zoom   <- TRACKPADZOOM

So one finger drag was being delivered correctly and then dropped on the floor
by the key map lookup: the event arrived, nothing consumed it.  That is why the
middle-button rewrites in v6/v7 changed nothing - the drag path was never the
problem.

This patch renames the two event types at the single place they are produced.
``wm_event_add_trackpad`` already encodes the delta as ``prev_xy = xy - delta``,
which is exactly what ``view3d.rotate`` reads, so no other change is needed.

Everything is marked ``IOS-TRACKPAD`` and is idempotent.

Usage:
    python3 patch_ios_trackpad.py [<blender source root>]   # default: current dir
"""
import os
import sys

MARK = "IOS-TRACKPAD"
TARGET = "source/blender/windowmanager/intern/wm_event_system.cc"

EDITS = [
    ("          event.type = MOUSEZOOM;",
     "          event.type = TRACKPADZOOM; /* %s: key map binds TRACKPADZOOM */" % MARK,
     "event.type = TRACKPADZOOM",
     "pinch -> TRACKPADZOOM"),
    ("          event.type = MOUSEPAN;",
     "          event.type = TRACKPADPAN; /* %s: key map binds TRACKPADPAN */" % MARK,
     "event.type = TRACKPADPAN",
     "drag  -> TRACKPADPAN"),
]


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    path = os.path.join(root, TARGET)
    if not os.path.isfile(path):
        raise SystemExit("missing %s (pass the source root)" % path)
    with open(path, encoding="utf-8") as f:
        text = f.read()

    applied = 0
    for old, new, marker, label in EDITS:
        if marker in text:
            print("  skip    %s (%s already applied)" % (path, label))
            continue
        if text.count(old) != 1:
            raise SystemExit("anchor for %s not unique/found (%d hits)"
                             % (label, text.count(old)))
        text = text.replace(old, new, 1)
        applied += 1
        print("  patched %s" % label)

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("  %d rule(s) applied to %s" % (applied, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
