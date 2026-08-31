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
    parser.add_argument("workflow", choices=("build-deploy", "steam-input", "tests"))
    args = parser.parse_args()
    py = sys.executable
    workflows = {
        "build-deploy": [[py, "packaging/steamrt4/build_steamdeck.py"],
                         [py, "packaging/steamrt4/deploy_steamdeck.py"]],
        "steam-input": [[py, "packaging/steamrt4/generate_iga_vdf.py"],
                        [py, "packaging/steamrt4/generate_deck_iga_config.py"]],
        "tests": [[py, "-m", "unittest",
                   "packaging.steamrt4.test_steam_input_iga",
                   "packaging.steamrt4.test_steam_input",
                   "packaging.steamrt4.test_install_steamdeck_spacewar",
                   "packaging.steamrt4.test_deploy_steamdeck"]],
    }
    return execute(workflows[args.workflow])


if __name__ == "__main__":
    raise SystemExit(main())
