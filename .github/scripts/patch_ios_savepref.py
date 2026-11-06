#!/usr/bin/env python3
"""Persist preferences when iOS backgrounds the app.

Blender has no "save preferences" button: it writes `userpref.blend` from
`WM_exit_ex`, i.e. only when the process terminates normally.  On iOS the
process is suspended and later killed without ever running that path, so every
setting made in a session - language, theme, add-on toggles, key-map edits -
was lost as soon as the user switched away and came back.

Wiring the write straight into the UIKit callback is not safe: Blender's window
manager runs on its own thread, and `BKE_blendfile_userdef_write_all` serialises
live DNA.  So:

* `GHOST_WindowIOS.mm` observes `UIApplicationDidEnterBackgroundNotification`
  and only raises a flag (`ios_wm_request_save`, C linkage because the GHOST
  side is Objective-C++).
* `wm_event_system.cc` checks that flag once per event-handler pass, on the
  thread that owns the data, and does the write there.

Idempotent: guarded by the ``IOS-SAVEPREF`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-SAVEPREF"

# ------------------------------------------------------------ window manager
WM_INCLUDE_ANCHOR = '#include "BKE_context.hh"'

WM_INCLUDE_NEW = """/* IOS-SAVEPREF: `BKE_blendfile_userdef_write_all` lives here. */
#include "BKE_blendfile.hh"
#include "BKE_context.hh\""""

WM_HANDLERS_ANCHOR = """void wm_event_do_handlers(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);"""

WM_HANDLERS_NEW = """/* IOS-SAVEPREF: raised from the UIKit background callback (GHOST_WindowIOS.mm),
 * consumed here.  A plain flag instead of a direct call because the write has to
 * happen on the window-manager thread, see the top of this file. */
static std::atomic<bool> ios_save_requested{false};

extern "C" void ios_wm_request_save(void)
{
  ios_save_requested.store(true);
}

void wm_event_do_handlers(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);

  if (ios_save_requested.exchange(false)) {
    BKE_blendfile_userdef_write_all(nullptr);
    fprintf(stderr, "[IOSSAVE] user preferences written\\n");
  }
  """

WM_ATOMIC_ANCHOR = "#include <cstdlib>"
WM_ATOMIC_NEW = """#include <atomic> /* IOS-SAVEPREF */
#include <cstdio> /* IOS-SAVEPREF */
#include <cstdlib>"""

# --------------------------------------------------------------------- GHOST
GHOST_METHOD = """/* IOS-SAVEPREF: ask the window-manager loop to write `userpref.blend`.
 *
 * Blender only saves on a normal exit and iOS never gives us one.  The actual
 * write cannot happen here - this runs on the UIKit thread, Blender's data is
 * owned by its own thread - so only a flag is raised. */
extern "C" void ios_wm_request_save(void);

- (void)iosSavePrefOnBackground
{
  ios_wm_request_save();
  fprintf(stdout, "[IOSSAVE] background: save requested\\n");
}

"""

GHOST_ANCHOR = """- (void)registerGestureRecognizers
{"""

GHOST_NEW = GHOST_METHOD + GHOST_ANCHOR + """
  [[NSNotificationCenter defaultCenter] addObserver:self
                                           selector:@selector(iosSavePrefOnBackground)
                                               name:UIApplicationDidEnterBackgroundNotification
                                             object:nil];
"""


def apply_once(text: str, rules: list[tuple[str, str, str]], name: str) -> str:
    for old, new, what in rules:
        if text.count(old) != 1:
            raise SystemExit(f"{name}: anchor not unique ({text.count(old)}): {what}")
        text = text.replace(old, new, 1)
    return text


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    win = root / "intern/ghost/intern/GHOST_WindowIOS.mm"
    wm = root / "source/blender/windowmanager/intern/wm_event_system.cc"
    for f in (win, wm):
        if not f.is_file():
            print(f"::error::missing file {f}")
            return 1

    wm_text = wm.read_text(encoding="utf-8")
    if MARK in wm_text:
        print(f"  already  {wm}")
    else:
        # <atomic> first, then the handler hook: the include anchor is checked
        # before anything else touches this file.
        wm_text = apply_once(
            wm_text,
            [
                (WM_ATOMIC_ANCHOR, WM_ATOMIC_NEW, "atomic include"),
                (WM_INCLUDE_ANCHOR, WM_INCLUDE_NEW, "blendfile include"),
                (WM_HANDLERS_ANCHOR, WM_HANDLERS_NEW, "save poll"),
            ],
            str(wm),
        )
        wm.write_text(wm_text, encoding="utf-8")
        print(f"  patched  {wm} (3 rules)")

    win_text = win.read_text(encoding="utf-8")
    if MARK in win_text:
        print(f"  already  {win}")
    else:
        win_text = apply_once(win_text, [(GHOST_ANCHOR, GHOST_NEW, "background hook")], str(win))
        win.write_text(win_text, encoding="utf-8")
        print(f"  patched  {win} (1 rule)")

    # Sanity: the inserted Objective-C method must be brace balanced.  (The
    # observer registration re-opens `registerGestureRecognizers`, so only the
    # method itself is checked.)
    block = GHOST_METHOD
    if block.count("{") != block.count("}"):
        raise SystemExit("GHOST block braces unbalanced: %d vs %d"
                         % (block.count("{"), block.count("}")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
