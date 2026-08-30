#!/usr/bin/env python3
"""Generate game_actions_480.vdf from src/system/action_table.h."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TABLE = REPO_ROOT / "src" / "system" / "action_table.h"
DEFAULT_OUTPUT = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "game_actions_480.vdf"

ENTRY_PATTERN = re.compile(
    r"\{\s*INPUT_BIND_\w+,\s*ACTION_KIND_(DIGITAL|ANALOG),\s*"
    r"INPUT_BIND_TYPE_\w+,\s*\d+,\s*\"(?P<name>[^\"]+)\",\s*(?P<retired>true|false)\s*\}"
)

ACTION_SETS = ("Menu", "Ground", "Air", "Host", "Map")

# StickPadGyro actions beyond the action table.
EXTRA_STICK_ACTIONS = {
    "Menu": (
        ("MenuCursor", "absolute_mouse", "Menu Cursor"),
    ),
    "Ground": (
        ("Aim", "absolute_mouse", "Aim"),
    ),
    "Air": (
        ("Aim", "absolute_mouse", "Aim"),
    ),
    "Host": (
        ("Aim", "absolute_mouse", "Aim"),
    ),
    "Map": (
        ("MenuCursor", "absolute_mouse", "Map Cursor"),
    ),
}

# Menu-only digital navigation actions for controller focus (Phase 7).
MENU_NAV_ACTIONS = (
    ("MenuUp", "Menu Up"),
    ("MenuDown", "Menu Down"),
    ("MenuLeft", "Menu Left"),
    ("MenuRight", "Menu Right"),
    ("MenuConfirm", "Confirm"),
    ("MenuCancel", "Cancel"),
)

# AnalogTrigger candidates among slider actions.
ANALOG_TRIGGER_NAMES = frozenset({"FlySpeed", "DriveSpeed"})

# StickPadGyro joystick_move candidates among slider actions.
JOYSTICK_MOVE_NAMES = frozenset({"FlyDir", "FlyHeight", "DriveDir", "GunHeight"})


def split_camel(name: str) -> str:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    return parts.replace("Ufo", "UFO").replace("Ui", "UI")


def parse_action_table(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for match in ENTRY_PATTERN.finditer(text):
        entries.append(
            {
                "name": match.group("name"),
                "kind": match.group(1).lower(),
                "retired": match.group("retired") == "true",
            }
        )
    if not entries:
        raise RuntimeError("no action_table entries parsed from {}".format(ACTION_TABLE))
    return entries


def classify_entry(entry: dict[str, object]) -> str:
    name = str(entry["name"])
    if entry["kind"] == "digital":
        return "button"
    if name in ANALOG_TRIGGER_NAMES:
        return "trigger"
    if name in JOYSTICK_MOVE_NAMES:
        return "stick"
    return "stick"


def emit_button(lines: list[str], indent: str, name: str) -> None:
    token = "Action_{}".format(name)
    lines.append('{}\"{}\"\t\t\"#{}\"'.format(indent, name, token))


def emit_stick(lines: list[str], indent: str, name: str, mode: str) -> None:
    token = "Action_{}".format(name)
    lines.append("{}\"{}\"".format(indent, name))
    lines.append("{}{{".format(indent))
    lines.append('{}\"title\"\t\t\"#{}\"'.format(indent + "\t", token))
    lines.append('{}\"input_mode\"\t\t\"{}\"'.format(indent + "\t", mode))
    lines.append("{}}}".format(indent))


def emit_trigger(lines: list[str], indent: str, name: str) -> None:
    token = "Action_{}".format(name)
    lines.append('{}\"{}\"\t\t\"#{}\"'.format(indent, name, token))


def build_vdf(entries: list[dict[str, object]]) -> str:
    lines: list[str] = []
    loc: dict[str, str] = {}

    lines.append('"In Game Actions"')
    lines.append("{")
    lines.append("\t\"actions\"")
    lines.append("\t{")

    for action_set in ACTION_SETS:
        lines.append('\t\t"{}"'.format(action_set))
        lines.append("\t\t{")
        lines.append('\t\t\t"title"\t\t"#Set_{}"'.format(action_set))

        buttons: list[str] = []
        triggers: list[str] = []
        sticks: list[str] = []

        for entry in entries:
            section = classify_entry(entry)
            name = str(entry["name"])
            loc["Action_{}".format(name)] = split_camel(name)
            if section == "button":
                buttons.append(name)
            elif section == "trigger":
                triggers.append(name)
            else:
                sticks.append((name, "joystick_move"))

        if action_set == "Menu":
            for nav_name, label in MENU_NAV_ACTIONS:
                buttons.append(nav_name)
                loc["Action_{}".format(nav_name)] = label

        for name, mode, label in EXTRA_STICK_ACTIONS.get(action_set, ()):
            sticks.append((name, mode))
            loc["Action_{}".format(name)] = label

        if buttons:
            lines.append('\t\t\t"Button"')
            lines.append("\t\t\t{")
            for name in buttons:
                emit_button(lines, "\t\t\t\t", name)
            lines.append("\t\t\t}")

        if triggers:
            lines.append('\t\t\t"AnalogTrigger"')
            lines.append("\t\t\t{")
            for name in triggers:
                emit_trigger(lines, "\t\t\t\t", name)
            lines.append("\t\t\t}")

        if sticks:
            lines.append('\t\t\t"StickPadGyro"')
            lines.append("\t\t\t{")
            for name, mode in sticks:
                emit_stick(lines, "\t\t\t\t", name, mode)
            lines.append("\t\t\t}")

        lines.append("\t\t}")

    lines.append("\t}")
    lines.append("\t\"localization\"")
    lines.append("\t{")
    lines.append('\t\t"english"')
    lines.append("\t\t{")
    for action_set in ACTION_SETS:
        loc["Set_{}".format(action_set)] = "{} Controls".format(action_set)
        lines.append('\t\t\t"Set_{}"\t\t"{} Controls"'.format(action_set, action_set))
    for token in sorted(loc):
        if token.startswith("Set_"):
            continue
        lines.append('\t\t\t"{}"\t\t"{}"'.format(token, loc[token]))
    lines.append("\t\t}")
    lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output VDF path",
    )
    args = parser.parse_args()

    text = ACTION_TABLE.read_text(encoding="utf-8")
    entries = parse_action_table(text)
    vdf = build_vdf(entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(vdf, encoding="utf-8")
    print("Wrote {} ({} actions)".format(args.output, len(entries)))


if __name__ == "__main__":
    main()
