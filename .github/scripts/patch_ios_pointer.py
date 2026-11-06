#!/usr/bin/env python3
"""One clean click per single finger, and get out of the way of drags.

Why drags are not done here
---------------------------
`LEFTMOUSE CLICK_DRAG` cannot work in this port, no matter what the key map
says: `wm_handlers_do()` only arms `event_queue_check_drag` for a press that was
*not* handled, and `view3d.select` handles every press in the viewport, so the
drag branch at the top of that function is unreachable.  v11 inserted
`("view3d.rotate", LEFTMOUSE + CLICK_DRAG)` at the head of `km_view3d` and it
could never have fired.

Drags therefore go through `handlePan:` instead, which sends MIDDLEMOUSE (see
`patch_ios_nav.py`).  That is the binding `view3d.rotate` (`MIDDLEMOUSE`,
`PRESS`) and `view2d.pan` listen to, so one finger rotates the viewport and pans
2D editors and panels.  v12 blocked exactly that with `if (iosptr_down) return;`
in `handlePan:` - `iosptr_down` is set on every touch-down, so the pan
recogniser never ran and nothing on the device could be dragged.

What is left here is the tap:

  down                   -> CURSOR_MOVE only (hover / hit-testing)
  move                   -> CURSOR_MOVE (so gizmos, cursors and tooltips follow)
  up, moved < 14 px      -> CURSOR_MOVE + LEFT_BUTTON_DOWN + LEFT_BUTTON_UP
  up, moved >= 14 px     -> nothing, `handlePan:` already drove the drag

A press and its release at the same point is what Blender turns into a
#KM_CLICK, and that is what selection, buttons, menus and the top bar consume.

Duplicate clicks
----------------
`handleTap:` runs for the same touch and emits its own click.  The old guard was
an 80 ms window, which is shorter than the delay between `touchesEnded` and a
gesture action on a main thread that is busy rendering - so both clicks landed,
the first opened a menu and the second closed it again ("everything needs two
taps").  The guard is now 350 ms *and* position-based, and it counts what it
does so the on-screen read-out can prove whether a duplicate still happens.

Idempotent: guarded by the ``IOS-PTR`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-PTR"

# --- 1. state ---------------------------------------------------------------
STATE_ANCHOR = ("/* GHOSTUITapGesture interface for capturing taps. */\n"
                "@interface GHOSTUITapGestureRecognizer")

STATE_NEW = """/* IOS-PTR: state */
/* IOS-PTR: state of the tap driven by the view touch callbacks. */
static BOOL iosptr_down = NO;
static BOOL iosptr_moved = NO;
static CGPoint iosptr_start = {0.0f, 0.0f};
static CGPoint iosptr_last = {0.0f, 0.0f};
static uintptr_t iosptr_token = 0;
static int iosptr_active = 0;
static int iosptr_presses = 0;
static int iosptr_clicks = 0;
static int iosptr_gesture_clicks = 0;
static int iosptr_click_drops = 0;
static CGPoint iosptr_last_click_xy = {0.0f, 0.0f};
static double iosptr_last_click = 0.0;

/* IOS-PTR: painted by the on-screen read-out (patch_ios_probe.py). */
extern "C" void iosdbg_slot(int idx, const char *text);

/* IOS-PTR: one click per physical tap, from whichever source gets there first.
 *
 * `handleTap:` and the touch callbacks below both produce a click for the same
 * touch.  A time-only window failed: the gesture action is dispatched after
 * `touchesEnded`, and on a main thread that is also rendering Blender that can
 * take far longer than the 80 ms v12 allowed - so the second click survived,
 * opened a menu and closed it again.  350 ms plus "same spot" catches it without
 * swallowing two deliberate taps. */
static BOOL iosptr_click_allowed(CGPoint iosptr_p, BOOL iosptr_from_gesture)
{
  const double iosptr_now = [NSDate timeIntervalSinceReferenceDate];
  const CGFloat iosptr_dx = iosptr_p.x - iosptr_last_click_xy.x;
  const CGFloat iosptr_dy = iosptr_p.y - iosptr_last_click_xy.y;
  if (((iosptr_now - iosptr_last_click) < 0.35) &&
      ((iosptr_dx * iosptr_dx) + (iosptr_dy * iosptr_dy)) < 144.0f)
  {
    iosptr_click_drops++;
    return NO;
  }
  iosptr_last_click = iosptr_now;
  iosptr_last_click_xy = iosptr_p;
  if (iosptr_from_gesture) {
    iosptr_gesture_clicks++;
  }
  else {
    iosptr_clicks++;
  }
  return YES;
}

/* IOS-PTR: keep the counters on screen, they are how a duplicate is spotted. */
static void iosptr_report_clicks(void)
{
  char iosptr_buf[192];
  snprintf(iosptr_buf,
           sizeof(iosptr_buf),
           "CLK touch=%d gest=%d drop=%d",
           iosptr_clicks,
           iosptr_gesture_clicks,
           iosptr_click_drops);
  iosdbg_slot(5, iosptr_buf);
}

""" + STATE_ANCHOR

# --- 2. touch callbacks -----------------------------------------------------
TOUCH_CALLS = [
    ("""/* Override touch methods to capture the UITouch object. */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesBegan:touches withEvent:event];""",
     """/* Override touch methods to capture the UITouch object. */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesBegan:touches withEvent:event];
  [self iosPointerUpdate:touches phase:0]; /* IOS-PTR */""",
     "touchesBegan"),
    ("""/* Get updated tablet data. */
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesMoved:touches withEvent:event];""",
     """/* Get updated tablet data. */
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesMoved:touches withEvent:event];
  [self iosPointerUpdate:touches phase:1]; /* IOS-PTR */""",
     "touchesMoved"),
    ("""/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];""",
     """/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];
  [self iosPointerUpdate:touches phase:2]; /* IOS-PTR */""",
     "touchesEnded"),
    ("""/* Reset tablet data. */
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];""",
     """/* Reset tablet data. */
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];
  [self iosPointerUpdate:touches phase:3]; /* IOS-PTR */""",
     "touchesCancelled"),
]

# --- 3. the tap -------------------------------------------------------------
METHOD_ANCHOR = """- (void)handleTap:(GHOSTUITapGestureRecognizer *)sender
{"""

METHOD_NEW = """/* IOS-PTR: tap = click, drag = `handlePan:` (MIDDLEMOUSE).
 *
 * phase: 0 = began, 1 = moved, 2 = ended, 3 = cancelled.
 *
 * No LEFTMOUSE is emitted while the finger moves.  In this port a left-drag has
 * nowhere to go (see the module docstring: `event_queue_check_drag` is never
 * armed), and pressing at touch-down used to start `view3d.select` on every tap.

 * The pan recogniser owns the drag: it fires after ~10 px and sends a
 * MIDDLEMOUSE drag, which rotates the viewport and pans 2D views. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase
{
  const int iosptr_n = int(touches.count);
  if (phase == 0) {
    iosptr_active += iosptr_n;
  }
  else if (phase >= 2) {
    iosptr_active -= iosptr_n;
    if (iosptr_active < 0) {
      iosptr_active = 0;
    }
  }

  if ((iosptr_n != 1) || ((phase == 0) && (iosptr_active > 1))) {
    /* Not a single-finger gesture: two fingers scroll and zoom through the
     * recognisers.  `touches` only holds the touches that CHANGED, so the
     * second finger arrives as a set of one and looks exactly like a new press
     * - `iosptr_active` is what tells the two apart, otherwise a scroll fired a
     * stray click when those fingers lifted. */
    if (iosptr_down) {
      iosptr_down = NO;
      iosptr_token = 0;
      iosptr_moved = NO;
    }
    return;
  }

  UITouch *iosptr_touch = [touches anyObject];
  if (iosptr_touch.type == UITouchTypePencil) {
    /* The pencil keeps the recognised tap path, it also needs the tablet data. */
    return;
  }

  CGPoint iosptr_p = [iosptr_touch locationInView:window->getView()];
  iosptr_p = window->scalePointToWindow(iosptr_p);

  if (phase == 0) {
    if (iosptr_down && ((uintptr_t)iosptr_touch == iosptr_token)) {
      /* The same press delivered twice, nothing to do. */
      return;
    }
    iosptr_down = YES;
    iosptr_moved = NO;
    iosptr_token = (uintptr_t)iosptr_touch;
    iosptr_start = iosptr_p;
    iosptr_last = iosptr_p;
    iosptr_presses++;

    /* Hover only: Blender takes the hit-test position from this and nothing
     * must be pressed yet - press or click is decided on release. */
    UserInputEvent iosptr_event(&iosptr_p, nullptr, nullptr, false);
    iosptr_event.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosptr_event];
    fprintf(stdout, "[IOSPTR] down n=%d type=%d\\n", iosptr_presses, int(iosptr_touch.type));
    return;
  }

  if (!iosptr_down || ((uintptr_t)iosptr_touch != iosptr_token)) {
    /* Not the touch that started this gesture. */
    return;
  }

  if (phase == 1) {
    iosptr_last = iosptr_p;

    UserInputEvent iosptr_move(&iosptr_p, nullptr, nullptr, false);
    iosptr_move.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosptr_move];

    {
      const CGFloat iosptr_dx = iosptr_p.x - iosptr_start.x;
      const CGFloat iosptr_dy = iosptr_p.y - iosptr_start.y;
      if (!iosptr_moved &&
          ((iosptr_dx * iosptr_dx) + (iosptr_dy * iosptr_dy)) > 196.0f)
      {
        /* 14 px: past a tap, `handlePan:` already turned this into a drag. */
        iosptr_moved = YES;
      }
    }
    return;
  }

  /* ended / cancelled */
  iosptr_down = NO;
  iosptr_token = 0;

  UserInputEvent iosptr_end(&iosptr_p, nullptr, nullptr, false);
  iosptr_end.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
  if ((phase == 2) && !iosptr_moved && iosptr_click_allowed(iosptr_p, NO)) {
    /* One press and one release at the same point: Blender turns that into a
     * #KM_CLICK, exactly like a mouse click. */
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
  }
  [self generateUserInputEvents:iosptr_end];
  fprintf(stdout, "[IOSPTR] up moved=%d\\n", int(iosptr_moved));

  if (!iosptr_moved) {
    /* Trailing hover after the click: Blender re-runs hit-testing on the next
     * move, and without it the button under the finger stays "cold" until a
     * second tap - the "top bar needs two taps" symptom. */
    UserInputEvent iosptr_hover(&iosptr_p, nullptr, nullptr, false);
    iosptr_hover.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosptr_hover];
  }
  iosptr_report_clicks();
  iosptr_moved = NO;
}

""" + METHOD_ANCHOR

# --- 4. interface declaration ----------------------------------------------
IFACE_ANCHOR = """/* On screen keyboard handling */
- (UITextField *)getUITextField;"""
IFACE_NEW = """/* IOS-PTR: tap driver, see the implementation for why. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase;

""" + IFACE_ANCHOR

# --- 5. touch delays --------------------------------------------------------
DELAYS = [
    ("tap2f_gesture_recognizer", "two fingers"),
    ("tap3f_gesture_recognizer", "three fingers"),
    ("tap4f_gesture_recognizer", "four fingers"),
]

# --- 6. the recogniser keeps every touch type ------------------------------
TAP_TYPES_OLD = """  tap_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];"""
TAP_TYPES_NEW = """  /* IOS-PTR: keep every touch type here.
   *
   * v11 narrowed this to the pencil, assuming `iosPointerUpdate:phase:` always
   * runs.  If UIKit ever stops delivering the window's touch callbacks the app
   * then has no click source at all, which is worse than the duplicate it
   * removed.  The duplicate is dropped by `iosptr_click_allowed()` instead, and
   * that guard works regardless of which of the two sources is reachable. */
  tap_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];"""

# --- 7. the same guard inside handleTap ------------------------------------
TAP_CLICK_OLD = """  /* Send events to indicate a 'click' on event end. */
  if (sender.state == UIGestureRecognizerStateEnded) {"""
TAP_CLICK_NEW = """  /* Send events to indicate a 'click' on event end. */
  /* IOS-PTR: `iosptr_click_allowed()` drops this click when the touch callbacks
   * already delivered one for the same tap. */
  if ((sender.state == UIGestureRecognizerStateEnded) &&
      iosptr_click_allowed(touch_point, YES))
  {"""


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1
                  else "intern/ghost/intern/GHOST_WindowIOS.mm")
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if "/* IOS-PTR: state of the tap" in text:
        print(f"  already  {target}")
        return 0

    rules = [
        (STATE_ANCHOR, STATE_NEW, "pointer state"),
        (IFACE_ANCHOR, IFACE_NEW, "interface"),
        (METHOD_ANCHOR, METHOD_NEW, "tap method"),
        (TAP_TYPES_OLD, TAP_TYPES_NEW, "tap recogniser types"),
        (TAP_CLICK_OLD, TAP_CLICK_NEW, "tap click guard"),
    ]
    for old, new, what in rules:
        if text.count(old) != 1:
            raise SystemExit(f"{target}: anchor not unique ({text.count(old)}): {what}")
        text = text.replace(old, new, 1)

    for call_old, call_new, what in TOUCH_CALLS:
        if text.count(call_old) != 1:
            raise SystemExit(f"{target}: touch anchor not unique: {what}")
        text = text.replace(call_old, call_new, 1)

    for prefix, human in DELAYS:
        old = f"  {prefix}.delaysTouchesBegan = YES;"
        new = (f"  /* IOS-PTR: the {human} recogniser must not hold back the\n"
               f"   * single-finger touch: the press arrived late or together with the\n"
               f"   * release, which made the first tap do nothing. */\n"
               f"  {prefix}.delaysTouchesBegan = NO;")
        if text.count(old) != 1:
            raise SystemExit(f"{target}: delays anchor not unique: {prefix}")
        text = text.replace(old, new, 1)

    target.write_text(text, encoding="utf-8")
    print(f"  patched  {target} ({len(rules) + len(TOUCH_CALLS) + len(DELAYS)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
