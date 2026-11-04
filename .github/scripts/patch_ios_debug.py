#!/usr/bin/env python3
"""Instrument the iOS build so the event path can be inspected from a log file.

Two edits:

1. `GHOST_SystemIOS.mm`: redirect stdout/stderr into `Documents/blender.log`.
   `UIFileSharingEnabled` is already on, so the file shows up in the Files app
   as "On My iPad / Blender / blender.log" -- no Mac needed to retrieve it.

2. `wm_event_system.cc`: log, for every mouse event, which area/region was hit
   and what the region handlers returned.  That single line tells apart the
   three possible causes of "viewport does not react but headers do":
     region=-1            -> region rect lookup failed (layout/rect problem)
     region=<n> action=1/4 -> region found, nothing handled it (keymap/workflow)
     region=<n> action=2   -> handled, so the problem is further downstream

Idempotent: every rule is anchored on a marker and skipped when already applied.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK_MAIN = "IOSDBG-LOG-START"
MARK_WM = "IOSDBG"
MARK_WM_INC = "IOSDBG-INCLUDE"

OLD_MAIN = """  @autoreleasepool {
    return UIApplicationMain(
        _argc, (char *_Nullable *)_argv, nil, NSStringFromClass([IOSAppDelegate class]));
  }"""

NEW_MAIN = """  @autoreleasepool {
    /* @MARK@: send stdout/stderr to Documents/blender.log.  UIFileSharingEnabled is
     * already set, so the file is reachable through the Files app on the device. */
    NSArray *iosdbg_paths = NSSearchPathForDirectoriesInDomains(
        NSDocumentDirectory, NSUserDomainMask, YES);
    if (iosdbg_paths.count > 0) {
      NSString *iosdbg_log = [iosdbg_paths[0] stringByAppendingPathComponent:@"blender.log"];
      const char *iosdbg_cpath = [iosdbg_log fileSystemRepresentation];
      if (freopen(iosdbg_cpath, "w", stdout) != nullptr) {
        setvbuf(stdout, nullptr, _IOLBF, 0);
      }
      if (freopen(iosdbg_cpath, "a", stderr) != nullptr) {
        setvbuf(stderr, nullptr, _IOLBF, 0);
      }
      fprintf(stderr, "[IOSDBG] === IOSDBG-LOG-START ===\\n");
    }
    return UIApplicationMain(
        _argc, (char *_Nullable *)_argv, nil, NSStringFromClass([IOSAppDelegate class]));
  }""".replace("@MARK@", MARK_MAIN)

OLD_WM = """  /* Case 2. */
  ARegion *region_hovered = ED_area_find_region_xy_visual(area, RGN_TYPE_ANY, event->xy);
  if (!region_hovered) {
    return WM_HANDLER_CONTINUE;
  }

  return wm_event_do_region_handlers(C, event, region_hovered);"""

NEW_WM = """  /* Case 2. */
  ARegion *region_hovered = ED_area_find_region_xy_visual(area, RGN_TYPE_ANY, event->xy);
  /* @MARK@: dump the area/region an event is routed to.  See patch_ios_debug.py. */
  const bool iosdbg_log = ELEM(event->type, MOUSEMOVE, LEFTMOUSE, RIGHTMOUSE, MOUSEPAN);
  if (iosdbg_log) {
    fprintf(stderr,
            "[IOSDBG] space=%d ev=%d val=%d xy=(%d,%d) area=(%d,%d)-(%d,%d) region=%d "
            "rect=(%d,%d)-(%d,%d)\\n",
            int(area->spacetype),
            int(event->type),
            int(event->val),
            event->xy[0],
            event->xy[1],
            area->totrct.xmin,
            area->totrct.ymin,
            area->totrct.xmax,
            area->totrct.ymax,
            region_hovered ? int(region_hovered->regiontype) : -1,
            region_hovered ? region_hovered->winrct.xmin : 0,
            region_hovered ? region_hovered->winrct.ymin : 0,
            region_hovered ? region_hovered->winrct.xmax : 0,
            region_hovered ? region_hovered->winrct.ymax : 0);
  }
  if (!region_hovered) {
    return WM_HANDLER_CONTINUE;
  }

  const eHandlerActionFlag iosdbg_action = wm_event_do_region_handlers(C, event, region_hovered);
  if (iosdbg_log) {
    fprintf(stderr, "[IOSDBG]   -> action=%d\\n", int(iosdbg_action));
  }
  return iosdbg_action;""".replace("@MARK@", MARK_WM)

OLD_UIKIT = "#import <UIKit/UIKit.h>"
NEW_UIKIT = "#import <UIKit/UIKit.h>\n\n#include <cstdio> /* @MARK@ */".replace("@MARK@", MARK_WM_INC)

OLD_WM_INC = "#include <cstdlib>"
NEW_WM_INC = "#include <cstdio> /* @MARK@ */\n#include <cstdlib>".replace("@MARK@", MARK_WM_INC)


def patch(path: Path, old: str, new: str, marker: str) -> str:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return "already"
    if text.count(old) != 1:
        raise SystemExit(f"{path}: anchor not unique ({text.count(old)} hits)")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return "patched"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_ios_debug.py <blender source root>")
        return 2
    root = Path(sys.argv[1])

    targets = [
        (root / "intern/ghost/intern/GHOST_SystemIOS.mm", OLD_UIKIT, NEW_UIKIT, MARK_WM_INC),
        (root / "intern/ghost/intern/GHOST_SystemIOS.mm", OLD_MAIN, NEW_MAIN, MARK_MAIN),
        (root / "source/blender/windowmanager/intern/wm_event_system.cc",
         OLD_WM, NEW_WM, MARK_WM),
        (root / "source/blender/windowmanager/intern/wm_event_system.cc",
         OLD_WM_INC, NEW_WM_INC, MARK_WM_INC),
    ]
    for path, old, new, marker in targets:
        if not path.exists():
            print(f"::error::missing {path}")
            return 1
        state = patch(path, old, new, marker)
        print(f"  {state:8s} {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
