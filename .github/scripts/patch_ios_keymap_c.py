#!/usr/bin/env python3
"""Repair the key-configuration from C, at the first main-loop frame on iOS (v3).

What the device told us, and what it could not
----------------------------------------------
v19/v20 proved the populate block **does** run (``flag=1``) and still leaves 12
items out of 3182, and that the hash-based operator registry is fine
(``patch_ios_opfind.py``'s linear fallback rescued nothing).  What it could not
say is *why*, because every Python diagnostic was lost: v20 emitted four
``[IOSPY]`` lines through ``print()`` and the log contained **zero** of them.
Python's stdout is buffered and nothing flushes it before iOS kills the app.
Only C's ``printf`` survives.

So v3 has two jobs: instrument with ``os.write`` (fd 1, unbuffered, reaches the
device log), and repair what the log has already hinted at:

    [IOSOP] registered=2171 tool_set=0 rotate=1 dropblend=0
    UILayout.operator_menu_hold(): unknown operator 'wm.tool_set_by_id'
    Error: dropbox with unknown operator: WM_OT_drop_blend_file
    UILayout.operator(): 'EXTENSIONS_OT_userpref_show_online' unknown operator

``wm.tool_set_by_id`` / ``wm.drop_blend_file`` are Python operators from
``scripts/startup/bl_operators/wm.py``; ``extensions.userpref_show_online``
belongs to the ``bl_pkg`` core add-on.  Both the ``startup`` package and the
core add-ons are registered by ``bpy.utils.load_scripts()`` /
``load_scripts_extensions()``, which ``WM_init()`` calls -- so on iOS something
in that chain did not happen.  This patch re-registers ``bl_operators`` class by
class (one bad class no longer kills the rest) and enables ``bl_pkg``, then
reloads the preset.

Note the preset itself is *not* all-or-nothing any more: ``patch_ios_kmio.py``
makes the loader skip an unusable item instead of discarding 3182 of them.  So
even if the repair below fails, the viewport key-map (``MIDDLEMOUSE`` ->
``view3d.rotate``) comes back; the ``[IOSPY]`` lines then say why the other 12
items are still missing.

What it prints
--------------
    [IOSKM] bootstrap flag=1 items=12
    [IOSOP] registered=2171 tool_set=0 rotate=1 dropblend=0
    [IOSPY] mods bl_operators=0 bl_ui=1 bl_pkg=0
    [IOSPY] paths=[...]
    [IOSPY] ops_wm=116 tool_set=0 drop_blend=0 ext_online=0
    [IOSPY] bl_operators classes ok=… fail=…
    [IOSPY] tool_set now=1
    [IOSKM] bootstrapped items=3182

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

#ifdef WITH_PYTHON
/* Re-register the Python "startup" modules the key-map preset depends on and
 * report everything through fd 1, because `print()` never reaches the log. */
static void ios_startup_modules_repair(bContext *C)
{
  const char *imports[] = {"bpy", nullptr};
  /* Raw string: keeps the Python readable and free of C escapes. */
  static const char *py =
      R"PY(
import bpy, os, sys, traceback

NL = chr(10)

def _w(m):
    try:
        os.write(1, (m + NL).encode("utf-8", "replace"))
    except Exception:
        pass

def _has(mod_name, op_name):
    try:
        return op_name in dir(getattr(bpy.ops, mod_name))
    except Exception:
        return False

_w("[IOSPY] mods bl_operators=%d bl_ui=%d bl_pkg=%d" % (
    "bl_operators" in sys.modules,
    "bl_ui" in sys.modules,
    "bl_pkg" in sys.modules))
try:
    _w("[IOSPY] paths=%r" % (bpy.utils.script_paths(),))
except BaseException:
    _w("[IOSPY] script_paths FAILED")
    _w(traceback.format_exc())
_w("[IOSPY] ops_wm=%d tool_set=%d drop_blend=%d ext_online=%d" % (
    len(dir(bpy.ops.wm)),
    _has("wm", "tool_set_by_id"),
    _has("wm", "drop_blend_file"),
    _has("extensions", "userpref_show_online")))

if not _has("wm", "tool_set_by_id"):
    try:
        import bl_operators as _bo
    except BaseException:
        _w("[IOSPY] import bl_operators FAILED")
        _w(traceback.format_exc())
    else:
        _ok = 0
        _fail = 0
        from bpy.utils import register_class
        for _mod in getattr(_bo, "_modules_loaded", ()):
            for _cls in getattr(_mod, "classes", ()):
                try:
                    register_class(_cls)
                    _ok += 1
                except BaseException:
                    _fail += 1
        _w("[IOSPY] bl_operators classes ok=%d fail=%d" % (_ok, _fail))
    _w("[IOSPY] tool_set now=%d" % _has("wm", "tool_set_by_id"))

if not _has("extensions", "userpref_show_online"):
    try:
        import addon_utils as _au
        _au.enable("bl_pkg")
        _w("[IOSPY] bl_pkg enabled")
    except BaseException:
        _w("[IOSPY] bl_pkg enable FAILED")
        _w(traceback.format_exc())

try:
    bpy.utils.keyconfig_init()
except BaseException:
    _w("[IOSPY] keyconfig_init FAILED")
    _w(traceback.format_exc())
)PY";
  const bool ok = BPY_run_string_exec(C, imports, py);
  printf("[IOSKM] python repair ok=%d\\n", int(ok));
  fflush(stdout);
}
#endif

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

  /* Diagnose + repair exactly once; the two main-loop attempts must not
   * register the same classes twice. */
  static bool ios_repaired = false;
  if (!ios_repaired) {
    ios_repaired = true;
#ifdef WITH_PYTHON
    printf("[IOSOP] registered=%d tool_set=%d rotate=%d dropblend=%d\\n",
           int(WM_operatortypes_registered_get().size()),
           int(WM_operatortype_find("WM_OT_tool_set_by_id", true) != nullptr),
           int(WM_operatortype_find("VIEW3D_OT_rotate", true) != nullptr),
           int(WM_operatortype_find("WM_OT_drop_blend_file", true) != nullptr));
    fflush(stdout);
    ios_startup_modules_repair(C);
#endif
  }

  /* A healthy configuration has ~3182 items; an empty one has 12. */
  if (ios_keyconfig_item_count(kc) >= 100) {
    printf("[IOSKM] keymap healthy, nothing to do\\n");
    fflush(stdout);
    return;
  }

  if (kc != nullptr && !(kc->flag & KEYCONF_INIT_DEFAULT)) {
    wm_window_keymap(kc);
    ED_spacetypes_keymap(kc);
    kc->flag |= KEYCONF_INIT_DEFAULT;
  }

#ifdef WITH_PYTHON
  {
    const char *imports[] = {"bpy", nullptr};
    const bool ok = BPY_run_string_exec(C, imports, "import bpy\\nbpy.utils.keyconfig_init()\\n");
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
