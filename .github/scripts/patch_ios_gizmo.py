#!/usr/bin/env python3
"""Guard against NULL wmOperatorType in the 3D view navigation gizmo.

Upstream ios branch already documents the problem in view3d_gizmo_navigate.cc:

    /*
     IOS_FIXME: This sometimes returns NULL on iOS, stepping into the function
     in the debugger fixes it. Possible race condition somewhere?
     */

...but the guard that follows is `#ifndef WITH_PYTHON if (ot != nullptr) #endif`,
so any WITH_PYTHON build skips the check and passes NULL to
WM_gizmo_operator_set() -> WM_operator_properties_create_ptr() which dereferences
it at offset 0x88 (observed: EXC_BAD_ACCESS KERN_INVALID_ADDRESS 0x88).

Guard every call site unconditionally. The navigation gizmo then simply loses
the buttons whose operator could not be resolved instead of aborting the app.
"""
import os
import sys

DEFAULT_TARGET = "source/blender/editors/space_view3d/view3d_gizmo_navigate.cc"
MARKER = "IOS_FIXME: WM_operatortype_find() is documented"

RULES = [
    (
        """    wmOperatorType *ot = WM_operatortype_find(info->opname, true);
#ifndef WITH_PYTHON
    if (ot != nullptr)
#endif
    {
""",
        """    wmOperatorType *ot = WM_operatortype_find(info->opname, true);
    /* IOS_FIXME: WM_operatortype_find() is documented to return NULL on iOS (see
     * the comment above). The WITH_PYTHON guard assumed that can never happen,
     * but it does, and WM_gizmo_operator_set(NULL) crashes inside
     * WM_operator_properties_create_ptr(). Guard unconditionally. */
    if (ot != nullptr)
    {
""",
    ),
    (
        """  {
    wmGizmo *gz = navgroup->gz_array[GZ_INDEX_CAMERA_OFF];
    WM_gizmo_operator_set(gz, 0, ot_view_camera, nullptr);
  }
  {
    wmGizmo *gz = navgroup->gz_array[GZ_INDEX_CAMERA_ON];
    WM_gizmo_operator_set(gz, 0, ot_view_camera, nullptr);
  }
""",
        """  if (ot_view_camera != nullptr) {
    wmGizmo *gz = navgroup->gz_array[GZ_INDEX_CAMERA_OFF];
    WM_gizmo_operator_set(gz, 0, ot_view_camera, nullptr);
  }
  if (ot_view_camera != nullptr) {
    wmGizmo *gz = navgroup->gz_array[GZ_INDEX_CAMERA_ON];
    WM_gizmo_operator_set(gz, 0, ot_view_camera, nullptr);
  }
""",
    ),
    (
        """      PointerRNA *ptr = WM_gizmo_operator_set(gz, part_index + 1, ot_view_axis, nullptr);
      RNA_enum_set(ptr, "type", mapping[part_index]);
""",
        """      if (ot_view_axis != nullptr) {
        PointerRNA *ptr = WM_gizmo_operator_set(gz, part_index + 1, ot_view_axis, nullptr);
        RNA_enum_set(ptr, "type", mapping[part_index]);
      }
""",
    ),
    (
        """      wmGizmoOpElem *gzop = WM_gizmo_operator_get(gz, 0);
      RNA_boolean_set(&gzop->ptr, "use_cursor_init", false);
""",
        """      wmGizmoOpElem *gzop = WM_gizmo_operator_get(gz, 0);
      if (gzop != nullptr) {
        RNA_boolean_set(&gzop->ptr, "use_cursor_init", false);
      }
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
        if old not in src:
            print("::error::anchor %d not found in %s" % (idx, target))
            return 1
        src = src.replace(old, new, 1)

    open(target, "w", encoding="utf-8").write(src)
    print("patched %s (%d rules)" % (target, len(RULES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
