#!/usr/bin/env python3
"""Make mouse / trackpad drags navigate the 3D view on iOS.

Why this exists
---------------
The upstream iOS port turns a drag into ``PAN_GESTURE`` -> ``MOUSEPAN``, and
``MOUSEPAN`` has zero bindings in the default key map, so the viewport never
moved.  Patch #292 replaced that with a synthetic middle-button drag inside
``handlePan`` - which is still a ``UIPanGestureRecognizer`` callback.  The drag
kept doing nothing, which means the recogniser never fires for
``UITouchTypeIndirectPointer`` on this build: the same reason the very first
(v4) build could not even click, only there we fixed the tap recogniser, not
the pan one.

This patch stops depending on the recogniser.  A ``UIView`` always receives its
own ``touchesBegan/Moved/Ended``, so the middle-button drag is generated from
the view's touch callbacks instead.  A short press that never passes the slop
threshold emits nothing, so clicks keep coming from the tap recogniser.

Everything is marked ``IOS-DRAG`` and is idempotent.

Usage:
    python3 patch_ios_drag.py [<blender source root>]   # default: current dir
"""
import os
import sys

MARK = "IOS-DRAG"

STATICS = '''
/* IOS-DRAG: an indirect-pointer (mouse / trackpad) drag becomes a middle-button
 * drag.  Generated from the view's touch callbacks instead of a gesture
 * recogniser, because UITouchTypeIndirectPointer touches never reached the pan
 * recogniser on this build. */
static BOOL iosdrag_armed = NO;
static BOOL iosdrag_active = NO;
static CGPoint iosdrag_start = {0.0f, 0.0f};
'''

TOUCH_BEGAN = '''
  /* IOS-DRAG: remember where an indirect-pointer press started.  Nothing is
   * emitted here: a plain click is still delivered by the tap recogniser. */
  for (UITouch *iosdrag_touch in touches) {
    if (iosdrag_touch.type == UITouchTypeIndirectPointer) {
      CGPoint iosdrag_p = [iosdrag_touch locationInView:window->getView()];
      iosdrag_armed = YES;
      iosdrag_active = NO;
      iosdrag_start = window->scalePointToWindow(iosdrag_p);
      fprintf(stderr, "[IOSGEST] press-begin n=%lu\\n", (unsigned long)touches.count);
    }
  }'''

TOUCH_MOVED = '''
  /* IOS-DRAG: promote a moving indirect-pointer press into a middle-button drag.
   * CURSOR_MOVE has to be emitted before the button press: GHOST_EventButton
   * carries no position and Blender copies it from the last cursor move. */
  for (UITouch *iosdrag_touch in touches) {
    if (iosdrag_touch.type != UITouchTypeIndirectPointer) {
      continue;
    }
    CGPoint iosdrag_p = [iosdrag_touch locationInView:window->getView()];
    iosdrag_p = window->scalePointToWindow(iosdrag_p);
    if (!iosdrag_active) {
      const CGFloat iosdrag_dx = iosdrag_p.x - iosdrag_start.x;
      const CGFloat iosdrag_dy = iosdrag_p.y - iosdrag_start.y;
      if (!iosdrag_armed || (iosdrag_dx * iosdrag_dx + iosdrag_dy * iosdrag_dy) < 64.0f) {
        continue;
      }
      iosdrag_active = YES;
      UserInputEvent iosdrag_down(&iosdrag_start, nullptr, nullptr, false);
      iosdrag_down.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
      iosdrag_down.add_event(UserInputEvent::EventTypes::MIDDLE_BUTTON_DOWN);
      [self generateUserInputEvents:iosdrag_down];
      fprintf(stderr, "[IOSGEST] drag-begin\\n");
    }
    UserInputEvent iosdrag_move(&iosdrag_p, nullptr, nullptr, false);
    iosdrag_move.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    [self generateUserInputEvents:iosdrag_move];
  }'''

TOUCH_ENDED = '''
  /* IOS-DRAG: finish the middle-button drag, if one is running. */
  if (iosdrag_active) {
    CGPoint iosdrag_p = iosdrag_start;
    for (UITouch *iosdrag_touch in touches) {
      if (iosdrag_touch.type == UITouchTypeIndirectPointer) {
        CGPoint iosdrag_q = [iosdrag_touch locationInView:window->getView()];
        iosdrag_p = window->scalePointToWindow(iosdrag_q);
        break;
      }
    }
    UserInputEvent iosdrag_up(&iosdrag_p, nullptr, nullptr, false);
    iosdrag_up.add_event(UserInputEvent::EventTypes::CURSOR_MOVE);
    iosdrag_up.add_event(UserInputEvent::EventTypes::MIDDLE_BUTTON_UP);
    [self generateUserInputEvents:iosdrag_up];
    fprintf(stderr, "[IOSGEST] drag-end\\n");
  }
  iosdrag_active = NO;
  iosdrag_armed = NO;'''

PAN_GUARD = '''  if ([sender isIndirectPointer]) {
    /* IOS-DRAG: indirect-pointer drags are produced by the view's touch
     * callbacks, do not emit a second set of events from here. */
    fprintf(stderr, "[IOSGEST] pan(indirect) suppressed\\n");
    return;
  }
'''

WM_FILTER_OLD = ("  const bool iosdbg_log = ELEM(event->type, MOUSEMOVE, LEFTMOUSE, RIGHTMOUSE, "
                 "MOUSEPAN);")
WM_FILTER_NEW = ("  const bool iosdbg_log = ELEM(\n"
                 "      event->type, MOUSEMOVE, LEFTMOUSE, RIGHTMOUSE, MOUSEPAN, MIDDLEMOUSE);\n"
                 "  if (event->type == MIDDLEMOUSE) {\n"
                 "    /* IOS-DRAG: prove a synthetic middle-button event reached the wm layer. */\n"
                 "    fprintf(stderr,\n"
                 "            \"[IOSGEST] wm MIDDLEMOUSE val=%d xy=(%d,%d) state=(%d,%d)\\n\",\n"
                 "            int(event->val),\n"
                 "            event->xy[0],\n"
                 "            event->xy[1],\n"
                 "            event->prev_xy[0],\n"
                 "            event->prev_xy[1]);\n"
                 "  }")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def apply(path, edits):
    """edits: list of (old, new, label).  Returns number of rules applied."""
    text = read(path)
    applied = 0
    for old, new, label in edits:
        if new in text:
            print("  skip    %s (%s already applied)" % (path, label))
            continue
        if old not in text:
            print("  MISS    %s (%s)" % (path, label))
            raise SystemExit("anchor not found: " + label)
        text = text.replace(old, new, 1)
        applied += 1
    write(path, text)
    return applied


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    win = os.path.join(root, "intern/ghost/intern/GHOST_WindowIOS.mm")
    wm = os.path.join(root, "source/blender/windowmanager/intern/wm_event_system.cc")
    for p in (win, wm):
        if not os.path.exists(p):
            raise SystemExit("missing file: " + p)

    # 1. stdio for fprintf + the drag state.
    win_text = read(win)
    if MARK + ": stdio" not in win_text:
        win_text = "/* %s: stdio */\n#include <cstdio>\n\n" % MARK + win_text
    if MARK + ": state" not in win_text:
        anchor = "} UserInputEvent;"
        if anchor not in win_text:
            raise SystemExit("anchor not found: UserInputEvent")
        win_text = win_text.replace(
            anchor, anchor + "\n/* %s: state */" % MARK + STATICS, 1)
    write(win, win_text)

    n = 0
    n += apply(win, [
        # view touch callbacks
        ("""  for (UITouch *touch in touches) {
    if (touch.type == UITouchTypePencil) {
      current_pencil_touch = touch;
      break;
    }
  }
}""",
         """  for (UITouch *touch in touches) {
    if (touch.type == UITouchTypePencil) {
      current_pencil_touch = touch;
      break;
    }
  }
""" + TOUCH_BEGAN + """
}""", "touchesBegan"),
    ])

    text = read(win)
    moved_anchor = """        break;
      }
    }
  }
}

/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];"""
    moved_new = """        break;
      }
    }
  }
""" + TOUCH_MOVED + """
}

/* Reset tablet data. */
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesEnded:touches withEvent:event];
""" + TOUCH_ENDED

    cancelled_anchor = """- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];"""
    cancelled_new = """- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesCancelled:touches withEvent:event];
""" + TOUCH_ENDED

    pan_anchor = """- (void)handlePan:(GHOSTUIPanGestureRecognizer *)sender
{
  CGPoint touch_point = [sender getScaledTouchPoint:window];"""
    pan_new = """- (void)handlePan:(GHOSTUIPanGestureRecognizer *)sender
{
""" + PAN_GUARD + """  CGPoint touch_point = [sender getScaledTouchPoint:window];"""

    n += apply(win, [
        (moved_anchor, moved_new, "touchesMoved + touchesEnded"),
        (cancelled_anchor, cancelled_new, "touchesCancelled"),
        (pan_anchor, pan_new, "handlePan guard"),
    ])
    print("  patched %s (%d rules)" % (win, n))

    # 2. wm layer: log MIDDLEMOUSE as well.
    m = apply(wm, [(WM_FILTER_OLD, WM_FILTER_NEW, "wm MIDDLEMOUSE log")])
    print("  patched %s (%d rules)" % (wm, m))


if __name__ == "__main__":
    main()
