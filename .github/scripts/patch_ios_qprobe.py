#!/usr/bin/env python3
"""Window-level probe for MIDDLEMOUSE, to explain a contradiction in the v18 log.

v18 device log:
  * GHOST side printed ``[IOSPTR] drag-start MID_DOWN xy=1032,778`` and
    ``[IOSPTR] drag-end MID_UP`` twice -- so the touch drag *does* synthesise
    middle-button events.
  * The window-manager probe (inserted in ``wm_event_do_handlers_area_regions``)
    logged 45 ``[IOSPROBE] WM LMB`` lines and **zero** ``MMB`` lines.

So the middle-button events either never enter the window event queue, or they
are consumed by a window-level modal handler before area/region handlers run.
``wm_event_do_handlers_area_regions`` only runs after the modal pass, which makes
"swallowed upstream" the likely explanation -- but guessing is not evidence.

This adds ``[IOSQ]`` lines at the top of the per-window event loop, printing the
event, its position, and whether a window modal handler is active.  One line per
middle-button event, so it cannot flood the log.

Idempotent: guarded by the ``IOSQ`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOSQ"

DEFAULT_TARGET = "source/blender/windowmanager/intern/wm_event_system.cc"

ANCHOR = """      eHandlerActionFlag action = WM_HANDLER_CONTINUE;

      /* Force handling drag if a key is pressed even if the drag threshold has not been met.
"""

NEW = """      eHandlerActionFlag action = WM_HANDLER_CONTINUE;

#if defined(__APPLE__)
      /* MARK@: window-level probe, see .github/scripts/patch_ios_qprobe.py */
      if (ELEM(event->type, MIDDLEMOUSE, MOUSEPAN)) {
        fprintf(stdout,
                "[MARK@] win %s val=%d xy=(%d,%d) modal=%d\\n",
                (event->type == MIDDLEMOUSE) ? "MMB" : "PAN",
                int(event->val),
                event->xy[0],
                event->xy[1],
                BLI_listbase_is_empty(&win.runtime->modalhandlers) ? 0 : 1);
        fflush(stdout);
      }
#endif

      /* Force handling drag if a key is pressed even if the drag threshold has not been met.
""".replace("MARK@", MARK)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {target}")
        return 0

    hits = text.count(ANCHOR)
    if hits != 1:
        print(f"::error::anchor not unique ({hits} hits)")
        return 1

    target.write_text(text.replace(ANCHOR, NEW, 1), encoding="utf-8")
    print(f"  patched  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
