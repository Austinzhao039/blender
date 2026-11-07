#!/usr/bin/env python3
"""Let the 3D-view navigation operators run on iOS (IOS-NAVOPS).

Why this exists
---------------
`view3d.rotate` / `view3d.move` are fully implemented on the `ios` branch --
they are the same files the desktop build uses (`view3d_navigate_view_rotate.cc`
411 lines of turntable + trackball rotation).  The touch plumbing works too: a
single-finger drag reaches `handlePan:` and is turned into a MIDDLEMOUSE drag by
`patch_ios_nav.py`, and `km_view3d` binds `view3d.rotate` to `MIDDLEMOUSE PRESS`.

What killed it is the entry guard both operators carry:

    #ifdef WITH_APPLE_CROSSPLATFORM
      /* Only scroll view with multiple fingers on iOS. */
      if (!(event->flag & WM_EVENT_MULTITOUCH_TWO_FINGERS)) {
        return OPERATOR_FINISHED;
      }
    #endif

`WM_EVENT_MULTITOUCH_TWO_FINGERS` is set in `wm_event_system.cc` **only** when a
trackpad scroll arrives with `pd->numFingers == 2`.  A synthesized button event
never carries it, so `viewrotate_invoke()` returned `OPERATOR_FINISHED` before
`view3d_navigate_invoke_impl()` ever ran -- the operator existed, matched the
key map, and did nothing.  That is exactly the "the middle of the screen never
moves" symptom.

The fix keeps the original intent (a one-finger *trackpad scroll* must scroll UI
lists instead of orbiting the view) while letting real mouse-button events
through.  `view3d.zoom` / `view3d.dolly` never had the guard and need nothing.
"""

import pathlib
import sys

MARK = "IOS-NAVOPS"

# The guarded `if` is byte-identical in both files; the surrounding comment
# differs, so anchor on the `if` itself.
GUARD_ANCHOR = """  if (!(event->flag & WM_EVENT_MULTITOUCH_TWO_FINGERS)) {
    return OPERATOR_FINISHED;
  }"""

# Deliberately no `ELEM()` here: `view3d_navigate_view_move.cc` never used it,
# so its transitive includes may not provide `BLI_utildefines.hh`.
GUARD_NEW = """  /* IOS-NAVOPS: a mouse-button event must not be filtered out here.
   *
   * The stock condition insists on #WM_EVENT_MULTITOUCH_TWO_FINGERS, which only
   * a two-finger trackpad scroll ever sets.  The middle-button drag synthesized
   * for a one-finger pan (see `patch_ios_nav.py`) carries no such flag, so this
   * operator returned #OPERATOR_FINISHED immediately and the view never moved.
   * Keep the original behaviour for trackpad scrolls only. */
  if (!(event->flag & WM_EVENT_MULTITOUCH_TWO_FINGERS) && event->type != LEFTMOUSE &&
      event->type != MIDDLEMOUSE && event->type != RIGHTMOUSE)
  {
    return OPERATOR_FINISHED;
  }"""

DEFAULT_TARGETS = [
    "source/blender/editors/space_view3d/view3d_navigate_view_rotate.cc",
    "source/blender/editors/space_view3d/view3d_navigate_view_move.cc",
]


def patch_file(path: pathlib.Path) -> str:
    text = path.read_text(encoding="utf-8")

    if MARK in text:
        return "already"

    if text.count(GUARD_ANCHOR) != 1:
        raise SystemExit(
            f"{path}: expected exactly one guard anchor, found {text.count(GUARD_ANCHOR)}"
        )

    text = text.replace(GUARD_ANCHOR, GUARD_NEW, 1)

    if MARK not in text:
        raise SystemExit(f"{path}: marker missing after replace")
    if text.count("{") != text.count("}"):
        raise SystemExit(f"{path}: braces unbalanced after patch")

    path.write_text(text, encoding="utf-8")
    return "patched"


def main() -> int:
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(".")
    for rel in DEFAULT_TARGETS:
        target = root / rel
        if not target.exists():
            raise SystemExit(f"missing {target}")
        print(f"{rel}: {patch_file(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
