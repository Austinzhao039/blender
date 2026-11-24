#!/usr/bin/env python3
"""Make a gizmo handle draggable on iOS.

The symptom
-----------
Tap the Move tool in the left toolbar, the move gizmo appears in the viewport,
and the arrows do nothing.  Same for rotate and scale.

Why
---
`iosPointerUpdate:` (patch_ios_pointer.py) never presses the left mouse button.
It sends CURSOR_MOVE at touch-down, CURSOR_MOVE while moving, and only at
*release* does it emit LEFT_BUTTON_DOWN + LEFT_BUTTON_UP for a tap.  A drag past
14 px becomes MIDDLEMOUSE, i.e. `view3d.rotate`.  `handlePan:` is a no-op since
patch_ios_nav.py.

That is deliberate - a press at touch-down started `view3d.select` and turned
every one-finger drag into a box-select instead of orbiting the view.  But it
also makes gizmos impossible to drag: `wm_handlers_do_gizmo_handler` reaches
`GIZMOGROUP_OT_gizmo_tweak` from a **LEFTMOUSE press** and from nothing else, and
`gizmo_tweak_invoke` then needs a MOUSEMOVE stream to drive the transform.  No
press, no tweak.  It is not a subtle bug, it is an unreachable code path.

What this does
--------------
Keep the whole existing policy and add one branch: when the touch went down on a
gizmo handle, that touch becomes a LEFTMOUSE press/move/release.  Everywhere
else nothing changes - taps are still clicks, one-finger drags still orbit.

"Went down on a gizmo handle" is answered by Blender, not guessed here:
`wm_handlers_do_gizmo_handler` already hit-tests the cursor against the gizmo
maps on every MOUSEMOVE (that is what makes the handle highlight under the
mouse).  It now also publishes the result -

    ghost_ios_gizmo_hover  1 when a gizmo was under the cursor
    ghost_ios_hover_xy     where that hit-test happened

and the touch layer compares that position with the touch-down point, so a stale
value from the last hover cannot fire.

The press is emitted at `iosptr_start`, not at the current point: Blender found
the highlight at the touch-down position, and `gizmo_tweak_invoke` re-uses that
highlight instead of hit-testing again.  It is also why the decision is taken on
the *first* move rather than at touch-down - the CURSOR_MOVE sent at touch-down
is only processed by the main loop afterwards, so the flag is one event young.

Idempotent: guarded by the IOS-GZDRAG marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-GZDRAG"

WIN = "intern/ghost/intern/GHOST_WindowIOS.mm"
WMEV = "source/blender/windowmanager/intern/wm_event_system.cc"

# --- 1. GHOST: the two globals Blender writes and this file reads -----------
STATE_OLD = """/* IOS-PTR: state */
/* IOS-PTR: state of the tap driven by the view touch callbacks. */
static BOOL iosptr_down = NO;
static BOOL iosptr_moved = NO;
static BOOL iosptr_drag_active = NO;"""

STATE_NEW = """/* IOS-GZDRAG: hit-test hand-off from source/blender/windowmanager.
 *
 * `wm_handlers_do_gizmo_handler` writes these on every MOUSEMOVE, so the touch
 * layer can tell a touch that landed on a gizmo handle from one that landed on
 * empty space.  Defined here, not there: GHOST is linked before the window
 * manager, so the definition has to live on this side. */
extern "C" {
int ghost_ios_gizmo_hover = 0;
int ghost_ios_hover_xy[2] = {0, 0};
}

""" + STATE_OLD + """
/* IOS-GZDRAG: a LEFTMOUSE press went out from the touch layer and its release
 * has not been sent yet.  ONE per touch, never set for taps. */
static BOOL iosptr_left_active = NO;"""

# --- 2. reset on touch-down -------------------------------------------------
DOWN_OLD = """    iosptr_down = YES;
    iosptr_moved = NO;
    iosptr_drag_active = NO;
    iosptr_token = (uintptr_t)iosptr_touch;"""

DOWN_NEW = """    iosptr_down = YES;
    iosptr_moved = NO;
    iosptr_drag_active = NO;
    iosptr_left_active = NO;
    iosptr_token = (uintptr_t)iosptr_touch;"""

# --- 3. the decision, taken on the first move ------------------------------
FIRST_OLD = """  if (phase == 1) {
    iosptr_last = iosptr_p;"""

FIRST_NEW = """  if (phase == 1) {
    iosptr_last = iosptr_p;

    /* IOS-GZDRAG: was the finger put down on a gizmo handle?
     *
     * Decided once, on the first move, because the CURSOR_MOVE that went out at
     * touch-down is processed by Blender afterwards - reading the flag at
     * touch-down would read the previous frame's hover.
     *
     * A 30 px radius guards against a leftover hover from somewhere else on
     * screen: the gizmo handler simply does not run while the pointer is over a
     * panel, so its last value can be old. */
    if (!iosptr_moved && !iosptr_left_active && !iosptr_drag_active &&
        (ghost_ios_gizmo_hover != 0))
    {
      const CGFloat iosptr_gdx = CGFloat(ghost_ios_hover_xy[0]) - iosptr_start.x;
      const CGFloat iosptr_gdy = CGFloat(ghost_ios_hover_xy[1]) - iosptr_start.y;
      if (((iosptr_gdx * iosptr_gdx) + (iosptr_gdy * iosptr_gdy)) < 900.0f) {
        iosptr_left_active = YES;
        /* Also marks the gesture as "not a tap", which keeps the click on
         * release and the 14 px MIDDLEMOUSE drag out of the way. */
        iosptr_moved = YES;
        /* Press at the touch-down point: that is where Blender highlighted the
         * handle, and `gizmo_tweak_invoke` re-uses the highlight without
         * hit-testing again.  The following CURSOR_MOVE (this same batch has
         * not been flushed yet) then supplies the first delta. */
        UserInputEvent iosptr_press(&iosptr_start, nullptr, nullptr, false);
        iosptr_press.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
        iosptr_press.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
        [self generateUserInputEvents:iosptr_press];
        fprintf(stdout,
                "[IOSPTR] gizmo-press xy=%.0f,%.0f hover=%d,%d\\n",
                iosptr_start.x,
                iosptr_start.y,
                ghost_ios_hover_xy[0],
                ghost_ios_hover_xy[1]);
      }
    }"""

# --- 4. release -------------------------------------------------------------
UP_OLD = """  UserInputEvent iosptr_end(&iosptr_p, nullptr, nullptr, false);
  iosptr_end.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
  if (iosptr_drag_active) {"""

UP_NEW = """  UserInputEvent iosptr_end(&iosptr_p, nullptr, nullptr, false);
  iosptr_end.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
  if (iosptr_left_active) {
    /* IOS-GZDRAG: finish the gizmo drag started on the first move. */
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
    iosptr_left_active = NO;
    fprintf(stdout, "[IOSPTR] gizmo-release\\n");
  }
  else if (iosptr_drag_active) {"""

# --- 5. gesture abandoned (second finger, cancel) --------------------------
CANCEL_OLD = """    if (iosptr_drag_active) {
      /* Close the MIDDLEMOUSE drag cleanly before abandoning the gesture. */
      UserInputEvent iosptr_cancel(nullptr, nullptr, nullptr, false);
      iosptr_cancel.add_event(UserInputEvent::EventTypes::MIDDLE_BUTTON_UP);
      [self generateUserInputEvents:iosptr_cancel];
      iosptr_drag_active = NO;
    }"""

CANCEL_NEW = """    if (iosptr_left_active) {
      /* IOS-GZDRAG: drop the LEFTMOUSE press before the gesture is abandoned,
       * otherwise the gizmo modal keeps the pointer grabbed and the next touch
       * lands inside it.  A button event carries no coordinates, so `nullptr`
       * here is safe - same as the MIDDLEMOUSE case below. */
      UserInputEvent iosptr_gzcancel(nullptr, nullptr, nullptr, false);
      iosptr_gzcancel.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
      [self generateUserInputEvents:iosptr_gzcancel];
      iosptr_left_active = NO;
    }
    if (iosptr_drag_active) {
      /* Close the MIDDLEMOUSE drag cleanly before abandoning the gesture. */
      UserInputEvent iosptr_cancel(nullptr, nullptr, nullptr, false);
      iosptr_cancel.add_event(UserInputEvent::EventTypes::MIDDLE_BUTTON_UP);
      [self generateUserInputEvents:iosptr_cancel];
      iosptr_drag_active = NO;
    }"""

# --- 6. build tag -----------------------------------------------------------
TAG_OLD = '  iosdbg_slot(7, "V14 tapclick middrag dedupe350");'
TAG_NEW = '  iosdbg_slot(7, "V15 tapclick middrag gzdrag");'

# --- 7. WM: declare the globals -------------------------------------------
DECL_OLD = """#if defined(__APPLE__)
/* IOS-PROBE: implemented in GHOST_WindowIOS.mm, paints the on-screen read-out. */
extern "C" void iosdbg_slot(int idx, const char *text);
#endif"""

DECL_NEW = DECL_OLD + """

#if defined(__APPLE__)
/* IOS-GZDRAG: defined in GHOST_WindowIOS.mm, written by the gizmo handler
 * below.  The iOS touch layer reads it to decide whether a finger that went
 * down on a gizmo handle has to become a LEFTMOUSE press. */
extern "C" {
extern int ghost_ios_gizmo_hover;
extern int ghost_ios_hover_xy[2];
}
#endif"""

# --- 8. WM: publish the hit-test result ------------------------------------
PUB_OLD = """    wm_gizmomap_highlight_handled(gzmap);
  }"""

PUB_NEW = """    wm_gizmomap_highlight_handled(gzmap);

#if defined(__APPLE__)
    /* IOS-GZDRAG: hand the hit-test result to the iOS touch layer.  `gz` is the
     * gizmo that `wm_gizmomap_highlight_find` just found under the cursor, and
     * `event->xy` is where it found it - the same bottom-left-origin pixel
     * space the touch layer works in. */
    ghost_ios_gizmo_hover = (gz != nullptr) ? 1 : 0;
    if (gz != nullptr) {
      ghost_ios_hover_xy[0] = event->xy[0];
      ghost_ios_hover_xy[1] = event->xy[1];
    }
#endif
  }"""


def patch_file(path: Path, rules, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"::error::missing file {path}")
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {path}")
        return
    for old, new, what in rules:
        hits = text.count(old)
        if hits != 1:
            raise SystemExit(f"{path}: anchor not unique ({hits} hits): {what}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print(f"  patched  {path} ({len(rules)} rules, {label})")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    patch_file(
        root / WIN,
        [
            (STATE_OLD, STATE_NEW, "ghost globals"),
            (DOWN_OLD, DOWN_NEW, "touch-down reset"),
            (FIRST_OLD, FIRST_NEW, "first-move decision"),
            (UP_OLD, UP_NEW, "release"),
            (CANCEL_OLD, CANCEL_NEW, "abandon"),
            (TAG_OLD, TAG_NEW, "build tag"),
        ],
        "ghost",
    )
    patch_file(
        root / WMEV,
        [
            (DECL_OLD, DECL_NEW, "declarations"),
            (PUB_OLD, PUB_NEW, "publish"),
        ],
        "wm",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
