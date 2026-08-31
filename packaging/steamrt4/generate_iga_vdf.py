#!/usr/bin/env python3
"""Generate game_actions_480.vdf from src/system/action_table.h."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TABLE = REPO_ROOT / "src" / "system" / "action_table.h"
DEFAULT_OUTPUT = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "game_actions_480.vdf"
DEFAULT_COVERAGE_OUTPUT = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "ACTION_COVERAGE.md"
DECK_IGA_CONFIG = "openneoua_deck_iga.vdf"

ENTRY_PATTERN = re.compile(
    r"\{\s*INPUT_BIND_\w+,\s*ACTION_KIND_(DIGITAL|ANALOG),\s*"
    r"INPUT_BIND_TYPE_\w+,\s*\d+,\s*\"(?P<name>[^\"]+)\",\s*(?P<retired>true|false)\s*\}"
)

ACTION_SETS = ("Menu", "Ground", "Air", "Host")
ACTION_LAYERS = {
    "Ground": "GroundStrategic",
    "Air": "AirStrategic",
    "Host": "HostStrategic",
}

# StickPadGyro actions beyond the action table.
EXTRA_STICK_ACTIONS = {
    "Menu": (
        ("MenuCursor", "absolute_mouse", "Menu Cursor"),
    ),
    "Ground": (
        ("Aim", "absolute_mouse", "Aim"),
        ("GroundMove", "joystick_move", "Ground Movement"),
        ("StrategicCursor", "absolute_mouse", "Strategic Cursor"),
    ),
    "Air": (
        ("Aim", "absolute_mouse", "Aim"),
        ("AirMove", "joystick_move", "Air Movement"),
        ("StrategicCursor", "absolute_mouse", "Strategic Cursor"),
    ),
    "Host": (
        ("Aim", "absolute_mouse", "Aim"),
        ("HostView", "joystick_move", "Host View"),
        ("StrategicCursor", "absolute_mouse", "Strategic Cursor"),
    ),
}

UI_ACTIONS = (("UiPrimary", "Primary UI"), ("UiSecondary", "Secondary UI"),
              ("UiMiddle", "Pan UI"), ("UiCancel", "Close UI"))

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

DIRECT_BOUND = frozenset({"Brake", "Quit", "SwitchWeapon", "AlternativeView", "ZoomIn", "ZoomOut",
    "SquadManager", "Order", "Map", "Pause", "CamFire", "CycleTarget", "NextUnit", "ControlUnit",
    "Fire", "Gun", "Sprint"})
RADIAL_BOUND = frozenset({"ControlUnit", "Autopilot", "Hud", "LogWindow", "SquadNew", "SquadAdd",
    "SetCommander", "Analyzer", "Map", "SquadManager", "ZoomIn", "ZoomOut", "MapLandLayer",
    "MapOwnerLayer", "MapHeightLayer", "MapLockView"})


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
        if action_set in ACTION_LAYERS:
            lines.append('\t\t\t"Layers"')
            lines.append("\t\t\t{")
            lines.append('\t\t\t\t"{}"\t\t"#Set_{}"'.format(ACTION_LAYERS[action_set], ACTION_LAYERS[action_set]))
            lines.append("\t\t\t}")

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
        else:
            for ui_name, label in UI_ACTIONS:
                buttons.append(ui_name)
                loc["Action_{}".format(ui_name)] = label

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
    lines.append('\t"action_layers"')
    lines.append("\t{")
    for parent, layer in ACTION_LAYERS.items():
        lines.append('\t\t"{}"'.format(layer))
        lines.append("\t\t{")
        lines.append('\t\t\t"title"\t\t"#Set_{}"'.format(layer))
        lines.append('\t\t\t"parent_set_name"\t\t"{}"'.format(parent))
        lines.append('\t\t\t"set_layer"\t\t"1"')
        lines.append("\t\t}")
        loc["Set_{}".format(layer)] = "{} UI".format(parent)
    lines.append("\t}")
    lines.append("\t\"configurations\"")
    lines.append("\t{")
    lines.append('\t\t"controller_neptune"')
    lines.append("\t\t{")
    lines.append('\t\t\t"0"')
    lines.append("\t\t\t{")
    lines.append('\t\t\t\t"path"\t\t"{}"'.format(DECK_IGA_CONFIG))
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
    for layer in ACTION_LAYERS.values():
        lines.append('\t\t\t"Set_{}"\t\t"{}"'.format(layer, loc["Set_{}".format(layer)]))
    for token in sorted(loc):
        if token.startswith("Set_"):
            continue
        lines.append('\t\t\t"{}"\t\t"{}"'.format(token, loc[token]))
    lines.append("\t\t}")
    lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def build_coverage(entries: list[dict[str, object]]) -> str:
    lines = ["# Steam Input action coverage", "", "Generated by `generate_iga_vdf.py`.", "",
             "| Action | Coverage |", "|---|---|"]
    for entry in entries:
        name = str(entry["name"])
        if name in RADIAL_BOUND:
            coverage = "radial-bound"
        elif name in DIRECT_BOUND or entry["kind"] == "analog":
            coverage = "directly bound"
        elif entry["retired"]:
            coverage = "intentionally retired"
        else:
            coverage = "remappable-only"
        lines.append("| {} | {} |".format(name, coverage))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output VDF path",
    )
    parser.add_argument("--coverage-output", type=Path, default=DEFAULT_COVERAGE_OUTPUT)
    args = parser.parse_args()

    text = ACTION_TABLE.read_text(encoding="utf-8")
    entries = parse_action_table(text)
    vdf = build_vdf(entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(vdf, encoding="utf-8")
    args.coverage_output.write_text(build_coverage(entries), encoding="utf-8")
    print("Wrote {} ({} actions)".format(args.output, len(entries)))


if __name__ == "__main__":
    main()
