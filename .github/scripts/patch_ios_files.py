#!/usr/bin/env python3
"""Make the iOS file browser land in a writable, user-reachable directory.

Why this is needed
------------------
On iOS the process `HOME` is the sandbox container root
(`/var/mobile/Containers/Data/Application/<UUID>`), and that directory is **read only**:
only `Documents/`, `Library/` and `tmp/` may be written.

The iOS port routes `BKE_appdir_folder_default()` straight to `BLI_dir_home()`, so:

  * "Export As" / "Save As" / "Save a Copy" pre-fill an unwritable directory and fail;
  * File > Open starts in the container root, where nothing the user dropped in is visible;
  * `BKE_appdir_folder_default_or_root()` even prefers `BLENDER_RESOURCE_PATH_LOCAL`
    (`WITH_APPLE_CROSSPLATFORM` branch), which resolves inside the read-only .app bundle.

`UIFileSharingEnabled` is already `true`, so `Documents/` is exactly the folder that shows
up as "On My iPad / Blender" in the Files app.  Using it fixes import *and* export without
needing a `UIDocumentPickerViewController`.

Three edits in `source/blender/blenkernel/intern/appdir.cc`:

1. `BKE_appdir_folder_default()`  -> `$HOME/Documents` when it exists (flag keeps the
   information for edit 2 through a file-static).
2. `BKE_appdir_folder_default_or_root()` -> stop preferring the app bundle.
3. `BKE_appdir_folder_home()` -> keep the real sandbox `HOME`, so user config keeps living
   in `HOME/Library/Application Support/Blender/...` instead of spilling into Documents/.

Idempotent: anchored on the `IOS-FILES` marker, skipped when already applied.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-FILES"

OLD_DEFAULT = """const char *BKE_appdir_folder_default()
{
#ifndef WIN32
  return BLI_dir_home();
#else  /* Windows */"""

NEW_DEFAULT = """/** @MARK@: set by #BKE_appdir_folder_default() when $HOME/Documents exists. */
static bool iosfiles_have_documents = false;

const char *BKE_appdir_folder_default()
{
#ifndef WIN32
  /* @MARK@: on iOS the process HOME is the read-only sandbox container root, so "Save As"
   * and export filled in an unwritable directory, and the file browser opened an empty
   * folder with nothing the user could have put there.  Documents/ is the one writable
   * location that is also visible in the Files app (UIFileSharingEnabled is on). */
  static char iosfiles_documents[FILE_MAXDIR];
  const char *iosfiles_home = BLI_dir_home();
  if (iosfiles_home != nullptr && iosfiles_home[0] != '\\0') {
    BLI_path_join(iosfiles_documents, sizeof(iosfiles_documents), iosfiles_home, "Documents");
    if (BLI_is_dir(iosfiles_documents)) {
      iosfiles_have_documents = true;
      return iosfiles_documents;
    }
  }
  iosfiles_have_documents = false;
  return iosfiles_home;
#else  /* Windows */"""

OLD_OR_ROOT = """#ifdef WITH_APPLE_CROSSPLATFORM
  const std::optional<std::string> def_path = BKE_appdir_resource_path_id_with_version(
      BLENDER_RESOURCE_PATH_LOCAL, true, BLENDER_VERSION);
  if (def_path.has_value()) {
    return def_path->c_str();
  }
#endif

  const char *path = BKE_appdir_folder_default();"""

NEW_OR_ROOT = """#ifdef WITH_APPLE_CROSSPLATFORM
  /* @MARK@: BLENDER_RESOURCE_PATH_LOCAL resolves inside the read-only .app bundle, so this
   * branch made the file browser open a directory that cannot be written to.  Ask
   * BKE_appdir_folder_default() first: it settles on Documents/ on iOS and records that in
   * #iosfiles_have_documents. */
  const char *iosfiles_default = BKE_appdir_folder_default();
  if (iosfiles_have_documents) {
    return iosfiles_default;
  }
  const std::optional<std::string> def_path = BKE_appdir_resource_path_id_with_version(
      BLENDER_RESOURCE_PATH_LOCAL, true, BLENDER_VERSION);
  if (def_path.has_value()) {
    return def_path->c_str();
  }
#endif

  const char *path = BKE_appdir_folder_default();"""

OLD_HOME = """const char *BKE_appdir_folder_home()
{
#ifdef WITH_APPLE_CROSSPLATFORM
  return BKE_appdir_folder_default_or_root();
#else
  return BLI_dir_home();
#endif
}"""

NEW_HOME = """const char *BKE_appdir_folder_home()
{
  /* @MARK@: keep the real sandbox HOME.  Routing this through default_or_root() pointed the
   * user config at the read-only app bundle, and would now move it into Documents/ (which
   * the user is supposed to see).  HOME/Library is writable on iOS, so the normal
   * "Library/Application Support/Blender/<version>" layout works unchanged. */
  return BLI_dir_home();
}"""


def patch(path: Path, old: str, new: str, marker: str) -> str:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return "already"
    if text.count(old) != 1:
        raise SystemExit(f"{path}: anchor not unique ({text.count(old)} hits)")
    path.write_text(text.replace(old, new), encoding="utf-8")
    return "patched"


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    target = root / "source/blender/blenkernel/intern/appdir.cc"
    if not target.exists():
        print(f"::error::missing {target}")
        return 1
    rules = (
        ("IOS-FILES-DEFAULT", OLD_DEFAULT, NEW_DEFAULT),
        ("IOS-FILES-ORROOT", OLD_OR_ROOT, NEW_OR_ROOT),
        ("IOS-FILES-HOME", OLD_HOME, NEW_HOME),
    )
    for marker, old, new in rules:
        state = patch(target, old.replace("@MARK@", marker), new.replace("@MARK@", marker), marker)
        print(f"  {state:8s} {target.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
