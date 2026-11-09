#!/usr/bin/env python3
"""Stop one unusable operator from discarding the whole key-map preset.

The chain that left the iPad unable to move the 3D view
--------------------------------------------------------
``WM_keyconfig_init()`` -> ``WM_keyconfig_reload()`` ->
``bpy.utils.keyconfig_init()`` -> ``keyconfig_set()`` -> ``execfile(Blender.py)``
-> ``keyconfig_init_from_data()`` -> ``keymap_init_from_data()``.

The preset has 3182 items and 278 key-maps.  On the iPad only **12** survive.

Measured on the local 5.1.2 build (same code, same preset):

* ``km.keymap_items.new("bogus.operator", ...)`` does **not** raise -- the item is
  created with the unknown id-name, so a missing operator is not fatal *by
  itself*.
* ``kmi.properties.name = "builtin.select_box"`` **does** raise
  ``AttributeError: 'OperatorProperties' object has no attribute 'name'`` when
  the operator is unregistered -- an unregistered operator exposes an empty
  property struct.

And the preset really does write properties on Python-only operators:

    blender_default.py:306  return ("wm.tool_set_by_id", kmi_args,
                                    {"properties": [("name", tool)]})

``wm.tool_set_by_id`` lives in ``scripts/startup/bl_operators/wm.py`` and was
**not registered** on the iPad (v20 log: ``[IOSOP] ... tool_set=0 dropblend=0``,
``UILayout.operator_menu_hold(): unknown operator 'wm.tool_set_by_id'``).
So the first tool item throws, ``execfile`` unwinds, ``keyconfig_set()`` reports
failure, removes the half-built config, and every short-cut -- including
``MIDDLEMOUSE -> view3d.rotate`` -- is gone.

Fixing the registration is the real repair (``patch_ios_keymap_c.py`` also tries
to re-register ``bl_operators`` on the device).  This patch is the safety net
that is independent of it: an unusable item must cost exactly one item.

Where
-----
``scripts/modules/bl_keymap_utils/io.py`` -- one call site, no recompile, but it
**must** be force-synced into the app bundle (workflow step
``Force-sync patched python data``).

``[IOSKMI]`` lines go straight to fd 1 on purpose: Python's ``print()`` is
buffered and never flushed before the app is killed, so ``print()`` diagnostics
are invisible in the device log.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARK = "IOS-KMI-SKIP"

DEFAULT_TARGET = "scripts/modules/bl_keymap_utils/io.py"

OLD_OUTER = '''def keyconfig_init_from_data(kc, keyconfig_data):
    # Load data in the format defined above.
    #
    # Runs at load time, keep this fast!
    for (km_name, km_args, km_content) in keyconfig_data:
        km = kc.keymaps.new(km_name, **km_args)
        km_items = km_content["items"]
        # Check here instead of inside 'keymap_init_from_data'
        # because we want to allow both tuple & list types in that case.
        #
        # For full keymaps, ensure these are always lists to allow for extending them
        # in a generic way that doesn't have to check for the type each time.
        assert type(km_items) is list
        keymap_init_from_data(km, km_items, is_modal=km_args.get("modal", False))
'''

NEW_OUTER = '''def keyconfig_init_from_data(kc, keyconfig_data):
    # Load data in the format defined above.
    #
    # Runs at load time, keep this fast!
    #
    # @MARK@: a single malformed key-map must not abort the rest.  Before this,
    # one exception anywhere in here unwound `execfile()` and every other
    # key-map was thrown away with it (12 items survive out of 3182).
    _ios_km_total = 0
    for (km_name, km_args, km_content) in keyconfig_data:
        try:
            km = kc.keymaps.new(km_name, **km_args)
            km_items = km_content["items"]
            # Check here instead of inside 'keymap_init_from_data'
            # because we want to allow both tuple & list types in that case.
            #
            # For full keymaps, ensure these are always lists to allow for extending them
            # in a generic way that doesn't have to check for the type each time.
            assert type(km_items) is list
            keymap_init_from_data(km, km_items, is_modal=km_args.get("modal", False))
        except Exception as _ios_ex:
            _ios_kmi_skip(km_name, "<whole key-map>", _ios_ex)
            continue
        _ios_km_total += 1
    try:
        import os
        os.write(1, ("[IOSKMI] applied %d/%d key-maps, skipped %d items\\n"
                     % (_ios_km_total, len(keyconfig_data), _IOS_KMI_SKIP_COUNT))
                 .encode("utf-8", "replace"))
    except Exception:
        pass
'''.replace("@MARK@", MARK)

OLD = '''def keymap_init_from_data(km, km_items, is_modal=False):
    new_fn = getattr(km.keymap_items, "new_modal" if is_modal else "new")
    for (kmi_idname, kmi_args, kmi_data) in km_items:
        kmi = new_fn(kmi_idname, **kmi_args)
        if kmi_data is not None:
            if not kmi_data.get("active", True):
                kmi.active = False
            kmi_props_data = kmi_data.get("properties", None)
            if kmi_props_data is not None:
                kmi_props = kmi.properties
                assert type(kmi_props_data) is list
                _init_properties_from_data(kmi_props, kmi_props_data)
'''

NEW = '''_IOS_KMI_SKIP_COUNT = 0


def _ios_kmi_skip(km_name, kmi_idname, ex):
    # @MARK@: report the item that could not be created, then keep going.
    # `os.write` instead of `print`: nothing flushes Python's stdout on iOS, so
    # a buffered diagnostic never reaches the device log.
    global _IOS_KMI_SKIP_COUNT
    _IOS_KMI_SKIP_COUNT += 1
    if _IOS_KMI_SKIP_COUNT > 60:
        return
    try:
        import os
        os.write(1, ("[IOSKMI] skip %s :: %s (%s)\\n" % (km_name, kmi_idname, ex))
                 .encode("utf-8", "replace"))
    except Exception:
        pass


def keymap_init_from_data(km, km_items, is_modal=False):
    new_fn = getattr(km.keymap_items, "new_modal" if is_modal else "new")
    for (kmi_idname, kmi_args, kmi_data) in km_items:
        # @MARK@: one bad item used to unwind `execfile()` and throw away the
        # other ~3000 short-cuts.  An operator that is not registered still gets
        # a key-map item, but `kmi.properties` is then an empty struct, so
        # writing the preset's properties raises `AttributeError`.
        try:
            kmi = new_fn(kmi_idname, **kmi_args)
            if kmi_data is not None:
                if not kmi_data.get("active", True):
                    kmi.active = False
                kmi_props_data = kmi_data.get("properties", None)
                if kmi_props_data is not None:
                    kmi_props = kmi.properties
                    assert type(kmi_props_data) is list
                    _init_properties_from_data(kmi_props, kmi_props_data)
        except Exception as _ios_ex:
            _ios_kmi_skip(getattr(km, "name", "?"), kmi_idname, _ios_ex)
            continue
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
        (OLD_OUTER, NEW_OUTER, "keyconfig_init_from_data"),
        (OLD, NEW, "keymap_init_from_data"),
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
