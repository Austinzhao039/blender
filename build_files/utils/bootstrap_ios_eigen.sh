#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This script must run on macOS.\n' >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
target_dir="${1:-${repo_root}/lib/ios_arm64/eigen}"

eigen_version="${EIGEN_VERSION:-8a1083e9bf41b91fdea6546681f806154efdc25a}"
work_dir="${EIGEN_BOOTSTRAP_WORK_DIR:-${repo_root}/build_eigen_ios_bootstrap}"
source_dir="${work_dir}/eigen-${eigen_version}"
build_dir="${source_dir}/build_ios"
install_dir="${work_dir}/out"

rm -rf "${source_dir}" "${install_dir}"
mkdir -p "${work_dir}" "${target_dir}"

curl -L "https://gitlab.com/libeigen/eigen/-/archive/${eigen_version}/eigen-${eigen_version}.tar.gz" | tar xz -C "${work_dir}"

cmake -S "${source_dir}" -B "${build_dir}" \
  -DCMAKE_SYSTEM_NAME=iOS \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_INSTALL_PREFIX="${install_dir}" \
  -DBUILD_TESTING=OFF \
  -DEIGEN_BUILD_DOC=OFF

cmake --install "${build_dir}"

rm -rf "${target_dir}/include" "${target_dir}/share"
mkdir -p "${target_dir}"
cp -R "${install_dir}/include" "${target_dir}/include"
cp -R "${install_dir}/share" "${target_dir}/share"
