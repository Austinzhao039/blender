#!/usr/bin/env python3
"""Put iOS touch coordinates into the same space as the window.

The bug
-------
`GHOST_SystemIOS::createWindow()` builds the window from
`[[UIScreen mainScreen] bounds]`, i.e. **points** (1194x834 on an 11" iPad), and that
value is what `GHOST_Window(size)` and therefore every `ARegion` rect uses.

But `GHOST_WindowIOS::scalePointToWindow()` multiplies the touch location by
`getWindowScaleFactor()` (= 2 on any Retina device) on top of the y-flip that the
flipped `MTKView` already applied.  So every pointer event lands at **twice** the real
coordinate:

    touch (490, 374) points  ->  event (980, 918) in a 1194x834 window

x is then correct only by accident in the left half, and y is outside the window for
anything below the middle of the screen.  Measured with the on-screen probe (v9):

    0 PRESS/TAP PRESS n=20 xy=(490,374) touch=1 type=3
    2 WM_MOVE WM LMB ev=1 v=2 xy=(980,918) area=1 rgn=0 act=0
    6 VIEW 1194x834 view=2.00 screen=2.00

(980, 918) = (490*2, (834-374)*2).  Region handlers return CONTINUE because the
coordinate is not inside the view, so clicks, drags and panel-resize grips all "do
nothing" while the buttons that happen to sit near a correct spot still work.

The fix is to stop scaling: the flipped view already hands out bottom-left-origin
points, which is exactly what GHOST expects.  `getScaledTranslation()` and
`getScaledDistance()` go through the same function, so drag deltas and pinch scaling
are corrected at the same time.

Idempotent: anchored on the `IOS-COORDS` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-COORDS"

OLD = """CGPoint GHOST_WindowIOS::scalePointToWindow(CGPoint &point)
{
  CGPoint scaled_point;
  scaled_point.x = point.x * getWindowScaleFactor();
  scaled_point.y = point.y * getWindowScaleFactor();
  return scaled_point;
}"""

NEW = """CGPoint GHOST_WindowIOS::scalePointToWindow(CGPoint &point)
{
  /* @MARK@: no scaling here.
   *
   * `createWindow()` sizes the window from `[UIScreen mainScreen].bounds` (points), and
   * every `ARegion` rect is in that same space.  The flipped MTKView already returns
   * bottom-left-origin points, which is exactly GHOST's convention -- multiplying by
   * `getWindowScaleFactor()` put every event at 2x, outside the window for anything below
   * the vertical middle, so region handlers ignored it and nothing responded.
   *
   * Pan translation and pinch distance are derived from this function as well, so they are
   * corrected by the same change. */
  return point;
}"""


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    path = root / "intern/ghost/intern/GHOST_WindowIOS.mm"
    if not path.exists():
        print(f"::error::missing {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {path.relative_to(root)}")
        return 0
    if text.count(OLD) != 1:
        raise SystemExit(f"{path}: anchor not unique ({text.count(OLD)} hits)")
    path.write_text(text.replace(OLD, NEW.replace("@MARK@", MARK)), encoding="utf-8")
    print(f"  patched  {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
