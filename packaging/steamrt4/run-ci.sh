#!/usr/bin/env bash
set -Eeuo pipefail

phase="initialize"
on_exit() {
    local status=$?
    if [[ "${status}" -ne 0 ]]; then
        echo "run-ci.sh: phase failed: ${phase} (exit ${status})" >&2
    fi
}
trap on_exit EXIT

source_root="${CI_SOURCE_ROOT:-/src}"
work_root="${CI_WORK_ROOT:?CI_WORK_ROOT must be set}"
output_dir="${CI_OUTPUT_DIR:?CI_OUTPUT_DIR must be set}"
runtime_dir="${CI_RUNTIME_DIR:?CI_RUNTIME_DIR must be set}"
dirty_base_commit="${CI_DIRTY_BASE_COMMIT:-}"
steamrt4_version="4.0.20260805.254769"
steamrt4_image="registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:${steamrt4_version}"

require_absolute_directory_path() {
    local name=$1
    local value=$2
    if [[ "${value}" != /* || "${value}" == "/" ]]; then
        echo "run-ci.sh: ${name} must be an absolute non-root path" >&2
        exit 2
    fi
}

require_absolute_directory_path CI_SOURCE_ROOT "${source_root}"
require_absolute_directory_path CI_WORK_ROOT "${work_root}"
require_absolute_directory_path CI_OUTPUT_DIR "${output_dir}"
require_absolute_directory_path CI_RUNTIME_DIR "${runtime_dir}"

build_dir="${work_root}/cmake-build"
staging_dir="${work_root}/staging-install"
dependency_report="${work_root}/dependency-versions.txt"

phase="prepare fresh work directories"
rm -rf "${build_dir}" "${staging_dir}"
if [[ -d "${output_dir}" ]] && find "${output_dir}" -mindepth 1 -print -quit | grep -q .; then
    echo "run-ci.sh: CI_OUTPUT_DIR must be empty" >&2
    exit 2
fi
mkdir -p \
    "${build_dir}" \
    "${staging_dir}" \
    "${output_dir}" \
    "${runtime_dir}" \
    "${HOME:?HOME must be set}" \
    "${PYTHONPYCACHEPREFIX:?PYTHONPYCACHEPREFIX must be set}"

phase="record dependency versions"
{
    echo "SteamRT4 image: ${steamrt4_image}"
    echo "SteamRT4 version: ${steamrt4_version}"
    cmake --version | sed -n '1s/^/CMake: /p'
    echo "Ninja: $(ninja --version)"
    gcc --version | sed -n '1s/^/GCC: /p'
    g++ --version | sed -n '1s/^/G++: /p'
    echo "pkgconf: $(pkgconf --version)"
    for package in \
        cmake ninja-build gcc g++ pkgconf \
        libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev libsdl2-net-dev \
        libopenal-dev libvorbis-dev libavformat-dev libavcodec-dev \
        libavutil-dev libswscale-dev libswresample-dev liblua5.4-dev \
        libgl-dev pax-utils; do
        dpkg-query -W -f='${binary:Package}\t${Version}\n' "${package}"
    done
} | tee "${dependency_report}"
test -s "${dependency_report}"

phase="verify fonts, scripts, and launcher"
(cd "${source_root}/Fonts" && sha256sum -c SHA256SUMS)
bash -n \
    "${source_root}/packaging/steamrt4/install-dependencies.sh" \
    "${source_root}/packaging/steamrt4/run-ci.sh"
sh -n "${source_root}/OpenNeoUA.sh"
python3 -m py_compile \
    "${source_root}/packaging/steamrt4/package.py" \
    "${source_root}/packaging/steamrt4/local_ci.py" \
    "${source_root}/packaging/steamrt4/test_local_ci.py" \
    "${source_root}/packaging/steamrt4/test_launcher.py" \
    "${source_root}/packaging/steamrt4/test_resolver_write_paths.py" \
    "${source_root}/packaging/steamrt4/test_overlay_mutation.py" \
    "${source_root}/packaging/steamrt4/test_game_menu.py" \
    "${source_root}/packaging/steamrt4/test_game_menu_policy.py" \
    "${source_root}/packaging/steamrt4/test_steamdeck.py" \
    "${source_root}/packaging/steamrt4/test_steam_input.py" \
    "${source_root}/packaging/steamrt4/test_redistribution_exemption.py"
python3 "${source_root}/packaging/steamrt4/test_launcher.py"
python3 "${source_root}/packaging/steamrt4/test_steam_input.py"
python3 "${source_root}/packaging/steamrt4/test_redistribution_exemption.py"

phase="configure Release build"
cmake \
    -S "${source_root}/src" \
    -B "${build_dir}" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache \
    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache

phase="build OpenNeoUA"
if [[ "${CI_CLEAR_CACHE:-0}" == "1" ]]; then
    ccache --clear
fi
cmake --build "${build_dir}"
ccache --show-stats

phase="run CTest for SDL virtual controller and action parity"
ctest --test-dir "${build_dir}" --output-on-failure

phase="verify resolver write destinations"
python3 "${source_root}/packaging/steamrt4/test_resolver_write_paths.py"
python3 "${source_root}/packaging/steamrt4/test_overlay_mutation.py"
python3 "${source_root}/packaging/steamrt4/test_game_menu_policy.py"
python3 "${source_root}/packaging/steamrt4/test_steamdeck.py"

phase="install OpenNeoUA to staging"
cmake --install "${build_dir}" --prefix "${staging_dir}"
test -x "${staging_dir}/bin/OpenNeoUA"

phase="build and verify overlay archive"
package_command=(
    python3 "${source_root}/packaging/steamrt4/package.py"
    --source-root "${source_root}"
    --build-dir "${build_dir}"
    --staging-dir "${staging_dir}"
    --output-dir "${output_dir}"
    --runtime-dir "${runtime_dir}"
    --runtime-version "${steamrt4_version}"
    --dependency-report "${dependency_report}"
)
if [[ -n "${dirty_base_commit}" ]]; then
    package_command+=(--dirty-base-commit "${dirty_base_commit}")
fi
"${package_command[@]}"

snapshot_commit=$(git -C "${source_root}" rev-parse HEAD)
if [[ -n "${dirty_base_commit}" ]]; then
    artifact_identifier="${dirty_base_commit:0:7}-dirty-${snapshot_commit:0:7}"
else
    artifact_identifier="${snapshot_commit:0:7}"
fi
archive_name="OpenNeoUA-steamrt4-x86_64-${artifact_identifier}.tar.xz"
checksum_name="${archive_name}.sha256"
test -f "${output_dir}/${archive_name}"
test -f "${output_dir}/${checksum_name}"
test "$(find "${output_dir}" -mindepth 1 -maxdepth 1 -type f -printf '.' | wc -c)" -eq 2
(cd "${output_dir}" && sha256sum -c "${checksum_name}")

phase="complete"
echo "run-ci.sh: completed ${archive_name}"
