#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This script must run on macOS.\n' >&2
  exit 1
fi

if [[ "$#" -eq 0 ]]; then
  set -- fmt
fi

build_dir="${IOS_DEPS_BOOTSTRAP_BUILD_DIR:-${repo_root}/build_deps_ios_bootstrap}"
host_build_dir="${IOS_HOST_DEPS_BUILD_DIR:-$(cd "${repo_root}/.." && pwd)/build_macos}"
host_install_dir="${IOS_HOST_DEPS_INSTALL_DIR:-${repo_root}/lib/macos_arm64}"

cmake -S "${repo_root}/build_files/build_environment" \
  -B "${build_dir}" \
  -DAPPLE_TARGET_DEVICE=ios \
  -DHARVEST_TARGET="${repo_root}/lib/ios_arm64" \
  -DCMAKE_DEPS_CROSSCOMPILE_BUILDDIR="${host_build_dir}" \
  -DCMAKE_DEPS_CROSSCOMPILE_INSTALLDIR="${host_install_dir}"

parallel_jobs="${IOS_DEPS_BOOTSTRAP_JOBS:-$(sysctl -n hw.logicalcpu)}"

for dep in "$@"; do
  target="${dep}"
  if [[ "${target}" != external_* ]]; then
    target="external_${target}"
  fi
  cmake --build "${build_dir}" --target "${target}" --parallel "${parallel_jobs}"
done
