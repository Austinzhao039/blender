#!/usr/bin/env python3
"""Make a drag on iOS rotate the 3D view.

Why this is needed
------------------
`handlePan` emits `PAN_GESTURE`, which GHOST turns into a trackpad scroll and
Blender turns into a `MOUSEPAN` event.  Grep the whole keymap preset for
`MOUSEPAN` and you get **zero hits**: the only places 3D-view navigation is
bound are

    MIDDLEMOUSE (press)          -> view3d.rotate
    MIDDLEMOUSE + shift          -> view3d.move
    MIDDLEMOUSE + ctrl           -> view3d.zoom
    TRACKPADPAN / TRACKPADZOOM   -> same three

`MOUSEPAN` is only special-cased by the C UI handlers (`is_wheel` in
wm_handlers.cc) so it scrolls list views, but no key-map consumes it.  That is
exactly the reported symptom: buttons and menus react, the viewport ignores
every gesture.

An iPad has no middle button, so the fix is to emit one: a drag becomes
MIDDLEMOUSE down / cursor-move / up, which the stock key-map already maps to
`view3d.rotate`.  A tap still emits LEFTMOUSE so selection keeps working.

Idempotent: a marker comment guards the enum and the handler.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-NAV-MIDDLE"

# --- 1. enum: two new event types -------------------------------------------
OLD_ENUM = """    LEFT_BUTTON_DOWN,
    LEFT_BUTTON_UP,
    PENCIL_TAP,
  };"""
NEW_ENUM = """    LEFT_BUTTON_DOWN,
    LEFT_BUTTON_UP,
    PENCIL_TAP,
    /* IOS-NAV-MIDDLE: drag maps to MIDDLEMOUSE so 3D-view navigation works. */
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
  };"""

# --- 2. description helper --------------------------------------------------
OLD_DESC = """      case PENCIL_TAP:
        return @"PENCIL-TAP";"""
NEW_DESC = """      case PENCIL_TAP:
        return @"PENCIL-TAP";
      case MIDDLE_BUTTON_DOWN:
        return @"MB-DOWN";
      case MIDDLE_BUTTON_UP:
        return @"MB-UP";"""

# --- 3. event emission ------------------------------------------------------
OLD_EMIT = """        case UserInputEvent::EventTypes::PENCIL_TAP:"""
NEW_EMIT = """        case UserInputEvent::EventTypes::MIDDLE_BUTTON_DOWN:
          system->pushEvent(std::make_unique<GHOST_EventButton>(system->getMilliSeconds(),
                                                                GHOST_kEventButtonDown,
                                                                window,
                                                                GHOST_kButtonMaskMiddle,
                                                                tablet_data));
          break;
        case UserInputEvent::EventTypes::MIDDLE_BUTTON_UP:
          system->pushEvent(std::make_unique<GHOST_EventButton>(system->getMilliSeconds(),
                                                                GHOST_kEventButtonUp,
                                                                window,
                                                                GHOST_kButtonMaskMiddle,
                                                                tablet_data));
          break;
        case UserInputEvent::EventTypes::PENCIL_TAP:"""

# --- 4. handlePan: LEFTMOUSE drag -> MIDDLEMOUSE drag -----------------------
# This is the text produced by patch_ios_input.py, so it is only present when
# that patch already ran (the workflow applies them in order).
OLD_PAN = """  if (sender.state == UIGestureRecognizerStateBegan ||
      sender.state == UIGestureRecognizerStateChanged)
  {
    /* Register initial click for click and drag support. */
    if (sender.state == UIGestureRecognizerStateBegan) {
      /* Set inital translation */
      [sender setCachedTranslation:translation];
      event_info.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      event_info.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
    }

    /* Calculate translation change since last begin/change event */
    CGPoint relative_translation = [sender getRelativeTranslation:translation];
    /* Update cached translation */
    [sender setCachedTranslation:translation];
    /* Send pan event if non zero.
     * A mouse drag must not scroll: keep the button down and only emit cursor
     * moves, so sliders, box-select and transforms behave like on desktop. */
    if (![sender isIndirectPointer] &&
        !CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f)))
    {
      event_info.translation = relative_translation;
      event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE);
    }

    /* Update cursor position on change */
    if (sender.state == UIGestureRecognizerStateChanged) {
      event_info.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    }
  }

  /* Mouse release for pan. */
  if (sender.state == UIGestureRecognizerStateEnded ||
      sender.state == UIGestureRecognizerStateCancelled ||
      sender.state == UIGestureRecognizerStateFailed)
  {
    event_info.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
  }"""

NEW_PAN = """  /* IOS-NAV-MIDDLE: handlePan is a no-op.
   *
   * The MIDDLEMOUSE drag is generated by `iosPointerUpdate` in the view touch
   * callbacks (patch_ios_pointer.py) instead of here.  The UIPanGestureRecognizer
   * does not always fire for every touch sequence, and when it stays silent both
   * it and iosPointerUpdate's 14px tap/drag split emit nothing at all — the
   * viewport stays frozen.  The touch callbacks are guaranteed by UIKit. */
  return;"""


DEFAULT_TARGET = "intern/ghost/intern/GHOST_WindowIOS.mm"


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    win = Path(target)
    if not win.is_file():
        print(f"::error::missing file {win}")
        return 1

    text = win.read_text(encoding="utf-8")
    if MARK in text and OLD_PAN not in text:
        print(f"already patched: {win}")
        return 0

    for old, new in ((OLD_ENUM, NEW_ENUM), (OLD_DESC, NEW_DESC), (OLD_EMIT, NEW_EMIT), (OLD_PAN, NEW_PAN)):
        if text.count(old) != 1:
            raise SystemExit(f"{win}: anchor not unique ({text.count(old)} hits): {old.splitlines()[0]!r}")
        text = text.replace(old, new, 1)

    win.write_text(text, encoding="utf-8")
    print(f"patched {win} (4 rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
