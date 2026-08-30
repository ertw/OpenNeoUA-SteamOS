#!/usr/bin/env python3
"""Run the rendered title/campaign-map smoke test against a private AppImage.

Uses the dedicated ``openneoua-smoketest`` Docker image when Docker is available.
On Linux hosts with ``xvfb-run``, the extracted AppImage can also be executed
directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Iterable, Mapping, Sequence


STEAMRT4_VERSION = "4.0.20260805.254769"
SMOKETEST_IMAGE = "openneoua-smoketest:" + STEAMRT4_VERSION
STEAMDECK_IMAGE = "openneoua-steamdeck-appimage:" + STEAMRT4_VERSION
IMAGE = SMOKETEST_IMAGE
WIDTH = 1280
HEIGHT = 800
DEFAULT_OUTPUT = Path("build/steamdeck-private/test-results")
EXPECTED_MODES_V2 = ("ENVMODE_TITLE", "ENVMODE_SINGLEPLAY")
REQUIRED_SCREENSHOTS_V2 = ("title-before", "campaign-map")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SmokeTestError(RuntimeError):
    """The AppImage smoke test did not produce a trustworthy result."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise SmokeTestError("{} is missing: {}".format(label, path)) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SmokeTestError("{} is not a regular file: {}".format(label, path))


def validate_external_checksum(appimage: Path) -> str:
    _regular(appimage, "AppImage")
    with appimage.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1 or int.from_bytes(header[18:20], "little") != 0x3E:
        raise SmokeTestError("AppImage is not an x86-64 ELF payload")
    checksum = appimage.with_name(appimage.name + ".sha256")
    _regular(checksum, "AppImage checksum")
    line = checksum.read_text(encoding="ascii").strip()
    expected, separator, name = line.partition("  ")
    if separator != "  " or len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected.lower()) or name != appimage.name:
        raise SmokeTestError("invalid AppImage checksum record")
    actual = _sha256(appimage)
    if actual != expected.lower():
        raise SmokeTestError("AppImage checksum mismatch")
    return actual


def parse_ppm(path: Path) -> tuple[int, int, bytes]:
    """Read a binary P6 PPM, returning dimensions and RGB bytes."""

    _regular(path, "screenshot")
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise SmokeTestError("screenshot is not a binary P6 PPM: {}".format(path.name))
    cursor = 2
    tokens: list[bytes] = []
    while len(tokens) < 3:
        while cursor < len(data) and data[cursor] in b" \t\r\n":
            cursor += 1
        if cursor < len(data) and data[cursor:cursor + 1] == b"#":
            end = data.find(b"\n", cursor)
            cursor = len(data) if end < 0 else end + 1
            continue
        end = cursor
        while end < len(data) and data[end] not in b" \t\r\n":
            end += 1
        if end == cursor:
            raise SmokeTestError("truncated PPM header: {}".format(path.name))
        tokens.append(data[cursor:end])
        cursor = end
    try:
        width, height, maxval = (int(item) for item in tokens)
    except ValueError as exc:
        raise SmokeTestError("invalid PPM dimensions: {}".format(path.name)) from exc
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    if width <= 0 or height <= 0 or maxval != 255:
        raise SmokeTestError("unsupported PPM header: {}".format(path.name))
    pixels = data[cursor:]
    if len(pixels) != width * height * 3:
        raise SmokeTestError("PPM pixel length mismatch: {}".format(path.name))
    return width, height, pixels


def pixel_variance(pixels: bytes) -> float:
    if not pixels:
        return 0.0
    mean = sum(pixels) / len(pixels)
    return sum((value - mean) ** 2 for value in pixels) / len(pixels)


def validate_screenshots(paths: Mapping[str, Path] | Iterable[Path]) -> dict[str, object]:
    if isinstance(paths, Mapping):
        named = dict(paths)
    else:
        ordered = sorted(paths)
        if len(ordered) != len(REQUIRED_SCREENSHOTS_V2):
            raise SmokeTestError("expected exactly {} menu screenshots".format(len(REQUIRED_SCREENSHOTS_V2)))
        named = dict(zip(REQUIRED_SCREENSHOTS_V2, ordered))
    if any(key not in named for key in REQUIRED_SCREENSHOTS_V2):
        raise SmokeTestError("screenshots must include {}".format(", ".join(REQUIRED_SCREENSHOTS_V2)))
    values: dict[str, tuple[int, int, bytes]] = {}
    for key in REQUIRED_SCREENSHOTS_V2:
        width, height, pixels = parse_ppm(Path(named[key]))
        if (width, height) != (WIDTH, HEIGHT):
            raise SmokeTestError("{} has dimensions {}x{}, expected {}x{}".format(key, width, height, WIDTH, HEIGHT))
        if pixel_variance(pixels) <= 2.0:
            raise SmokeTestError("{} framebuffer is blank or nearly uniform".format(key))
        values[key] = (width, height, pixels)
    title_hash = hashlib.sha256(values["title-before"][2]).hexdigest()
    map_hash = hashlib.sha256(values["campaign-map"][2]).hexdigest()
    if title_hash == map_hash:
        raise SmokeTestError("title and campaign-map framebuffer captures are identical")
    return {
        "dimensions": {key: [values[key][0], values[key][1]] for key in REQUIRED_SCREENSHOTS_V2},
        "variance": {key: pixel_variance(values[key][2]) for key in REQUIRED_SCREENSHOTS_V2},
        "sha256": {"title-before": title_hash, "campaign-map": map_hash},
    }


def _mode_name(value: object) -> str:
    if isinstance(value, str):
        return value
    # Smoke-controller versions may report numeric enum values.  The title is
    # the historical 0/1 menu state and settings is 5 in the original engine;
    # accept only those known values.
    if value == 0:
        return "ENVMODE_TITLE"
    if value == 5:
        return "ENVMODE_SINGLEPLAY"
    if value == 1:
        return "ENVMODE_SETTINGS"
    return str(value)


def validate_smoke_report(report: Mapping[str, object]) -> None:
    version = report.get("version")
    if version not in (1, 2):
        raise SmokeTestError("unsupported menu smoke report version")
    if version == 1:
        _validate_smoke_report_v1(report)
        return
    _validate_smoke_report_v2(report)


def _validate_smoke_report_v1(report: Mapping[str, object]) -> None:
    milestones = report.get("milestones")
    if not isinstance(milestones, list):
        raise SmokeTestError("smoke report has no milestone sequence")
    modes: list[str] = []
    for item in milestones:
        if isinstance(item, Mapping):
            mode = item.get("mode", item.get("state"))
        else:
            mode = item
        modes.append(_mode_name(mode))
    compact: list[str] = []
    for mode in modes:
        if not compact or compact[-1] != mode:
            compact.append(mode)
    if tuple(compact) != ("ENVMODE_TITLE", "ENVMODE_SETTINGS", "ENVMODE_TITLE"):
        raise SmokeTestError("unexpected legacy menu transition sequence: {}".format(compact))
    if report.get("final_mode") not in ("ENVMODE_TITLE", 0):
        raise SmokeTestError("smoke test did not return to title mode")
    _validate_common_report_fields(report)


def _validate_smoke_report_v2(report: Mapping[str, object]) -> None:
    if report.get("steam_input") is not True:
        raise SmokeTestError("smoke report did not use Steam Input")
    milestones = report.get("milestones")
    if not isinstance(milestones, list):
        raise SmokeTestError("smoke report has no milestone sequence")
    modes: list[str] = []
    for item in milestones:
        if isinstance(item, Mapping):
            mode = item.get("mode", item.get("state"))
        else:
            mode = item
        modes.append(_mode_name(mode))
    compact: list[str] = []
    for mode in modes:
        if not compact or compact[-1] != mode:
            compact.append(mode)
    if tuple(compact) != EXPECTED_MODES_V2:
        raise SmokeTestError("unexpected menu transition sequence: {}".format(compact))
    if report.get("final_mode") not in ("ENVMODE_SINGLEPLAY", 5):
        raise SmokeTestError("smoke test did not finish on campaign map select")
    selected = report.get("selected_region")
    if not isinstance(selected, int) or selected <= 0:
        raise SmokeTestError("smoke report has no selected campaign map region")
    _validate_common_report_fields(report)


def _validate_common_report_fields(report: Mapping[str, object]) -> None:
    if report.get("clean_teardown") is not True:
        raise SmokeTestError("smoke test did not report clean teardown")
    resolution = report.get("resolution")
    if resolution not in ([WIDTH, HEIGHT], {"width": WIDTH, "height": HEIGHT}, (WIDTH, HEIGHT)):
        raise SmokeTestError("smoke report has unexpected resolution")
    provenance = report.get("asset_provenance")
    if not isinstance(provenance, Mapping) or not provenance.get("iso_sha256"):
        raise SmokeTestError("smoke report is missing packaged asset provenance")


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, int, int]]:
    if not root.exists():
        return {}
    result: dict[str, tuple[int, int, int, int]] = {}
    for path in root.rglob("*"):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            relative = path.relative_to(root).parts
            try:
                payload_index = relative.index("squashfs-root")
            except ValueError as exc:
                raise SmokeTestError("sandbox contains a symlink outside extracted payload: {}".format(path)) from exc
            # A type-2 AppImage legitimately contains confined links in its
            # extracted payload (at minimum ``.DirIcon``).  Keep them in the
            # snapshot so replacing or retargeting one is a mutation rather
            # than silently excluding all payload links.
            link_target = PurePosixPath(os.readlink(path))
            if link_target.is_absolute() or ".." in link_target.parts:
                raise SmokeTestError("extracted payload symlink escapes its root: {}".format(path))
            extracted_root = root.joinpath(*relative[: payload_index + 1]).resolve()
            resolved = path.parent.joinpath(*link_target.parts).resolve()
            try:
                resolved.relative_to(extracted_root)
            except ValueError as exc:
                raise SmokeTestError("extracted payload symlink escapes its root: {}".format(path)) from exc
            if not resolved.exists():
                raise SmokeTestError("extracted payload symlink target is missing: {}".format(path))
            link_digest = int.from_bytes(hashlib.sha256(os.readlink(path).encode("utf-8")).digest()[:8], "big")
            result[path.relative_to(root).as_posix()] = (0, 0, stat.S_IMODE(info.st_mode), link_digest)
            continue
        if stat.S_ISREG(info.st_mode):
            result[path.relative_to(root).as_posix()] = (
                info.st_size,
                info.st_mtime_ns,
                stat.S_IMODE(info.st_mode),
                0,
            )
        elif stat.S_ISDIR(info.st_mode):
            result[path.relative_to(root).as_posix()] = (
                0,
                info.st_mtime_ns,
                stat.S_IMODE(info.st_mode),
                0,
            )
        else:
            raise SmokeTestError("sandbox contains a special file: {}".format(path))
    return result


def snapshot_tree(root: Path) -> dict[str, tuple[int, int, int, int]]:
    """Public alias used by asset-free tests."""

    return _tree_snapshot(root)


def assert_no_external_writes(
    before: Mapping[str, tuple[int, int, int, int]],
    after: Mapping[str, tuple[int, int, int, int]],
    allowed_prefix: str = "user/",
    allowed_paths: Iterable[str] = (),
) -> None:
    changed = set(before) ^ set(after)
    changed.update(key for key in set(before) & set(after) if before[key] != after[key])
    allowed = set(allowed_paths)
    external = sorted(
        path
        for path in changed
        if path not in allowed
        and not (path == allowed_prefix.rstrip("/") or path.startswith(allowed_prefix))
    )
    if external:
        raise SmokeTestError("smoke test wrote outside its isolated user directory: {}".format(", ".join(external)))


def _process_output(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _write_menu_log(log: Path, stdout: object, *, elapsed: float | None = None,
                    exit_status: object | None = None, engine_log: Path | None = None,
                    timeout: bool = False) -> None:
    sections: list[str] = []
    if elapsed is not None:
        sections.append("elapsed_seconds={:.3f}".format(elapsed))
    if exit_status is not None:
        sections.append("exit_status={}".format(exit_status))
    captured = _process_output(stdout)
    if captured:
        sections.append(captured.rstrip("\n"))
    if engine_log is not None and engine_log.is_file():
        engine_output = engine_log.read_text(encoding="utf-8", errors="replace")
        if engine_output:
            sections.append("[engine-menu.log]\n" + engine_output.rstrip("\n"))
    if timeout:
        sections.append("TIMEOUT")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(sections) + "\n", encoding="utf-8", errors="replace")


def _find_report(root: Path) -> Path:
    candidates = sorted(root.rglob("menu-smoke.json"))
    if len(candidates) != 1:
        raise SmokeTestError("expected one menu-smoke.json report, found {}".format(len(candidates)))
    return candidates[0]


def _find_screenshots(root: Path) -> dict[str, Path]:
    candidates = sorted(root.rglob("*.ppm"))
    if len(candidates) < len(REQUIRED_SCREENSHOTS_V2):
        raise SmokeTestError("expected at least {} framebuffer screenshots, found {}".format(len(REQUIRED_SCREENSHOTS_V2), len(candidates)))
    named: dict[str, Path] = {}
    for path in candidates:
        lower = path.stem.lower()
        if "campaign" in lower or "map" in lower:
            named["campaign-map"] = path
        elif "before" in lower or lower.endswith("title"):
            named["title-before"] = path
    if len(named) != len(REQUIRED_SCREENSHOTS_V2):
        raise SmokeTestError("could not classify screenshots: {}".format([path.name for path in candidates]))
    return named


def _direct_extract(appimage: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    command = [str(appimage), "--appimage-extract"]
    try:
        result = subprocess.run(command, cwd=str(destination), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeTestError("AppImage extraction failed: {}".format(exc)) from exc
    if result.returncode != 0:
        raise SmokeTestError("AppImage extraction failed: {}".format((result.stderr or result.stdout).strip()[-600:]))
    root = destination / "squashfs-root"
    if not root.is_dir() or root.is_symlink():
        raise SmokeTestError("AppImage did not create squashfs-root")
    return root


def _make_read_only_tree(root: Path) -> None:
    """Lock an extracted payload before direct host execution."""

    if root.is_symlink() or not root.is_dir():
        raise SmokeTestError("extracted payload is not a directory")
    for path in sorted(root.rglob("*"), reverse=True):
        info = path.lstat()
        if not stat.S_ISLNK(info.st_mode):
            path.chmod(stat.S_IMODE(info.st_mode) & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def _make_work_tree_removable(root: Path) -> None:
    """Restore write permission only on this generated smoke work tree."""

    if not root.exists() or root.is_symlink():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        info = path.lstat()
        if not stat.S_ISLNK(info.st_mode):
            path.chmod(stat.S_IMODE(info.st_mode) | stat.S_IWUSR)
    root.chmod(stat.S_IMODE(root.stat().st_mode) | stat.S_IWUSR)


def _docker_extract(appimage: Path, destination: Path) -> Path:
    """Extract the AppImage in a throw-away staging directory."""

    if shutil.which("docker") is None:
        raise SmokeTestError("Docker is unavailable for Linux AppImage smoke test")
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--mount", "type=bind,src={},dst=/input/OpenNeoUA.AppImage,readonly".format(appimage.resolve()),
        "--mount", "type=bind,src={},dst=/extract".format(destination.resolve()),
        IMAGE,
        "bash", "-lc",
        "set -eu; cd /extract; "
        "if /input/OpenNeoUA.AppImage --appimage-extract > /extract/extract.log 2>&1; then "
        "  :; "
        "else "
        "  offset=\"$(LC_ALL=C grep -abo 'hsqs' /input/OpenNeoUA.AppImage | tail -n 1 | cut -d: -f1)\"; "
        "  test -n \"$offset\"; "
        "  unsquashfs -quiet -offset \"$offset\" -d /extract/squashfs-root /input/OpenNeoUA.AppImage >>/extract/extract.log 2>&1; "
        "fi; "
        "test -d /extract/squashfs-root",
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeTestError("Docker AppImage extraction failed: {}".format(exc)) from exc
    if result.returncode != 0:
        raise SmokeTestError("Docker AppImage extraction failed: {}".format((result.stdout or "").strip()[-800:]))
    root = destination / "squashfs-root"
    if not root.is_dir() or root.is_symlink():
        raise SmokeTestError("Docker extraction did not create squashfs-root")
    return root


def _run_smoke(root: Path, smoke_dir: Path, log: Path, timeout: int) -> None:
    apprun = root / "AppRun"
    _regular(apprun, "extracted AppRun")
    if not stat.S_IMODE(apprun.stat().st_mode) & stat.S_IXUSR:
        raise SmokeTestError("extracted AppRun is not executable")
    smoke_dir.mkdir(parents=True, exist_ok=True)
    sandbox = smoke_dir.parent
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(smoke_dir),
            "XDG_DATA_HOME": str(smoke_dir / "xdg-data"),
            "XDG_CONFIG_HOME": str(smoke_dir / "xdg-config"),
            "XDG_CACHE_HOME": str(smoke_dir / "xdg-cache"),
            "SDL_VIDEODRIVER": "x11",
            "SDL_AUDIODRIVER": "dummy",
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "MESA_LOADER_DRIVER_OVERRIDE": "softpipe",
            "GALLIUM_DRIVER": "softpipe",
            "ALSOFT_DRIVERS": "null",
            "OPENALSOFT_DRIVERS": "null",
        }
    )
    command = [str(apprun), "--menu-smoke-dir", str(smoke_dir / "xdg-data" / "OpenNeoUA")]
    xvfb = shutil.which("xvfb-run")
    if xvfb:
        command = [xvfb, "-a", "--server-args=-screen 0 1280x800x24", "--"] + command
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=str(smoke_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        _write_menu_log(log, exc.stdout, timeout=True)
        raise SmokeTestError("menu smoke timed out after {} seconds".format(timeout)) from exc
    elapsed = time.monotonic() - started
    _write_menu_log(log, result.stdout, elapsed=elapsed, exit_status=result.returncode)
    if result.returncode != 0:
        raise SmokeTestError("OpenNeoUA menu smoke exited with status {}".format(result.returncode))


def _docker_run_full_smoke(appimage: Path, output_dir: Path, work: Path, log: Path, timeout: int) -> None:
    if shutil.which("docker") is None:
        raise SmokeTestError("Docker is unavailable for Linux AppImage smoke test")

    docker_output = work / "docker-output"
    docker_output.mkdir(parents=True, exist_ok=True)
    command = [
        "docker", "run", "--rm", "--platform", "linux/amd64",
        "--mount", "type=bind,src={},dst=/input/OpenNeoUA.AppImage,readonly".format(appimage.resolve()),
        "--mount", "type=bind,src={},dst=/output".format(docker_output.resolve()),
        "--mount", "type=bind,src={},dst=/work".format(work.resolve()),
        "-e", "SMOKETEST_TIMEOUT={}".format(timeout),
        IMAGE,
        "/opt/openneoua/packaging/steamrt4/run_smoketest.sh",
        "/input/OpenNeoUA.AppImage",
        "/output",
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout + 180, check=False)
    except subprocess.TimeoutExpired as exc:
        _write_menu_log(log, exc.stdout, timeout=True)
        raise SmokeTestError("Docker menu smoke timed out after {} seconds".format(timeout)) from exc
    except OSError as exc:
        _write_menu_log(log, str(exc))
        raise SmokeTestError("Docker menu smoke failed: {}".format(exc)) from exc

    engine_log = docker_output / "menu-smoke.log"
    _write_menu_log(log, result.stdout, engine_log=engine_log if engine_log.is_file() else None)
    if result.returncode != 0:
        raise SmokeTestError("Docker menu smoke exited with status {}".format(result.returncode))

    for name in ("menu-smoke.json", "menu-smoke.log"):
        source = docker_output / name
        if source.is_file():
            shutil.copyfile(source, output_dir / name)
    screenshots_src = docker_output / "screenshots"
    if screenshots_src.is_dir():
        screenshots_dst = output_dir / "screenshots"
        if screenshots_dst.exists():
            shutil.rmtree(screenshots_dst)
        shutil.copytree(screenshots_src, screenshots_dst)


def _refresh_image_command(snapshot: Path) -> list[str]:
    """Build the smoketest image exclusively from local_ci's sanitized snapshot."""

    dockerfile = snapshot / "packaging" / "steamrt4" / "Dockerfile.smoketest"
    if snapshot.is_symlink() or not snapshot.is_dir() or not dockerfile.is_file():
        raise SmokeTestError("sanitized SteamRT4 snapshot is invalid")
    if any(child.name.casefold() == "ua-complete" for child in snapshot.iterdir()):
        raise SmokeTestError("sanitized Docker context contains UA-Complete")
    vendor_iso = snapshot / "vendor" / "ua.iso"
    if vendor_iso.is_file() or vendor_iso.is_symlink():
        raise SmokeTestError("sanitized Docker context contains vendor/ua.iso")
    return [
        "docker", "build", "--platform", "linux/amd64", "--tag", IMAGE,
        "--file", str(dockerfile), "--pull", str(snapshot),
    ]


def _refresh_test_image(output: Path) -> None:
    """Refresh both local CI and the cached smoke-test image."""

    try:
        from build_steamdeck import _docker_run, _run_local_ci
    except ImportError:  # pragma: no cover - package execution fallback
        from packaging.steamrt4.build_steamdeck import _docker_run, _run_local_ci
    refresh_work = Path(tempfile.mkdtemp(prefix="refresh-image-", dir=str(output.parent)))
    try:
        _archive, _source_id, _source_state, snapshot = _run_local_ci(REPOSITORY_ROOT, refresh_work, True)
        _docker_run(_refresh_image_command(snapshot))
    except SmokeTestError:
        raise
    except Exception as exc:
        raise SmokeTestError("unable to refresh SteamRT4 smoke image: {}".format(exc)) from exc
    finally:
        shutil.rmtree(refresh_work, ignore_errors=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh-image", action="store_true")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        appimage = args.appimage.expanduser().resolve()
        digest = validate_external_checksum(appimage)
        if args.refresh_image:
            _refresh_test_image(output)
        work_parent = output.parent / "work"
        work_parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="menu-", dir=work_parent))
        try:
            extract_dir = work / "extract"
            smoke_dir = work / "user"
            log = output / "menu-smoke.log"
            used_docker = False
            if shutil.which("docker"):
                _docker_run_full_smoke(appimage, output, work, log, args.timeout)
                report_path = output / "menu-smoke.json"
                screenshot_root = output / "screenshots"
                used_docker = True
            elif sys.platform.startswith("linux") and shutil.which("xvfb-run"):
                root = _direct_extract(appimage, extract_dir)
                _make_read_only_tree(root)
                before = snapshot_tree(work)
                _run_smoke(root, smoke_dir / "xdg-data" / "OpenNeoUA", log, args.timeout)
                report_path = _find_report(smoke_dir)
                screenshot_root = smoke_dir
                after = snapshot_tree(work)
                assert_no_external_writes(before, after, allowed_paths=("extract/extract.log",))
            else:
                raise SmokeTestError("Docker or Linux xvfb-run is required for menu smoke test")

            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, Mapping):
                raise SmokeTestError("menu smoke report is not an object")
            validate_smoke_report(report)
            if used_docker:
                screenshots = _find_screenshots(output / "screenshots")
            else:
                screenshots = _find_screenshots(screenshot_root)
            screenshot_report = validate_screenshots(screenshots)
            if not used_docker:
                result_screens = output / "screenshots"
                result_screens.mkdir(parents=True, exist_ok=True)
                copied: dict[str, str] = {}
                for name, source in screenshots.items():
                    target = result_screens / (name + ".ppm")
                    shutil.copyfile(source, target)
                    copied[name] = str(target)
                screenshots = copied
            else:
                copied = {name: str(path) for name, path in screenshots.items()}
            report_target = output / "menu-smoke.json"
            if not used_docker:
                report_target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            summary = {
                "status": "passed",
                "appimage": str(appimage),
                "appimage_sha256": digest,
                "smoketest_image": IMAGE,
                "report": str(report_target),
                "screenshots": copied,
                "screenshot_validation": screenshot_report,
                "log": str(log),
                "work_preserved": bool(args.keep_work),
            }
            (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        finally:
            if not args.keep_work:
                _make_work_tree_removable(work)
                shutil.rmtree(work, ignore_errors=True)
        return 0
    except (SmokeTestError, OSError, json.JSONDecodeError, ValueError) as exc:
        print("test_game_menu.py: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
