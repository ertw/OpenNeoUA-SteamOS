#!/usr/bin/env python3
"""Non-interactive composite commands used by dev_menu.py."""

from __future__ import annotations

import argparse
import subprocess
import sys

from config import REPOSITORY_ROOT


def execute(commands: list[list[str]]) -> int:
    for command in commands:
        result = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
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
        "tests": [[py, "-m", "unittest", "discover", "-v",
                   "-s", "packaging/steamrt4/tests", "-t", "packaging/steamrt4"]],
    }
    return execute(workflows[args.workflow])


if __name__ == "__main__":
    raise SystemExit(main())
