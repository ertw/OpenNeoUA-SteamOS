#!/usr/bin/env python3
"""Build the dedicated OpenNeoUA smoketest Docker image."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


STEAMRT4_VERSION = "4.0.20260805.254769"
STEAMRT4_IMAGE = (
    "registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:" + STEAMRT4_VERSION
)
SMOKETEST_IMAGE = "openneoua-smoketest:" + STEAMRT4_VERSION
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPOSITORY_ROOT / "packaging" / "steamrt4" / "Dockerfile.smoketest"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=SMOKETEST_IMAGE)
    parser.add_argument("--pull", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    command = [
        "docker",
        "build",
        "--platform",
        "linux/amd64",
        "-f",
        str(DOCKERFILE),
        "-t",
        args.tag,
        str(REPOSITORY_ROOT),
    ]
    if args.pull:
        command.insert(2, "--pull")
    print("build_smoketest_image.py: {}".format(" ".join(command)), file=sys.stderr)
    subprocess.run(command, check=True)
    print('{"image": "%s", "base": "%s"}' % (args.tag, STEAMRT4_IMAGE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
