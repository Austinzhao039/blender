# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: BSD-3-Clause

if(DEFINED fmt_ROOT)
  # Pass.
elseif(DEFINED ENV{fmt_ROOT})
  set(fmt_ROOT $ENV{fmt_ROOT})
else()
  set(fmt_ROOT "")
endif()

set(_fmt_CONFIG_DIRS)
if(DEFINED fmt_DIR)
  list(APPEND _fmt_CONFIG_DIRS ${fmt_DIR})
endif()
if(fmt_ROOT)
  list(APPEND _fmt_CONFIG_DIRS
    ${fmt_ROOT}
    ${fmt_ROOT}/lib/cmake/fmt
    ${fmt_ROOT}/lib64/cmake/fmt
  )
endif()

if(_fmt_CONFIG_DIRS)
  find_package(fmt QUIET CONFIG PATHS ${_fmt_CONFIG_DIRS} NO_DEFAULT_PATH)
else()
  find_package(fmt QUIET CONFIG)
endif()

if(TARGET fmt::fmt)
  set(fmt_FOUND TRUE)
  get_target_property(fmt_INCLUDE_DIRS fmt::fmt INTERFACE_INCLUDE_DIRECTORIES)
else()
  set(_fmt_SEARCH_DIRS ${fmt_ROOT})

  find_path(fmt_INCLUDE_DIR
    NAMES
      fmt/format.h
    HINTS
      ${_fmt_SEARCH_DIRS}
    PATH_SUFFIXES
      include
  )

  find_library(fmt_LIBRARY
    NAMES
      fmt
      libfmt
    HINTS
      ${_fmt_SEARCH_DIRS}
    PATH_SUFFIXES
      lib64 lib
  )

  if(EXISTS "${fmt_INCLUDE_DIR}/fmt/core.h")
    file(STRINGS "${fmt_INCLUDE_DIR}/fmt/core.h" _fmt_version_string
      REGEX "^#define FMT_VERSION [0-9]+$")
    if(_fmt_version_string)
      string(REGEX REPLACE ".* ([0-9]+)$" "\\1" _fmt_version_int "${_fmt_version_string}")
      math(EXPR _fmt_version_major "${_fmt_version_int} / 10000")
      math(EXPR _fmt_version_minor "(${_fmt_version_int} / 100) % 100")
      math(EXPR _fmt_version_patch "${_fmt_version_int} % 100")
      set(fmt_VERSION "${_fmt_version_major}.${_fmt_version_minor}.${_fmt_version_patch}")
      unset(_fmt_version_major)
      unset(_fmt_version_minor)
      unset(_fmt_version_patch)
      unset(_fmt_version_int)
    endif()
    unset(_fmt_version_string)
  endif()

  include(FindPackageHandleStandardArgs)
  find_package_handle_standard_args(fmt
    REQUIRED_VARS fmt_INCLUDE_DIR
    VERSION_VAR fmt_VERSION)

  if(fmt_FOUND)
    set(fmt_INCLUDE_DIRS ${fmt_INCLUDE_DIR})
    set(fmt_LIBRARIES ${fmt_LIBRARY})

    if(NOT TARGET fmt::fmt)
      if(fmt_LIBRARY)
        add_library(fmt::fmt UNKNOWN IMPORTED GLOBAL)
        set_target_properties(fmt::fmt PROPERTIES
          IMPORTED_LOCATION "${fmt_LIBRARY}"
          INTERFACE_INCLUDE_DIRECTORIES "${fmt_INCLUDE_DIR}")
      else()
        add_library(fmt::fmt INTERFACE IMPORTED GLOBAL)
        set_target_properties(fmt::fmt PROPERTIES
          INTERFACE_COMPILE_DEFINITIONS "FMT_HEADER_ONLY=1"
          INTERFACE_INCLUDE_DIRECTORIES "${fmt_INCLUDE_DIR}")
      endif()
    endif()
  endif()

  unset(_fmt_SEARCH_DIRS)
endif()

mark_as_advanced(
  fmt_INCLUDE_DIR
  fmt_LIBRARY
)

unset(_fmt_CONFIG_DIRS)
