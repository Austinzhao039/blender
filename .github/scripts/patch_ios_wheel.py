#!/usr/bin/env python3
"""Give the iOS port a mouse wheel.

`GHOST_SystemIOS` never pushes a `GHOST_kEventWheel`, so nothing in Blender can
be scrolled or zoomed with a mouse wheel - `UIPanGestureRecognizer` fed through
`allowedScrollTypesMask` (the only way iPadOS reports a wheel) was turned into a
`PAN_GESTURE` / `MOUSEPAN` trackpad scroll, which no key-map consumes outside
the 3D view.

The scroll gesture now accumulates its continuous delta and emits discrete
wheel notches, which is exactly what `WM_event_add_ghostevent` turns into
`WHEELUPMOUSE` / `WHEELDOWNMOUSE`:

    View2D      -> view2d.scroll_up / scroll_down   (panels, outliner, prefs)
    View3D      -> view3d.zoom                      (default key-map)

Idempotent: guarded by the ``IOS-WHEEL`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-WHEEL"

INCLUDE_ANCHOR = """#include "GHOST_EventTrackpad.hh\""""
INCLUDE_NEW = """#include <cstdio> /* IOS-WHEEL: stdio for the diagnostic traces */
#include "GHOST_EventTrackpad.hh"
#include "GHOST_EventWheel.hh" /* IOS-WHEEL */"""

ENUM_ANCHOR = """    /* IOS-NAV-MIDDLE: drag maps to MIDDLEMOUSE so 3D-view navigation works. */
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
  };"""
ENUM_NEW = """    /* IOS-NAV-MIDDLE: drag maps to MIDDLEMOUSE so 3D-view navigation works. */
    MIDDLE_BUTTON_DOWN,
    MIDDLE_BUTTON_UP,
    /* IOS-WHEEL: discrete wheel notches. */
    WHEEL_UP,
    WHEEL_DOWN,
  };"""

SIZE_OLD = "  EventTypes event_list[10];"
SIZE_NEW = "  EventTypes event_list[16];"

DESC_ANCHOR = """      case MIDDLE_BUTTON_UP:
        return @"MB-UP";"""
DESC_NEW = DESC_ANCHOR + """
      case WHEEL_UP:
        return @"WHEEL-UP";
      case WHEEL_DOWN:
        return @"WHEEL-DOWN";"""

EMIT_ANCHOR = """        case UserInputEvent::EventTypes::MIDDLE_BUTTON_DOWN:"""
EMIT_NEW = """        case UserInputEvent::EventTypes::WHEEL_UP:
          system->pushEvent(std::make_unique<GHOST_EventWheel>(system->getMilliSeconds(),
                                                               window,
                                                               GHOST_kEventWheelAxisVertical,
                                                               1));
          break;
        case UserInputEvent::EventTypes::WHEEL_DOWN:
          system->pushEvent(std::make_unique<GHOST_EventWheel>(system->getMilliSeconds(),
                                                               window,
                                                               GHOST_kEventWheelAxisVertical,
                                                               -1));
          break;
        case UserInputEvent::EventTypes::MIDDLE_BUTTON_DOWN:"""

SCROLL_OLD = """  CGPoint scroll_point = [sender getScaledTouchPoint:window];
  UserInputEvent event_info(&scroll_point, nullptr, nullptr, false);
  event_info.translation = relative_translation;
  event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE);
  [self generateUserInputEvents:event_info];"""

SCROLL_NEW = """  /* IOS-WHEEL: turn the continuous scroll into discrete wheel notches.
   *
   * MOUSEPAN (what this used to emit) is only consumed by the 3D view, so a
   * wheel did nothing anywhere else and never scrolled a panel. */
  static CGFloat iOswheel_rest = 0.0f;
  const CGFloat iOswheel_step = 16.0f;
  int iOswheel_notches = 0;
  iOswheel_rest += relative_translation.y;
  while (iOswheel_rest <= -iOswheel_step && iOswheel_notches > -4) {
    iOswheel_notches -= 1;
    iOswheel_rest += iOswheel_step;
  }
  while (iOswheel_rest >= iOswheel_step && iOswheel_notches < 4) {
    iOswheel_notches += 1;
    iOswheel_rest -= iOswheel_step;
  }
  if (iOswheel_notches == 0) {
    return;
  }

  CGPoint scroll_point = [sender getScaledTouchPoint:window];
  UserInputEvent event_info(&scroll_point, nullptr, nullptr, false);
  event_info.translation = relative_translation;
  for (int i = 0; i < (iOswheel_notches > 0 ? iOswheel_notches : -iOswheel_notches); i++) {
    event_info.add_event(iOswheel_notches > 0 ? UserInputEvent::EventTypes::WHEEL_UP
                                              : UserInputEvent::EventTypes::WHEEL_DOWN);
  }
  [self generateUserInputEvents:event_info];
  fprintf(stdout, "[IOSWHEEL] notches=%d\\n", iOswheel_notches);"""


PAN2F_OLD = """    /* Generate pan event if translation is non zero. */
    if (!CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f))) {
      CGPoint touch_point = [sender getScaledTouchPoint:window];
      bool pencil_pan = current_pencil_touch ? true : false;
      UserInputEvent event_info(&touch_point, &relative_translation, nullptr, pencil_pan);
      event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE_TWO_FINGERS);
      [self generateUserInputEvents:event_info];
    }"""

PAN2F_NEW = """    /* Generate pan event if translation is non zero. */
    if (!CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f))) {
      CGPoint touch_point = [sender getScaledTouchPoint:window];
      bool pencil_pan = current_pencil_touch ? true : false;
      UserInputEvent event_info(&touch_point, &relative_translation, nullptr, pencil_pan);
      /* IOS-WHEEL: a mostly vertical two-finger drag scrolls the panel under the
       * fingers.
       *
       * Panels, the outliner and the preferences window only consume wheel
       * events; a trackpad scroll (MOUSEPAN) is read by the 3D view alone.  So
       * a finger could never scroll anything on the device, no matter what the
       * single-finger path did. */
      if (fabs(relative_translation.y) > fabs(relative_translation.x)) {
        static CGFloat iOswheel2f_rest = 0.0f;
        const CGFloat iOswheel2f_step = 16.0f;
        int iOswheel2f_notches = 0;
        iOswheel2f_rest += relative_translation.y;
        while (iOswheel2f_rest <= -iOswheel2f_step && iOswheel2f_notches > -4) {
          iOswheel2f_notches -= 1;
          iOswheel2f_rest += iOswheel2f_step;
        }
        while (iOswheel2f_rest >= iOswheel2f_step && iOswheel2f_notches < 4) {
          iOswheel2f_notches += 1;
          iOswheel2f_rest -= iOswheel2f_step;
        }
        if (iOswheel2f_notches != 0) {
          const int iOswheel2f_count =
              (iOswheel2f_notches > 0) ? iOswheel2f_notches : -iOswheel2f_notches;
          for (int i = 0; i < iOswheel2f_count; i++) {
            event_info.add_event(iOswheel2f_notches > 0 ? UserInputEvent::EventTypes::WHEEL_UP
                                                        : UserInputEvent::EventTypes::WHEEL_DOWN);
          }
          [self generateUserInputEvents:event_info];
          fprintf(stdout, "[IOSWHEEL] 2f notches=%d\\n", iOswheel2f_notches);
          return;
        }
      }
      event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE_TWO_FINGERS);
      [self generateUserInputEvents:event_info];
    }"""


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1
                  else "intern/ghost/intern/GHOST_WindowIOS.mm")
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if f"{MARK}: discrete wheel" in text:
        print(f"  already  {target}")
        return 0

    rules = [
        (INCLUDE_ANCHOR, INCLUDE_NEW, "include"),
        (ENUM_ANCHOR, ENUM_NEW, "enum"),
        (SIZE_OLD, SIZE_NEW, "event_list size"),
        (DESC_ANCHOR, DESC_NEW, "enum description"),
        (EMIT_ANCHOR, EMIT_NEW, "event emission"),
        (SCROLL_OLD, SCROLL_NEW, "scroll wheel handler"),
        (PAN2F_OLD, PAN2F_NEW, "two finger scroll"),
    ]
    for old, new, what in rules:
        if text.count(old) != 1:
            raise SystemExit(f"{target}: anchor not unique ({text.count(old)}): {what}")
        text = text.replace(old, new, 1)

    target.write_text(text, encoding="utf-8")
    print(f"  patched  {target} ({len(rules)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
