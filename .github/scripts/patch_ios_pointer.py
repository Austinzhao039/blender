#!/usr/bin/env python3
"""One complete left-button gesture per single touch, driven by the view's own
touch callbacks.

Upstream only emits a click when the finger LIFTS (`handleTap:` on state
``Ended``), so the button is never held while the pointer moves - every drag in
Blender (sliders, scroll-bars, panel borders, box select, transforms) is
impossible by construction.

This patch replaces that with a real gesture:

  press                  -> CURSOR_MOVE only (hover / hit-testing stays correct)
  move, > threshold      -> CURSOR_MOVE(start) + LEFT_BUTTON_DOWN, then moves
  release after a drag   -> CURSOR_MOVE + LEFT_BUTTON_UP
  release without a drag -> CURSOR_MOVE + LEFT_BUTTON_DOWN + LEFT_BUTTON_UP

A tap therefore stays a click (selection keeps working) while a drag is a real
press-drag-release, which is what ``view2d.scroller_activate``, ``ui_but``
dragging and ``view3d.rotate`` (see patch_ios_preset.py) all consume.

v12 changes, all three fixing a "needs two taps" / "drag does nothing" class of
bug that survived v11:

* A gesture that never receives its release (a popup closed under the finger, the
  touch was cancelled, the app was covered) left ``iosptr_down`` set forever.
  Every later press then bailed out at ``if (iosptr_down) return;`` and only the
  release path ran, against a start point from the previous gesture.  A new
  press now closes the stale gesture first, so the state matches reality.

* ``handleTap:`` and this callback can both produce a click for the same touch.
  v11 tried to fix that by restricting the recogniser to the pencil, which
  assumes these touch callbacks always run - when UIKit does not deliver them,
  *no* tap produces a click at all, which is worse than the duplicate.  Both
  sources stay enabled and a shared 80 ms guard drops whichever fires second.

* ``delaysTouchesBegan`` on the two/three/four finger tap recognisers delays the
  delivery of a single-finger touch to the view until the recogniser fails.

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
/* IOS-PTR: state of the left-button gesture driven by the view touch callbacks. */
static BOOL iosptr_down = NO;
static BOOL iosptr_dragging = NO;
static BOOL iosptr_moved = NO;
static CGPoint iosptr_start = {0.0f, 0.0f};
static CGPoint iosptr_last = {0.0f, 0.0f};
static uintptr_t iosptr_token = 0;
static int iosptr_presses = 0;
static int iosptr_drags = 0;
static double iosptr_last_click = 0.0;

/* IOS-PTR: exactly one click per physical tap.
 *
 * Both the touch callbacks below and `handleTap:` can deliver the click for the
 * same touch.  Two clicks in a row is what made a top-bar menu need two taps -
 * the first one opened the popup and the second closed it again.  The guard is
 * shared by both sources, so it does not matter which one runs first, and it
 * stays harmless when only one of them is reachable at all. */
static BOOL iosptr_click_allowed(void)
{
  const double iosptr_now = [NSDate timeIntervalSinceReferenceDate];
  if (iosptr_now - iosptr_last_click < 0.08) {
    return NO;
  }
  iosptr_last_click = iosptr_now;
  return YES;
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

# --- 3. the gesture itself --------------------------------------------------
METHOD_ANCHOR = """- (void)handleTap:(GHOSTUITapGestureRecognizer *)sender
{"""

METHOD_NEW = """/* IOS-PTR: one complete left-button gesture per single non-pencil touch.
 *
 * phase: 0 = began, 1 = moved, 2 = ended, 3 = cancelled.
 *
 * The press is only sent once the pointer has travelled far enough to be a
 * drag: a tap stays a clean click (selection, menus, buttons) while a drag is
 * a real press-drag-release, which is what sliders, scroll-bars, panel borders
 * and `view3d.rotate` need.  Pressing at touch-down would also start a
 * transform on every tap. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase
{
  if (touches.count != 1) {
    /* A second finger joined: the gesture recognisers own it now.  Finish any
     * drag we started so the button cannot stay stuck down. */
    if (iosptr_down) {
      iosptr_down = NO;
      iosptr_dragging = NO;
      iosptr_token = 0;
      UserInputEvent iosptr_up(&iosptr_last, nullptr, nullptr, false);
      iosptr_up.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      iosptr_up.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
      [self generateUserInputEvents:iosptr_up];
      fprintf(stdout, "[IOSPTR] up (multi-touch)\\n");
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
    if (iosptr_down) {
      /* A gesture that never got its release - a popup closed under the finger,
       * the touch was cancelled, the app went to the background.  Without this
       * the next press bailed out here and only the release ran, using a start
       * point from minutes ago: that is the "first tap does nothing" symptom. */
      iosptr_down = NO;
      iosptr_dragging = NO;
      iosptr_token = 0;
      UserInputEvent iosptr_stale(&iosptr_last, nullptr, nullptr, false);
      iosptr_stale.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      iosptr_stale.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
      [self generateUserInputEvents:iosptr_stale];
      fprintf(stdout, "[IOSPTR] up (stale gesture closed)\\n");
    }
    iosptr_down = YES;
    iosptr_dragging = NO;
    iosptr_moved = NO;
    iosptr_token = (uintptr_t)iosptr_touch;
    iosptr_start = iosptr_p;
    iosptr_last = iosptr_p;
    iosptr_presses++;

    /* Only move the cursor: Blender takes the hit-test position from this, and
     * nothing must be pressed yet - press or click is decided on release. */
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
    if (!iosptr_dragging) {
      const CGFloat iosptr_dx = iosptr_p.x - iosptr_start.x;
      const CGFloat iosptr_dy = iosptr_p.y - iosptr_start.y;
      if ((iosptr_dx * iosptr_dx + iosptr_dy * iosptr_dy) <= 144.0f) {
        /* Still inside the click radius, keep waiting. */
        return;
      }
      /* Crossed the threshold: this is a drag.  Press at the point where the
       * gesture started, that is where the widget under the finger is. */
      iosptr_dragging = YES;
      iosptr_moved = YES;
      iosptr_drags++;
      UserInputEvent iosptr_begin(&iosptr_start, nullptr, nullptr, false);
      iosptr_begin.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      iosptr_begin.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
      [self generateUserInputEvents:iosptr_begin];
      fprintf(stdout, "[IOSPTR] drag begin\\n");
    }

    iosptr_last = iosptr_p;

    UserInputEvent iosptr_move(&iosptr_p, nullptr, nullptr, false);
    iosptr_move.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosptr_move];
    return;
  }

  /* ended / cancelled */
  iosptr_down = NO;
  iosptr_token = 0;

  UserInputEvent iosptr_end(&iosptr_p, nullptr, nullptr, false);
  iosptr_end.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
  if (iosptr_dragging) {
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
  }
  else if (iosptr_click_allowed()) {
    /* A tap: one press and one release at the same position, so Blender turns
     * it into a #KM_CLICK exactly like a mouse click. */
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
    iosptr_end.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
  }
  [self generateUserInputEvents:iosptr_end];
  fprintf(stdout, "[IOSPTR] up moved=%d\\n", int(iosptr_moved));
  iosptr_dragging = NO;
  iosptr_moved = NO;
}

""" + METHOD_ANCHOR

# --- 4. interface declaration ----------------------------------------------
IFACE_ANCHOR = """/* On screen keyboard handling */
- (UITextField *)getUITextField;"""
IFACE_NEW = """/* IOS-PTR: gesture driver, see the implementation for why. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase;

""" + IFACE_ANCHOR

# --- 5. handlePan: hands off while our gesture owns the touch --------------
PAN_ANCHOR = """- (void)handlePan:(GHOSTUIPanGestureRecognizer *)sender
{"""
PAN_NEW = PAN_ANCHOR + """
  if (iosptr_down) {
    /* IOS-PTR: the same single finger is already driving a left-button drag.
     * Letting this also emit a MOUSEPAN scroll would fight it. */
    return;
  }
"""

# --- 6. touch delays --------------------------------------------------------
DELAYS = [
    ("tap2f_gesture_recognizer", "two fingers"),
    ("tap3f_gesture_recognizer", "three fingers"),
    ("tap4f_gesture_recognizer", "four fingers"),
]

# --- 7. the recogniser keeps every touch type ------------------------------
TAP_TYPES_OLD = """  tap_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];"""
TAP_TYPES_NEW = """  /* IOS-PTR: keep every touch type here.
   *
   * v11 narrowed this to the pencil, assuming `iosPointerUpdate:phase:` always
   * runs.  If UIKit does not deliver the window's touch callbacks the app then
   * has no click source at all, which is worse than the duplicate it removed.
   * The duplicate is dropped by `iosptr_click_allowed()` instead, and that
   * guard works regardless of which of the two sources is reachable. */
  tap_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];"""

# --- 8. the same guard inside handleTap ------------------------------------
TAP_CLICK_OLD = """  /* Send events to indicate a 'click' on event end. */
  if (sender.state == UIGestureRecognizerStateEnded) {"""
TAP_CLICK_NEW = """  /* Send events to indicate a 'click' on event end. */
  /* IOS-PTR: `iosptr_click_allowed()` drops this click when the touch callbacks
   * already delivered one for the same tap. */
  if ((sender.state == UIGestureRecognizerStateEnded) && iosptr_click_allowed()) {"""


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1
                  else "intern/ghost/intern/GHOST_WindowIOS.mm")
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if "/* IOS-PTR: state of the left-button gesture" in text:
        print(f"  already  {target}")
        return 0

    rules = [
        (STATE_ANCHOR, STATE_NEW, "pointer state"),
        (IFACE_ANCHOR, IFACE_NEW, "interface"),
        (METHOD_ANCHOR, METHOD_NEW, "gesture method"),
        (PAN_ANCHOR, PAN_NEW, "pan hands off"),
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
