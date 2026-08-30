#!/usr/bin/env bash
# Run the OpenNeoUA menu/campaign-map smoke test inside this image.
#
# Usage:
#   run_smoketest.sh /input/OpenNeoUA.AppImage [/output/results]
#
# The AppImage is extracted read-only from /input.  All writes go to /output.
set -Eeuo pipefail

appimage="${1:?AppImage path required}"
output_dir="${2:-/output}"
work_root="${SMOKETEST_WORK_ROOT:-/work}"
timeout="${SMOKETEST_TIMEOUT:-300}"

if [[ ! -f "${appimage}" ]]; then
    echo "run_smoketest.sh: AppImage not found: ${appimage}" >&2
    exit 2
fi

mkdir -p "${work_root}/extract" "${output_dir}"
extract_log="${work_root}/extract.log"
if [[ -d "${work_root}/extract/squashfs-root" ]]; then
    rm -rf "${work_root}/extract/squashfs-root"
fi

cd "${work_root}/extract"
if ! "${appimage}" --appimage-extract >"${extract_log}" 2>&1; then
    offset="$(LC_ALL=C grep -abo 'hsqs' "${appimage}" | tail -n 1 | cut -d: -f1)"
    if [[ -z "${offset}" ]]; then
        echo "run_smoketest.sh: AppImage extraction failed" >&2
        cat "${extract_log}" >&2
        exit 2
    fi
    unsquashfs -quiet -offset "${offset}" -d "${work_root}/extract/squashfs-root" "${appimage}" >>"${extract_log}" 2>&1
fi

payload="${work_root}/extract/squashfs-root"
if [[ ! -x "${payload}/AppRun" ]]; then
    echo "run_smoketest.sh: extracted payload has no AppRun" >&2
    exit 2
fi

state="${work_root}/state"
rm -rf "${state}"
mkdir -p "${state}/xdg-data/OpenNeoUA"
chmod -R a+rwX "${state}"

useradd -m -u 65532 smokeuser 2>/dev/null || true
chown -R smokeuser:smokeuser "${state}" "${output_dir}" "${work_root}"

set +e
su smokeuser -c "set -eu; \
    HOME=${state} \
    XDG_DATA_HOME=${state}/xdg-data \
    XDG_CONFIG_HOME=${state}/xdg-config \
    XDG_CACHE_HOME=${state}/xdg-cache \
    timeout ${timeout} \
    xvfb-run -a --server-args='-screen 0 1280x800x24' \
    ${payload}/AppRun --menu-smoke-dir ${state}/xdg-data/OpenNeoUA \
    >${state}/menu.log 2>&1"
status=$?
set -e

if [[ -f "${state}/menu.log" ]]; then
    cp "${state}/menu.log" "${output_dir}/menu-smoke.log"
fi

report="$(find "${state}" -name menu-smoke.json | head -n 1 || true)"
if [[ -n "${report}" ]]; then
    cp "${report}" "${output_dir}/menu-smoke.json"
fi

screens_dir="${output_dir}/screenshots"
mkdir -p "${screens_dir}"
while IFS= read -r ppm; do
    [[ -n "${ppm}" ]] || continue
    cp "${ppm}" "${screens_dir}/$(basename "${ppm}")"
done < <(find "${state}" -name '*.ppm' -print 2>/dev/null || true)

if [[ "${status}" -ne 0 ]]; then
    echo "run_smoketest.sh: OpenNeoUA exited with status ${status}" >&2
    if [[ -f "${output_dir}/menu-smoke.log" ]]; then
        tail -n 40 "${output_dir}/menu-smoke.log" >&2
    fi
    exit "${status}"
fi

if [[ ! -f "${output_dir}/menu-smoke.json" ]]; then
    echo "run_smoketest.sh: smoke report missing" >&2
    exit 2
fi

echo "run_smoketest.sh: passed"
