#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for OpenNeoUA.
#
# Installs the system build/runtime dependencies, adds the headless GUI tools
# needed to smoke-test the engine without a physical display, and produces a
# Release build of the engine and its test harness. Safe to re-run.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [ "$(id -u)" -ne 0 ]; then
    sudo_cmd="sudo"
else
    sudo_cmd=""
fi

# Core build + runtime dependencies (identical set used by CI).
$sudo_cmd bash packaging/steamrt4/install-dependencies.sh

# Headless rendering support: a virtual X server plus the Mesa software GL
# driver let the engine's `--menu-smoke-dir` mode and manual GUI runs work
# without a physical display or GPU.
export DEBIAN_FRONTEND=noninteractive
$sudo_cmd apt-get update
$sudo_cmd apt-get install --no-install-recommends -y \
    xvfb \
    libgl1-mesa-dri \
    mesa-utils
$sudo_cmd apt-get clean
$sudo_cmd rm -rf /var/lib/apt/lists/*

# Configure + build (Release), matching packaging/steamrt4/run-ci.sh.
#
# gcc/g++ are selected explicitly: on the default Cloud Agent base image the
# cc/c++ alternatives resolve to clang, which cannot locate libstdc++ and makes
# CMake's compiler check fail. The CI SteamRT4 image defaults to gcc.
export CC=gcc CXX=g++
cmake -S src -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache \
    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
cmake --build build

echo "OpenNeoUA setup complete: build/OpenNeoUA"
