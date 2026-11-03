#!/usr/bin/env python3
"""Build the dedicated OpenNeoUA smoketest Docker image."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from config import REPOSITORY_ROOT, SMOKETEST_IMAGE, STEAMRT4_IMAGE
from local_ci import capture_source, create_snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=SMOKETEST_IMAGE)
    parser.add_argument("--pull", action="store_true")
    return parser.parse_args(argv)


def image_command(snapshot: Path, *, tag: str = SMOKETEST_IMAGE, pull: bool = False) -> list[str]:
    """Use only a sanitized source snapshot as the Docker build context."""
    dockerfile = snapshot / "packaging" / "steamrt4" / "Dockerfile.smoketest"
    if snapshot.is_symlink() or not snapshot.is_dir() or not dockerfile.is_file():
        raise ValueError("sanitized SteamRT4 snapshot is invalid")
    if any(child.name.casefold() == "ua-complete" for child in snapshot.iterdir()):
        raise ValueError("sanitized Docker context contains UA-Complete")
    vendor_iso = snapshot / "vendor" / "ua.iso"
    if vendor_iso.is_file() or vendor_iso.is_symlink():
        raise ValueError("sanitized Docker context contains vendor/ua.iso")
    command = ["docker", "build", "--platform", "linux/amd64", "--tag", tag,
               "--file", str(dockerfile)]
    if pull:
        command.append("--pull")
    return [*command, str(snapshot)]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    capture = capture_source(REPOSITORY_ROOT)
    with tempfile.TemporaryDirectory(prefix="openneoua-smoketest-image-") as directory:
        snapshot = create_snapshot(REPOSITORY_ROOT, capture, Path(directory) / "source")
        command = image_command(snapshot.path, tag=args.tag, pull=args.pull)
        print("build_smoketest_image.py: {}".format(" ".join(command)), file=sys.stderr)
        subprocess.run(command, check=True)
    print(json.dumps({"image": args.tag, "base": STEAMRT4_IMAGE}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
