#!/usr/bin/env python3
"""Give the iOS port a hardware-keyboard path.

Why this exists
---------------
The upstream iOS port has no way to deliver a hardware key press to Blender:

  * ``GHOST_SystemIOS::handleKeyEvent()`` is a stub whose whole body is
    ``GHOST_ASSERT(FALSE, "unsupported on iOS")``;
  * the only place that pushes a ``GHOST_EventKey`` is
    ``generateKeyboardReturnEvent()``, and it only runs while the on-screen
    keyboard is up;
  * there is no ``pressesBegan:withEvent:`` anywhere, no
    ``UIKeyboardHIDUsage -> GHOST_TKey`` table and no modifier tracking.

So ``Shift+A``, ``G``, ``Tab``, ``F3``, ``Ctrl+Z`` cannot work at all, and the
"typing works" the user sees is the hidden ``UITextField`` UIKit puts on top of
Blender, not Blender's own text field.

UIKit delivers hardware keys through the responder chain (``pressesBegan`` /
``pressesEnded``).  Nothing in this port overrides those, so they bubble up from
the content view to this ``UIWindow``.  This patch implements them there.

Modifiers are not read from a state flag: Blender derives ``event.modifier``
purely from receiving ``GHOST_kEventKeyDown/Up`` for
``GHOST_kKeyLeftShift`` / ``RightShift`` / ``LeftControl`` / ... (see
``wm_event_system.cc`` around ``case EVT_LEFTSHIFTKEY``).  So a modifier press
only takes effect if we emit those key events ourselves.  The mask is tracked
here and the transitions are emitted before the key that depends on them.

Everything is marked ``IOS-KEYBOARD`` and is idempotent.

Usage:
    python3 patch_ios_keyboard.py [<blender source root>]   # default: current dir
"""
import os
import sys

MARK = "IOS-KEYBOARD"

WIN = os.path.join("intern", "ghost", "intern", "GHOST_WindowIOS.mm")

# ---------------------------------------------------------------- declarations

IFACE_ANCHOR = "- (void)generateUserInputEvents:(const UserInputEvent &)event_info;"

IFACE_NEW = IFACE_ANCHOR + """

  /* IOS-KEYBOARD: hardware keyboard.  UIKit delivers key presses through the
   * responder chain, which reaches this window while no text field is focused. */
  - (void)iosKeyboardHandlePresses:(NSSet<UIPress *> *)presses down:(BOOL)down;"""

# ------------------------------------------------------------------ C helpers

HELPERS_ANCHOR = (
    "@interface GHOSTUIWindow : UIWindow <UIGestureRecognizerDelegate, "
    "UIPencilInteractionDelegate>"
)

HELPERS = '''/* IOS-KEYBOARD: hardware keyboard plumbing.
 *
 * UIKeyboardHIDUsage values are raw USB HID keyboard-page codes; they are
 * written out as numbers so the table does not depend on the spelling of the
 * UIKit enum (UIKeyboardHIDUsageKeyboardA, ...). */
#define IOSKBD_MOD_SHIFT (1u << 0)
#define IOSKBD_MOD_CTRL (1u << 1)
#define IOSKBD_MOD_ALT (1u << 2)
#define IOSKBD_MOD_OS (1u << 3)

/* Last modifier state we reported to Blender.  Only transitions are emitted. */
static unsigned int ioskbd_mod_state = 0;

/* HID usage -> Blender modifier flag (0 for anything that is not a modifier). */
static unsigned int ioskbd_mod_from_hid(int hid)
{
  switch (hid) {
    case 0xE1: /* Left Shift */
    case 0xE5: /* Right Shift */
      return IOSKBD_MOD_SHIFT;
    case 0xE0: /* Left Control */
    case 0xE4: /* Right Control */
      return IOSKBD_MOD_CTRL;
    case 0xE2: /* Left Alt */
    case 0xE6: /* Right Alt */
      return IOSKBD_MOD_ALT;
    case 0xE3: /* Left GUI */
    case 0xE7: /* Right GUI */
      return IOSKBD_MOD_OS;
    default:
      return 0;
  }
}

static GHOST_TKey ioskbd_key_from_hid(int hid)
{
  /* a..z */
  if (hid >= 0x04 && hid <= 0x1D) {
    return (GHOST_TKey)(int(GHOST_kKeyA) + (hid - 0x04));
  }
  /* 1..9 then 0 */
  if (hid >= 0x1E && hid <= 0x26) {
    return (GHOST_TKey)(int(GHOST_kKey1) + (hid - 0x1E));
  }
  if (hid == 0x27) {
    return GHOST_kKey0;
  }
  /* F1..F12 */
  if (hid >= 0x3A && hid <= 0x45) {
    return (GHOST_TKey)(int(GHOST_kKeyF1) + (hid - 0x3A));
  }
  /* F13..F24 */
  if (hid >= 0x68 && hid <= 0x73) {
    return (GHOST_TKey)(int(GHOST_kKeyF13) + (hid - 0x68));
  }
  /* Numpad 1..9 */
  if (hid >= 0x59 && hid <= 0x61) {
    return (GHOST_TKey)(int(GHOST_kKeyNumpad1) + (hid - 0x59));
  }

  switch (hid) {
    case 0x28:
      return GHOST_kKeyEnter;
    case 0x29:
      return GHOST_kKeyEsc;
    case 0x2A:
      return GHOST_kKeyBackSpace;
    case 0x2B:
      return GHOST_kKeyTab;
    case 0x2C:
      return GHOST_kKeySpace;
    case 0x2D:
      return GHOST_kKeyMinus;
    case 0x2E:
      return GHOST_kKeyEqual;
    case 0x2F:
      return GHOST_kKeyLeftBracket;
    case 0x30:
      return GHOST_kKeyRightBracket;
    case 0x31:
      return GHOST_kKeyBackslash;
    case 0x33:
      return GHOST_kKeySemicolon;
    case 0x34:
      return GHOST_kKeyQuote;
    case 0x35:
      return GHOST_kKeyAccentGrave;
    case 0x36:
      return GHOST_kKeyComma;
    case 0x37:
      return GHOST_kKeyPeriod;
    case 0x38:
      return GHOST_kKeySlash;
    case 0x39:
      return GHOST_kKeyCapsLock;
    case 0x46:
      return GHOST_kKeyPrintScreen;
    case 0x47:
      return GHOST_kKeyScrollLock;
    case 0x48:
      return GHOST_kKeyPause;
    case 0x49:
      return GHOST_kKeyInsert;
    case 0x4A:
      return GHOST_kKeyHome;
    case 0x4B:
      return GHOST_kKeyUpPage;
    case 0x4C:
      return GHOST_kKeyDelete;
    case 0x4D:
      return GHOST_kKeyEnd;
    case 0x4E:
      return GHOST_kKeyDownPage;
    /* HID order is Right, Left, Down, Up - not the order one expects. */
    case 0x4F:
      return GHOST_kKeyRightArrow;
    case 0x50:
      return GHOST_kKeyLeftArrow;
    case 0x51:
      return GHOST_kKeyDownArrow;
    case 0x52:
      return GHOST_kKeyUpArrow;
    case 0x53:
      return GHOST_kKeyNumLock;
    case 0x54:
      return GHOST_kKeyNumpadSlash;
    case 0x55:
      return GHOST_kKeyNumpadAsterisk;
    case 0x56:
      return GHOST_kKeyNumpadMinus;
    case 0x57:
      return GHOST_kKeyNumpadPlus;
    case 0x58:
      return GHOST_kKeyNumpadEnter;
    case 0x62:
      return GHOST_kKeyNumpad0;
    case 0x63:
      return GHOST_kKeyNumpadPeriod;
    case 0x65:
      return GHOST_kKeyApp;
    default:
      return GHOST_kKeyUnknown;
  }
}

/* Printable ASCII for the US layout.  Not a full input-method replacement, but
 * enough for Blender's own text fields, which read ``event->utf8_buf``. */
static void ioskbd_utf8_from_hid(int hid, int shift, char *out)
{
  out[0] = '\\0';
  out[1] = '\\0';

  if (hid >= 0x04 && hid <= 0x1D) {
    char c = (char)('a' + (hid - 0x04));
    out[0] = shift ? (char)(c - 'a' + 'A') : c;
    return;
  }
  if (hid >= 0x1E && hid <= 0x27) {
    static const char *const plain = "1234567890";
    static const char *const shifted = "!@#$%^&*()";
    const int index = (hid == 0x27) ? 9 : (hid - 0x1E);
    out[0] = shift ? shifted[index] : plain[index];
    return;
  }

  switch (hid) {
    case 0x2C:
      out[0] = ' ';
      break;
    case 0x2D:
      out[0] = shift ? '_' : '-';
      break;
    case 0x2E:
      out[0] = shift ? '+' : '=';
      break;
    case 0x2F:
      out[0] = shift ? '{' : '[';
      break;
    case 0x30:
      out[0] = shift ? '}' : ']';
      break;
    case 0x31:
      out[0] = shift ? '|' : '\\\\';
      break;
    case 0x33:
      out[0] = shift ? ':' : ';';
      break;
    case 0x34:
      out[0] = shift ? '"' : '\\'';
      break;
    case 0x35:
      out[0] = shift ? '~' : '`';
      break;
    case 0x36:
      out[0] = shift ? '<' : ',';
      break;
    case 0x37:
      out[0] = shift ? '>' : '.';
      break;
    case 0x38:
      out[0] = shift ? '?' : '/';
      break;
    default:
      out[0] = '\\0';
      break;
  }
}

static void ioskbd_emit_key(GHOST_SystemIOS *system,
                            GHOST_WindowIOS *window,
                            GHOST_TKey key,
                            bool down,
                            const char *utf8)
{
  char buf[6] = {'\\0', '\\0', '\\0', '\\0', '\\0', '\\0'};
  if (utf8 != nullptr) {
    buf[0] = utf8[0];
    buf[1] = utf8[1];
  }
  system->pushEvent(std::make_unique<GHOST_EventKey>(system->getMilliSeconds(),
                                                     down ? GHOST_kEventKeyDown :
                                                            GHOST_kEventKeyUp,
                                                     window,
                                                     key,
                                                     false,
                                                     buf));
}

/* Emit only the modifier transitions between the last reported state and
 * ``desired``.  Called before the key that uses them, so ``Shift+A`` arrives
 * with ``KM_SHIFT`` already set in the event state. */
static void ioskbd_sync_modifiers(GHOST_SystemIOS *system,
                                  GHOST_WindowIOS *window,
                                  unsigned int desired)
{
  const unsigned int diff = desired ^ ioskbd_mod_state;
  if (diff == 0) {
    return;
  }
  if (diff & IOSKBD_MOD_SHIFT) {
    const bool down = (desired & IOSKBD_MOD_SHIFT) != 0;
    ioskbd_emit_key(system, window, GHOST_kKeyLeftShift, down, nullptr);
  }
  if (diff & IOSKBD_MOD_CTRL) {
    const bool down = (desired & IOSKBD_MOD_CTRL) != 0;
    ioskbd_emit_key(system, window, GHOST_kKeyLeftControl, down, nullptr);
  }
  if (diff & IOSKBD_MOD_ALT) {
    const bool down = (desired & IOSKBD_MOD_ALT) != 0;
    ioskbd_emit_key(system, window, GHOST_kKeyLeftAlt, down, nullptr);
  }
  if (diff & IOSKBD_MOD_OS) {
    const bool down = (desired & IOSKBD_MOD_OS) != 0;
    ioskbd_emit_key(system, window, GHOST_kKeyLeftOS, down, nullptr);
  }
  ioskbd_mod_state = desired;
}

'''

# ------------------------------------------------------------------ methods

METHODS_ANCHOR = "/* Override touch methods to capture the UITouch object. */"

METHODS = '''/* IOS-KEYBOARD: turn a UIKit press set into Blender key events.
 *
 * Two passes on purpose: the modifier state has to be updated (and the modifier
 * key events emitted) *before* the key that relies on them, otherwise
 * ``Shift+A`` arrives as a plain ``A``.
 *
 * Modifiers come from the HID code of the pressed key itself, and are only
 * nudged by ``UIKey.modifierFlags`` for regular keys.  That way a mismatch can
 * never leave a modifier stuck down: the next non-modifier key corrects it. */
- (void)iosKeyboardHandlePresses:(NSSet<UIPress *> *)presses down:(BOOL)down
{
  if (system == nullptr || window == nullptr) {
    return;
  }

  unsigned int ioskbd_desired = ioskbd_mod_state;

  for (UIPress *ioskbd_press in presses) {
    UIKey *ioskbd_key = ioskbd_press.key;
    if (ioskbd_key == nil) {
      continue;
    }
    const int ioskbd_hid = (int)ioskbd_key.keyCode;
    const unsigned int ioskbd_toggle = ioskbd_mod_from_hid(ioskbd_hid);
    if (ioskbd_toggle != 0) {
      if (down) {
        ioskbd_desired |= ioskbd_toggle;
      }
      else {
        ioskbd_desired &= ~ioskbd_toggle;
      }
      continue;
    }
    if (down) {
      /* UIKit knows the real modifier state; use it to recover from drift. */
      const UIKeyModifierFlags ioskbd_flags = ioskbd_key.modifierFlags;
      if (ioskbd_flags & UIKeyModifierShift) {
        ioskbd_desired |= IOSKBD_MOD_SHIFT;
      }
      if (ioskbd_flags & UIKeyModifierControl) {
        ioskbd_desired |= IOSKBD_MOD_CTRL;
      }
      if (ioskbd_flags & UIKeyModifierAlternate) {
        ioskbd_desired |= IOSKBD_MOD_ALT;
      }
      if (ioskbd_flags & UIKeyModifierCommand) {
        ioskbd_desired |= IOSKBD_MOD_OS;
      }
    }
  }

  ioskbd_sync_modifiers(system, window, ioskbd_desired);

  for (UIPress *ioskbd_press in presses) {
    UIKey *ioskbd_key = ioskbd_press.key;
    if (ioskbd_key == nil) {
      continue;
    }
    const int ioskbd_hid = (int)ioskbd_key.keyCode;
    if (ioskbd_mod_from_hid(ioskbd_hid) != 0) {
      continue;
    }
    const GHOST_TKey ioskbd_ghost_key = ioskbd_key_from_hid(ioskbd_hid);
    if (ioskbd_ghost_key == GHOST_kKeyUnknown) {
      continue;
    }
    char ioskbd_utf8[6] = {'\\0', '\\0', '\\0', '\\0', '\\0', '\\0'};
    if (down) {
      ioskbd_utf8_from_hid(ioskbd_hid, (ioskbd_desired & IOSKBD_MOD_SHIFT) != 0, ioskbd_utf8);
    }
    ioskbd_emit_key(system, window, ioskbd_ghost_key, down ? true : false, ioskbd_utf8);
  }
}

- (void)pressesBegan:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)event
{
  [super pressesBegan:presses withEvent:event];

  /* IOS-KEYBOARD: while the on-screen keyboard holds first responder status,
   * UIKit keeps the presses there; nothing to forward. */
  if (text_field != nil && [text_field isFirstResponder]) {
    return;
  }
  [self iosKeyboardHandlePresses:presses down:YES];
}

- (void)pressesEnded:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)event
{
  [super pressesEnded:presses withEvent:event];

  if (text_field != nil && [text_field isFirstResponder]) {
    return;
  }
  [self iosKeyboardHandlePresses:presses down:NO];
}

- (void)pressesCancelled:(NSSet<UIPress *> *)presses withEvent:(UIPressesEvent *)event
{
  [super pressesCancelled:presses withEvent:event];

  /* Never leave a modifier stuck down after an interrupted press. */
  if (system != nullptr && window != nullptr) {
    ioskbd_sync_modifiers(system, window, 0);
  }
}

'''

METHODS_NEW = METHODS_ANCHOR + "\n" + METHODS


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
            raise SystemExit("anchor %r not found in %s" % (label, path))
        if text.count(old) != 1:
            raise SystemExit("anchor %r not unique in %s (%d hits)"
                             % (label, path, text.count(old)))
        text = text.replace(old, new, 1)
        applied += 1
    write(path, text)
    return applied


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    win = os.path.join(root, WIN)
    if not os.path.isfile(win):
        raise SystemExit("not found: " + win)

    n = apply(win,
              [(IFACE_ANCHOR, IFACE_NEW, "keyboard method declaration"),
               (HELPERS_ANCHOR, HELPERS + HELPERS_ANCHOR, "keyboard helpers"),
               (METHODS_ANCHOR, METHODS_NEW, "keyboard presses")])
    print("  patched %s (%d rules)" % (win, n))


if __name__ == "__main__":
    main()
