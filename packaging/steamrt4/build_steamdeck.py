#!/usr/bin/env python3
"""Build a private, asset-backed OpenNeoUA AppImage for Steam Deck.

This module intentionally keeps all proprietary-asset handling on the host
side of the Docker boundary.  The source snapshot passed to Docker is made by
``local_ci.py`` and never contains game ISOs.  The owned base-game ISO at
``vendor/ua.iso`` (gitignored, local only) is mounted into a short-lived
assembly container read-only and only the validated base-game payload is copied
into the AppDir.

The small validation functions are public on purpose: the GitHub asset-free
test job and downstream packagers can exercise archive/path policy without
having a game ISO available.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zlib
from typing import Iterable, Iterator, Mapping, Sequence
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STEAMRT4_VERSION = "4.0.20260805.254769"
STEAMRT4_IMAGE = (
    "registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:" + STEAMRT4_VERSION
)
STEAMDECK_IMAGE = "openneoua-steamdeck-appimage:" + STEAMRT4_VERSION

# These are deliberately immutable URLs and hashes.  In particular, do not
# let appimagetool fetch a runtime at package time: that makes a private build
# depend on an unreviewed mutable release.
APPIMAGETOOL_VERSION = "1.9.1"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/"
    "appimagetool-x86_64.AppImage"
)
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGE_RUNTIME_VERSION = "20251108"
APPIMAGE_RUNTIME_URL = (
    "https://github.com/AppImage/type2-runtime/releases/download/20251108/"
    "runtime-x86_64"
)
APPIMAGE_RUNTIME_SHA256 = "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

DEFAULT_ISO = Path("vendor/ua.iso")
DEFAULT_OUTPUT_DIR = Path("build/steamdeck-private/artifacts")
DEFAULT_CACHE_DIR = Path("build/steamdeck-private/cache")

BASE_ROOTS = {
    "DATA": "Data",
    "ENV": "Env",
    "LEVELS": "Levels",
    "LOCALE": "Locale",
    "SAVE": "Save",
}
BASE_FILE = ("NUCLEUS.INI", "Nucleus.ini")
EXPANSION_MARKERS = {
    "METROPOLIS DAWN",
    "METROPOLISDAWN",
    "METROPOLIS_DAWN",
    "METROPOLIS-DAWN",
    "EXPANSION",
}
KNOWN_EXCLUDED_GAME_ROOTS = {"HELP"}
# The legal-edition ISO also stores these launcher/support files directly
# below GAME.  They are known non-payload members: validate them explicitly so
# they are not confused with an unrecognized directory, but never select them
# for extraction into the AppDir.
KNOWN_EXCLUDED_GAME_FILES = {"DUNGEON.TTF", "MSS32.DLL", "README.TXT", "UA.EXE"}
FORBIDDEN_PAYLOAD_SUFFIXES = {
    ".EXE",
    ".DLL",
    ".COM",
    ".BAT",
    ".MSI",
    ".CAB",
    ".INF",
}
FORBIDDEN_PAYLOAD_WORDS = ("SETUP", "INSTALL", "PATCH", "README", "HELP")
REQUIRED_MENU_ASSETS = (
    "Data/SET46/FONTPAGE.ILB",
    "Data/SET46/GADGSHLL.ILB",
    "Data/SET46/GADGSHLO.ILB",
    "Data/SET46/ICONPAGE.ILB",
    "Data/SET46/MB.ILB",
    "Levels/BG/STARTUP.IFF",
    "Levels/BG/SETTINGS.IFF",
    "Nucleus.ini",
)


class AssetBuildError(RuntimeError):
    """Raised when an asset archive or AppDir fails the safety policy."""


@dataclass(frozen=True)
class ArchiveEntry:
    """A normalized archive listing entry.

    ``kind`` is one of ``file`` or ``dir``.  Links and special files are
    represented explicitly so validators can reject them rather than silently
    treating them as regular files.
    """

    path: str
    kind: str = "file"
    link_target: str | None = None
    size: int = 0


@dataclass(frozen=True)
class BaseSelection:
    """Validated base payload selection from an ISO listing."""

    files: tuple[tuple[str, str], ...]
    directories: tuple[str, ...]
    excluded_expansion: tuple[str, ...]


@dataclass(frozen=True)
class BuildMetadata:
    source_id: str
    source_state: str
    overlay_checksum: str
    iso_sha256: str
    iso12: str
    excluded_expansion: tuple[str, ...]


def _error(message: str) -> AssetBuildError:
    return AssetBuildError(message)


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _normalize_archive_path(value: str) -> str:
    if not isinstance(value, str):
        raise _error("archive entry path is not text")
    if "\0" in value:
        raise _error("archive entry contains NUL")
    value = value.replace("\\", "/")
    if value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise _error("archive entry is absolute: {!r}".format(value))
    while value.startswith("./"):
        value = value[2:]
    parts = value.split("/")
    if not value or any(not item or item in (".", "..") for item in parts):
        raise _error("archive entry has traversal or empty components: {!r}".format(value))
    normalized = "/".join(parts)
    if normalized != value:
        raise _error("archive entry is not canonical: {!r}".format(value))
    return normalized


# Stable public names for callers that want to exercise policy without
# depending on this module's private helper spelling.
normalize_archive_path = _normalize_archive_path


def _coerce_entry(item: ArchiveEntry | str | Mapping[str, object]) -> ArchiveEntry:
    if isinstance(item, ArchiveEntry):
        return ArchiveEntry(_normalize_archive_path(item.path), item.kind, item.link_target, item.size)
    if isinstance(item, str):
        path = item
        kind = "dir" if path.endswith(("/", "\\")) else "file"
        return ArchiveEntry(_normalize_archive_path(path.rstrip("/\\")), kind)
    if isinstance(item, Mapping):
        raw_path = item.get("path", item.get("Path"))
        if not isinstance(raw_path, str):
            raise _error("archive listing record has no path")
        raw_kind = item.get("kind", item.get("type", "file"))
        kind = str(raw_kind).lower()
        if kind in {"directory", "folder", "d"}:
            kind = "dir"
        elif kind in {"regular", "regular_file", "f"}:
            kind = "file"
        link = item.get("link_target", item.get("target"))
        size = item.get("size", 0)
        try:
            size_int = int(size)
        except (TypeError, ValueError):
            raise _error("archive listing has an invalid size")
        return ArchiveEntry(_normalize_archive_path(raw_path), kind, str(link) if link is not None else None, size_int)
    raise _error("unsupported archive listing entry")


def validate_iso_listing(entries: Iterable[ArchiveEntry | str | Mapping[str, object]]) -> tuple[ArchiveEntry, ...]:
    """Validate an ISO/7z listing for safe extraction.

    The validator applies to the complete listing, including installer files
    that will later be ignored.  This is important: a hostile ignored entry
    must not be able to turn into an extraction escape or a case-fold collision.
    """

    result: list[ArchiveEntry] = []
    exact: dict[str, ArchiveEntry] = {}
    folded: dict[tuple[str, ...], tuple[str, ...]] = {}
    for original in entries:
        entry = _coerce_entry(original)
        if entry.kind not in {"file", "dir"}:
            raise _error("ISO contains a link or special file: {}".format(entry.path))
        if entry.link_target is not None:
            raise _error("ISO contains a link: {}".format(entry.path))
        if entry.size < 0:
            raise _error("ISO contains a negative-sized entry: {}".format(entry.path))
        previous = exact.get(entry.path)
        if previous is not None:
            raise _error("duplicate ISO path: {}".format(entry.path))
        exact[entry.path] = entry
        parts = tuple(entry.path.split("/"))
        for count in range(1, len(parts) + 1):
            actual = parts[:count]
            key = tuple(_fold(part) for part in actual)
            old = folded.get(key)
            if old is not None and old != actual:
                raise _error(
                    "case-fold collision: {} and {}".format("/".join(old), "/".join(actual))
                )
            folded[key] = actual
        result.append(entry)

    # A file cannot simultaneously be a parent directory.  Some archive
    # tools omit explicit directory records, so only reject when the listing
    # explicitly says the parent is a file.
    for entry in result:
        prefix = entry.path + "/"
        if entry.kind == "file" and any(other.path.startswith(prefix) for other in result):
            raise _error("ISO file/directory conflict: {}".format(entry.path))
    return tuple(result)


def _relative_under(path: str, root: str) -> str | None:
    parts = path.split("/")
    root_parts = root.split("/")
    if len(parts) <= len(root_parts):
        return None
    if tuple(_fold(part) for part in parts[: len(root_parts)]) != tuple(_fold(part) for part in root_parts):
        return None
    return "/".join(parts[len(root_parts) :])


def select_base_game_entries(entries: Iterable[ArchiveEntry | str | Mapping[str, object]]) -> BaseSelection:
    """Select only the six base roots and ``GAME/NUCLEUS.INI``.

    The ISO may contain a normal installer and other legal-edition support
    files.  They are deliberately excluded.  Metropolis Dawn is excluded even
    if a future edition stores it inside the ISO; its paths are returned in
    provenance so the omission is auditable.
    """

    listing = validate_iso_listing(entries)
    files: list[tuple[str, str]] = []
    directories: set[str] = set()
    excluded: list[str] = []

    # Validate the immediate GAME root from every member path before selecting
    # files.  ISO/7z listings are allowed to omit directory records, so a
    # check that only sees ``GAME/UNKNOWN`` as an explicit directory would
    # miss ``GAME/UNKNOWN/payload.bin`` and later sweep it up with a wildcard.
    # Expansion paths are known and intentionally excluded; HELP is the only
    # other historical support tree that may be present without being copied.
    for entry in listing:
        parts = entry.path.split("/")
        if len(parts) < 2 or _fold(parts[0]) != "game":
            continue
        upper_parts = [_fold(part).upper() for part in parts]
        if any(marker in upper_parts[1:] for marker in EXPANSION_MARKERS):
            continue
        root = upper_parts[1]
        if root in BASE_ROOTS or root in KNOWN_EXCLUDED_GAME_ROOTS or root in {"NUCLEUS.INI"}:
            if root == "NUCLEUS.INI" and len(parts) != 2:
                raise _error("GAME/NUCLEUS.INI cannot contain child members")
            continue
        if len(parts) == 2 and root in KNOWN_EXCLUDED_GAME_FILES:
            continue
        raise _error("unexpected GAME root: {}".format("/".join(parts[:2])))

    for entry in listing:
        parts = entry.path.split("/")
        if not parts or _fold(parts[0]) != "game":
            continue
        upper_parts = [_fold(part).upper() for part in parts]
        if any(marker in upper_parts for marker in EXPANSION_MARKERS):
            excluded.append(entry.path)
            continue
        if len(parts) < 2:
            continue
        root = upper_parts[1]
        if root in BASE_ROOTS:
            canonical_root = BASE_ROOTS[root]
            if entry.kind == "dir":
                directories.add(canonical_root + ("/" + "/".join(parts[2:]) if len(parts) > 2 else ""))
                continue
            relative = "/".join(parts[2:])
            if not relative:
                raise _error("base root is a file: {}".format(entry.path))
            # The original game stores its language catalogue as
            # ``LOCALE/LANGUAGE.DLL``; that DLL is data consumed by the engine,
            # not a Windows executable to launch.  Other selected roots must
            # not carry executable/installer payloads.
            if canonical_root != "Locale" and any(part.upper().endswith(tuple(FORBIDDEN_PAYLOAD_SUFFIXES)) for part in parts[2:]):
                raise _error("executable/installer inside selected base root: {}".format(entry.path))
            if any(word in _fold(part).upper() for part in parts[2:] for word in FORBIDDEN_PAYLOAD_WORDS):
                raise _error("installer/help/patch file inside selected base root: {}".format(entry.path))
            files.append((entry.path, canonical_root + "/" + relative))
        elif upper_parts[1] in {"NUCLEUS.INI"} and len(parts) == 2:
            if entry.kind != "file":
                raise _error("GAME/NUCLEUS.INI is not a regular file")
            files.append((entry.path, "Nucleus.ini"))
        elif any(marker in upper_parts[1:] for marker in EXPANSION_MARKERS):
            excluded.append(entry.path)
        # Everything else below GAME is installer/readme/Windows content and
        # is intentionally not selected.

    if not files:
        raise _error("ISO has no GAME base payload")
    selected_roots = {canonical for _source, canonical in files}
    required_root_names = {"Data", "Env", "Levels", "Locale", "Save", "Nucleus.ini"}
    present_roots = {path.split("/", 1)[0] for path in selected_roots}
    missing = required_root_names - present_roots
    if missing:
        raise _error("ISO base payload is missing: {}".format(", ".join(sorted(missing))))
    return BaseSelection(tuple(sorted(files)), tuple(sorted(directories)), tuple(sorted(set(excluded))))


select_base_roots = select_base_game_entries


def validate_menu_assets(paths: Iterable[str], *, required: Iterable[str] = REQUIRED_MENU_ASSETS) -> None:
    """Require the menu payload while respecting ISO case-insensitivity."""

    available = {_fold(_normalize_archive_path(path)) for path in paths}
    missing = [path for path in required if _fold(path) not in available]
    if missing:
        raise _error("required menu assets are missing: {}".format(", ".join(missing)))


def parse_7z_listing(output: str) -> tuple[ArchiveEntry, ...]:
    """Parse the machine-readable ``7z l -slt`` listing format."""

    records: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for raw in output.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            if "Path" in current:
                records.append(current)
            current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key in {"Path", "Folder", "Attributes", "Symbolic Link", "Size"}:
            current[key] = value
    if "Path" in current:
        records.append(current)

    result: list[ArchiveEntry] = []
    for record in records:
        path = str(record["Path"])
        # ISO9660 directory records may retain their ``;1`` version suffix in
        # a 7-Zip listing.  It is metadata, not part of the engine filename.
        path = re.sub(r";[0-9]+$", "", path)
        # 7z emits a first pseudo-record for the archive itself.  It has no
        # Folder/Attributes field and is not an archive member.
        if "Folder" not in record and "Attributes" not in record:
            continue
        attrs = str(record.get("Attributes", ""))
        is_dir = str(record.get("Folder", "")).strip() == "+" or attrs.startswith("D")
        # 7-Zip emits an empty ``Symbolic Link =`` field for ordinary ISO
        # members.  Only a non-empty target (or an explicit link attribute)
        # denotes a link; treating field presence as a link rejects every
        # regular file in the legal-edition ISO.
        link_value = str(record.get("Symbolic Link", "")).strip()
        if link_value or attrs.upper().startswith("L") or "LINK" in attrs.upper():
            kind = "link"
            target = link_value
        elif attrs.upper().startswith("?"):
            # Unknown/special filesystem objects are never accepted.  Hidden,
            # system, compressed, and read-only bits are ordinary file
            # attributes and must not be mistaken for special files here.
            kind = "special"
            target = None
        else:
            kind = "dir" if is_dir else "file"
            target = None
        size = int(str(record.get("Size", "0")) or "0")
        result.append(ArchiveEntry(path.rstrip("/\\") if is_dir else path, kind, target, size))
    return validate_iso_listing(result)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_destination(root: Path, relative: str) -> Path:
    normalized = _normalize_archive_path(relative)
    target = root.joinpath(*PurePosixPath(normalized).parts)
    root_resolved = root.resolve()
    try:
        target.parent.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise _error("extraction path escapes work directory: {}".format(relative)) from exc
    return target


def _check_regular_tree(root: Path) -> None:
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise _error("expected regular extraction directory: {}".format(root))
    folded: dict[tuple[str, ...], str] = {}
    for path in root.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise _error("extracted tree contains a link or special file: {}".format(path))
        relative = path.relative_to(root).as_posix()
        key = tuple(_fold(part) for part in relative.split("/"))
        previous = folded.get(key)
        if previous is not None and previous != relative:
            raise _error("case-fold collision in extracted tree: {} and {}".format(previous, relative))
        folded[key] = relative
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise _error("extracted tree escapes its root: {}".format(path)) from exc


def _validate_relative_symlink(path: Path, root: Path) -> None:
    """Validate a packaging symlink without ever following it out of root."""

    target = os.readlink(path)
    target_path = PurePosixPath(target)
    if not target or target_path.is_absolute() or ".." in target_path.parts:
        raise _error("symlink escapes its packaging root: {} -> {}".format(path, target))
    resolved = path.parent.joinpath(*target_path.parts).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise _error("symlink escapes its packaging root: {} -> {}".format(path, target)) from exc
    if not resolved.exists():
        raise _error("symlink target is missing: {} -> {}".format(path, target))


def _check_overlay_tree(root: Path) -> None:
    """Check a native overlay tree, allowing only confined relative links.

    package.py intentionally retains SONAME links in ``lib/``.  Those links
    are part of the ELF closure and must survive into ``usr/lib``; ISO/base
    payloads still use the stricter ``_check_regular_tree`` policy above.
    """

    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise _error("expected regular overlay directory: {}".format(root))
    folded: dict[tuple[str, ...], str] = {}
    for path in root.rglob("*"):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        key = tuple(_fold(part) for part in relative.split("/"))
        previous = folded.get(key)
        if previous is not None and previous != relative:
            raise _error("case-fold collision in overlay: {} and {}".format(previous, relative))
        folded[key] = relative
        if stat.S_ISLNK(info.st_mode):
            _validate_relative_symlink(path, root)
        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise _error("overlay contains a special file: {}".format(path))
        else:
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise _error("overlay escapes its root: {}".format(path)) from exc


def list_iso(iso: Path, seven_zip: str = "7z") -> tuple[ArchiveEntry, ...]:
    if not iso.is_file() or iso.is_symlink():
        raise _error("ISO must be a regular file: {}".format(iso))
    try:
        result = subprocess.run(
            [seven_zip, "l", "-slt", str(iso)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise _error("unable to execute {}: {}".format(seven_zip, exc)) from exc
    if result.returncode != 0:
        raise _error("7-Zip listing failed: {}".format(result.stderr.strip()[-400:]))
    return parse_7z_listing(result.stdout)


def extract_base_payload(
    iso: Path,
    destination: Path,
    seven_zip: str = "7z",
    listing: Iterable[ArchiveEntry | str | Mapping[str, object]] | None = None,
) -> BaseSelection:
    """Extract and canonicalize the validated base payload.

    Extraction is performed into a throw-away directory with 7-Zip, then only
    selected regular files are copied to ``destination``.  This gives us a
    second post-extraction boundary check even if a future 7-Zip version has a
    surprising archive feature.
    """

    listing_tuple = validate_iso_listing(listing if listing is not None else list_iso(iso, seven_zip))
    selection = select_base_game_entries(listing_tuple)
    destination.mkdir(parents=True, exist_ok=True)
    _check_regular_tree(destination)
    with tempfile.TemporaryDirectory(prefix="openneoua-iso-") as temp_name:
        raw_root = Path(temp_name) / "raw"
        raw_root.mkdir()
        selection_list = Path(temp_name) / "selected-members.txt"
        # Pass only the validated regular members to 7-Zip.  In particular,
        # never use GAME/*: that temporarily extracts installers, help,
        # expansion content, and any future unrecognized roots before the
        # canonical copy loop can discard them.
        selection_list.write_text(
            "".join(source + "\n" for source, _canonical in selection.files),
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    seven_zip,
                    "x",
                    "-y",
                    "-aoa",
                    "-bd",
                    "-o" + str(raw_root),
                    str(iso),
                    "-i@" + str(selection_list),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise _error("unable to execute {}: {}".format(seven_zip, exc)) from exc
        if result.returncode != 0:
            raise _error("7-Zip extraction failed: {}".format(result.stderr.strip()[-400:]))
        _check_regular_tree(raw_root)
        for source_path, canonical in selection.files:
            source = _safe_destination(raw_root, source_path)
            target = _safe_destination(destination, canonical)
            if not source.is_file() or source.is_symlink():
                raise _error("selected ISO entry did not extract as a regular file: {}".format(source_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise _error("duplicate canonical base path: {}".format(canonical))
            shutil.copyfile(source, target)
            target.chmod(0o644)
    _check_regular_tree(destination)
    return selection


def _copy_regular_tree(source: Path, destination: Path, *, allow_symlinks: bool = False) -> None:
    if not source.exists() or source.is_symlink() or not source.is_dir():
        raise _error("overlay directory is not a regular directory: {}".format(source))
    if allow_symlinks:
        _check_overlay_tree(source)
    else:
        _check_regular_tree(source)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        target = _safe_destination(destination, relative)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            if not allow_symlinks:
                raise _error("overlay contains a link: {}".format(relative))
            _validate_relative_symlink(path, source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                if not target.is_symlink() or os.readlink(target) != os.readlink(path):
                    raise _error("conflicting overlay symlink: {}".format(relative))
            else:
                target.symlink_to(os.readlink(path))
            continue
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise _error("overlay contains a special file: {}".format(relative))
        if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise _error("overlay contains a privileged file: {}".format(relative))
        if stat.S_ISDIR(info.st_mode):
            if target.exists() and not target.is_dir():
                raise _error("overlay directory/file conflict: {}".format(relative))
            target.mkdir(parents=True, exist_ok=True)
        else:
            if target.exists() and target.is_dir():
                raise _error("overlay file/directory conflict: {}".format(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(stat.S_IMODE(info.st_mode) | stat.S_IRUSR)


def merge_overlay(asset_root: Path, overlay_root: Path) -> None:
    """Merge an OpenNeoUA overlay after proprietary base assets."""

    _copy_regular_tree(overlay_root, asset_root)
    _check_regular_tree(asset_root)


def write_sha256_manifest(root: Path, name: str = "ASSET-MANIFEST.sha256") -> Path:
    """Write a complete, sorted manifest of every regular file below root."""

    _check_regular_tree(root)
    records: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == name:
            continue
        relative = path.relative_to(root).as_posix()
        _normalize_archive_path(relative)
        records.append("{}  {}".format(sha256_file(path), relative))
    target = root / name
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(records) + "\n", encoding="ascii")
    temporary.chmod(0o644)
    os.replace(temporary, target)
    return target


def verify_sha256_manifest(root: Path, manifest: Path) -> None:
    if manifest.resolve().parent != root.resolve():
        raise _error("manifest must be located at AppDir asset root")
    seen: set[str] = set()
    try:
        lines = manifest.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _error("unable to read asset manifest") from exc
    for line in lines:
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise _error("malformed asset manifest record")
        digest, relative = match.groups()
        _normalize_archive_path(relative)
        if relative in seen or relative == manifest.name:
            raise _error("duplicate/invalid asset manifest path: {}".format(relative))
        seen.add(relative)
        path = _safe_destination(root, relative)
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise _error("asset manifest mismatch: {}".format(relative))
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name != manifest.name
    }
    if seen != actual:
        raise _error("asset manifest is incomplete")


def _png_rgba_256(source: Path | None, destination: Path) -> None:
    """Create a deterministic 256x256 PNG derived from the shipped icon.

    The historical icon is an ICO.  If an image converter is available we use
    it directly.  The fallback still records the ICO digest in provenance and
    draws an unmistakable OpenNeoUA mark, which keeps the AppImage build
    functional on minimal SteamRT images.
    """

    if source is not None:
        for converter in (("convert",), ("magick",), ("rsvg-convert",)):
            executable = shutil.which(converter[0])
            if executable:
                command = [executable, str(source), "-resize", "256x256!", "PNG32:" + str(destination)]
                if converter[0] == "rsvg-convert":
                    command = [executable, "-w", "256", "-h", "256", "-o", str(destination), str(source)]
                try:
                    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                    if result.returncode == 0 and destination.is_file():
                        return
                except OSError:
                    pass
    width = height = 256
    pixels = bytearray()
    # A dark blue field with a gold OA monogram.  The pixel data is intentionally
    # generated from the existing icon digest, so two icon revisions cannot
    # silently produce the same fallback asset.
    seed = hashlib.sha256(source.read_bytes() if source and source.is_file() else b"OpenNeoUA").digest()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            edge = min(x, y, width - 1 - x, height - 1 - y)
            gold = (x - 64) * (x - 64) + (y - 128) * (y - 128) < 48 * 48
            cross = 104 < x < 152 and 65 < y < 192
            color = (220, 180, 55, 255) if gold or cross else (16 + seed[0] // 8, 27 + seed[1] // 8, 56 + edge // 8, 255)
            pixels.extend(color)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(pixels), 9)) + chunk(b"IEND", b"")
    destination.write_bytes(payload)
    destination.chmod(0o644)


def _resolve_iso(repository: Path, value: Path) -> Path:
    candidate = value if value.is_absolute() else repository / value
    if candidate.is_symlink() or not candidate.is_file():
        raise _error(
            "owned base-game ISO is missing: {} (copy your disc image to vendor/ua.iso)".format(
                candidate
            )
        )
    return candidate


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, path)


def _read_overlay_archive(archive: Path, destination: Path) -> str:
    """Extract the existing native overlay archive with a safe tar policy."""

    import tarfile

    if archive.is_symlink() or not archive.is_file():
        raise _error("overlay archive is not a regular file: {}".format(archive))
    digest = sha256_file(archive)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:*", errorlevel=2) as stream:
        members = stream.getmembers()
        seen: set[tuple[str, ...]] = set()
        for member in members:
            name = _normalize_archive_path(member.name.rstrip("/"))
            parts = tuple(name.split("/"))
            folded = tuple(_fold(part) for part in parts)
            if folded in seen:
                raise _error("overlay archive duplicate path: {}".format(name))
            seen.add(folded)
            if member.islnk() or not (member.isfile() or member.isdir() or member.issym()):
                raise _error("overlay archive contains a hard link or special file: {}".format(name))
            target = _safe_destination(destination, name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym():
                link_target = member.linkname
                link_path = PurePosixPath(link_target)
                if not link_target or link_path.is_absolute() or ".." in link_path.parts:
                    raise _error("overlay archive symlink escapes its root: {} -> {}".format(name, link_target))
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise _error("duplicate overlay archive path: {}".format(name))
                target.symlink_to(link_target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = stream.extractfile(member)
            if extracted is None:
                raise _error("unable to read overlay member: {}".format(name))
            with target.open("xb") as output:
                shutil.copyfileobj(extracted, output)
            target.chmod(stat.S_IMODE(member.mode) | stat.S_IRUSR)
    _check_overlay_tree(destination)
    return digest


def create_apprun(path: Path) -> None:
    script = """#!/bin/sh
set -eu
APPDIR=${APPDIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}
ASSET_ROOT="$APPDIR/usr/share/openneoua"
USER_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/OpenNeoUA"
mkdir -p "$USER_DIR"
if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
else
    LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu"
fi
export LD_LIBRARY_PATH
exec "$APPDIR/usr/bin/OpenNeoUA" --asset-root "$ASSET_ROOT" --user-dir "$USER_DIR" "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def _copy_overlay_payload(overlay: Path, appdir: Path, asset_root: Path) -> None:
    binary = overlay / "bin" / "OpenNeoUA"
    if not binary.is_file() or binary.is_symlink():
        raise _error("overlay does not contain bin/OpenNeoUA")
    target_binary = appdir / "usr" / "bin" / "OpenNeoUA"
    target_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, target_binary)
    target_binary.chmod(0o755)
    (appdir / "usr" / "lib").mkdir(parents=True, exist_ok=True)
    library_source = overlay / "lib"
    if library_source.is_dir():
        _copy_regular_tree(library_source, appdir / "usr" / "lib", allow_symlinks=True)
    # Native overlay assets have already been canonicalized by package.py.  Do
    # not copy the legacy launcher or the outer package manifest into the
    # private payload.  BUILD-INFO.txt is intentionally retained: it is the
    # complete, sanitized dependency-version report that must remain covered
    # by the AppImage asset manifest and provenance.
    ignored = {"bin", "lib", "MANIFEST.sha256", "OpenNeoUA.sh"}
    for child in sorted(overlay.iterdir()):
        if child.name in ignored or child.name == ".git":
            continue
        destination = asset_root / child.name
        if child.is_dir():
            _copy_regular_tree(child, destination)
        elif child.is_file() and not child.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(child, destination)
        else:
            raise _error("overlay contains unsupported top-level path: {}".format(child.name))


def assemble_appdir(
    base_root: Path,
    overlay_root: Path,
    appdir: Path,
    *,
    icon_source: Path | None = None,
) -> None:
    """Create and validate the conforming AppDir before appimagetool runs."""

    if appdir.exists():
        if appdir.is_symlink() or not appdir.is_dir():
            raise _error("AppDir is not a regular directory")
        shutil.rmtree(appdir)
    asset_root = appdir / "usr" / "share" / "openneoua"
    asset_root.mkdir(parents=True)
    _copy_regular_tree(base_root, asset_root)
    _copy_overlay_payload(overlay_root, appdir, asset_root)
    write_sha256_manifest(asset_root)

    apprun = appdir / "AppRun"
    create_apprun(apprun)
    desktop = appdir / "OpenNeoUA.desktop"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=OpenNeoUA\nComment=Urban Assault\n"
        "Exec=OpenNeoUA %F\nIcon=OpenNeoUA\nCategories=Game;\nTerminal=false\n",
        encoding="utf-8",
    )
    desktop.chmod(0o644)
    icon_path = appdir / "OpenNeoUA.png"
    _png_rgba_256(icon_source, icon_path)
    verify_appdir(appdir)


def verify_appdir(appdir: Path) -> None:
    if appdir.is_symlink() or not appdir.is_dir():
        raise _error("AppDir is not a directory")
    apprun = appdir / "AppRun"
    desktop = appdir / "OpenNeoUA.desktop"
    binary = appdir / "usr" / "bin" / "OpenNeoUA"
    asset_root = appdir / "usr" / "share" / "openneoua"
    library_root = appdir / "usr" / "lib"
    for path in (apprun, desktop, binary, asset_root, library_root):
        if not path.exists() or path.is_symlink():
            raise _error("AppDir entry is missing or a symlink: {}".format(path.relative_to(appdir)))
    if not stat.S_IMODE(apprun.stat().st_mode) & stat.S_IXUSR:
        raise _error("AppRun is not executable")
    if not stat.S_IMODE(binary.stat().st_mode) & stat.S_IXUSR:
        raise _error("OpenNeoUA executable is not executable")
    desktop_text = desktop.read_text(encoding="utf-8")
    for required in ("Type=Application", "Exec=OpenNeoUA %F", "Icon=OpenNeoUA"):
        if required not in desktop_text:
            raise _error("desktop metadata is missing {}".format(required))
    icon = appdir / "OpenNeoUA.png"
    if icon.read_bytes()[:24] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00":
        raise _error("icon is not a 256x256 PNG")
    verify_sha256_manifest(asset_root, asset_root / "ASSET-MANIFEST.sha256")
    for path in appdir.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            if path == appdir / ".DirIcon":
                _validate_relative_symlink(path, appdir)
                continue
            try:
                path.relative_to(library_root)
            except ValueError as exc:
                raise _error("AppDir contains a link outside usr/lib: {}".format(path.relative_to(appdir))) from exc
            _validate_relative_symlink(path, library_root)
        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise _error("AppDir contains a link or special file: {}".format(path))


def verify_appimage(path: Path) -> None:
    """Validate the outer AppImage ELF and its adjacent checksum record."""

    if path.is_symlink() or not path.is_file():
        raise _error("AppImage is not a regular file: {}".format(path))
    with path.open("rb") as stream:
        header = stream.read(64)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
        raise _error("AppImage is not a little-endian ELF64 payload")
    machine = int.from_bytes(header[18:20], "little")
    if machine != 0x3E:
        raise _error("AppImage is not x86-64 (ELF machine {})".format(machine))
    checksum = path.with_name(path.name + ".sha256")
    if not checksum.is_file() or checksum.is_symlink():
        raise _error("AppImage checksum is missing")
    if checksum.read_text(encoding="ascii").strip() != "{}  {}".format(sha256_file(path), path.name):
        raise _error("AppImage checksum does not match payload")


def _squashfs_offset(path: Path) -> int:
    """Find the final SquashFS magic without loading a whole AppImage."""

    offset = -1
    position = 0
    carry = b""
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            data = carry + chunk
            found = data.rfind(b"hsqs")
            if found >= 0:
                offset = position - len(carry) + found
            position += len(chunk)
            carry = data[-3:]
    return offset


def _extract_appimage_payload(path: Path, destination: Path) -> Path:
    """Extract one staged AppImage for validation, without FUSE."""

    destination.mkdir(parents=True, exist_ok=True)
    extraction_error: OSError | None = None
    try:
        result = subprocess.run(
            [str(path.resolve()), "--appimage-extract"],
            cwd=str(destination),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=180,
        )
    except OSError as exc:
        # Docker Desktop's amd64 emulation may reject an AppImage's custom
        # outer ELF header with ENOEXEC even though its SquashFS payload is
        # valid.  Treat that the same as a normal extraction failure and use
        # the offset-based unsquashfs fallback below.
        extraction_error = exc
    except subprocess.TimeoutExpired as exc:
        raise _error("unable to extract staged AppImage: {}".format(exc)) from exc
    if extraction_error is not None or result.returncode != 0:
        offset = _squashfs_offset(path)
        if offset < 0:
            raise _error("staged AppImage has no SquashFS payload: {}".format(path))
        root = destination / "squashfs-root"
        try:
            fallback = subprocess.run(
                ["unsquashfs", "-quiet", "-offset", str(offset), "-d", str(root), str(path.resolve())],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _error("unable to run unsquashfs for staged AppImage: {}".format(exc)) from exc
        if fallback.returncode != 0:
            details = (fallback.stderr or fallback.stdout).strip()[-800:]
            raise _error("staged AppImage extraction failed: {}".format(details))
    root = destination / "squashfs-root"
    if root.is_symlink() or not root.is_dir():
        raise _error("staged AppImage did not create squashfs-root")
    return root


def _is_x86_64_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError:
        return False
    return (
        len(header) >= 20
        and header[:4] == b"\x7fELF"
        and header[4] == 2
        and header[5] == 1
        and int.from_bytes(header[18:20], "little") == 0x3E
    )


def _elf_needed(path: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["readelf", "-d", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise _error("unable to inspect embedded ELF dependencies: {}".format(exc)) from exc
    if result.returncode != 0:
        raise _error("readelf rejected embedded ELF {}: {}".format(path.name, result.stderr.strip()[-400:]))
    return tuple(sorted(set(re.findall(r"Shared library: \[([^]]+)\]", result.stdout))))


def _verify_embedded_elf_closure(appdir: Path) -> None:
    """Verify executable architecture and private DT_NEEDED closure in-place."""

    binary = appdir / "usr" / "bin" / "OpenNeoUA"
    library_root = appdir / "usr" / "lib"
    if not _is_x86_64_elf(binary):
        raise _error("embedded OpenNeoUA is not x86-64 ELF")

    embedded: dict[str, Path] = {}
    for path in library_root.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            try:
                target.relative_to(library_root.resolve())
            except ValueError as exc:
                raise _error("embedded library symlink escapes usr/lib: {}".format(path.relative_to(appdir))) from exc
            if not target.is_file():
                raise _error("embedded library symlink target is missing: {}".format(path.relative_to(appdir)))
            embedded[path.name] = path
        elif path.is_file():
            if not _is_x86_64_elf(path):
                raise _error("embedded library is not x86-64 ELF: {}".format(path.relative_to(appdir)))
            embedded[path.name] = path

    # BUILD-INFO is generated by package.py and records every runtime SONAME
    # classification.  Runtime-provided names need not be embedded; every
    # private name must resolve through the staged usr/lib tree.
    report = appdir / "usr" / "share" / "openneoua" / "BUILD-INFO.txt"
    if not report.is_file() or report.is_symlink():
        raise _error("embedded dependency-version report is missing")
    runtime_names = {
        match.group(1)
        for match in (
            re.match(r"^\s*(\S+)\s*=\s*runtime \(", line)
            for line in report.read_text(encoding="utf-8", errors="strict").splitlines()
        )
        if match is not None
    }
    queue = [binary]
    seen: set[Path] = set()
    while queue:
        owner = queue.pop()
        resolved_owner = owner.resolve()
        if resolved_owner in seen:
            continue
        seen.add(resolved_owner)
        if not _is_x86_64_elf(resolved_owner):
            raise _error("embedded dependency is not x86-64 ELF: {}".format(owner.relative_to(appdir)))
        for name in _elf_needed(resolved_owner):
            if name in runtime_names:
                continue
            candidate = embedded.get(name)
            if candidate is None:
                raise _error("embedded private ELF dependency is missing: {} (from {})".format(name, owner.relative_to(appdir)))
            queue.append(candidate)


def verify_appimage_embedded(path: Path) -> None:
    """Validate the complete layout after appimagetool has repacked it."""

    verify_appimage(path)
    with tempfile.TemporaryDirectory(prefix="openneoua-embedded-", dir=str(path.parent)) as temporary:
        root = _extract_appimage_payload(path, Path(temporary))
        verify_appdir(root)
        _verify_embedded_elf_closure(root)


def _download_pinned(url: str, digest: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and not destination.is_symlink() and sha256_file(destination) == digest:
        return destination
    temporary = destination.with_name(destination.name + ".tmp")
    request = Request(url, headers={"User-Agent": "OpenNeoUA-SteamDeck-private"})
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
        if sha256_file(temporary) != digest:
            raise _error("downloaded pinned file has an unexpected SHA-256")
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    destination.chmod(0o755)
    return destination


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return False
    return result.returncode == 0


def _docker_run(command: Sequence[str], *, cwd: Path | None = None) -> None:
    try:
        result = subprocess.run(list(command), cwd=str(cwd) if cwd else None, check=False)
    except OSError as exc:
        raise _error("unable to execute Docker: {}".format(exc)) from exc
    if result.returncode != 0:
        raise _error("Docker command failed with exit status {}".format(result.returncode))


def _remove_work_tree(path: Path) -> None:
    """Remove one of this script's temporary trees, including locked files."""

    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return
    # AppDir is intentionally made read-only before appimagetool runs.  Make
    # only this generated work tree writable again so a retry can clean it;
    # never broaden this helper to user-selected asset or output directories.
    for child in sorted(path.rglob("*"), reverse=True):
        try:
            info = child.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            continue
        child.chmod(stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    shutil.rmtree(path)


def _find_overlay_archive(directory: Path, source_id: str) -> Path:
    candidates = sorted(directory.glob("OpenNeoUA-steamrt4-x86_64-*.tar.xz"))
    if not candidates:
        raise _error("local CI did not produce a native overlay archive")
    # local_ci publishes one exact pair per invocation.  Prefer the source id
    # if the caller kept previous combinations in the same output directory.
    matching = [path for path in candidates if source_id in path.name]
    return matching[0] if matching else candidates[-1]


def _run_local_ci(repository: Path, work: Path, refresh: bool) -> tuple[Path, str, str, Path]:
    script = repository / "packaging" / "steamrt4" / "local_ci.py"
    if not script.is_file():
        raise _error("local_ci.py is missing")
    output = work / "overlay-artifacts"
    # Keep the sanitized snapshot long enough to use it as the Docker build
    # context.  The outer --keep-work flag controls the surrounding assembly
    # directory; local_ci's own temporary snapshot is otherwise removed before
    # we can build the AppImage image.
    command = [sys.executable, str(script), "--output-dir", str(output), "--keep-work"]
    if refresh:
        command.append("--refresh-image")
    try:
        result = subprocess.run(
            command,
            cwd=str(repository),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise _error("unable to run local_ci.py: {}".format(exc)) from exc
    if result.returncode != 0:
        raise _error("local_ci.py failed with exit status {}: {}".format(result.returncode, result.stdout.strip()[-800:]))
    archives = sorted(output.glob("OpenNeoUA-steamrt4-x86_64-*.tar.xz"))
    if len(archives) != 1:
        raise _error("local_ci output did not contain exactly one overlay archive")
    archive = archives[0]
    source_id = archive.stem.removeprefix("OpenNeoUA-steamrt4-x86_64-").removesuffix(".tar")
    source_state = "dirty" if "-dirty-" in source_id else "clean"
    snapshot_match = re.search(r"Sanitized snapshot:\s*(.+)", result.stdout)
    if snapshot_match is None:
        raise _error("local_ci did not retain a sanitized snapshot; use --keep-work")
    snapshot = Path(snapshot_match.group(1).strip())
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise _error("local_ci returned an invalid sanitized snapshot")
    return archive, source_id, source_state, snapshot


def _build_image(snapshot: Path, *, refresh: bool) -> None:
    dockerfile = snapshot / "packaging" / "steamrt4" / "Dockerfile.steamdeck"
    if not dockerfile.is_file():
        raise _error("Dockerfile.steamdeck is missing from sanitized snapshot")
    command = ["docker", "build", "--platform", "linux/amd64", "--tag", STEAMDECK_IMAGE, "--file", str(dockerfile)]
    if refresh:
        command.append("--pull")
    command.append(str(snapshot))
    _docker_run(command)


def _assembly_in_docker(
    iso: Path,
    overlay_archive: Path,
    output: Path,
    snapshot: Path,
    source_id: str,
    source_state: str,
    *,
    refresh: bool,
) -> tuple[Path, Path]:
    overlay_dir = output.parent / "overlay-unpacked"
    if overlay_dir.exists():
        shutil.rmtree(overlay_dir)
    overlay_dir.mkdir(parents=True)
    _read_overlay_archive(overlay_archive, overlay_dir)
    work = output.parent / "assembly-work"
    # Each assembly container must start from an empty extraction tree.  A
    # failed appimagetool invocation can leave a complete base payload behind;
    # reusing it would turn a retry into a false canonical-path collision.
    if work.exists() or work.is_symlink():
        if work.is_symlink() or not work.is_dir():
            raise _error("assembly work path is not a regular directory: {}".format(work))
        _remove_work_tree(work)
    work.mkdir(parents=True, exist_ok=True)
    command = [
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--mount", "type=bind,src={},dst=/input/Urban Assault.iso,readonly".format(iso.resolve()),
        "--mount", "type=bind,src={},dst=/input/overlay,readonly".format(overlay_dir.resolve()),
        "--mount", "type=bind,src={},dst=/work".format(work.resolve()),
        STEAMDECK_IMAGE,
        "python3", "/opt/openneoua/packaging/steamrt4/build_steamdeck.py",
        "--assemble-only", "--iso", "/input/Urban Assault.iso",
        "--overlay-dir", "/input/overlay", "--output-dir", "/work/artifacts",
        "--base-output", "/work/base", "--appdir", "/work/AppDir",
        "--source-id", source_id, "--source-state", source_state,
    ]
    if refresh:
        # The image is rebuilt by the caller; this branch exists to make the
        # command line explicit in logs and future-proof an alternate backend.
        command.append("--refresh-image")
    _docker_run(command)
    produced = sorted((work / "artifacts").glob("*.AppImage"))
    checksums = sorted((work / "artifacts").glob("*.AppImage.sha256"))
    if len(produced) != 1 or len(checksums) != 1:
        raise _error("assembly container did not produce an AppImage/checksum pair")
    staged_output = output.parent / "assembly-staged"
    if staged_output.exists():
        shutil.rmtree(staged_output)
    staged_output.mkdir(parents=True)
    for path in produced + checksums:
        os.replace(path, staged_output / path.name)
    return staged_output / produced[0].name, staged_output / checksums[0].name


def publish_pair(appimage: Path, checksum: Path, output_dir: Path) -> tuple[Path, Path]:
    """Atomically publish an AppImage/checksum pair without deleting variants."""

    if appimage.is_symlink() or checksum.is_symlink() or not appimage.is_file() or not checksum.is_file():
        raise _error("cannot publish non-regular AppImage pair")
    digest = sha256_file(appimage)
    record = checksum.read_text(encoding="ascii").strip()
    if record != "{}  {}".format(digest, appimage.name):
        raise _error("AppImage checksum does not match the payload")
    output_dir.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".steamdeck-publish-", dir=output_dir))
    final_app = output_dir / appimage.name
    final_sum = output_dir / checksum.name
    existing_app = final_app.exists() or final_app.is_symlink()
    existing_sum = final_sum.exists() or final_sum.is_symlink()
    if existing_app != existing_sum:
        shutil.rmtree(transaction, ignore_errors=True)
        raise _error("cannot replace an incomplete existing AppImage pair")
    blocked = {signal.SIGINT, signal.SIGTERM}
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked) if hasattr(signal, "pthread_sigmask") else None
    try:
        staged_app = transaction / appimage.name
        staged_sum = transaction / checksum.name
        shutil.copy2(appimage, staged_app)
        shutil.copy2(checksum, staged_sum)
        for path in (staged_app, staged_sum):
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        backup_app = transaction / (appimage.name + ".previous")
        backup_sum = transaction / (checksum.name + ".previous")
        if existing_app:
            if final_app.is_symlink() or final_sum.is_symlink():
                raise _error("refusing to replace a symlinked AppImage pair")
            os.replace(final_app, backup_app)
            os.replace(final_sum, backup_sum)
        replaced_app = False
        replaced_sum = False
        try:
            os.replace(staged_app, final_app)
            replaced_app = True
            os.replace(staged_sum, final_sum)
            replaced_sum = True
        except BaseException:
            if replaced_sum and final_sum.exists():
                final_sum.unlink()
            if replaced_app and final_app.exists():
                final_app.unlink()
            if backup_app.exists():
                os.replace(backup_app, final_app)
            if backup_sum.exists():
                os.replace(backup_sum, final_sum)
            raise
        descriptor = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        shutil.rmtree(transaction, ignore_errors=True)
    return output_dir / appimage.name, output_dir / checksum.name


def _write_assembly_result(
    iso: Path,
    overlay_dir: Path,
    output_dir: Path,
    appdir: Path,
    source_id: str,
    source_state: str,
    *,
    base_output: Path,
) -> tuple[Path, Path]:
    listing = list_iso(iso)
    selection = extract_base_payload(iso, base_output, listing=listing)
    validate_menu_assets(
        [canonical for _source, canonical in selection.files],
        required=REQUIRED_MENU_ASSETS,
    )
    iso_digest = sha256_file(iso)
    overlay_digest = _directory_digest(overlay_dir)
    dependency_report = overlay_dir / "BUILD-INFO.txt"
    if dependency_report.is_symlink() or not dependency_report.is_file():
        raise _error("overlay is missing the complete dependency-version report: BUILD-INFO.txt")
    dependency_report_digest = sha256_file(dependency_report)
    icon = REPOSITORY_ROOT / "svg" / "icon" / "icon.ico"
    assemble_appdir(base_output, overlay_dir, appdir, icon_source=icon if icon.is_file() else None)
    provenance = {
        "format": 1,
        "private_non_redistributable": True,
        "source_id": source_id,
        "source_state": source_state,
        "overlay_sha256": overlay_digest,
        "dependency_report": {
            "path": "usr/share/openneoua/BUILD-INFO.txt",
            "sha256": dependency_report_digest,
        },
        "iso_sha256": iso_digest,
        "iso_sha256_12": iso_digest[:12],
        "excluded_expansion": "Metropolis Dawn",
        "excluded_expansion_paths": list(selection.excluded_expansion),
        "steamrt4_version": STEAMRT4_VERSION,
        "appimagetool": {"version": APPIMAGETOOL_VERSION, "sha256": APPIMAGETOOL_SHA256},
        "type2_runtime": {"version": APPIMAGE_RUNTIME_VERSION, "sha256": APPIMAGE_RUNTIME_SHA256},
        "asset_manifest": "usr/share/openneoua/ASSET-MANIFEST.sha256",
    }
    _atomic_json(appdir / "usr" / "share" / "openneoua" / "PROVENANCE.json", provenance)
    # Provenance is part of the complete internal manifest.
    write_sha256_manifest(appdir / "usr" / "share" / "openneoua")
    verify_appdir(appdir)

    image_cache = Path("/opt/appimage-cache")
    if (
        (image_cache / "appimagetool").is_file()
        and not (image_cache / "appimagetool").is_symlink()
        and (image_cache / "appimagetool-x86_64.AppImage").is_file()
        and sha256_file(image_cache / "appimagetool-x86_64.AppImage") == APPIMAGETOOL_SHA256
        and (image_cache / "runtime-x86_64").is_file()
        and sha256_file(image_cache / "runtime-x86_64") == APPIMAGE_RUNTIME_SHA256
    ):
        # The original download is a verified AppImage, while the extracted
        # inner binary is the executable accepted by ARM64 Docker Desktop's
        # amd64 emulation.  Keep both: provenance remains tied to the former,
        # packaging invokes the latter.
        tool = image_cache / "appimagetool"
        runtime = image_cache / "runtime-x86_64"
    else:
        cache = output_dir.parent / "cache"
        tool = _download_pinned(APPIMAGETOOL_URL, APPIMAGETOOL_SHA256, cache / "appimagetool-x86_64.AppImage")
        runtime = _download_pinned(APPIMAGE_RUNTIME_URL, APPIMAGE_RUNTIME_SHA256, cache / "runtime-x86_64")
    artifact_dir = output_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    iso12 = iso_digest[:12]
    name = "OpenNeoUA-SteamDeck-private-x86_64-{}-assets-{}.AppImage".format(source_id, iso12)
    target = artifact_dir / name
    temporary = artifact_dir / (name + ".tmp")
    command = [str(tool), "--runtime-file", str(runtime), str(appdir), str(temporary)]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    except OSError as exc:
        raise _error("unable to execute pinned appimagetool: {}".format(exc)) from exc
    if result.returncode != 0:
        raise _error("appimagetool failed: {}".format((result.stderr or result.stdout).strip()[-800:]))
    if not temporary.is_file() or temporary.is_symlink():
        raise _error("appimagetool did not produce a regular AppImage")
    # appimagetool creates .DirIcon as part of its normal AppDir preparation.
    # Validate the confined link and only then lock the completed AppDir so the
    # packaged payload cannot become a writable state location at runtime.
    verify_appdir(appdir)
    for path in sorted(appdir.rglob("*"), reverse=True):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            continue
        path.chmod(stat.S_IMODE(info.st_mode) & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    appdir.chmod(stat.S_IMODE(appdir.stat().st_mode) & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    os.replace(temporary, target)
    target.chmod(0o755)
    checksum = target.with_name(target.name + ".sha256")
    checksum_tmp = checksum.with_name(checksum.name + ".tmp")
    checksum_tmp.write_text("{}  {}\n".format(sha256_file(target), target.name), encoding="ascii")
    checksum_tmp.chmod(0o644)
    os.replace(checksum_tmp, checksum)
    verify_appimage(target)
    # This is the staged candidate inside the SteamRT4 assembly container.
    # Validate the contents produced by appimagetool before the host-side
    # atomic publish_pair operation can make it visible as a deliverable.
    verify_appimage_embedded(target)
    return target, checksum


def _directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(relative + b"\0" + bytes.fromhex(sha256_file(path)) + b"\n")
    return digest.hexdigest()


def _assemble_only(args: argparse.Namespace) -> int:
    iso = Path(args.iso)
    overlay = Path(args.overlay_dir)
    output = Path(args.output_dir)
    base = Path(args.base_output)
    appdir = Path(args.appdir)
    target, checksum = _write_assembly_result(iso, overlay, output, appdir, args.source_id, args.source_state, base_output=base)
    print(json.dumps({"appimage": str(target), "sha256": str(checksum)}, sort_keys=True))
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iso",
        type=Path,
        default=DEFAULT_ISO,
        help="path to the owned Urban Assault base-game ISO (default: vendor/ua.iso)",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--refresh-image", action="store_true")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--assemble-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--iso", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--overlay-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--base-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--appdir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--source-id", default="local", help=argparse.SUPPRESS)
    parser.add_argument("--source-state", default="dirty", choices=("clean", "dirty"), help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.assemble_only:
            for required in (args.iso, args.overlay_dir, args.base_output, args.appdir):
                if required is None:
                    raise _error("assembly mode requires ISO, overlay, base output, and AppDir")
            return _assemble_only(args)

        repository = REPOSITORY_ROOT
        iso = _resolve_iso(repository, args.iso)
        output = args.output_dir if args.output_dir.is_absolute() else repository / args.output_dir
        work_parent = repository / "build" / "steamdeck-private" / "work"
        work_parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="build-", dir=work_parent))
        snapshot_parent: Path | None = None
        try:
            overlay_archive, source_id, source_state, snapshot = _run_local_ci(repository, work, args.refresh_image)
            snapshot_parent = snapshot.parent
            # local_ci creates a sanitized snapshot; use it as the only Docker
            # build context.  It cannot contain vendor/ua.iso by construction.
            if not _docker_available():
                raise _error("Docker daemon is unavailable; private AppImage build cannot run")
            _build_image(snapshot, refresh=args.refresh_image)
            staged_appimage, staged_checksum = _assembly_in_docker(
                iso,
                overlay_archive,
                output,
                snapshot,
                source_id,
                source_state,
                refresh=args.refresh_image,
            )
            dependency_report = output.parent / "overlay-unpacked" / "BUILD-INFO.txt"
            if dependency_report.is_symlink() or not dependency_report.is_file():
                raise _error("assembled overlay dependency-version report is missing")
            # Publish only the validated pair, preserving prior source/ISO
            # combinations in the destination directory.
            publish_pair(staged_appimage, staged_checksum, output)
            metadata = {
                "private_non_redistributable": True,
                "source_id": source_id,
                "source_state": source_state,
                "overlay_sha256": sha256_file(overlay_archive),
                "dependency_report": {
                    "path": "usr/share/openneoua/BUILD-INFO.txt",
                    "sha256": sha256_file(dependency_report),
                },
                "iso_sha256": sha256_file(iso),
                "excluded_expansion": "Metropolis Dawn",
                "steamrt4_version": STEAMRT4_VERSION,
                "appimagetool": {"version": APPIMAGETOOL_VERSION, "sha256": APPIMAGETOOL_SHA256},
                "type2_runtime": {"version": APPIMAGE_RUNTIME_VERSION, "sha256": APPIMAGE_RUNTIME_SHA256},
            }
            _atomic_json(output / ("OpenNeoUA-SteamDeck-private-{}-provenance.json".format(source_id)), metadata)
            shutil.rmtree(staged_appimage.parent, ignore_errors=True)
        finally:
            if not args.keep_work:
                shutil.rmtree(work, ignore_errors=True)
                if snapshot_parent is not None:
                    shutil.rmtree(snapshot_parent, ignore_errors=True)
        return 0
    except (AssetBuildError, OSError, ValueError) as exc:
        print("build_steamdeck.py: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
