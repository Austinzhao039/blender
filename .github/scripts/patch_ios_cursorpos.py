#!/usr/bin/env python3
"""Make ``GHOST_SystemIOS::getCursorPosition()`` answer with a real position.

Bug
---
    GHOST_TSuccess GHOST_SystemIOS::getCursorPosition(int32_t & /*x*/, int32_t & /*y*/) const
    {
      /* iOS Passthrough. */
      GHOST_IWindow *window = this->window_manager_->getActiveWindow();
      if (!window) { return GHOST_kFailure; }
      return GHOST_kSuccess;
    }

It reports **success** and never writes ``x``/``y``, so the caller keeps
whatever was in its own variable.  ``GHOST_System::getCursorPositionClientRelative``
is built on top of this, and ``wm_window.cc`` uses it in
``wm_window_update_eventstate()``:

    int xy[2];                                   /* uninitialised */
    if (wm_cursor_position_get(win, &xy[0], &xy[1])) {
      copy_v2_v2_int(win->runtime->eventstate->xy, xy);   /* garbage copied */
    }

That runs once per window from ``wm_window_ensure_eventstate()``, so the window
starts out believing the mouse is at an arbitrary coordinate.  ``eventstate->xy``
is what ``WM_event_add_mousemove()``, the "mouse outside the window, close the
popup" test and the cursor-shape logic read.

Fix
---
Record the position of every ``CURSOR_MOVE`` we push and hand that back.  The
two globals are defined in ``GHOST_WindowIOS.mm`` (which is where the events are
generated) and declared ``extern`` here -- no header change, no new API.

Idempotent: guarded by the ``IOS-CURSORPOS`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-CURSORPOS"

DEFAULT_SYSTEM = "intern/ghost/intern/GHOST_SystemIOS.mm"
DEFAULT_WINDOW = "intern/ghost/intern/GHOST_WindowIOS.mm"

OLD_GET = '''GHOST_TSuccess GHOST_SystemIOS::getCursorPosition(int32_t & /*x*/, int32_t & /*y*/) const
{
  /* iOS Passthrough. */
  GHOST_IWindow *window = this->window_manager_->getActiveWindow();
  if (!window) {
    return GHOST_kFailure;
  }
  // GHOST_ASSERT(FALSE,"GHOST_SystemIOS::getCursorPosition unsupported on iOS");
  return GHOST_kSuccess;
}
'''

NEW_GET = '''/* @MARK@: last pointer position the touch layer pushed, in window pixels with
 * the origin at the bottom-left (same space as `GHOST_EventCursor`).  Defined in
 * GHOST_WindowIOS.mm. */
extern int32_t ios_last_cursor_x;
extern int32_t ios_last_cursor_y;

GHOST_TSuccess GHOST_SystemIOS::getCursorPosition(int32_t &x, int32_t &y) const
{
  GHOST_IWindow *window = this->window_manager_->getActiveWindow();
  if (!window) {
    return GHOST_kFailure;
  }
  /* @MARK@: this used to return success without touching the outputs, leaving
   * the caller with an uninitialised value -- `wm_window_update_eventstate()`
   * copied that straight into `eventstate->xy`. */
  x = ios_last_cursor_x;
  y = ios_last_cursor_y;
  return GHOST_kSuccess;
}
'''.replace("@MARK@", MARK)

OLD_DEF_ANCHOR = "} UserInputEvent;\n"

NEW_DEF_ANCHOR = '''} UserInputEvent;

/* @MARK@: written on every cursor-move event, read by
 * `GHOST_SystemIOS::getCursorPosition()`. */
int32_t ios_last_cursor_x = 0;
int32_t ios_last_cursor_y = 0;
'''.replace("@MARK@", MARK)

OLD_EMIT = '''        case UserInputEvent::EventTypes::CURSOR_MOVE:
          system->pushEvent(std::make_unique<GHOST_EventCursor>(system->getMilliSeconds(),
'''

NEW_EMIT = '''        case UserInputEvent::EventTypes::CURSOR_MOVE:
          /* @MARK@: remember where the pointer is, for `getCursorPosition()`. */
          ios_last_cursor_x = int32_t(event_info.location.x);
          ios_last_cursor_y = int32_t(event_info.location.y);
          system->pushEvent(std::make_unique<GHOST_EventCursor>(system->getMilliSeconds(),
'''.replace("@MARK@", MARK)


def patch(path: Path, edits, marker: str) -> int:
    if not path.is_file():
        print(f"::error::missing file {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"  already  {path}")
        return 0
    for old, new, label in edits:
        hits = text.count(old)
        if hits != 1:
            print(f"::error::{path}: anchor not unique ({hits} hits): {label}")
            return 1
        text = text.replace(old, new, 1)
        print(f"  patched  {path.name}: {label}")
    path.write_text(text, encoding="utf-8")
    return 0


def main() -> int:
    system = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYSTEM)
    window = Path(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_WINDOW)

    rc = patch(system, [(OLD_GET, NEW_GET, "getCursorPosition")], MARK)
    if rc != 0:
        return rc
    return patch(window,
                 [(OLD_DEF_ANCHOR, NEW_DEF_ANCHOR, "cursor-position globals"),
                  (OLD_EMIT, NEW_EMIT, "record cursor move")],
                 MARK)


if __name__ == "__main__":
    raise SystemExit(main())
