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
DEFAULT_DESTINATION = ".local/bin/OpenNeoUA-dev.AppImage"


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


def remote_script(destination: str, digest: str, configure_spacewar: bool) -> str:
    final = remote_path_expression(destination)
    temporary = final + ".incoming"
    lines = [
        "set -eu",
        "test -f {tmp}".format(tmp=temporary),
        "actual=$(sha256sum {tmp} | awk '{{print $1}}')".format(tmp=temporary),
        "test \"$actual\" = {digest}".format(digest=shlex.quote(digest)),
        "chmod 0755 {tmp}".format(tmp=temporary),
        "mv -f {tmp} {final}".format(tmp=temporary, final=final),
    ]
    if configure_spacewar:
        lines.append("{final} --install-steam-spacewar --input-debug".format(final=final))
    lines.append("printf '%s  %s\\n' {digest} {final}".format(
        digest=shlex.quote(digest), final=shlex.quote(destination)))
    return "\n".join(lines)


def ensure_remote_steam_stopped(host: str) -> None:
    check = (
        "if pgrep -x steam >/dev/null 2>&1; then "
        "echo 'Steam is running on the Deck. Quit Steam completely before deploying.' >&2; "
        "exit 2; fi"
    )
    run(["ssh", host, check])


def deploy(appimage: Path, *, host: str = DEFAULT_HOST,
           destination: str = DEFAULT_DESTINATION, configure_spacewar: bool = True,
           use_rsync: bool = False) -> None:
    appimage = appimage.resolve()
    if not appimage.is_file() or appimage.is_symlink():
        raise DeployError("AppImage is not a regular file: {}".format(appimage))
    final = remote_path_expression(destination)
    incoming = destination + ".incoming"
    parent = str(Path(destination).parent)
    # Check before making directories, copying a delta seed, or transferring
    # any bytes. This also prevents replacing an AppImage Steam may be running.
    ensure_remote_steam_stopped(host)
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

    run(["ssh", host, remote_script(destination, digest, configure_spacewar)])
    print("Installed {} on {} as ~/{}".format(appimage.name, host, destination))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appimage", nargs="?", type=Path,
                        help="AppImage to deploy; defaults to the newest private build")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help="SSH config host (default: steamdeck)")
    parser.add_argument("--destination", default=DEFAULT_DESTINATION,
                        help="stable path relative to the Deck home")
    parser.add_argument("--configure-spacewar", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--skip-spacewar-config", action="store_true",
                        help="do not refresh Spacewar launch options after installing")
    parser.add_argument("--rsync", action="store_true",
                        help="seed from the installed image and transfer changed blocks")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        appimage = args.appimage or find_latest_appimage(args.artifact_dir)
        deploy(appimage, host=args.host, destination=args.destination,
               configure_spacewar=not args.skip_spacewar_config, use_rsync=args.rsync)
    except DeployError as exc:
        print("deploy_steamdeck.py: {}".format(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
