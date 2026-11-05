#!/usr/bin/env python3
"""Give the iOS port a real press-drag-release pointer path.

What was wrong
--------------
Upstream only produces a click **when the finger lifts**: ``handleTap:`` fires on
``UIGestureRecognizerStateEnded`` and pushes ``CURSOR_MOVE + LEFT_DOWN + LEFT_UP``
in one batch.  There is no ``LEFT_DOWN`` at touch-down and no ``CURSOR_MOVE``
while the finger is down, so **nothing in Blender can ever be dragged**:
scrollbars, slider handles, panel borders, box-select, colour pickers - all of
them need "button held while the pointer moves".  That is exactly the list the
user reported ("滚动条调不动", "旁边小的部分拖不动, 显示不全").

The mouse was worse: ``tap_gesture_recognizer.allowedTouchTypes`` only lists
``UITouchTypePencil`` and ``UITouchTypeDirect``, so an indirect pointer (mouse /
trackpad) never even produces a tap - clicks were dropped before Blender saw
them.

What this does
--------------
1. ``UITouchTypeIndirectPointer`` is added to the tap recogniser, so mouse clicks
   work even if the responder callbacks below never fire.
2. ``touchesBegan/Moved/Ended/Cancelled`` (which the port already overrides for
   pencil pressure) now drive a proper left-button drag for a single non-pencil
   touch: DOWN at touch-down, CURSOR_MOVE while moving, UP at release.
3. As soon as we have seen a real press from a given touch type, that type is
   removed from the tap recogniser so the click is not delivered twice.  First
   press of each type may double-fire once; that is the price of not being able
   to predict whether the callbacks fire at all.
4. ``handlePan:`` returns while our drag is running, otherwise the same single
   finger would also emit a ``MOUSEPAN`` scroll.

``CURSOR_MOVE`` is always emitted before the button event: ``GHOST_EventButton``
carries no position, Blender copies the coordinates from the last cursor move.

Marked ``IOS-PTR``; idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-PTR"

STATICS = '''
/* @MARK@: state of the left-button drag driven by the view touch callbacks. */
static BOOL iosptr_down = NO;
static BOOL iosptr_moved = NO;
static CGPoint iosptr_start = {0.0f, 0.0f};
static CGPoint iosptr_last = {0.0f, 0.0f};
static uintptr_t iosptr_token = 0;
static int iosptr_presses = 0;
static BOOL iosptr_seen_direct = NO;
static BOOL iosptr_seen_indirect = NO;
'''

METHOD = '''
/* @MARK@: one complete left-button press per single non-pencil touch.
 *
 * phase: 0 = began, 1 = moved, 2 = ended, 3 = cancelled.
 *
 * Upstream only ever sends a click when the finger lifts (``handleTap:`` on
 * state ``Ended``), which makes every drag - scrollbars, sliders, panel
 * borders, box select - impossible.  This emits the press at touch-down and a
 * cursor move for every movement in between, which is what Blender's UI and the
 * 3D-view key map actually consume. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase
{
  if (touches.count != 1) {
    /* A second finger joined, or this is a multi-touch gesture: the gesture
     * recognisers own it.  Finish any drag we started so the button is not left
     * stuck down. */
    if (iosptr_down) {
      iosptr_down = NO;
      iosptr_token = 0;
      UserInputEvent iosptr_up(&iosptr_last, nullptr, nullptr, false);
      iosptr_up.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      iosptr_up.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
      [self generateUserInputEvents:iosptr_up];
      fprintf(stderr, "[IOSPTR] up (multi-touch)\\n");
    }
    return;
  }

  UITouch *iosptr_touch = [touches anyObject];
  if (iosptr_touch.type == UITouchTypePencil) {
    /* The pencil keeps the recognised tap path (it also needs the tablet data). */
    return;
  }

  CGPoint iosptr_p = [iosptr_touch locationInView:window->getView()];
  iosptr_p = window->scalePointToWindow(iosptr_p);

  if (phase == 0) {
    if (iosptr_down) {
      return;
    }
    iosptr_down = YES;
    iosptr_moved = NO;
    iosptr_token = (uintptr_t)iosptr_touch;
    iosptr_start = iosptr_p;
    iosptr_last = iosptr_p;
    iosptr_presses++;

    /* Now that a real press reached us for this touch type, stop the tap
     * recogniser from sending a second, duplicate click for it. */
    const BOOL iosptr_indirect = (iosptr_touch.type == UITouchTypeIndirectPointer);
    if (iosptr_indirect) {
      iosptr_seen_indirect = YES;
    }
    else {
      iosptr_seen_direct = YES;
    }
    NSMutableArray *iosptr_types = [NSMutableArray arrayWithObject:@( UITouchTypePencil )];
    if (!iosptr_seen_direct) {
      [iosptr_types addObject:@( UITouchTypeDirect )];
    }
    if (!iosptr_seen_indirect) {
      [iosptr_types addObject:@( UITouchTypeIndirectPointer )];
    }
    tap_gesture_recognizer.allowedTouchTypes = iosptr_types;

    UserInputEvent iosptr_event(&iosptr_p, nullptr, nullptr, false);
    iosptr_event.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    iosptr_event.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_DOWN);
    [self generateUserInputEvents:iosptr_event];
    fprintf(stderr, "[IOSPTR] down n=%d type=%d\\n", iosptr_presses, int(iosptr_touch.type));
    return;
  }

  if ((uintptr_t)iosptr_touch != iosptr_token) {
    /* Not the touch that started the drag. */
    return;
  }

  if (phase == 1) {
    if (!iosptr_down) {
      return;
    }
    const CGFloat iosptr_dx = iosptr_p.x - iosptr_start.x;
    const CGFloat iosptr_dy = iosptr_p.y - iosptr_start.y;
    if ((iosptr_dx * iosptr_dx + iosptr_dy * iosptr_dy) > 25.0f) {
      iosptr_moved = YES;
    }
    iosptr_last = iosptr_p;

    UserInputEvent iosptr_move(&iosptr_p, nullptr, nullptr, false);
    iosptr_move.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosptr_move];
    return;
  }

  /* ended / cancelled */
  if (!iosptr_down) {
    return;
  }
  iosptr_down = NO;
  iosptr_token = 0;
  iosptr_last = iosptr_p;

  UserInputEvent iosptr_up(&iosptr_p, nullptr, nullptr, false);
  iosptr_up.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
  iosptr_up.add_event(UserInputEvent::EventTypes::LEFT_BUTTON_UP);
  [self generateUserInputEvents:iosptr_up];
  fprintf(stderr, "[IOSPTR] up moved=%d\\n", int(iosptr_moved));
}
'''

PAN_OLD = """- (void)handlePan:(GHOSTUIPanGestureRecognizer *)sender
{
  CGPoint touch_point = [sender getScaledTouchPoint:window];"""

PAN_NEW = """- (void)handlePan:(GHOSTUIPanGestureRecognizer *)sender
{
  if (iosptr_down) {
    /* @MARK@: the same single finger is already driving a left-button drag.
     * Letting this also emit a MOUSEPAN scroll would fight it. */
    return;
  }
  CGPoint touch_point = [sender getScaledTouchPoint:window];"""

TOUCH_CALLS = [
    ("""/* Override touch methods to capture the UITouch object. */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesBegan:touches withEvent:event];""",
     """/* Override touch methods to capture the UITouch object. */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesBegan:touches withEvent:event];
  [self iosPointerUpdate:touches phase:0]; /* @MARK@ */""",
     "touchesBegan"),
    ("""/* Get updated tablet data. */
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesMoved:touches withEvent:event];""",
     """/* Get updated tablet data. */
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesMoved:touches withEvent:event];
  [self iosPointerUpdate:touches phase:1]; /* @MARK@ */""",
     "touchesMoved"),
    ("""/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];""",
     """/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];
  [self iosPointerUpdate:touches phase:2]; /* @MARK@ */""",
     "touchesEnded"),
    ("""/* Reset tablet data. */
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];""",
     """/* Reset tablet data. */
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];
  [self iosPointerUpdate:touches phase:3]; /* @MARK@ */""",
     "touchesCancelled"),
]

IFACE_OLD = "- (void)handleTap:(GHOSTUITapGestureRecognizer *)sender;"
IFACE_NEW = """- (void)handleTap:(GHOSTUITapGestureRecognizer *)sender;
/* @MARK@: single-finger press/drag/release, see the implementation for why. */
- (void)iosPointerUpdate:(NSSet<UITouch *> *)touches phase:(int)phase;"""

METHOD_ANCHOR = "- (void)handleTap:(GHOSTUITapGestureRecognizer *)sender\n{"


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    path = root / "intern/ghost/intern/GHOST_WindowIOS.mm"
    if not path.exists():
        print(f"::error::missing {path}")
        return 1
    text = path.read_text(encoding="utf-8")

    if MARK + ": state */" in text:
        print("  already  %s" % path)
        return 0

    if MARK + ": stdio" not in text:
        text = "/* %s: stdio */\n#include <cstdio>\n#include <cstdint>\n\n" % MARK + text
    if MARK + ": state" not in text:
        anchor = "} UserInputEvent;"
        if anchor not in text:
            raise SystemExit("anchor not found: UserInputEvent")
        text = text.replace(anchor, anchor + "\n/* %s: state */" % MARK + STATICS.replace("@MARK@", MARK), 1)

    rules = [
        (IFACE_OLD, IFACE_NEW, "iosPointerUpdate declaration"),
        (PAN_OLD, PAN_NEW, "handlePan guard"),
    ]
    rules += [(old, new, label) for old, new, label in TOUCH_CALLS]

    for old, new, label in rules:
        old = old.replace("@MARK@", MARK)
        new = new.replace("@MARK@", MARK)
        if new in text:
            print("  skip    %s" % label)
            continue
        if old not in text:
            raise SystemExit("anchor not found: " + label)
        text = text.replace(old, new, 1)
        print("  patched %s" % label)

    if MARK + ": method" not in text:
        if text.count(METHOD_ANCHOR) != 1:
            raise SystemExit("anchor not unique: handleTap")
        text = text.replace(METHOD_ANCHOR, METHOD.replace("@MARK@", MARK) + "\n" + METHOD_ANCHOR, 1)
        print("  patched pointer method")

    path.write_text(text, encoding="utf-8")
    print("  written %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
