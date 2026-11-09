#!/usr/bin/env python3
"""Give a pencil tap a matching button *up*.

Bug
---
``generateUserInputEvents()`` maps ``PENCIL_TAP`` (Apple Pencil double-tap) to a
**right button down** and nothing else:

    case UserInputEvent::EventTypes::PENCIL_TAP:
      /* Simulate clicking with the right mouse button. */
      system->pushEvent(… GHOST_kEventButtonDown … GHOST_kButtonMaskRight …);
      break;

There is no button-up.  ``wm`` tracks the pressed state per button, so after one
pencil tap the right button stays down for the rest of the session: the context
menu that a right click opens can never be dismissed, ``wm_event_...`` keeps
routing events as an ongoing RMB drag, and any modal operator waiting for the
release never finishes.

Fix
---
Emit the pair.  Anchored on the ``PENCIL_TAP`` case body, which no earlier patch
touches (``patch_ios_nav.py`` only inserts two extra cases *before* it).

Idempotent: guarded by the ``IOS-PENCIL-UP`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-PENCIL-UP"

DEFAULT_TARGET = "intern/ghost/intern/GHOST_WindowIOS.mm"

OLD = '''        case UserInputEvent::EventTypes::PENCIL_TAP:
          /* Simulate clicking with the right mouse button. */
          system->pushEvent(std::make_unique<GHOST_EventButton>(system->getMilliSeconds(),
                                                                GHOST_kEventButtonDown,
                                                                window,
                                                                GHOST_kButtonMaskRight,
                                                                tablet_data));
          break;
'''

NEW = '''        case UserInputEvent::EventTypes::PENCIL_TAP:
          /* @MARK@: simulate clicking with the right mouse button -- down *and*
           * up.  Without the matching release the window manager keeps the right
           * button marked as held, so the context menu this opens can never be
           * closed again and later events are treated as one endless RMB drag. */
          system->pushEvent(std::make_unique<GHOST_EventButton>(system->getMilliSeconds(),
                                                                GHOST_kEventButtonDown,
                                                                window,
                                                                GHOST_kButtonMaskRight,
                                                                tablet_data));
          system->pushEvent(std::make_unique<GHOST_EventButton>(system->getMilliSeconds(),
                                                                GHOST_kEventButtonUp,
                                                                window,
                                                                GHOST_kButtonMaskRight,
                                                                tablet_data));
          break;
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

    hits = text.count(OLD)
    if hits != 1:
        print(f"::error::{target}: anchor not unique ({hits} hits)")
        return 1

    text = text.replace(OLD, NEW, 1)
    target.write_text(text, encoding="utf-8")
    print(f"  patched  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
