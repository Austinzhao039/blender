#!/usr/bin/env python3
"""Repair the key-configuration from C, at the first main-loop frame on iOS.

Why not Python
--------------
v18 shipped a Python timer guard in ``scripts/startup/bl_ui/__init__.py`` that
called ``bpy.utils.keyconfig_init()``.  The v18 device log contains **zero**
``[IOSKM]`` lines, so that guard never executed: either ``bl_ui`` is not
imported on iOS, or timers do not tick before the first draw.  Whatever the
reason, the Python hook is not a dependable place to bootstrap state.

Diagnosis (measured, not guessed)
---------------------------------
``WM_keyconfig_init()`` only populates key-maps inside

    if (CTX_py_init_get(C) && (wm->init_flag & WM_INIT_FLAG_KEYCONFIG) == 0)

``WM_INIT_FLAG_KEYCONFIG`` is written in exactly one place (this very block), so
seeing ``Window`` / ``Screen`` / ``3D View`` all empty in the device log proves
the block never ran at all -- not that it ran and produced nothing.

Reference table (local Blender 5.1.2, ``--factory-startup``):

    state                    n_keymaps  total  Window  Screen  ScreenEdit  View3D
    populate block skipped         106     12       0       0           0       0
    after keyconfig_init()         278   3182      33      26          13     115

Fix
---
At the first ``WM_main_loop_body()`` frame -- which is guaranteed to run after
``main_ios_callback()`` finished ``WM_init()`` -- re-attempt the block that was
skipped, then rebuild the handlers.  Guarded by the same ``init_flag`` bit, so
it is a no-op (no duplicated items) once the configuration is in place.

Prints ``[IOSKM]`` lines in both directions so the next device log answers the
question without another guess.

Idempotent: guarded by the ``IOS-KEYMAP-BOOTSTRAP`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-KEYMAP-BOOTSTRAP"

DEFAULT_TARGET = "source/blender/windowmanager/intern/wm.cc"

INCLUDE_OLD = "#include <cstring>\n"
INCLUDE_NEW = "#include <cstring>\n#include <cstdio>\n"

ANCHOR_INIT = "void WM_keyconfig_init(bContext *C)\n{\n  wmWindowManager *wm = CTX_wm_manager(C);\n"

ANCHOR_INIT_NEW = '''/* -------------------------------------------------------------------------
 * @MARK@ -- iOS key-map bootstrap.
 *
 * The iOS port creates its window before Python is up, so `WM_keyconfig_init()`
 * never enters its populate block and nothing re-runs it afterwards.  Every
 * key-map then holds zero items and the viewport ignores all input.
 * ------------------------------------------------------------------------- */

static int ios_keyconfig_item_count(wmKeyConfig *kc)
{
  if (kc == nullptr) {
    return -1;
  }
  int total = 0;
  for (wmKeyMap *km = static_cast<wmKeyMap *>(kc->keymaps.first); km != nullptr;
       km = km->next)
  {
    total += BLI_listbase_count(&km->items);
  }
  return total;
}

static void ios_keyconfig_bootstrap(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr || wm->runtime == nullptr) {
    return;
  }
  if (!CTX_py_init_get(C)) {
    /* Python is not up yet; try again on the next frame. */
    return;
  }

  wmKeyConfig *kc = wm->runtime->defaultconf;
  const int already = (wm->init_flag & WM_INIT_FLAG_KEYCONFIG) != 0;
  printf("[IOSKM] bootstrap py_init=1 flag=%d items=%d\\n",
         already ? 1 : 0,
         ios_keyconfig_item_count(kc));
  fflush(stdout);

  if (already) {
    return;
  }

  if (kc != nullptr && !(kc->flag & KEYCONF_INIT_DEFAULT)) {
    wm_window_keymap(kc);
    ED_spacetypes_keymap(kc);
    WM_keyconfig_reload(C);
    kc->flag |= KEYCONF_INIT_DEFAULT;
  }
  if (!G.background) {
    WM_keyconfig_update_tag(nullptr, nullptr);
  }
  wm->init_flag |= WM_INIT_FLAG_KEYCONFIG;

  WM_keyconfig_update(wm);

  printf("[IOSKM] bootstrapped items=%d\\n", ios_keyconfig_item_count(kc));
  fflush(stdout);
}

void WM_keyconfig_init(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);

  printf("[IOSKM] WM_keyconfig_init py_init=%d flag=%d items=%d\\n",
         int(CTX_py_init_get(C)),
         int((wm->init_flag & WM_INIT_FLAG_KEYCONFIG) != 0),
         ios_keyconfig_item_count(wm->runtime ? wm->runtime->defaultconf : nullptr));
  fflush(stdout);
'''.replace("@MARK@", MARK)

ANCHOR_LOOP = """void WM_main_loop_body(bContext *C)
{
  /* Get events from ghost, handle window events, add to window queues. */
  wm_window_events_process(C);
"""

ANCHOR_LOOP_NEW = """void WM_main_loop_body(bContext *C)
{
  /* @MARK@ -- one-shot, see the block above #WM_keyconfig_init. */
  static bool ios_keyconfig_done = false;
  if (!ios_keyconfig_done) {
    ios_keyconfig_bootstrap(C);
    ios_keyconfig_done = CTX_py_init_get(C);
  }

  /* Get events from ghost, handle window events, add to window queues. */
  wm_window_events_process(C);
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
        (INCLUDE_OLD, INCLUDE_NEW, "include <cstdio>"),
        (ANCHOR_INIT, ANCHOR_INIT_NEW, "bootstrap helpers"),
        (ANCHOR_LOOP, ANCHOR_LOOP_NEW, "main-loop hook"),
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
