#!/usr/bin/env python3
"""Make a left-button drag orbit the 3D view.

An iPad has no middle mouse button, and `view3d.rotate` is bound to
`MIDDLEMOUSE` / `TRACKPADPAN` (== `MOUSEPAN`) only - a left drag in the viewport
is `transform.translate`, i.e. "move the object under the cursor", which looks
like "the viewport does nothing" when the cursor is over empty space.

This adds, as the FIRST item of the "3D View" key-map:

    ("view3d.rotate", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'}, None)

First position matters: `_template_items_transform_actions()` also binds
`transform.translate` to `LEFTMOUSE` + `CLICK_DRAG`, and the first matching
item wins.  A *click* is untouched, so selection still works.

This is a data patch of a shipped python preset - no recompile involved.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-NAV-DRAG"

OLD = """def km_view3d(params):
    items = []
"""
NEW = """def km_view3d(params):
    items = [
        # @MARK@: no middle mouse button on a tablet, so a left-button drag
        # orbits the view.  Deliberately the first item: the transform tweak
        # below uses LEFTMOUSE + CLICK_DRAG too and would win otherwise.
        ("view3d.rotate", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'}, None),
    ]
""".replace("@MARK@", MARK)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1
                  else "scripts/presets/keyconfig/keymap_data/blender_default.py")
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {target}")
        return 0

    if text.count(OLD) != 1:
        raise SystemExit(f"{target}: km_view3d anchor not unique ({text.count(OLD)})")

    text = text.replace(OLD, NEW, 1)
    target.write_text(text, encoding="utf-8")
    print(f"  patched  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
