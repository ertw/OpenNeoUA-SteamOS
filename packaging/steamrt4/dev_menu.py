#!/usr/bin/env python3
"""Small terminal menu for OpenNeoUA Steam Deck development tasks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    description: str
    command: tuple[str, ...]


TASKS = (
    Task("build", "Build Steam Deck AppImage", "Build the private asset-backed development AppImage.",
         (PYTHON, "packaging/steamrt4/build_steamdeck.py")),
    Task("deploy", "Deploy latest AppImage", "Atomically replace the Deck development build over SSH.",
         (PYTHON, "packaging/steamrt4/deploy_steamdeck.py")),
    Task("deploy-delta", "Deploy latest with rsync", "Use block deltas, verify, then atomically replace.",
         (PYTHON, "packaging/steamrt4/deploy_steamdeck.py", "--rsync")),
    Task("first-install", "First install / configure Spacewar", "Deploy and set Spacewar launch options; Steam must be closed.",
         (PYTHON, "packaging/steamrt4/deploy_steamdeck.py")),
    Task("build-deploy", "Build and deploy", "Build a private AppImage, then deploy the newest artifact.",
         (PYTHON, "packaging/steamrt4/dev_workflow.py", "build-deploy")),
    Task("steam-input", "Regenerate Steam Input files", "Regenerate the action manifest and Deck IGA layout.",
         (PYTHON, "packaging/steamrt4/dev_workflow.py", "steam-input")),
    Task("tests", "Run focused Steam Input tests", "Run manifest, layout, installer, and deployment tests.",
         (PYTHON, "packaging/steamrt4/dev_workflow.py", "tests")),
    Task("ci", "Run full SteamRT4 CI", "Compile, test, package, and checksum the redistributable build.",
         (PYTHON, "packaging/steamrt4/local_ci.py")),
)


def run_task(task: Task) -> int:
    print("\n\033[1;36m{}\033[0m\n{}\n".format(task.title, task.description))
    return subprocess.run(task.command, cwd=ROOT, check=False).returncode


def interactive() -> int:
    while True:
        print("\n\033[1mOpenNeoUA Steam Deck Developer Menu\033[0m")
        for index, task in enumerate(TASKS, 1):
            print("  {:>2}. {:<36} {}".format(index, task.title, task.description))
        print("   q. Quit")
        try:
            choice = input("\nSelect a task: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in {"q", "quit", "exit"}:
            return 0
        task = next((item for item in TASKS if item.key == choice), None)
        if task is None and choice.isdigit() and 1 <= int(choice) <= len(TASKS):
            task = TASKS[int(choice) - 1]
        if task is None:
            print("Unknown selection: {}".format(choice), file=sys.stderr)
            continue
        status = run_task(task)
        print("\n{}: {}".format(task.title, "completed" if status == 0 else "failed ({})".format(status)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list task keys and exit")
    parser.add_argument("--run", choices=[task.key for task in TASKS], help="run one task without prompting")
    args = parser.parse_args()
    if args.list:
        for task in TASKS:
            print("{:<14} {}".format(task.key, task.title))
        return 0
    if args.run:
        return run_task(next(task for task in TASKS if task.key == args.run))
    return interactive()


if __name__ == "__main__":
    raise SystemExit(main())
