#!/usr/bin/env python3
"""Repair the key-configuration from C, at the first main-loop frame on iOS (v2).

What v19 proved
---------------
The v19 device log printed exactly three ``[IOSKM]`` lines:

    [IOSKM] WM_keyconfig_init py_init=0 flag=0 items=-1
    [IOSKM] WM_keyconfig_init py_init=1 flag=0 items=0
    [IOSKM] bootstrap py_init=1 flag=1 items=12

``flag=1`` at the first frame means the upstream populate block **did** run, so
the trigger was never the problem (the v18 Python guard was a dead end for a
different reason).  The block ran and still left 12 items -- the same number the
local build has immediately after ``WM_init()``, before
``bpy.utils.keyconfig_init()`` has had an effect.  The healthy total is
**3182 items / 278 key-maps**.

So ``bpy.utils.keyconfig_init()`` produced nothing on device.  It re-executes
``presets/keyconfig/Blender.py``, whose ``km.keymap_items.new(...)`` calls are
dropped silently when ``WM_operatortype_find()`` returns NULL -- which the
upstream ios branch documents as an iOS-specific bug.  ``patch_ios_opfind.py``
adds the linear fallback for that.  This patch keeps an honest, verbose record
so the next log says whether that was enough.

What this does
--------------
At the first ``WM_main_loop_body()`` frame (= after ``main_ios_callback()`` ran
``WM_init()``, so Python is up):

1. print the item count and the ``init_flag`` bit,
2. if the count is already healthy, do nothing,
3. otherwise print the operator-registry size and three probe lookups,
4. re-run the populate block (C key-maps + the Python preset load, with the
   preset path and any traceback printed),
5. print the resulting item count.

A second attempt happens if the first one still leaves the config empty, because
nothing was added in that case, so no items can be duplicated.

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
 * `WM_keyconfig_init()` does run on iOS but its result is empty, so the window
 * manager ends up with 106 key-maps holding 12 items in total: no select, no
 * orbit, no shortcuts.  See .github/scripts/patch_ios_keymap_c.py.
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
  printf("[IOSKM] bootstrap flag=%d items=%d\\n",
         int((wm->init_flag & WM_INIT_FLAG_KEYCONFIG) != 0),
         ios_keyconfig_item_count(kc));
  fflush(stdout);

  /* A healthy configuration has ~3182 items; an empty one has 12. */
  if (ios_keyconfig_item_count(kc) >= 100) {
    return;
  }

  printf("[IOSOP] registered=%d tool_set=%d rotate=%d dropblend=%d\\n",
         int(WM_operatortypes_registered_get().size()),
         int(WM_operatortype_find("WM_OT_tool_set_by_id", true) != nullptr),
         int(WM_operatortype_find("VIEW3D_OT_rotate", true) != nullptr),
         int(WM_operatortype_find("WM_OT_drop_blend_file", true) != nullptr));
  fflush(stdout);

  if (kc != nullptr && !(kc->flag & KEYCONF_INIT_DEFAULT)) {
    wm_window_keymap(kc);
    ED_spacetypes_keymap(kc);
    kc->flag |= KEYCONF_INIT_DEFAULT;
  }

#ifdef WITH_PYTHON
  {
    const char *imports[] = {"bpy", nullptr};
    const bool ok = BPY_run_string_exec(
        C,
        imports,
        "import bpy, traceback\\n"
        "try:\\n"
        "    _p = bpy.utils.preset_find('Blender', 'keyconfig')\\n"
        "    print('[IOSPY] preset=%r' % (_p,))\\n"
        "except Exception:\\n"
        "    print('[IOSPY] preset_find raised')\\n"
        "    traceback.print_exc()\\n"
        "try:\\n"
        "    bpy.utils.keyconfig_init()\\n"
        "except Exception:\\n"
        "    print('[IOSPY] keyconfig_init raised')\\n"
        "    traceback.print_exc()\\n"
        "kc = bpy.context.window_manager.keyconfigs.active\\n"
        "print('[IOSPY] after kc=%r kms=%d' % (getattr(kc, 'name', None), len(kc.keymaps) if kc else -1))\\n"
        "km = kc.keymaps.get('3D View') if kc else None\\n"
        "print('[IOSPY] 3DView items=%d' % (len(km.keymap_items) if km else -1))\\n");
    printf("[IOSKM] python keyconfig_init ok=%d\\n", int(ok));
    fflush(stdout);
  }
#endif

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
  /* @MARK@ -- two attempts, see the block above #WM_keyconfig_init. */
  static int ios_keyconfig_tries = 0;
  if (ios_keyconfig_tries < 2) {
    ios_keyconfig_bootstrap(C);
    ios_keyconfig_tries++;
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
