#!/usr/bin/env python3
"""Atomically install or update a development AppImage on a Steam Deck."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "build" / "steamdeck-private" / "artifacts"
DEFAULT_HOST = "steamdeck"
DEFAULT_DESTINATION = "Applications/OpenNeoUA-dev.AppImage"
DESKTOP_ENTRY = ".local/share/applications/openneoua-dev.desktop"


class DeployError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_latest_appimage(directory: Path = DEFAULT_ARTIFACT_DIR) -> Path:
    candidates = [path for path in directory.glob("*.AppImage") if path.is_file() and not path.is_symlink()]
    if not candidates:
        raise DeployError("no AppImage found in {} (build one first)".format(directory))
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    printable = " ".join(shlex.quote(item) for item in command)
    print("+ {}".format(printable))
    result = subprocess.run(command, text=True, capture_output=capture, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise DeployError("command failed ({}): {}{}".format(result.returncode, printable,
                          "\n" + detail if detail else ""))
    return result


def remote_path_expression(relative: str) -> str:
    path = Path(relative)
    if (path.is_absolute() or ".." in path.parts or not path.parts or
            any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in path.parts)):
        raise DeployError("remote destination must be a safe path relative to the Deck home")
    return "$HOME/" + "/".join(shlex.quote(part) for part in path.parts)


def remote_script(destination: str, digest: str) -> str:
    final = remote_path_expression(destination)
    temporary = final + ".incoming"
    desktop = remote_path_expression(DESKTOP_ENTRY)
    desktop_temporary = desktop + ".incoming"
    lines = [
        "set -eu",
        "test -f \"{tmp}\"".format(tmp=temporary),
        "actual=$(sha256sum \"{tmp}\" | awk '{{print $1}}')".format(tmp=temporary),
        "test \"$actual\" = {digest}".format(digest=shlex.quote(digest)),
        "chmod 0755 \"{tmp}\"".format(tmp=temporary),
        "mv -f \"{tmp}\" \"{final}\"".format(tmp=temporary, final=final),
        "mkdir -p \"$HOME/.local/share/applications\"",
        "{{ printf '%s\\n' '[Desktop Entry]' 'Type=Application' "
        "'Name=OpenNeoUA (Development)' 'Comment=Urban Assault' "
        "'Icon=applications-games' 'Categories=Game;' 'Terminal=false'; "
        "printf 'Exec=%s\\n' \"{final}\"; }} > \"{desktop_tmp}\"".format(
            final=final, desktop_tmp=desktop_temporary
        ),
        "chmod 0644 \"{desktop_tmp}\"".format(desktop_tmp=desktop_temporary),
        "mv -f \"{desktop_tmp}\" \"{desktop}\"".format(
            desktop_tmp=desktop_temporary, desktop=desktop
        ),
        "command -v update-desktop-database >/dev/null 2>&1 && "
        "update-desktop-database \"$HOME/.local/share/applications\" >/dev/null 2>&1 || true",
        "printf '%s  %s\\n' {digest} \"{final}\"".format(
            digest=shlex.quote(digest), final=final
        ),
    ]
    return "\n".join(lines)


def deploy(appimage: Path, *, host: str = DEFAULT_HOST,
           destination: str = DEFAULT_DESTINATION, use_rsync: bool = False) -> None:
    appimage = appimage.resolve()
    if not appimage.is_file() or appimage.is_symlink():
        raise DeployError("AppImage is not a regular file: {}".format(appimage))
    final = remote_path_expression(destination)
    incoming = destination + ".incoming"
    parent = str(Path(destination).parent)
    digest = sha256_file(appimage)
    run(["ssh", host, "mkdir -p {} && rm -f {}".format(
        remote_path_expression(parent), final + ".incoming")])

    if use_rsync:
        if not shutil.which("rsync"):
            raise DeployError("--rsync requested but rsync is not installed locally")
        # Seed the temporary file from the current release. rsync then sends
        # only changed blocks, while the final rename remains atomic.
        run(["ssh", host, "test ! -f {0} || cp -f {0} {0}.incoming".format(final)])
        run(["rsync", "--archive", "--checksum", "--inplace", "--progress",
             str(appimage), "{}:{}".format(host, incoming)])
    else:
        run(["scp", str(appimage), "{}:{}".format(host, incoming)])

    run(["ssh", host, remote_script(destination, digest)])
    print("Installed {} on {} as ~/{}".format(appimage.name, host, destination))
    print("For the first Game Mode install, add 'OpenNeoUA (Development)' as a Non-Steam game in Desktop Mode.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appimage", nargs="?", type=Path,
                        help="AppImage to deploy; defaults to the newest private build")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="SSH config host (default: steamdeck)")
    parser.add_argument("--destination", default=DEFAULT_DESTINATION,
                        help="stable path relative to the Deck home")
    parser.add_argument("--rsync", action="store_true",
                        help="seed from the installed image and transfer changed blocks")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        appimage = args.appimage or find_latest_appimage(args.artifact_dir)
        deploy(appimage, host=args.host, destination=args.destination,
               use_rsync=args.rsync)
    except DeployError as exc:
        print("deploy_steamdeck.py: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
