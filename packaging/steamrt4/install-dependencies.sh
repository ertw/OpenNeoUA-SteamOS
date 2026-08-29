#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "install-dependencies.sh: must run as root" >&2
    exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --no-install-recommends -y \
    ca-certificates \
    curl \
    cmake \
    ninja-build \
    gcc \
    g++ \
    pkgconf \
    libsdl2-dev \
    libsdl2-image-dev \
    libsdl2-ttf-dev \
    libsdl2-net-dev \
    libopenal-dev \
    libvorbis-dev \
    libavformat-dev \
    libavcodec-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    liblua5.4-dev \
    libgl-dev \
    pax-utils \
    binutils \
    file \
    xz-utils \
    ccache \
    python3
apt-get clean
rm -rf /var/lib/apt/lists/*
