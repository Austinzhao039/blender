#!/usr/bin/env python3
"""Put a diagnostic read-out on the device screen.

Why
---
Seven builds were spent guessing which layer drops the input, because the
event log written to ``Documents/blender.log`` could not be retrieved from the
iPad.  This patch stops depending on file access: it adds a small label in the
bottom-left corner of the window that always shows the last thing that happened
in each layer, so a single screenshot answers what used to need a log file.

Slots (one line each, bottom-up order is the slot order):

  0  press / tap        what ``GHOSTUIWindow`` received and sent
  1  move               the live position during a drag
  2  wm entry           type/val/xy, area, region and handler result
  3  wm button          the last non-move event (survives later mouse moves)
  4  drag state         drag begin/end markers
  5  log                where stdout/stderr went, and whether it opened

Read it like this:

  * press appears, ``wm`` line for the button never appears
      -> the event dies between GHOST and the window manager
  * ``wm ... act=1`` (not 2)
      -> it reached the region but nothing handled it (key map / handler issue)
  * ``wm ... act=2`` but the view does not react
      -> the handler ran; the problem is inside the operator or the redraw

Everything is marked ``IOS-PROBE`` and is idempotent.

Usage:
    python3 patch_ios_probe.py [<blender source root>]   # default: current dir
"""
import os
import sys

MARK = "IOS-PROBE"

# ---------------------------------------------------------------------------
# 1. the overlay itself (GHOST_WindowIOS.mm)
# ---------------------------------------------------------------------------

OVERLAY = r'''
/* IOS-PROBE: on-screen diagnostic read-out.
 *
 * A label in the bottom-left corner mirrors what each input layer last saw, so
 * a screenshot is enough to tell where an event is dropped.  `iosdbg_slot` is
 * called from the window-manager layer as well, hence C linkage. */
#define IOSDBG_SLOTS 7
static char iosdbg_lines[IOSDBG_SLOTS][192];
static UILabel *iosdbg_label = nil;
static int iosdbg_taps = 0;
static int iosdbg_presses = 0;

/* Fixed captions: an untouched slot must still occupy its own row, otherwise
 * the rows shift and a screenshot becomes ambiguous. */
static const char *const iosdbg_caps[IOSDBG_SLOTS] = {
    "0 PRESS/TAP",
    "1 MOVE     ",
    "2 WM MOVE  ",
    "3 WM EVENT ",
    "4 PTR      ",
    "5 LOG      ",
    "6 VIEW     ",
};

static void iosdbg_repaint(void)
{
  if (iosdbg_label == nil) {
    return;
  }
  NSMutableString *iosdbg_all = [NSMutableString string];
  for (int iosdbg_i = 0; iosdbg_i < IOSDBG_SLOTS; iosdbg_i++) {
    [iosdbg_all appendFormat:@"%s %s\n",
                             iosdbg_caps[iosdbg_i],
                             iosdbg_lines[iosdbg_i][0] ? iosdbg_lines[iosdbg_i] : "-"];
  }
  iosdbg_label.text = iosdbg_all;
  /* The root view controller's view may be attached to the window after this
   * label is created; keep the read-out on top of it. */
  [iosdbg_label.superview bringSubviewToFront:iosdbg_label];
}

extern "C" void iosdbg_slot(int idx, const char *text)
{
  if (idx < 0 || idx >= IOSDBG_SLOTS) {
    return;
  }
  snprintf(iosdbg_lines[idx], sizeof(iosdbg_lines[idx]), "%s", text ? text : "");
  iosdbg_repaint();
}

static void iosdbg_install(UIWindow *iosdbg_root,
                           CGSize iosdbg_size,
                           CGSize iosdbg_px,
                           CGFloat iosdbg_view_scale,
                           CGFloat iosdbg_screen_scale)
{
  if (iosdbg_root == nil || iosdbg_label != nil) {
    return;
  }
  {
    char iosdbg_buf[192];
    snprintf(iosdbg_buf,
             sizeof(iosdbg_buf),
             "VIEW %dx%d px=%dx%d view=%.2f screen=%.2f",
             int(iosdbg_size.width),
             int(iosdbg_size.height),
             int(iosdbg_px.width),
             int(iosdbg_px.height),
             double(iosdbg_view_scale),
             double(iosdbg_screen_scale));
    iosdbg_slot(6, iosdbg_buf);
  }
  const CGFloat iosdbg_h = 94.0;
  iosdbg_label = [[UILabel alloc]
      initWithFrame:CGRectMake(4.0, iosdbg_size.height - iosdbg_h - 4.0, iosdbg_size.width - 8.0,
                               iosdbg_h)];
  iosdbg_label.numberOfLines = 0;
  iosdbg_label.font = [UIFont monospacedSystemFontOfSize:9.0 weight:UIFontWeightRegular];
  iosdbg_label.textColor = [UIColor colorWithWhite:1.0 alpha:0.95];
  iosdbg_label.backgroundColor = [UIColor colorWithWhite:0.0 alpha:0.55];
  iosdbg_label.userInteractionEnabled = NO;
  [iosdbg_root addSubview:iosdbg_label];
  [iosdbg_root bringSubviewToFront:iosdbg_label];
  iosdbg_repaint();
}
'''

INSTALL_ANCHOR = """  pencil_interaction = [[UIPencilInteraction alloc] init];
  pencil_interaction.delegate = self;
  [window->getView() addInteraction:pencil_interaction];"""

INSTALL_NEW = INSTALL_ANCHOR + """
  /* IOS-PROBE: create the diagnostic read-out once the view exists. */
  iosdbg_install(window->rootWindow,
                 [window->getView() bounds].size,
                 window->getNativeWindowSize(),
                 [window->getView() contentScaleFactor],
                 [[UIScreen mainScreen] scale]);"""

# slot 0: handleTap
TAP_ANCHOR = "  last_tap_with_pencil = current_pencil_touch ? true : false;"
TAP_NEW = TAP_ANCHOR + """
  {
    char iosdbg_buf[192];
    iosdbg_taps++;
    snprintf(iosdbg_buf,
             sizeof(iosdbg_buf),
             "TAP n=%d xy=(%d,%d) st=%d pencil=%d",
             iosdbg_taps,
             int(touch_point.x),
             int(touch_point.y),
             int(sender.state),
             int(last_tap_with_pencil) != 0);
    iosdbg_slot(0, iosdbg_buf);
  }"""

# slot 4: handlePan returns while our left-button drag is running, mark it.
PAN_ANCHOR = """  if (iosptr_down) {
    /* IOS-PTR: the same single finger is already driving a left-button drag.
     * Letting this also emit a MOUSEPAN scroll would fight it. */
    return;
  }"""
PAN_NEW = PAN_ANCHOR + """
  iosdbg_slot(4, "PAN suppressed (drag running)");"""

# slot 0: a real press reached the view touch callbacks
PRESS_ANCHOR = """    fprintf(stdout, "[IOSPTR] down n=%d type=%d\\n", iosptr_presses, int(iosptr_touch.type));"""
PRESS_NEW = PRESS_ANCHOR + """
    {
      char iosdbg_buf[192];
      snprintf(iosdbg_buf,
               sizeof(iosdbg_buf),
               "PRESS n=%d xy=(%d,%d) type=%d",
               iosptr_presses,
               int(iosptr_p.x),
               int(iosptr_p.y),
               int(iosptr_touch.type));
      iosdbg_slot(0, iosdbg_buf);
    }"""

# slot 1: live drag read-out
MOVE_ANCHOR = """    iosptr_last = iosptr_p;

    UserInputEvent iosptr_move(&iosptr_p, nullptr, nullptr, false);"""
MOVE_NEW = """    iosptr_last = iosptr_p;
    {
      char iosdbg_buf[192];
      snprintf(iosdbg_buf,
               sizeof(iosdbg_buf),
               "MOVE xy=(%d,%d) d=%d hold=%d",
               int(iosptr_p.x),
               int(iosptr_p.y),
               int(iosptr_p.x - iosptr_start.x),
               int(iosptr_down) != 0);
      iosdbg_slot(1, iosdbg_buf);
    }

    UserInputEvent iosptr_move(&iosptr_p, nullptr, nullptr, false);"""

RELEASE_ANCHOR = """  fprintf(stdout, "[IOSPTR] up moved=%d\\n", int(iosptr_moved));"""
RELEASE_NEW = RELEASE_ANCHOR + """
  {
    char iosdbg_buf[192];
    snprintf(iosdbg_buf,
             sizeof(iosdbg_buf),
             "UP xy=(%d,%d) moved=%d",
             int(iosptr_p.x),
             int(iosptr_p.y),
             int(iosptr_moved));
    iosdbg_slot(4, iosdbg_buf);
  }"""

MULTI_ANCHOR = """      fprintf(stdout, "[IOSPTR] up (multi-touch)\\n");"""
MULTI_NEW = MULTI_ANCHOR + """
      iosdbg_slot(4, "UP  multi-touch, drag aborted");"""

# ---------------------------------------------------------------------------
# 2. the window-manager probe (wm_event_system.cc)
# ---------------------------------------------------------------------------

WM_DECL_ANCHOR = "#include <cstdio> /* IOSDBG-INCLUDE */"
WM_DECL_NEW = """#include <cstdio> /* IOSDBG-INCLUDE */

#if defined(__APPLE__)
/* IOS-PROBE: implemented in GHOST_WindowIOS.mm, paints the on-screen read-out. */
extern "C" void iosdbg_slot(int idx, const char *text);
#endif"""

WM_PROBE_ANCHOR = """  if (iosdbg_log) {
    fprintf(stderr, "[IOSDBG]   -> action=%d\\n", int(iosdbg_action));
  }
  return iosdbg_action;"""

WM_PROBE_NEW = """  if (iosdbg_log) {
    fprintf(stderr, "[IOSDBG]   -> action=%d\\n", int(iosdbg_action));
#if defined(__APPLE__)
    {
      const char *iosdbg_name = (event->type == MOUSEMOVE)    ? "MOVE" :
                                (event->type == LEFTMOUSE)   ? "LMB" :
                                (event->type == MIDDLEMOUSE) ? "MMB" :
                                (event->type == RIGHTMOUSE)  ? "RMB" :
                                (event->type == MOUSEPAN)    ? "PAN" :
                                                               "KEY";
      const wmWindow *iosdbg_win = CTX_wm_window(C);
      char iosdbg_buf[192];
      snprintf(iosdbg_buf,
               sizeof(iosdbg_buf),
               "WM %s ev=%d v=%d xy=(%d,%d) a=%d r=%d act=%d win=%dx%d",
               iosdbg_name,
               int(event->type),
               int(event->val),
               event->xy[0],
               event->xy[1],
               int(area->spacetype),
               region_hovered ? int(region_hovered->regiontype) : -1,
               int(iosdbg_action),
               iosdbg_win ? int(iosdbg_win->sizex) : 0,
               iosdbg_win ? int(iosdbg_win->sizey) : 0);
      iosdbg_slot(2, iosdbg_buf);
      if (event->type != MOUSEMOVE) {
        iosdbg_slot(3, iosdbg_buf);
        /* Only non-motion events reach the log, mouse-moves would flood it. */
        fprintf(stdout, "[IOSPROBE] %s\\n", iosdbg_buf);
      }
    }
#endif
  }
  return iosdbg_action;"""

# ---------------------------------------------------------------------------
# 3. report where the log went (GHOST_SystemIOS.mm)
# ---------------------------------------------------------------------------

SYS_DECL_ANCHOR = "int main_ios_callback(int argc, const char **argv);"
SYS_DECL_NEW = SYS_DECL_ANCHOR + """

#if defined(__APPLE__)
/* IOS-PROBE: implemented in GHOST_WindowIOS.mm. */
extern "C" void iosdbg_slot(int idx, const char *text);
#endif"""

SYS_LOG_ANCHOR = """      fprintf(stderr, "[IOSDBG] === IOSDBG-LOG-START ===\\n");"""
SYS_LOG_NEW = SYS_LOG_ANCHOR + """
      {
        char iosdbg_buf[192];
        snprintf(iosdbg_buf,
                 sizeof(iosdbg_buf),
                 "LOG  %s",
                 iosdbg_cpath ? iosdbg_cpath : "(no path)");
        iosdbg_slot(5, iosdbg_buf);
      }"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def apply(path, edits):
    text = read(path)
    applied = 0
    for old, new, label, marker, *rest in edits:
        times = rest[0] if rest else 1
        if marker in text:
            print("  skip    %s (%s already applied)" % (path, label))
            continue
        found = text.count(old)
        if found != times:
            raise SystemExit("anchor %r not unique/found in %s (%d hits, want %d)"
                             % (label, path, found, times))
        text = text.replace(old, new, times)
        applied += 1
    write(path, text)
    return applied


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    win = os.path.join(root, "intern/ghost/intern/GHOST_WindowIOS.mm")
    wm = os.path.join(root, "source/blender/windowmanager/intern/wm_event_system.cc")
    sysios = os.path.join(root, "intern/ghost/intern/GHOST_SystemIOS.mm")
    for p in (win, wm, sysios):
        if not os.path.exists(p):
            raise SystemExit("missing file: " + p)

    text = read(win)
    if MARK + ": overlay" not in text:
        anchor = "} UserInputEvent;"
        text = text.replace(anchor, anchor + "\n/* %s: overlay */" % MARK + OVERLAY, 1)
        write(win, text)

    n = apply(win, [
        (INSTALL_ANCHOR, INSTALL_NEW, "install overlay", "iosdbg_install(window->rootWindow"),
        (TAP_ANCHOR, TAP_NEW, "tap slot", "TAP n=%d xy=(%d,%d) st=%d"),
        (PAN_ANCHOR, PAN_NEW, "pan slot", "PAN  indirect -> suppressed"),
        (PRESS_ANCHOR, PRESS_NEW, "press slot", "PRESS n=%d xy=(%d,%d) type=%d"),
        (MOVE_ANCHOR, MOVE_NEW, "move slot", "MOVE xy=(%d,%d) d=%d hold=%d"),
        (RELEASE_ANCHOR, RELEASE_NEW, "release slot", "UP xy=(%d,%d) moved=%d"),
        (MULTI_ANCHOR, MULTI_NEW, "multi-touch slot", "UP  multi-touch, drag aborted"),
    ])
    print("  patched %s (%d rules)" % (win, n))

    m = apply(wm, [(WM_DECL_ANCHOR, WM_DECL_NEW, "iosdbg_slot decl",
                    'extern "C" void iosdbg_slot(int idx, const char *text);'),
                   (WM_PROBE_ANCHOR, WM_PROBE_NEW, "wm probe", "iosdbg_slot(2, iosdbg_buf);")])
    print("  patched %s (%d rules)" % (wm, m))

    s = apply(sysios, [(SYS_DECL_ANCHOR, SYS_DECL_NEW, "iosdbg_slot decl",
                        'extern "C" void iosdbg_slot(int idx, const char *text);'),
                       (SYS_LOG_ANCHOR, SYS_LOG_NEW, "log slot", "LOG  %s")])
    print("  patched %s (%d rules)" % (sysios, s))

    # Sanity: brace balance of the overlay block, catches a truncated edit early.
    block = OVERLAY
    if block.count("{") != block.count("}"):
        raise SystemExit("overlay braces unbalanced: %d vs %d"
                         % (block.count("{"), block.count("}")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
