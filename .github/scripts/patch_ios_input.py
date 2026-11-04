#!/usr/bin/env python3
"""Make mouse / trackpad input work in the iOS port.

Symptom: the pointer moves and hover tooltips appear, but no click ever reaches
Blender; touch still works. That rules out coordinates and the event queue.

Root cause: on iOS 17+ an app without UIApplicationSupportsIndirectInputEvents
in its Info.plist is treated as if the key were YES, so a mouse click is
delivered as a UITouch of type UITouchTypeIndirectPointer. UIKit refuses to
hand such a touch to a gesture recognizer that does not list the type in
`allowedTouchTypes`, and GHOST_WindowIOS.mm only lists Pencil + Direct -- the
click is dropped before Blender sees it. Hover is unaffected because it travels
through UIHoverGestureRecognizer, which is indirect-pointer only by design,
which is exactly why the cursor moves and tooltips show but nothing clicks.

Fixes, all in intern/ghost/intern/GHOST_WindowIOS.mm:

1. tap + pan recognizers also accept UITouchTypeIndirectPointer.
2. A mouse drag must not become PAN_GESTURE (scroll), or sliders and box-select
   break -- the pan recognizer is taught to tell the two devices apart and only
   emits pans for fingers / pencil.
3. A scroll wheel reports UIEventType.scroll, which carries no touches at all,
   so it needs its own recognizer with an empty allowedTouchTypes and
   allowedScrollTypesMask = all. Without it the wheel does nothing.

Info.plist is deliberately left alone: adding the key would only change iOS
< 17 behaviour, where clicks already arrive as UITouchTypeDirect and work.

Idempotent: re-running is a no-op once the marker is present.
"""
import os
import sys

DEFAULT_TARGET = "intern/ghost/intern/GHOST_WindowIOS.mm"
MARKER = "UITouchTypeIndirectPointer"

RULES = [
    (
        """  tap_gesture_recognizer.allowedTouchTypes = @[ @(UITouchTypePencil), @(UITouchTypeDirect) ];
""",
        """  /* IOS_FIXME: UIKit does not deliver indirect-pointer touches (mouse click,
   * trackpad click) to a recognizer that omits UITouchTypeIndirectPointer from
   * allowedTouchTypes, so clicks never reached Blender while hover worked.
   * See .github/scripts/patch_ios_input.py. */
  tap_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];
""",
    ),
    (
        """  pan_gesture_recognizer.allowedTouchTypes = @[ @(UITouchTypePencil), @(UITouchTypeDirect) ];
""",
        """  pan_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];
""",
    ),
    (
        """@interface GHOSTUIPanGestureRecognizer : UIPanGestureRecognizer
{
  CGPoint cached_translation;
}
""",
        """@interface GHOSTUIPanGestureRecognizer : UIPanGestureRecognizer
{
  CGPoint cached_translation;
  BOOL indirect_pointer;
}
""",
    ),
    (
        """- (void)setCachedTranslation:(CGPoint)translation;
- (CGPoint)getCachedTranslation;
@end
""",
        """- (void)setCachedTranslation:(CGPoint)translation;
- (CGPoint)getCachedTranslation;
- (BOOL)isIndirectPointer;
@end
""",
    ),
    (
        """@implementation GHOSTUIPanGestureRecognizer

- (CGPoint)getScaledTouchPoint:(GHOST_WindowIOS *)window
""",
        """@implementation GHOSTUIPanGestureRecognizer

/* Remember which kind of device drives this gesture: fingers and the pencil
 * scroll, a mouse drag has to behave like a real drag. */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event
{
  [super touchesBegan:touches withEvent:event];
  indirect_pointer = NO;
  for (UITouch *touch in touches) {
    if (touch.type == UITouchTypeIndirectPointer) {
      indirect_pointer = YES;
    }
  }
}

- (BOOL)isIndirectPointer
{
  return indirect_pointer;
}

- (CGPoint)getScaledTouchPoint:(GHOST_WindowIOS *)window
""",
    ),
    (
        """    /* Send pan event if non zero */
    if (!CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f))) {
      event_info.translation = relative_translation;
      event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE);
    }
""",
        """    /* Send pan event if non zero.
     * A mouse drag must not scroll: keep the button down and only emit cursor
     * moves, so sliders, box-select and transforms behave like on desktop. */
    if (![sender isIndirectPointer] &&
        !CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f)))
    {
      event_info.translation = relative_translation;
      event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE);
    }
""",
    ),
    (
        """  GHOSTUIPanGestureRecognizer *pan2f_gesture_recognizer;
""",
        """  GHOSTUIPanGestureRecognizer *pan2f_gesture_recognizer;
  GHOSTUIPanGestureRecognizer *scroll_gesture_recognizer;
""",
    ),
    (
        """- (void)handlePan2f:(GHOSTUIPanGestureRecognizer *)sender;
""",
        """- (void)handlePan2f:(GHOSTUIPanGestureRecognizer *)sender;
- (void)handleScrollWheel:(GHOSTUIPanGestureRecognizer *)sender;
""",
    ),
    (
        """  pan_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];
  [window->getView() addGestureRecognizer:pan_gesture_recognizer];
""",
        """  pan_gesture_recognizer.allowedTouchTypes = @[
    @(UITouchTypePencil), @(UITouchTypeDirect), @(UITouchTypeIndirectPointer)
  ];
  [window->getView() addGestureRecognizer:pan_gesture_recognizer];

  /* Scroll wheel. UIEventType.scroll carries no touches at all, so this
   * recognizer must accept no touch type and opt into scroll events instead. */
  scroll_gesture_recognizer = [[GHOSTUIPanGestureRecognizer alloc]
      initWithTarget:self
              action:@selector(handleScrollWheel:)];
  scroll_gesture_recognizer.cancelsTouchesInView = false;
  scroll_gesture_recognizer.allowedTouchTypes = @[];
  scroll_gesture_recognizer.allowedScrollTypesMask = UIScrollTypeMaskAll;
  [window->getView() addGestureRecognizer:scroll_gesture_recognizer];
""",
    ),
    (
        """- (void)pencilInteractionDidTap:(UIPencilInteraction *)interaction
""",
        """/* Mouse wheel / trackpad scroll surface. No touches are involved, so only
 * translation is meaningful here. */
- (void)handleScrollWheel:(GHOSTUIPanGestureRecognizer *)sender
{
  if (sender.state != UIGestureRecognizerStateBegan &&
      sender.state != UIGestureRecognizerStateChanged)
  {
    return;
  }

  CGPoint translation = [sender getScaledTranslation:window];
  if (sender.state == UIGestureRecognizerStateBegan) {
    [sender setCachedTranslation:translation];
    return;
  }

  CGPoint relative_translation = [sender getRelativeTranslation:translation];
  [sender setCachedTranslation:translation];
  if (CGPointEqualToPoint(relative_translation, CGPointMake(0.0f, 0.0f))) {
    return;
  }

  CGPoint scroll_point = [sender getScaledTouchPoint:window];
  UserInputEvent event_info(&scroll_point, nullptr, nullptr, false);
  event_info.translation = relative_translation;
  event_info.add_event(UserInputEvent::EventTypes::PAN_GESTURE);
  [self generateUserInputEvents:event_info];
}

- (void)pencilInteractionDidTap:(UIPencilInteraction *)interaction
""",
    ),
]


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    if not os.path.isfile(target):
        print("::error::missing file %s" % target)
        return 1

    src = open(target, encoding="utf-8").read()
    if MARKER in src:
        print("already patched: %s" % target)
        return 0

    for idx, (old, new) in enumerate(RULES):
        hits = src.count(old)
        if hits != 1:
            print("::error::anchor %d matched %d times in %s (expected 1)" % (idx, hits, target))
            return 1
        src = src.replace(old, new, 1)

    open(target, "w", encoding="utf-8").write(src)
    print("patched %s (%d rules)" % (target, len(RULES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
