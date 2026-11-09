#!/usr/bin/env python3
"""Make a failed key-configuration load visible in the device log.

Why
---
``bpy.utils.keyconfig_set()`` already catches the exception raised while running
the preset and then does ``print(error_msg)``.  On iOS that message never
appears: Python writes to a buffered stream that nothing flushes before the app
is killed, so **every** Python-side diagnostic in the previous builds was
invisible (v20 printed four ``[IOSPY]`` lines and the log contained zero).

Meanwhile the C side (``printf``) is visible and flushes fine.  So the cheapest
honest instrument is to write from Python straight to fd 1 with ``os.write``.

What it logs
------------
    [IOSKC] keyconfig_set '/…/presets/keyconfig/Blender.py'
    [IOSKC] OK 'Blender' kms=278 items=3182
    or
    [IOSKC] FAILED '/…/presets/keyconfig/Blender.py'
    <full traceback>

If ``keyconfig_set`` is never called at all, neither line shows up -- that is
also an answer, and it rules the preset out in one build.

Idempotent: guarded by the ``IOS-KCSET`` marker.  Target file must be
force-synced into the app bundle.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-KCSET"

DEFAULT_TARGET = "scripts/modules/bpy/utils/__init__.py"

OLD = '''    # Store the old key-configuration case of error, to know if it should be removed or not on failure.
    kc_old = keyconfigs.get(name)

    try:
        error_msg = ""
        execfile(filepath)
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
'''

NEW = '''    # Store the old key-configuration case of error, to know if it should be removed or not on failure.
    kc_old = keyconfigs.get(name)

    # @MARK@: `print()` is buffered and never flushed on iOS, so a failure here
    # used to be completely silent.  Write to fd 1, which the device log keeps.
    _ios_fd = None
    try:
        import os as _ios_os
        _ios_fd = 1
        _ios_os.write(1, ("[IOSKC] keyconfig_set %r\\n" % (filepath,)).encode("utf-8", "replace"))
    except Exception:
        _ios_fd = None

    try:
        error_msg = ""
        execfile(filepath)
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        try:
            if _ios_fd is not None:
                _ios_os.write(1, ("[IOSKC] FAILED %r\\n%s\\n" % (filepath, error_msg))
                              .encode("utf-8", "replace"))
        except Exception:
            pass
'''.replace("@MARK@", MARK)

OLD_OK = '''    else:
        keyconfigs.active = kc_new
        return True
'''

NEW_OK = '''    else:
        keyconfigs.active = kc_new
        # @MARK@: report the result, so "the preset loaded but produced nothing"
        # and "the preset never ran" can be told apart from the log alone.
        try:
            _kc_n = sum(len(km.keymap_items) for km in kc_new.keymaps)
            _ios_os.write(1, ("[IOSKC] OK %r kms=%d items=%d\\n"
                              % (kc_new.name, len(kc_new.keymaps), _kc_n))
                          .encode("utf-8", "replace"))
        except Exception:
            pass
        return True
'''.replace("@MARK@", MARK)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET)
    if not target.is_file():
        print(f"::error::missing file {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if MARK in text:
        print(f"  already  {target}")
        return 0

    for old, new, label in (
        (OLD, NEW, "keyconfig_set failure log"),
        (OLD_OK, NEW_OK, "keyconfig_set success log"),
    ):
        hits = text.count(old)
        if hits != 1:
            print(f"::error::{target}: anchor not unique ({hits} hits): {label}")
            return 1
        text = text.replace(old, new, 1)

    target.write_text(text, encoding="utf-8")
    print(f"  patched  {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
