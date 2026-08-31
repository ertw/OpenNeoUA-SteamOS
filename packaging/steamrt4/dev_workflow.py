#!/usr/bin/env python3
"""Non-interactive composite commands used by dev_menu.py."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def execute(commands: list[list[str]]) -> int:
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=("build-deploy", "tests"))
    args = parser.parse_args()
    py = sys.executable
    workflows = {
        "build-deploy": [[py, "packaging/steamrt4/build_steamdeck.py"],
                         [py, "packaging/steamrt4/deploy_steamdeck.py"]],
        "tests": [[py, "-m", "unittest",
                   "packaging.steamrt4.test_apprun",
                   "packaging.steamrt4.test_steamdeck",
                   "packaging.steamrt4.test_deploy_steamdeck"]],
    }
    return execute(workflows[args.workflow])


if __name__ == "__main__":
    raise SystemExit(main())
