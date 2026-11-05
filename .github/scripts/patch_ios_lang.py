#!/usr/bin/env python3
"""Make the iOS build start in the device language instead of English.

`UserDef.language` defaults to `ULANGUAGE_ENGLISH` (not `ULANGUAGE_AUTO`, see
`DNA_userdef_types.h`), and even `ULANGUAGE_AUTO` cannot work on iOS: that path
lets the locale library work the language out from the process environment, and
nothing on iOS sets `LANG`, so it always lands on "C" = English.  The device
language is only reachable through Foundation.

So:

* `GHOST_SystemIOS.mm` gets a tiny `extern "C"` helper that writes
  `[NSLocale preferredLanguages][0]` (`"zh-Hans-CN"`) into a caller buffer.
* `wm_init_exit.cc` maps that onto one of the locale codes shipped in
  `datafiles/locale/languages` (`zh_HANS`, `ja_JP`, `es`, ...) by looking the
  code up in the very table Blender builds its language menu from, so no list
  of languages is duplicated here.

It only runs when the preference is untouched (`ULANGUAGE_ENGLISH`, once per
install - a marker file in the user config dir remembers that) or explicitly
set to "Automatic".  A language the user picks by hand always wins.

Idempotent: guarded by the ``IOS-LANG`` marker.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-LANG"

# ---------------------------------------------------------------- GHOST side
GHOST_INCLUDE_ANCHOR = """#include "GHOST_SystemIOS.hh"

#include "GHOST_ContextIOS.hh\""""

GHOST_INCLUDE_NEW = """#include "GHOST_SystemIOS.hh"

/* IOS-LANG */
#include <cstdio>

#include "GHOST_ContextIOS.hh\""""

GHOST_ANCHOR = """GHOST_SystemIOS::GHOST_SystemIOS()
{"""

GHOST_NEW = """/* IOS-LANG: the device UI language, e.g. `zh-Hans-CN`, or "" when unknown.
 *
 * Exposed as a plain C symbol because the caller (`wm_init_exit.cc`) is a pure
 * C++ translation unit and cannot touch Objective-C.  Both ends live in the
 * same final link. */
extern "C" void ios_system_locale(char *buf, size_t buf_len)
{
  if (buf == nullptr || buf_len == 0) {
    return;
  }
  buf[0] = '\\0';
  NSString *code = nil;
  NSArray<NSString *> *preferred = [NSLocale preferredLanguages];
  if (preferred.count > 0) {
    code = preferred[0];
  }
  if (code.length == 0) {
    code = [[NSLocale currentLocale] localeIdentifier];
  }
  if (code.length == 0) {
    return;
  }
  snprintf(buf, buf_len, "%s", code.UTF8String);
}

""" + GHOST_ANCHOR

# ------------------------------------------------------------------ WM side
WM_INCLUDE_ANCHOR = """#include "BLT_lang.hh\""""

WM_INCLUDE_NEW = """#include "BLT_lang.hh"

/* IOS-LANG: `ios_system_locale` is defined in `GHOST_SystemIOS.mm`. */
extern "C" void ios_system_locale(char *buf, size_t buf_len);

#if defined(__APPLE__)
#  include <TargetConditionals.h>
#  define IOS_LANG_SUPPORTED TARGET_OS_IPHONE
#else
#  define IOS_LANG_SUPPORTED 0
#endif

#if IOS_LANG_SUPPORTED
#  include "RNA_types.hh" /* EnumPropertyItem */
#endif"""

WM_FUNC_ANCHOR = """void WM_init(bContext *C, int argc, const char **argv)
{"""

WM_FUNC_NEW = """#if IOS_LANG_SUPPORTED
/* IOS-LANG: find the locale Blender ships that matches the device language.
 *
 * `str` is the raw Foundation identifier, `"zh-Hans-CN"`.  It is normalised to
 * `"zh_HANS_CN"` (language lower-case, the remaining subtags upper-case - that
 * is how the locale directories are spelled) and tried against the locale table
 * built from `datafiles/locale/languages`, most specific form first. */
static const EnumPropertyItem *ios_language_match(const char *str)
{
  const EnumPropertyItem *items = BLT_lang_RNA_enum_properties();
  if (items == nullptr) {
    return nullptr;
  }

  /* Split the identifier into at most three subtags. */
  char sub[3][12] = {{0}};
  int num_sub = 0;
  int len = 0;
  for (const char *p = str; *p != '\\0' && num_sub < 3; p++) {
    char c = *p;
    if (c == '-' || c == '_' || c == '.') {
      sub[num_sub][len] = '\\0';
      num_sub++;
      len = 0;
      continue;
    }
    if (c >= 'a' && c <= 'z') {
      if (num_sub > 0) {
        c = char(c - 'a' + 'A');
      }
    }
    else if (c >= 'A' && c <= 'Z') {
      if (num_sub == 0) {
        c = char(c - 'A' + 'a');
      }
    }
    if (len < int(sizeof(sub[0])) - 1) {
      sub[num_sub][len++] = c;
    }
  }
  if (len > 0 && num_sub < 3) {
    sub[num_sub][len] = '\\0';
    num_sub++;
  }
  if (num_sub == 0) {
    return nullptr;
  }

  /* Candidates, most specific first: `zh_HANS_CN`, `zh_HANS`, `zh_CN`, `zh`.
   * The script form has to be tried before the country form, it is what decides
   * simplified vs traditional Chinese and both share the `zh` prefix. */
  char candidates[4][40];
  int num_cand = 0;
  if (num_sub >= 3) {
    snprintf(candidates[num_cand++], sizeof(candidates[0]), "%s_%s_%s", sub[0], sub[1], sub[2]);
  }
  if (num_sub >= 2) {
    snprintf(candidates[num_cand++], sizeof(candidates[0]), "%s_%s", sub[0], sub[1]);
  }
  if (num_sub >= 3) {
    snprintf(candidates[num_cand++], sizeof(candidates[0]), "%s_%s", sub[0], sub[2]);
  }
  snprintf(candidates[num_cand++], sizeof(candidates[0]), "%s", sub[0]);

  for (int i = 0; i < num_cand; i++) {
    for (const EnumPropertyItem *item = items; item->identifier != nullptr; item++) {
      if (item->value == 0) {
        continue; /* The "Automatic" entry, it has no translation of its own. */
      }
      if (BLI_strcasecmp(item->identifier, candidates[i]) == 0) {
        return item;
      }
    }
  }
  return nullptr;
}

static void ios_language_autodetect()
{
  /* "Automatic" asks for this on every start, a hand-picked language is left
   * alone - apart from the untranslated default, which is retried once. */
  const bool is_auto = (U.language == ULANGUAGE_AUTO);
  if (!is_auto && (U.language != ULANGUAGE_ENGLISH)) {
    return;
  }

  /* A directory in the user config folder is the "already decided" marker; it
   * needs no file handling and survives for as long as the install does. */
  const bool already_done = BKE_appdir_folder_id(BLENDER_USER_CONFIG, "ios_lang_v1").has_value();
  if (!is_auto && already_done) {
    return;
  }

  char sys_locale[64];
  ios_system_locale(sys_locale, sizeof(sys_locale));

  const EnumPropertyItem *match = (sys_locale[0] != '\\0') ? ios_language_match(sys_locale) :
                                                             nullptr;
  if (match != nullptr) {
    BLT_lang_set(match->identifier);
    if (!is_auto) {
      U.language = short(match->value);
    }
  }
  fprintf(stdout,
          "[IOSLANG] system=%s match=%s id=%d auto=%d\\n",
          sys_locale,
          match != nullptr ? match->identifier : "<none>",
          match != nullptr ? match->value : -1,
          int(is_auto));

  if (!is_auto && !already_done) {
    BKE_appdir_folder_id_create(BLENDER_USER_CONFIG, "ios_lang_v1");
  }
}
#endif /* IOS_LANG_SUPPORTED */

""" + WM_FUNC_ANCHOR

WM_CALL_ANCHOR = """  /* Call again to set from preferences. */
  BLT_lang_set(nullptr);
"""

WM_CALL_NEW = WM_CALL_ANCHOR + """
#if IOS_LANG_SUPPORTED
  /* IOS-LANG: nothing in the iOS environment describes a locale, so without
   * this the preference default ("English") would stick forever. */
  ios_language_autodetect();
#endif
"""


def patch(path: Path, rules: list[tuple[str, str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {path}")
        return
    for old, new, what in rules:
        if text.count(old) != 1:
            raise SystemExit(f"{path}: anchor not unique ({text.count(old)}): {what}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print(f"  patched  {path} ({len(rules)} rules)")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    ghost = root / "intern/ghost/intern/GHOST_SystemIOS.mm"
    wm = root / "source/blender/windowmanager/intern/wm_init_exit.cc"
    for f in (ghost, wm):
        if not f.is_file():
            print(f"::error::missing file {f}")
            return 1

    patch(ghost, [
        (GHOST_INCLUDE_ANCHOR, GHOST_INCLUDE_NEW, "ghost include"),
        (GHOST_ANCHOR, GHOST_NEW, "ghost helper"),
    ])
    patch(wm, [
        (WM_INCLUDE_ANCHOR, WM_INCLUDE_NEW, "wm include"),
        (WM_FUNC_ANCHOR, WM_FUNC_NEW, "wm autodetect"),
        (WM_CALL_ANCHOR, WM_CALL_NEW, "wm call"),
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
