#!/usr/bin/env python3
"""Make ``WM_operatortype_find()`` reliable on iOS.

Evidence chain (v19 device log)
------------------------------
1. Upstream ``source/blender/editors/space_view3d/view3d_gizmo_navigate.cc``
   already documents the bug in a comment:

       IOS_FIXME: This sometimes returns NULL on iOS, stepping into the function
       in the debugger fixes it. Possible race condition somewhere?

2. The v19 log shows the *consequence* of those NULLs, not a crash:

       Error: dropbox with unknown operator: WM_OT_drop_blend_file
       UILayout.operator_menu_hold(): unknown operator 'wm.tool_set_by_id'
       ERROR Python script error in VIEW3D_PT_tools_active.draw

3. And crucially, the key-maps never fill up:

       [IOSKM] WM_keyconfig_init py_init=1 flag=0 items=0
       [IOSKM] bootstrap py_init=1 flag=1 items=12      <- block DID run

   ``flag=1`` proves the populate block executed, so the problem is not the
   trigger. ``bpy.utils.keyconfig_init()`` re-executes
   ``presets/keyconfig/Blender.py``, which builds the key-maps with
   ``km.keymap_items.new("view3d.rotate", ...)``.  Each of those calls resolves
   the operator by name, so a NULL from ``WM_operatortype_find()`` silently
   drops the item instead of raising -- no traceback, no error, just 12 items
   left (all in a modal map registered from C).

   Reference: the same version locally ends at 278 key-maps / 3182 items.

Fix
---
``get_operators_map()`` is a lazily built ``CustomIDVectorSet``; the hashed
lookup is the part that returns NULL.  Keep the hash as the fast path and fall
back to a linear scan of ``WM_operatortypes_registered_get()`` on a miss.  It is
the same data, cannot disagree with itself, and only runs when the hash misses.

Idempotent: guarded by the ``IOS-OPFIND`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-OPFIND"

DEFAULT_TARGET = "source/blender/windowmanager/intern/wm_operator_type.cc"

INCLUDE_OLD = '#include "MEM_guardedalloc.h"\n'
INCLUDE_NEW = '#include "MEM_guardedalloc.h"\n\n#include <cstdio>\n#include <cstring>\n'

ANCHOR = """wmOperatorType *WM_operatortype_find(const char *idname, bool quiet)
{
  if (idname[0]) {
    /* Needed to support python style names without the `_OT_` syntax. */
    char idname_bl[OP_MAX_TYPENAME];
    WM_operator_bl_idname(idname_bl, idname);

    if (wmOperatorType *const *ot = get_operators_map().lookup_key_ptr_as(StringRef(idname_bl))) {
      return *ot;
    }

    if (!quiet) {
      CLOG_INFO(WM_LOG_OPERATORS, "Search for unknown operator '%s', '%s'", idname_bl, idname);
    }
  }
"""

NEW = """/* -------------------------------------------------------------------------
 * @MARK@
 *
 * Upstream documents that `WM_operatortype_find()` "sometimes returns NULL on
 * iOS, stepping into the function in the debugger fixes it" (see the IOS_FIXME
 * in view3d_gizmo_navigate.cc).  A NULL here never crashes, it silently
 * disables every feature that resolves an operator by name: key-maps cannot be
 * filled (each `keymap_items.new()` is dropped), drop-boxes are skipped, the
 * tool system loses `wm.tool_set_by_id`.
 *
 * The hashed lookup is the part that misbehaves, so on a miss fall back to a
 * linear scan of the registered operator span.
 * ------------------------------------------------------------------------- */

static int ios_opfind_rescued = 0;
static bool ios_opfind_first = true;

static wmOperatorType *ios_operatortype_find_linear(const char *idname_bl, const char *idname)
{
  for (wmOperatorType *op : WM_operatortypes_registered_get()) {
    if (op->idname == nullptr) {
      continue;
    }
    if (strcmp(op->idname, idname_bl) == 0 || strcmp(op->idname, idname) == 0) {
      return op;
    }
  }
  return nullptr;
}

wmOperatorType *WM_operatortype_find(const char *idname, bool quiet)
{
  if (idname[0]) {
    /* Needed to support python style names without the `_OT_` syntax. */
    char idname_bl[OP_MAX_TYPENAME];
    WM_operator_bl_idname(idname_bl, idname);

    if (wmOperatorType *const *ot = get_operators_map().lookup_key_ptr_as(StringRef(idname_bl))) {
      return *ot;
    }

    if (ios_opfind_first) {
      ios_opfind_first = false;
      printf("[IOSOP] first lookup '%s' registered=%d\\n",
             idname_bl,
             int(WM_operatortypes_registered_get().size()));
      fflush(stdout);
    }

    if (wmOperatorType *ot_linear = ios_operatortype_find_linear(idname_bl, idname)) {
      ios_opfind_rescued++;
      if (ios_opfind_rescued <= 15 || (ios_opfind_rescued % 250) == 0) {
        printf("[IOSOP] rescued '%s' (total=%d registered=%d)\\n",
               ot_linear->idname,
               ios_opfind_rescued,
               int(WM_operatortypes_registered_get().size()));
        fflush(stdout);
      }
      return ot_linear;
    }

    if (!quiet) {
      CLOG_INFO(WM_LOG_OPERATORS, "Search for unknown operator '%s', '%s'", idname_bl, idname);
    }
  }
""".replace("@MARK@", MARK)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {target}")
        return 0

    for old, new, label in (
        (INCLUDE_OLD, INCLUDE_NEW, "includes"),
        (ANCHOR, NEW, "linear fallback"),
    ):
        hits = text.count(old)
        if hits != 1:
            print(f"::error::anchor not unique ({hits} hits): {label}")
            return 1
        text = text.replace(old, new, 1)
        print(f"  patched  {label}")

    target.write_text(text, encoding="utf-8")
    print(f"  wrote    {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
