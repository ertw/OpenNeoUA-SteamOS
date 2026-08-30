#!/usr/bin/env python3
"""Build and verify the native Steam Linux Runtime 4 overlay archive.

The script deliberately uses only Python's standard library.  CMake remains
the build system; this module only stages the installed executable, resolves
its ELF closure, copies tracked assets, and creates the final archive.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


RUNTIME_VERSION = "4.0.20260805.254769"
RUNTIME_BASE_URL = (
    "https://repo.steampowered.com/steamrt4/images/" + RUNTIME_VERSION + "/"
)
RUNTIME_MANIFEST = (
    "com.valvesoftware.SteamRuntime.Platform-amd64,i386-steamrt4.manifest.dpkg"
)
RUNTIME_MTREE = (
    "com.valvesoftware.SteamRuntime.Platform-amd64,i386-steamrt4-runtime.mtree.gz"
)
RUNTIME_FILES = ("VERSION.txt", RUNTIME_MANIFEST, RUNTIME_MTREE)

FONT_CHECKSUMS = {
    "LiberationMono-Regular.ttf": "a9b21391536aec1c8fad37f2d5f24750e7f2d63cd86bccbb2463b6e17005f52e",
    "LiberationSans-Regular.ttf": "e5b0af421ea2bfbc1ac8d251d647268087ae82786234c57f757d1f0b90fa8b49",
    "LiberationSerif-Regular.ttf": "26cd653d3312cee66f1d4f2c1065ba2ad324abd411b298f771bf7057e213d723",
    "PressStart2P.ttf": "78b71542749b2f6920f60fe2c74fe85738284dcb9cd26a7ff6a642c54d38470b",
    "Xolonium-Bold.otf": "3755edcf3bd28a47ec2f18af09e5d1bca7757797bdd8993f58a075815f71a3e1",
    "Xolonium-Regular.otf": "302078ebb5211a158758f15ab6f8f6f355a0a6af345786f6b2354fec745d88f3",
    "textar.ttf": "23a45bd8acec486e94add0cfd9e4ccef99a9502e11e8af8467d651e2e01c4105",
}

REDISTRIBUTABLE_SOURCE_DIR = Path("packaging") / "steamrt4" / "redistributable"
STEAM_API_LIBRARY_NAME = "libsteam_api.so"
VENDOR_STEAMWORKS_SDK = Path("vendor") / "steamworks-sdk"
VENDOR_STEAM_API_LIBRARY = (
    VENDOR_STEAMWORKS_SDK / "redistributable_bin" / "linux64" / STEAM_API_LIBRARY_NAME
)
# Sentinel for an exemption whose real digest is not known yet.  Staging refuses
# to ship a library while its pin still carries this value.
REDISTRIBUTION_PLACEHOLDER_SHA256 = "placeholder-pin-the-real-sha256"


class RedistributionExemption(NamedTuple):
    """A non-Debian shared object cleared for redistribution by pinned digest."""

    name: str
    sha256: str
    license_path: str
    origin: str


# Pinned digest of vendor/steamworks-sdk/redistributable_bin/linux64/libsteam_api.so
# (Steamworks SDK v1.65).  Regenerate after upgrading the vendored SDK:
#     sha256sum vendor/steamworks-sdk/redistributable_bin/linux64/libsteam_api.so
REDISTRIBUTION_EXEMPTION_RECORDS = (
    RedistributionExemption(
        name=STEAM_API_LIBRARY_NAME,
        sha256="eb2dd015b84177cf4f4326fe578aab375fd8931bbbd719c7492420d9777007fe",
        license_path=str(VENDOR_STEAMWORKS_SDK / "Readme.txt"),
        origin="Steamworks SDK redistributable (Valve Corporation), dlopen()ed for Steam Input",
    ),
)

ALLOWED_ASSET_ROOTS = (
    "3ds",
    "Database",
    "Env",
    "Filters",
    "Fonts",
    "Interface",
    "Locale",
    "Res",
    "Scripts",
    "Sounds",
    "Wireless",
)
PACKAGE_TOP_LEVEL = (
    "OpenNeoUA.sh",
    "bin",
    "lib",
    "Fonts",
    "3ds",
    "Database",
    "Env",
    "Filters",
    "Interface",
    "Locale",
    "Res",
    "Scripts",
    "Sounds",
    "Wireless",
    "SteamInput",
    "licenses",
    "BUILD-INFO.txt",
    "MANIFEST.sha256",
)
DEPENDENCY_PACKAGES = (
    "cmake",
    "ninja-build",
    "gcc",
    "g++",
    "pkgconf",
    "libsdl2-dev",
    "libsdl2-image-dev",
    "libsdl2-ttf-dev",
    "libsdl2-net-dev",
    "libopenal-dev",
    "libvorbis-dev",
    "libavformat-dev",
    "libavcodec-dev",
    "libavutil-dev",
    "libswscale-dev",
    "libswresample-dev",
    "liblua5.4-dev",
    "libgl-dev",
    "pax-utils",
)
REQUIRED_ELF_FAMILIES = (
    ("SDL2_image", ("sdl2_image",)),
    ("SDL2_ttf", ("sdl2_ttf",)),
    ("SDL2_net", ("sdl2_net",)),
    ("FFmpeg libavformat", ("libavformat",)),
    ("FFmpeg libavcodec", ("libavcodec",)),
    ("FFmpeg libavutil", ("libavutil",)),
    ("FFmpeg libswscale", ("libswscale",)),
    ("FFmpeg libswresample", ("libswresample",)),
    ("Lua 5.4", ("liblua5.4", "liblua-5.4")),
)
STEAM_INPUT_SOURCE_DIR = Path("packaging") / "steamrt4" / "steam_input"
STEAM_INPUT_REQUIRED_FILES = (
    "REVISION.txt",
    "openneoua_deck_default.vdf",
    "openneoua_deck_iga.vdf",
    "game_actions_480.vdf",
)
STEAM_APPID = "480"
BIN_PACKAGE_FILES = ("OpenNeoUA", "steam_appid.txt")


class PackagingError(RuntimeError):
    """An unsafe or unverifiable package cannot be produced."""


def fail(message: str) -> None:
    raise PackagingError(message)


def index_redistribution_exemptions(
    records: Sequence[RedistributionExemption],
) -> Mapping[str, RedistributionExemption]:
    table: Dict[str, RedistributionExemption] = {}
    for record in records:
        if not record.name or "/" in record.name:
            fail("invalid redistribution exemption name: {}".format(record.name))
        if record.name in table:
            fail("duplicate redistribution exemption: {}".format(record.name))
        if record.sha256 != REDISTRIBUTION_PLACEHOLDER_SHA256 and not re.fullmatch(
            r"[0-9a-f]{64}", record.sha256
        ):
            fail("redistribution exemption pin is not a lowercase SHA-256: {}".format(record.name))
        if not record.license_path or not record.origin:
            fail("redistribution exemption lacks a license path or origin: {}".format(record.name))
        relative = PurePosixPath(record.license_path)
        if relative.is_absolute() or ".." in relative.parts:
            fail("unsafe redistribution license path: {}".format(record.license_path))
        table[record.name] = record
    return MappingProxyType(table)


REDISTRIBUTION_EXEMPTIONS: Mapping[str, RedistributionExemption] = (
    index_redistribution_exemptions(REDISTRIBUTION_EXEMPTION_RECORDS)
)


def run_command(
    command: Sequence[str],
    cwd: Optional[Path] = None,
    check: bool = True,
) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail("unable to execute {}: {}".format(" ".join(command), exc))
    if check and result.returncode != 0:
        details = (result.stderr.strip() or result.stdout.strip()).splitlines()
        tail = "\n".join(details[-12:])
        fail("command failed ({}): {}\n{}".format(result.returncode, " ".join(command), tail))
    return result.stdout


def require_regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        fail("{} is missing: {}".format(label, path))
    if not stat.S_ISREG(mode):
        fail("{} must be a regular file, not a symlink or special file: {}".format(label, path))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sums(path: Path, allow_relative_paths: bool = False) -> Dict[str, str]:
    require_regular_file(path, "checksum manifest")
    result: Dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
            fail("invalid checksum record at {}:{}".format(path, line_number))
        name = fields[1]
        if name.startswith("*"):
            name = name[1:]
        if not name or "\\" in name:
            fail("unsafe checksum filename at {}:{}".format(path, line_number))
        if allow_relative_paths:
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                fail("unsafe checksum path at {}:{}".format(path, line_number))
        elif "/" in name:
            fail("unsafe checksum filename at {}:{}".format(path, line_number))
        if name in result:
            fail("duplicate checksum filename at {}:{}".format(path, line_number))
        result[name] = fields[0].lower()
    return result


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    request = Request(url, headers={"User-Agent": "OpenNeoUA-steamrt4-packager"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
        os.replace(temporary, destination)
    except Exception as exc:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        fail("unable to download {}: {}".format(url, exc))


def ensure_runtime_manifests(
    runtime_dir: Path,
    base_url: str,
    expected_version: str,
) -> Tuple[Path, Path, Dict[str, str]]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    checksum_path = runtime_dir / "SHA256SUMS"
    if not checksum_path.exists():
        download_file(urljoin(base_url.rstrip("/") + "/", "SHA256SUMS"), checksum_path)

    checksums = parse_sha256sums(checksum_path, allow_relative_paths=True)
    for filename in RUNTIME_FILES:
        if filename not in checksums:
            fail("pinned runtime SHA256SUMS does not contain {}".format(filename))
        destination = runtime_dir / filename
        if not destination.exists():
            encoded = quote(filename, safe="")
            download_file(urljoin(base_url.rstrip("/") + "/", encoded), destination)
        require_regular_file(destination, "SteamRT4 runtime manifest")
        actual = sha256_file(destination)
        if actual != checksums[filename]:
            fail(
                "SteamRT4 checksum mismatch for {}: expected {}, got {}".format(
                    filename, checksums[filename], actual
                )
            )

    version = (runtime_dir / "VERSION.txt").read_text(encoding="utf-8").strip()
    if version != expected_version:
        fail("SteamRT4 VERSION.txt is {}, expected {}".format(version, expected_version))
    return runtime_dir / RUNTIME_MANIFEST, runtime_dir / RUNTIME_MTREE, checksums


# Library prefixes that are safe to assume present on stock SteamOS (Arch-based).
# Everything else from the SteamRT4 mtree must be bundled because SteamOS may
# lack it entirely or ship an incompatible SONAME version (e.g. Debian's
# libjpeg.so.62 vs Arch's libjpeg.so.8).  The ``forbidden_soname`` function
# already blocks outright system libraries (glibc, libstdc++, graphics stack);
# this allowlist covers the Arch base packages that are reliably present on a
# stock Steam Deck, even when the AppImage runs outside Steam Linux Runtime.
_HOST_GUARANTEED_PREFIXES = (
    # glibc / base toolchain — also in forbidden_soname, listed here for
    # completeness so the mtree filter doesn't accidentally drop them.
    "ld-linux",
    "libc.so",
    "libm.so",
    "libdl.so",
    "libpthread.so",
    "librt.so",
    "libresolv.so",
    "libnsl.so",
    "libutil.so",
    "libstdc++.so",
    "libgcc_s.so",
    # X11 / Wayland / input core — part of the SteamOS desktop session.
    "libx11.so",
    "libx11-xcb.so",
    "libxext.so",
    "libxcb.so",
    "libxcb-",            # libxcb-shm, libxcb-render, libxcb-xfixes, etc.
    "libxau.so",
    "libxdmcp.so",
    "libxrender.so",
    "libxfixes.so",
    "libxcursor.so",
    "libxrandr.so",
    "libxi.so",
    "libxinerama.so",
    "libxss.so",
    "libxtst.so",
    "libxxf86vm.so",
    "libxkbcommon.so",
    "libwayland-client.so",
    "libwayland-cursor.so",
    "libwayland-server.so",
    "libwayland-egl.so",
    # Graphics stack — driver-coupled, must always come from the host.
    "libgl.so",
    "libglx.so",
    "libgldispatch.so",
    "libopengl.so",
    "libegl.so",
    "libgles",
    "libvulkan.so",
    "libdrm.so",
    "libgbm.so",
    "libmesa",
    # Misc Arch base packages that are practically always present.
    "libz.so",
    "libffi.so",
    "libpcre2-",          # libpcre2-8, libpcre2-posix, etc.
    "libsystemd.so",
    "libudev.so",
    "libdbus-1.so",
    "libxcb.so",
    # Core gaming libraries — present on SteamOS and also in forbidden_soname.
    "libsdl2-2.0.so",
    "libopenal.so",
    "libvorbis.so",
    "libvorbisenc.so",
    "libvorbisfile.so",
    "libogg.so",
    # Audio backend — SteamOS ships PulseAudio/PipeWire and ALSA.
    "libasound.so",
    "libpulse",           # libpulse.so, libpulse-simple.so
    "libpipewire",
    "libsndfile.so",
)


def runtime_sonames(mtree_path: Path) -> Set[str]:
    """Return amd64 library filenames from the runtime's file-level mtree.

    Only libraries whose basenames start with a known host-guaranteed prefix
    are kept in the runtime set.  Everything else is excluded so that the ELF
    closure walker bundles it into the overlay / AppImage.  This is safer than
    the previous approach of listing individual libraries to force-bundle,
    because it automatically catches new transitive dependencies instead of
    failing at launch on the Steam Deck.
    """
    require_regular_file(mtree_path, "SteamRT4 runtime mtree")
    names: Set[str] = set()
    with gzip.open(mtree_path, "rt", encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            fields = raw.strip().split()
            if not fields:
                continue
            entry = fields[0]
            if not entry.startswith("./files/"):
                continue
            relative = entry[len("./files/") :]
            # The archive carries both amd64 and i386 trees.  Generic /lib and
            # /usr/lib entries are architecture-neutral and are safe to retain;
            # explicit i386 paths must not classify an amd64 dependency.
            if "i386-linux-gnu" in relative or relative.startswith("lib/i386"):
                continue
            if not any(field in fields[1:] for field in ("type=file", "type=link")):
                continue
            name = Path(relative).name
            if name.startswith("lib") or name.startswith("ld-"):
                if name.lower().startswith(_HOST_GUARANTEED_PREFIXES):
                    names.add(name)
                # Everything else is intentionally omitted so the closure
                # walker treats it as a private dependency to bundle.
    if not names:
        fail("SteamRT4 runtime mtree contains no amd64 library entries")
    return names


def runtime_packages(manifest_path: Path) -> Dict[str, Tuple[str, str]]:
    """Parse package -> (version, source package) from manifest.dpkg."""
    require_regular_file(manifest_path, "SteamRT4 Debian package manifest")
    packages: Dict[str, Tuple[str, str]] = {}
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            fail("malformed SteamRT4 Debian package manifest record")
        package = fields[0].strip()
        version = fields[1].strip()
        source = fields[2].strip() if len(fields) > 2 else ""
        if not package or not version:
            fail("malformed SteamRT4 Debian package manifest record")
        packages[package] = (version, source)
    if not packages:
        fail("SteamRT4 Debian package manifest contains no package records")
    return packages


def readelf_dynamic(path: Path) -> Tuple[List[str], Optional[str]]:
    output = run_command(["readelf", "-d", str(path)], check=False)
    if not output:
        fail("readelf could not inspect ELF file {}".format(path))
    needed: List[str] = []
    soname: Optional[str] = None
    for line in output.splitlines():
        match = re.search(r"\(NEEDED\).*?: \[([^\]]+)\]", line)
        if match:
            needed.append(match.group(1))
        match = re.search(r"\(SONAME\).*?: \[([^\]]+)\]", line)
        if match:
            soname = match.group(1)
    return needed, soname


def readelf_runpath(path: Path) -> List[str]:
    output = run_command(["readelf", "-d", str(path)], check=False)
    if not output:
        fail("readelf could not inspect ELF file {}".format(path))
    for line in output.splitlines():
        match = re.search(r"\((?:RPATH|RUNPATH)\).*?: \[([^\]]+)\]", line)
        if match:
            return [entry for entry in match.group(1).split(":") if entry]
    return []


def is_x86_64_elf(path: Path) -> bool:
    output = run_command(["readelf", "-h", str(path)], check=False)
    return (
        "Class:" in output
        and "ELF64" in output
        and "Machine:" in output
        and "Advanced Micro Devices X86-64" in output
    )


def forbidden_soname(name: str) -> bool:
    lower = name.lower()
    prefixes = (
        "ld-linux",
        "ld-musl",
        "libc.so",
        "libanl.so",
        "libbrokenlocale.so",
        "libcrypt.so",
        "libm.so",
        "libmvec.so",
        "libdl.so",
        "libnsl.so",
        "libpthread.so",
        "librt.so",
        "libnss_",
        "libresolv.so",
        "libthread_db.so",
        "libutil.so",
        "libstdc++.so",
        "libgcc_s.so",
        "libsdl2-2.0.so",
        "libopenal.so",
        "libvorbis.so",
        "libvorbisenc.so",
        "libvorbisfile.so",
        "libogg.so",
        "libgl.so",
        "libglx.so",
        "libgldispatch.so",
        "libopengl.so",
        "libegl.so",
        "libgles",
        "libvulkan.so",
        "libdrm.so",
        "libgbm.so",
        "libmesa",
        "libwayland-egl.so",
    )
    return lower.startswith(prefixes)


def safe_relative(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail("unsafe path: {}".format(path))
    return candidate


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class PackageRecord:
    def __init__(self, package: str, version: str, source_package: str, source: Path):
        self.package = package
        self.version = version
        self.source_package = source_package
        self.source_files: Set[Path] = {source.resolve()}
        self.staged_names: Set[str] = set()
        self.copyright_path: Optional[Path] = None


class ElfClosure:
    def __init__(
        self,
        runtime_names: Set[str],
        runtime_packages: Dict[str, Tuple[str, str]],
        staging_lib: Path,
    ):
        self.runtime_names = runtime_names
        self.runtime_packages = runtime_packages
        self.staging_lib = staging_lib
        self.classifications: Dict[str, str] = {}
        self.runtime_dependency_packages: Dict[str, str] = {}
        self.resolved_paths: Dict[str, Path] = {}
        self.packages: Dict[str, PackageRecord] = {}
        self.search_map: Dict[str, List[Path]] = {}
        self.inspected_targets: Set[Path] = set()

    def _add_search_paths(self, target: Path) -> None:
        if not shutil.which("lddtree"):
            return
        output = run_command(["lddtree", "-l", str(target)], check=False)
        for raw in output.splitlines():
            candidate = raw.strip()
            if not candidate.startswith("/"):
                continue
            path = Path(candidate)
            if not path.exists() or not path.is_file():
                continue
            self.search_map.setdefault(path.name, []).append(path)

    def _library_candidates(self, name: str) -> Iterable[Path]:
        seen: Set[Path] = set()
        for candidate in self.search_map.get(name, []):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate

        ldconfig = shutil.which("ldconfig")
        if ldconfig:
            output = run_command([ldconfig, "-p", "-N", "-X"], check=False)
            for line in output.splitlines():
                if "=>" not in line or not line.lstrip().startswith(name):
                    continue
                candidate = Path(line.split("=>", 1)[1].strip())
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate

        search_dirs = [
            Path("/lib/x86_64-linux-gnu"),
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/lib64"),
            Path("/usr/lib64"),
            Path("/lib"),
            Path("/usr/lib"),
            Path("/usr/local/lib"),
        ]
        for directory in search_dirs:
            candidate = directory / name
            if candidate.exists() and candidate not in seen:
                seen.add(candidate)
                yield candidate

    def resolve_library(self, name: str, owner: Path) -> Path:
        if name.startswith("/"):
            fail("absolute DT_NEEDED path is forbidden: {} in {}".format(name, owner))

        self._add_search_paths(owner)
        candidates = list(self._library_candidates(name))
        for candidate in candidates:
            try:
                if is_x86_64_elf(candidate.resolve()):
                    return candidate
            except (OSError, PackagingError):
                continue
        fail("unable to resolve DT_NEEDED {} from {}".format(name, owner))

    def _runtime_package_for(self, name: str, owner: Path) -> str:
        """Resolve a runtime SONAME and verify its Debian owner is in the pin."""
        self._add_search_paths(owner)
        for candidate in self._library_candidates(name):
            try:
                real_candidate = candidate.resolve()
                if not is_x86_64_elf(real_candidate):
                    continue
            except (OSError, PackagingError):
                continue

            query = run_command(["dpkg-query", "-S", str(real_candidate)], check=False).strip()
            if not query:
                query = run_command(["dpkg-query", "-S", str(candidate)], check=False).strip()
            package = ""
            for line in query.splitlines():
                if ": " in line:
                    package = line.split(": ", 1)[0].strip()
                    break
            if not package:
                continue

            package_base = package.split(":", 1)[0]
            manifest_package = next(
                (
                    item
                    for item in self.runtime_packages
                    if item == package or item.split(":", 1)[0] == package_base
                ),
                None,
            )
            if manifest_package is None:
                continue
            self.runtime_dependency_packages[name] = manifest_package
            return manifest_package

        fail("runtime DT_NEEDED {} cannot be mapped to a pinned Debian package".format(name))

    def _package_for(self, source: Path) -> PackageRecord:
        real_source = source.resolve()
        query = run_command(["dpkg-query", "-S", str(real_source)], check=False).strip()
        package = ""
        for line in query.splitlines():
            if ": " in line:
                package = line.split(": ", 1)[0].strip()
                break
        if not package:
            query = run_command(["dpkg-query", "-S", str(source)], check=False).strip()
            for line in query.splitlines():
                if ": " in line:
                    package = line.split(": ", 1)[0].strip()
                    break
        if not package:
            fail("cannot determine Debian package owner for {}".format(source))

        details = run_command(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${source:Package}\n", package],
            check=False,
        ).strip()
        if not details:
            fail("cannot determine Debian package version for {} ({})".format(source, package))
        fields = details.split("\t")
        version = fields[1] if len(fields) > 1 else ""
        source_package = fields[2] if len(fields) > 2 else ""
        if not version:
            fail("Debian package {} has no version".format(package))

        record = self.packages.get(package)
        if record is None:
            record = PackageRecord(package, version, source_package, real_source)
            self.packages[package] = record
        record.source_files.add(real_source)
        return record

    def _stage_library(self, requested_name: str, source: Path) -> PackageRecord:
        real_source = source.resolve()
        if not real_source.exists() or not real_source.is_file():
            fail("resolved library is not a regular file: {}".format(source))
        if not is_x86_64_elf(real_source):
            fail("resolved library is not x86-64 ELF: {}".format(real_source))

        needed, soname = readelf_dynamic(real_source)
        target_name = real_source.name
        if forbidden_soname(target_name) or (soname is not None and forbidden_soname(soname)):
            fail("forbidden system library resolved for {}: {}".format(requested_name, target_name))
        destination = self.staging_lib / target_name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or sha256_file(destination) != sha256_file(real_source):
                fail("conflicting staged library basename: {}".format(target_name))
        else:
            shutil.copy2(real_source, destination)
            os.chmod(destination, stat.S_IMODE(real_source.stat().st_mode) or 0o644)

        names = {requested_name}
        if soname:
            names.add(soname)
        for name in names:
            safe_relative(name)
            link = self.staging_lib / name
            if link == destination:
                continue
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or os.readlink(link) != target_name:
                    fail("conflicting staged SONAME link: {}".format(name))
            else:
                link.symlink_to(target_name)

        record = self._package_for(real_source)
        record.staged_names.update(names)
        self.resolved_paths[requested_name] = real_source
        for name in names:
            self.resolved_paths[name] = real_source
        for name in names:
            self.classifications[name] = "private lib"
        for name in needed:
            self.classifications.setdefault(name, "unclassified")
        return record

    def collect(self, executable: Path) -> None:
        queue: List[Tuple[Path, str]] = [(executable, name) for name in readelf_dynamic(executable)[0]]
        queued: Set[Tuple[Path, str]] = set(queue)
        while queue:
            owner, name = queue.pop(0)
            if name.startswith("/"):
                fail("absolute DT_NEEDED path is forbidden: {} in {}".format(name, owner))
            if name in self.runtime_names:
                package = self._runtime_package_for(name, owner)
                self.classifications[name] = "runtime ({})".format(package)
                continue
            if forbidden_soname(name):
                fail("forbidden library {} is absent from the SteamRT4 runtime".format(name))

            source = self.resolved_paths.get(name)
            if source is None:
                source = self.resolve_library(name, owner)
            self._stage_library(name, source)
            target = source.resolve()
            if target in self.inspected_targets:
                continue
            self.inspected_targets.add(target)
            for dependency in readelf_dynamic(target)[0]:
                item = (target, dependency)
                if item not in queued:
                    queued.add(item)
                    queue.append(item)

        for name, classification in list(self.classifications.items()):
            if classification == "unclassified":
                fail("ELF dependency was not classified: {}".format(name))

    def materialize_licenses(self, staging_root: Path) -> None:
        for record in self.packages.values():
            package_base = record.package.split(":", 1)[0]
            candidates = [
                Path("/usr/share/doc") / package_base / "copyright",
                Path("/usr/share/doc") / record.package / "copyright",
            ]
            copyright_path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if copyright_path is None:
                listing = run_command(["dpkg-query", "-L", record.package], check=False)
                for line in listing.splitlines():
                    candidate = Path(line.strip())
                    if candidate.name == "copyright" and candidate.is_file():
                        copyright_path = candidate
                        break
            if copyright_path is None:
                fail("Debian copyright is missing for {}".format(record.package))

            safe_package = re.sub(r"[^A-Za-z0-9._+-]", "_", record.package)
            destination_dir = staging_root / "licenses" / "debian" / safe_package
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / "copyright"
            shutil.copyfile(copyright_path, destination)
            record.copyright_path = copyright_path
            metadata = destination_dir / "metadata.txt"
            lines = [
                "Package: {}".format(record.package),
                "Version: {}".format(record.version),
                "Source package: {}".format(record.source_package or "unknown"),
                "Copyright source: {}".format(copyright_path),
            ]
            lines.extend(
                "Source file: {}".format(source_file)
                for source_file in sorted(record.source_files, key=lambda item: str(item))
            )
            lines.append("Staged libraries:")
            lines.extend("  {}".format(name) for name in sorted(record.staged_names))
            metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_redistribution_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)


def redistribution_exemption(
    name: str,
    table: Mapping[str, RedistributionExemption] = REDISTRIBUTION_EXEMPTIONS,
) -> RedistributionExemption:
    """Return the declared exemption for a staged basename.

    The exemption waives Debian provenance only; the SONAME policy that keeps
    host-owned system libraries out of the package still applies.
    """
    exemption = table.get(name)
    if exemption is None:
        fail("no redistribution exemption is declared for {}".format(name))
    if forbidden_soname(name):
        fail("forbidden system library cannot be redistribution-exempt: {}".format(name))
    return exemption


def materialize_redistribution_license(
    source_root: Path,
    staging_root: Path,
    exemption: RedistributionExemption,
    digest: str,
    source: Path,
) -> None:
    license_source = source_root / PurePosixPath(exemption.license_path)
    require_regular_file(license_source, "redistributable license")
    destination_dir = (
        staging_root / "licenses" / "redistributable" / safe_redistribution_name(exemption.name)
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_source, destination_dir / "LICENSE.txt")
    lines = [
        "Name: {}".format(exemption.name),
        "Pinned SHA256: {}".format(digest),
        "Origin: {}".format(exemption.origin),
        "License source: {}".format(exemption.license_path),
        "Source file: {}".format(source),
        "Staged libraries:",
        "  {}".format(exemption.name),
    ]
    (destination_dir / "metadata.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_redistribution_exemption(
    source_root: Path,
    staging_root: Path,
    name: str,
    source: Path,
    table: Mapping[str, RedistributionExemption] = REDISTRIBUTION_EXEMPTIONS,
) -> Optional[str]:
    """Check the pinned digest and stage the license for one exempt library.

    Returns the verified digest, or ``None`` when the library is absent, which
    is a supported configuration because the game ``dlopen``s it at runtime.
    """
    exemption = redistribution_exemption(name, table)
    if not source.exists() and not source.is_symlink():
        return None
    require_regular_file(source, "redistributable library")
    if exemption.sha256 == REDISTRIBUTION_PLACEHOLDER_SHA256:
        fail(
            "redistribution exemption for {} still carries the placeholder pin; record the "
            "lowercase SHA-256 of {} in REDISTRIBUTION_EXEMPTION_RECORDS before staging it".format(
                name, source
            )
        )
    actual = sha256_file(source)
    if actual != exemption.sha256:
        fail(
            "redistributable checksum mismatch for {}: expected {}, got {}".format(
                name, exemption.sha256, actual
            )
        )
    materialize_redistribution_license(source_root, staging_root, exemption, actual, source)
    return actual


def stage_redistributable_library(
    source_root: Path,
    staging_root: Path,
    name: str,
    source: Path,
    table: Mapping[str, RedistributionExemption] = REDISTRIBUTION_EXEMPTIONS,
) -> Optional[str]:
    digest = verify_redistribution_exemption(source_root, staging_root, name, source, table)
    if digest is None:
        return None
    real_source = source.resolve()
    if not is_x86_64_elf(real_source):
        fail("redistributable library is not x86-64 ELF: {}".format(source))
    library_dir = staging_root / "lib"
    library_dir.mkdir(parents=True, exist_ok=True)
    destination = library_dir / name
    if destination.exists() or destination.is_symlink():
        fail("conflicting staged library basename: {}".format(name))
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o644)
    return digest


def verify_redistribution_records(
    staging_root: Path,
    redistributed: Mapping[str, str],
    table: Mapping[str, RedistributionExemption] = REDISTRIBUTION_EXEMPTIONS,
) -> None:
    """Require every exempt library in lib/ to carry a verified pin and license."""
    library_dir = staging_root / "lib"
    for name, digest in sorted(redistributed.items()):
        exemption = redistribution_exemption(name, table)
        if digest != exemption.sha256 or exemption.sha256 == REDISTRIBUTION_PLACEHOLDER_SHA256:
            fail("redistributable {} was staged without a verified pin".format(name))
        staged = library_dir / name
        require_regular_file(staged, "staged redistributable library")
        actual = sha256_file(staged)
        if actual != exemption.sha256:
            fail(
                "staged redistributable checksum mismatch for {}: expected {}, got {}".format(
                    name, exemption.sha256, actual
                )
            )
        license_dir = (
            staging_root / "licenses" / "redistributable" / safe_redistribution_name(name)
        )
        require_regular_file(license_dir / "LICENSE.txt", "staged redistributable license")
        metadata_path = license_dir / "metadata.txt"
        require_regular_file(metadata_path, "staged redistributable metadata")
        metadata_lines = metadata_path.read_text(encoding="utf-8").splitlines()
        if "Name: {}".format(name) not in metadata_lines:
            fail("staged redistributable metadata has no name record: {}".format(name))
        if "Pinned SHA256: {}".format(exemption.sha256) not in metadata_lines:
            fail("staged redistributable metadata has no checksum record: {}".format(name))
        if "Origin: {}".format(exemption.origin) not in metadata_lines:
            fail("staged redistributable metadata has no origin record: {}".format(name))


def verify_elf_license_records(
    staging_root: Path,
    closure: ElfClosure,
    redistributed: Mapping[str, str],
) -> None:
    """Require every staged real ELF to have complete Debian provenance."""
    records = tuple(closure.packages.values())
    if not records:
        fail("ELF closure contains no Debian package records")

    source_map: Dict[Tuple[str, str], List[PackageRecord]] = {}
    for record in records:
        if not record.package or not record.version:
            fail("ELF package record is missing package or version")
        if not record.source_files:
            fail("ELF package record has no source files: {}".format(record.package))
        if record.copyright_path is None:
            fail("ELF package record has no copyright source: {}".format(record.package))
        require_regular_file(record.copyright_path, "Debian copyright source")

        safe_package = re.sub(r"[^A-Za-z0-9._+-]", "_", record.package)
        metadata_dir = staging_root / "licenses" / "debian" / safe_package
        require_regular_file(metadata_dir / "copyright", "staged Debian copyright")
        metadata_path = metadata_dir / "metadata.txt"
        require_regular_file(metadata_path, "staged Debian metadata")
        metadata_lines = metadata_path.read_text(encoding="utf-8").splitlines()
        if "Package: {}".format(record.package) not in metadata_lines:
            fail("staged Debian metadata has no package record: {}".format(record.package))
        if "Version: {}".format(record.version) not in metadata_lines:
            fail("staged Debian metadata has no version record: {}".format(record.package))

        expected_sources = [str(path) for path in sorted(record.source_files, key=lambda item: str(item))]
        actual_sources = [
            line[len("Source file: ") :]
            for line in metadata_lines
            if line.startswith("Source file: ")
        ]
        if actual_sources != expected_sources:
            fail("staged Debian metadata has incomplete source files: {}".format(record.package))

        for source in record.source_files:
            require_regular_file(source, "ELF source file")
            if not is_x86_64_elf(source):
                fail("ELF source file is not x86-64: {}".format(source))
            key = (source.name, sha256_file(source))
            source_map.setdefault(key, []).append(record)

    staged_keys: Set[Tuple[str, str]] = set()
    library_dir = staging_root / "lib"
    for path in sorted(library_dir.iterdir()):
        if path.is_symlink():
            continue
        if not path.is_file():
            fail("non-file entry in ELF library directory: {}".format(path.name))
        if not is_x86_64_elf(path):
            fail("real ELF library is not x86-64: {}".format(path.name))
        if forbidden_soname(path.name):
            fail("forbidden system library bundled: {}".format(path.name))
        if path.name in redistributed:
            continue
        key = (path.name, sha256_file(path))
        if key not in source_map:
            fail(
                "real ELF library lacks package/version/copyright/source record: {}".format(
                    path.name
                )
            )
        staged_keys.add(key)

    for key, records_for_source in source_map.items():
        if key not in staged_keys:
            packages = ", ".join(sorted(record.package for record in records_for_source))
            fail("ELF source file is not staged for package(s) {}: {}".format(packages, key[0]))

    verify_redistribution_records(staging_root, redistributed)


def verify_font_checksums(source_root: Path) -> None:
    font_dir = source_root / "Fonts"
    manifest = font_dir / "SHA256SUMS"
    for required in (
        manifest,
        font_dir / "SOURCES.md",
        font_dir / "licenses" / "OFL-1.1.txt",
        font_dir / "licenses" / "IPA-Font-License-Agreement-v1.0.txt",
        font_dir / "licenses" / "FONT-ATTRIBUTIONS.txt",
    ):
        require_regular_file(required, "font metadata")
    checksums = parse_sha256sums(manifest)
    if checksums != FONT_CHECKSUMS:
        fail("Fonts/SHA256SUMS does not match the pinned seven-font set")
    for filename, expected in checksums.items():
        path = font_dir / filename
        require_regular_file(path, "font")
        actual = sha256_file(path)
        if actual != expected:
            fail("font checksum mismatch for {}: expected {}, got {}".format(filename, expected, actual))
    for path in font_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".ttf", ".otf", ".fon"):
            if path.name not in FONT_CHECKSUMS or path.parent != font_dir:
                fail("unlisted font binary under Fonts/: {}".format(path.relative_to(font_dir)))


def verify_required_elf_families(closure: ElfClosure) -> None:
    names = tuple(name.lower() for name in closure.classifications)
    for label, needles in REQUIRED_ELF_FAMILIES:
        if not any(any(needle in name for needle in needles) for name in names):
            fail("required ELF dependency family is absent: {}".format(label))


def tracked_allowlist(source_root: Path) -> List[str]:
    arguments = ["git", "-C", str(source_root), "ls-files", "-z", "--", "OpenNeoUA.sh"]
    arguments.extend(ALLOWED_ASSET_ROOTS)
    output = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if output.returncode != 0:
        fail("git ls-files allowlist failed: {}".format(output.stderr.decode(errors="replace").strip()))
    paths = [item.decode("utf-8") for item in output.stdout.split(b"\0") if item]
    if "OpenNeoUA.sh" not in paths:
        fail("OpenNeoUA.sh is not tracked by Git")
    return paths


def copy_tracked_assets(source_root: Path, staging_root: Path) -> None:
    paths = tracked_allowlist(source_root)
    allowed = {"OpenNeoUA.sh"}.union(ALLOWED_ASSET_ROOTS)
    root_resolved = source_root.resolve()
    for relative in paths:
        posix = safe_relative(relative)
        top = posix.parts[0]
        if top not in allowed:
            fail("allowlist returned unexpected path: {}".format(relative))
        source = source_root.joinpath(*posix.parts)
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            fail("tracked package input must be a regular file: {}".format(relative))
        if source.resolve() != source and not is_relative_to(source.resolve(), root_resolved):
            fail("tracked package input escapes source root: {}".format(relative))
        destination = staging_root.joinpath(*posix.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        os.chmod(destination, stat.S_IMODE(mode))


def read_steam_input_revision(source_root: Path) -> str:
    revision_path = source_root / STEAM_INPUT_SOURCE_DIR / "REVISION.txt"
    require_regular_file(revision_path, "Steam Input revision metadata")
    for raw in revision_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.lower().startswith("openneoua steam deck layout revision:"):
            value = line.split(":", 1)[1].strip()
            if value:
                return value
    fail("Steam Input REVISION.txt is missing a layout revision line")


def copy_steam_input_assets(source_root: Path, staging_root: Path) -> str:
    source_dir = source_root / STEAM_INPUT_SOURCE_DIR
    if source_dir.is_symlink() or not source_dir.is_dir():
        fail("Steam Input source directory is missing: {}".format(STEAM_INPUT_SOURCE_DIR))
    revision = read_steam_input_revision(source_root)
    destination = staging_root / "SteamInput"
    destination.mkdir(parents=True, exist_ok=True)
    for name in STEAM_INPUT_REQUIRED_FILES:
        source = source_dir / name
        require_regular_file(source, "Steam Input asset {}".format(name))
        if source.is_symlink():
            fail("Steam Input asset must not be a symlink: {}".format(name))
        target = destination / name
        shutil.copyfile(source, target)
        os.chmod(target, 0o644)
    unexpected = sorted(
        path.name
        for path in destination.iterdir()
        if path.name not in STEAM_INPUT_REQUIRED_FILES
    )
    if unexpected:
        fail("SteamInput/ contains unexpected entries: {}".format(", ".join(unexpected)))
    return revision


def write_steam_appid(staging_root: Path) -> None:
    destination = staging_root / "bin" / "steam_appid.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(STEAM_APPID + "\n", encoding="utf-8")
    os.chmod(destination, 0o644)


def source_provenance_lines(
    commit: str,
    dirty_base_commit: Optional[str],
    artifact_identifier: str,
) -> List[str]:
    if dirty_base_commit is None:
        return [
            "Source state: clean",
            "Base commit: {}".format(commit),
            "Synthetic snapshot commit: none",
            "Artifact identifier: {}".format(artifact_identifier),
        ]
    return [
        "Source state: dirty synthetic snapshot",
        "Base commit: {}".format(dirty_base_commit),
        "Synthetic snapshot commit: {}".format(commit),
        "Artifact identifier: {}".format(artifact_identifier),
    ]


def write_package_licenses(
    source_root: Path,
    staging_root: Path,
    repository: str,
    commit: str,
    dirty_base_commit: Optional[str],
    artifact_identifier: str,
) -> None:
    license_source = source_root / "License.txt"
    require_regular_file(license_source, "OpenNeoUA source license")
    licenses = staging_root / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_source, licenses / "OpenNeoUA-GPL-2.0.txt")
    source_notice_lines = [
        "OpenNeoUA source repository",
        "Repository: {}".format(repository),
        "Commit: {}".format(commit),
    ]
    source_notice_lines.extend(
        source_provenance_lines(commit, dirty_base_commit, artifact_identifier)
    )
    source_notice_lines.append("The package contains no original Urban Assault data.")
    source_notice = "\n".join(source_notice_lines) + "\n"
    (licenses / "OpenNeoUA-SOURCE.txt").write_text(source_notice, encoding="utf-8")


def find_repository_url(source_root: Path) -> str:
    configured = run_command(
        ["git", "-C", str(source_root), "remote", "get-url", "origin"], check=False
    ).strip()
    if configured:
        return configured
    return "https://github.com/ertw/OpenNeoUA-SteamOS"


def tool_version(command: Sequence[str]) -> str:
    output = run_command(command, check=False).strip().splitlines()
    return output[0] if output else "unavailable"


def package_dependency_versions(report: Optional[Path]) -> str:
    if report is not None:
        require_regular_file(report, "dependency version report")
        return report.read_text(encoding="utf-8")

    lines = [
        "CMake: {}".format(tool_version(["cmake", "--version"])),
        "Ninja: {}".format(tool_version(["ninja", "--version"])),
        "GCC: {}".format(tool_version(["gcc", "--version"])),
        "G++: {}".format(tool_version(["g++", "--version"])),
        "pkgconf: {}".format(tool_version(["pkgconf", "--version"])),
        "pax-utils: package version recorded by CI when available",
    ]
    for package in DEPENDENCY_PACKAGES:
        value = run_command(
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n", package], check=False
        ).strip()
        lines.append("{}: {}".format(package, value or "unavailable"))
    return "\n".join(lines) + "\n"


def write_build_info(
    staging_root: Path,
    source_root: Path,
    commit: str,
    repository: str,
    runtime_dir: Path,
    runtime_checksums: Dict[str, str],
    runtime_package_count: int,
    closure: ElfClosure,
    dependency_report: Optional[Path],
    dirty_base_commit: Optional[str],
    artifact_identifier: str,
    redistributed: Mapping[str, str],
) -> None:
    build_time = run_command(
        ["git", "-C", str(source_root), "show", "-s", "--format=%ct", commit], check=False
    ).strip()
    lines = [
        "OpenNeoUA SteamRT4 build information",
        "Source commit: {}".format(commit),
        "Source short SHA: {}".format(commit[:7]),
    ]
    lines.extend(source_provenance_lines(commit, dirty_base_commit, artifact_identifier))
    lines.extend(
        [
            "Source repository: {}".format(repository),
            "Source commit timestamp: {}".format(build_time or "unknown"),
            "Architecture: x86_64",
            "Steam Linux Runtime version: {}".format(RUNTIME_VERSION),
            "SteamRT4 container: registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:{}".format(
                RUNTIME_VERSION
            ),
            "Runtime Debian package manifest entries: {}".format(runtime_package_count),
            "Runtime SHA256SUMS: {}".format(
                runtime_checksums.get(
                    "SHA256SUMS", sha256_file(runtime_dir / "SHA256SUMS")
                )
            ),
        ]
    )
    for filename in RUNTIME_FILES:
        lines.append("Runtime {} SHA256: {}".format(filename, runtime_checksums[filename]))
    lines.extend(
        [
            "Compiler: {}".format(tool_version(["gcc", "--version"])),
            "Linker/readelf: {}".format(tool_version(["readelf", "--version"])),
            "Packaging tools: Python standard library, GNU tar, xz",
            "Build dependencies:",
            package_dependency_versions(dependency_report).rstrip(),
            "ELF dependency classification:",
        ]
    )
    for name in sorted(closure.classifications):
        lines.append("  {} = {}".format(name, closure.classifications[name]))
    lines.extend(
        [
            "Redistributed Debian packages:",
        ]
    )
    for package in sorted(closure.packages.values(), key=lambda item: item.package):
        lines.append("  {} {}".format(package.package, package.version))
    lines.append("Redistributed non-Debian libraries:")
    if redistributed:
        for name in sorted(redistributed):
            lines.append(
                "  {} {} ({})".format(
                    name, redistributed[name], REDISTRIBUTION_EXEMPTIONS[name].origin
                )
            )
    else:
        lines.append("  none")
    lines.append(
        "Steam Input runtime library: {}".format(
            "{} staged in lib/".format(STEAM_API_LIBRARY_NAME)
            if STEAM_API_LIBRARY_NAME in redistributed
            else "{} absent; Steam Input support unavailable at runtime".format(
                STEAM_API_LIBRARY_NAME
            )
        )
    )
    lines.extend(
        [
            "Steam Input layout: OpenNeoUA Deck Default",
            "Steam Input layout revision: {}".format(
                read_steam_input_revision(source_root)
            ),
            "Steam Input package path: SteamInput/",
            "Steam Deck tests: manual, not run in this CI job",
            "Bazzite tests: manual, not run in this CI job",
            "Deck Verified: not claimed",
        ]
    )
    (staging_root / "BUILD-INFO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_symlinks(staging_root: Path) -> None:
    for path in staging_root.rglob("*"):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        target_path = PurePosixPath(target)
        if target_path.is_absolute() or ".." in target_path.parts:
            fail("package symlink escapes its tree: {} -> {}".format(path, target))
        resolved = path.parent.joinpath(*target_path.parts).resolve()
        if not is_relative_to(resolved, staging_root.resolve()):
            fail("package symlink resolves outside staging root: {}".format(path))
        if not resolved.exists():
            fail("package symlink target is missing: {} -> {}".format(path, target))


def iter_payload_files(staging_root: Path) -> Iterable[Path]:
    for path in sorted(staging_root.rglob("*")):
        if path.name == "MANIFEST.sha256":
            continue
        if path.is_symlink() or path.is_file():
            yield path


def write_payload_manifest(staging_root: Path) -> None:
    validate_symlinks(staging_root)
    entries: List[str] = []
    for path in iter_payload_files(staging_root):
        relative = path.relative_to(staging_root).as_posix()
        entries.append("{}  {}".format(sha256_file(path), relative))
    (staging_root / "MANIFEST.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def verify_payload_manifest(staging_root: Path) -> None:
    manifest = staging_root / "MANIFEST.sha256"
    require_regular_file(manifest, "package payload manifest")
    seen: Set[str] = set()
    for line_number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        fields = raw.split("  ", 1)
        if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            fail("invalid package manifest line {}".format(line_number))
        relative = safe_relative(fields[1]).as_posix()
        if relative in seen or relative == "MANIFEST.sha256":
            fail("duplicate or self-referential package manifest entry: {}".format(relative))
        seen.add(relative)
        path = staging_root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() and not path.is_symlink():
            fail("package manifest entry is missing: {}".format(relative))
        if sha256_file(path) != fields[0]:
            fail("package manifest checksum mismatch: {}".format(relative))
    expected = {
        path.relative_to(staging_root).as_posix() for path in iter_payload_files(staging_root)
    }
    if seen != expected:
        missing = sorted(expected - seen)
        unlisted = sorted(seen - expected)
        fail(
            "package manifest coverage mismatch (missing: {}; unlisted: {})".format(
                ", ".join(missing) or "none", ", ".join(unlisted) or "none"
            )
        )


def verify_package_layout(staging_root: Path) -> None:
    validate_symlinks(staging_root)
    top_level = sorted(path.name for path in staging_root.iterdir())
    if top_level != sorted(PACKAGE_TOP_LEVEL):
        fail("package top-level layout mismatch: {}".format(", ".join(top_level)))
    for directory in (
        "bin",
        "lib",
        "Fonts",
        "3ds",
        "Database",
        "Env",
        "Filters",
        "Interface",
        "Locale",
        "Res",
        "Scripts",
        "Sounds",
        "Wireless",
        "SteamInput",
        "licenses",
    ):
        if not (staging_root / directory).is_dir():
            fail("package entry is not a directory: {}".format(directory))
    steam_input = staging_root / "SteamInput"
    expected_steam_input = sorted(STEAM_INPUT_REQUIRED_FILES)
    actual_steam_input = sorted(path.name for path in steam_input.iterdir())
    if actual_steam_input != expected_steam_input:
        fail(
            "SteamInput/ layout mismatch: {}".format(", ".join(actual_steam_input))
        )
    if sorted(path.name for path in (staging_root / "bin").iterdir()) != sorted(BIN_PACKAGE_FILES):
        fail("package bin/ layout mismatch: {}".format(
            ", ".join(sorted(path.name for path in (staging_root / "bin").iterdir()))
        ))
    executable = staging_root / "bin" / "OpenNeoUA"
    require_regular_file(executable, "installed OpenNeoUA executable")
    if not is_x86_64_elf(executable):
        fail("installed OpenNeoUA is not x86-64 ELF")
    if not os.access(executable, os.X_OK):
        fail("installed OpenNeoUA is not executable")
    for path in staging_root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".iso":
            fail("game ISO must not be packaged: {}".format(path.relative_to(staging_root)))
    runpath = readelf_runpath(executable)
    if "$ORIGIN/../lib" not in runpath:
        fail(
            "installed OpenNeoUA is missing $ORIGIN/../lib RUNPATH (got {})".format(
                runpath
            )
        )
    launcher = staging_root / "OpenNeoUA.sh"
    require_regular_file(launcher, "OpenNeoUA launcher")
    if not os.access(launcher, os.X_OK):
        fail("OpenNeoUA.sh is not executable")
    for path in (staging_root / "lib").iterdir():
        if path.is_symlink():
            continue
        if not path.is_file():
            fail("non-file entry bundled in lib/: {}".format(path.name))
        if forbidden_soname(path.name):
            fail("forbidden system library bundled: {}".format(path.name))
        if not is_x86_64_elf(path):
            fail("non-x86-64 file bundled in lib/: {}".format(path.name))


def verify_no_unresolved_dependencies(staging_root: Path, runtime_names: Set[str]) -> None:
    executable = staging_root / "bin" / "OpenNeoUA"
    queue = [executable]
    seen: Set[Path] = set()
    while queue:
        target = queue.pop()
        target = target.resolve()
        if target in seen:
            continue
        seen.add(target)
        for name in readelf_dynamic(target)[0]:
            if name in runtime_names:
                continue
            candidate = staging_root / "lib" / name
            if not candidate.exists():
                fail("private ELF dependency is not bundled: {} (from {})".format(name, target))
            queue.append(candidate)


def create_archive(
    staging_root: Path,
    output_dir: Path,
    commit: str,
    source_root: Path,
    artifact_identifier: str,
) -> Tuple[Path, Path]:
    tar_path = shutil.which("tar")
    if tar_path is None:
        fail("GNU tar is required to create the Steam artifact")
    tar_version = run_command([tar_path, "--version"], check=False)
    if "GNU tar" not in tar_version:
        fail("GNU tar is required to create the Steam artifact")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "OpenNeoUA-steamrt4-x86_64-{}.tar.xz".format(
        artifact_identifier
    )
    timestamp = run_command(
        ["git", "-C", str(source_root), "show", "-s", "--format=%ct", commit], check=False
    ).strip()
    if not timestamp.isdigit():
        timestamp = "0"
    names = sorted(path.name for path in staging_root.iterdir())
    command = [
        tar_path,
        "--sort=name",
        "--mtime=@{}".format(timestamp),
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "-cJf",
        str(archive),
        "-C",
        str(staging_root),
    ] + names
    run_command(command)
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text("{}  {}\n".format(sha256_file(archive), archive.name), encoding="utf-8")
    return archive, checksum


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=default_root)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--runtime-base-url", default=RUNTIME_BASE_URL)
    parser.add_argument("--runtime-version", default=RUNTIME_VERSION)
    parser.add_argument("--dependency-report", type=Path)
    parser.add_argument(
        "--steam-api-library",
        type=Path,
        help=(
            "optional {} to stage under the Steamworks redistribution exemption "
            "(default: <source-root>/{} when present, else <source-root>/{}); "
            "packaging succeeds without it and Steam Input support is unavailable at runtime".format(
                STEAM_API_LIBRARY_NAME,
                VENDOR_STEAM_API_LIBRARY.as_posix(),
                (REDISTRIBUTABLE_SOURCE_DIR / STEAM_API_LIBRARY_NAME).as_posix(),
            )
        ),
    )
    parser.add_argument(
        "--dirty-base-commit",
        help="full base commit for a deterministic dirty synthetic snapshot",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        source_root = args.source_root.resolve()
        build_dir = args.build_dir.resolve()
        staging_root = args.staging_dir.resolve()
        output_dir = args.output_dir.resolve()
        if args.runtime_version != RUNTIME_VERSION:
            fail(
                "only pinned SteamRT4 version {} is supported (got {})".format(
                    RUNTIME_VERSION, args.runtime_version
                )
            )
        if not build_dir.is_dir():
            fail("build directory is missing: {}".format(build_dir))
        executable = staging_root / "bin" / "OpenNeoUA"
        require_regular_file(executable, "CMake-installed executable")
        if not is_x86_64_elf(executable):
            fail("CMake-installed executable is not x86-64 ELF")

        verify_font_checksums(source_root)
        commit = run_command(["git", "-C", str(source_root), "rev-parse", "HEAD"]).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            fail("source root is not at a valid Git commit")
        dirty_base_commit = args.dirty_base_commit
        if dirty_base_commit is not None:
            if not re.fullmatch(r"[0-9a-f]{40}", dirty_base_commit):
                fail("--dirty-base-commit must be a full 40-character lowercase commit")
            parents = run_command(
                ["git", "-C", str(source_root), "show", "-s", "--format=%P", commit]
            ).strip().split()
            if parents != [dirty_base_commit]:
                fail(
                    "dirty snapshot commit must have the declared base as its single parent"
                )
            artifact_identifier = "{}-dirty-{}".format(
                dirty_base_commit[:7], commit[:7]
            )
        else:
            artifact_identifier = commit[:7]
        repository = find_repository_url(source_root)
        runtime_dir = (args.runtime_dir or (output_dir / ".steamrt4-runtime")).resolve()
        manifest_path, mtree_path, checksums = ensure_runtime_manifests(
            runtime_dir, args.runtime_base_url, args.runtime_version
        )
        runtime_names = runtime_sonames(mtree_path)
        runtime_package_map = runtime_packages(manifest_path)

        staging_root.mkdir(parents=True, exist_ok=True)
        (staging_root / "lib").mkdir(parents=True, exist_ok=True)
        closure = ElfClosure(runtime_names, runtime_package_map, staging_root / "lib")
        closure.collect(executable)
        verify_required_elf_families(closure)
        closure.materialize_licenses(staging_root)

        steam_api_source = (
            args.steam_api_library.resolve()
            if args.steam_api_library is not None
            else (source_root / VENDOR_STEAM_API_LIBRARY)
            if (source_root / VENDOR_STEAM_API_LIBRARY).is_file()
            else source_root / REDISTRIBUTABLE_SOURCE_DIR / STEAM_API_LIBRARY_NAME
        )
        redistributed: Dict[str, str] = {}
        steam_api_digest = stage_redistributable_library(
            source_root, staging_root, STEAM_API_LIBRARY_NAME, steam_api_source
        )
        if steam_api_digest is None:
            print(
                "package.py: {} not found at {}; Steam Input support will be "
                "unavailable at runtime".format(STEAM_API_LIBRARY_NAME, steam_api_source)
            )
        else:
            redistributed[STEAM_API_LIBRARY_NAME] = steam_api_digest

        verify_elf_license_records(staging_root, closure, redistributed)
        copy_tracked_assets(source_root, staging_root)
        copy_steam_input_assets(source_root, staging_root)
        write_steam_appid(staging_root)
        write_package_licenses(
            source_root,
            staging_root,
            repository,
            commit,
            dirty_base_commit,
            artifact_identifier,
        )
        write_build_info(
            staging_root,
            source_root,
            commit,
            repository,
            runtime_dir,
            checksums,
            len(runtime_package_map),
            closure,
            args.dependency_report,
            dirty_base_commit,
            artifact_identifier,
            redistributed,
        )
        write_payload_manifest(staging_root)
        verify_package_layout(staging_root)
        verify_no_unresolved_dependencies(staging_root, runtime_names)
        verify_payload_manifest(staging_root)
        archive, checksum = create_archive(
            staging_root,
            output_dir,
            commit,
            source_root,
            artifact_identifier,
        )
        print("Created {}".format(archive))
        print("Created {}".format(checksum))
        return 0
    except PackagingError as exc:
        print("package.py: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
