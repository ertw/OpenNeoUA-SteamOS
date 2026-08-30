#!/usr/bin/env python3
"""Generate openneoua_deck_iga.vdf — Neptune preset bindings for IGA action sets."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from generate_iga_vdf import ACTION_SETS
except ImportError:  # pragma: no cover
    from packaging.steamrt4.generate_iga_vdf import ACTION_SETS


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "openneoua_deck_iga.vdf"

# Shared face / shoulder / d-pad bindings per action set (same physical layout).
FACE_BINDINGS = (
    ("button_a", "Brake", "Brake"),
    ("button_b", "Quit", "Quit"),
    ("button_x", "SwitchWeapon", "Switch Weapon"),
    ("button_y", "AlternativeView", "Alternative View"),
)

DPAD_BINDINGS = (
    ("dpad_north", "ZoomIn", "Zoom In"),
    ("dpad_south", "ZoomOut", "Zoom Out"),
    ("dpad_west", "SquadManager", "Squad Manager"),
    ("dpad_east", "Order", "Order"),
)

SWITCH_BINDINGS = (
    ("button_escape", "Map", "Map"),
    ("button_menu", "Pause", "Pause"),
    ("left_bumper", "CamFire", "Cam Fire"),
    ("right_bumper", "CycleTarget", "Cycle Target"),
    ("button_back_left_upper", "NextUnit", "Next Unit"),
    ("button_back_right_upper", "ControlUnit", "Control Unit"),
)


def game_action(action_set: str, action: str, label: str) -> str:
    return 'game_action {} {}, {}'.format(action_set, action, label)


def emit_face_group(lines: list[str], action_set: str, indent: str = "\t") -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"0"'.format(indent + "\t"))
    lines.append('{}\"mode\"\t\t"four_buttons"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    for control, action, label in FACE_BINDINGS:
        lines.append(
            '{}\"{}\"\t\t"{}"'.format(
                indent + "\t\t", control, game_action(action_set, action, label)
            )
        )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"requires_click\"\t\t"0"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_dpad_group(lines: list[str], action_set: str, indent: str = "\t") -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"1"'.format(indent + "\t"))
    lines.append('{}\"mode\"\t\t"dpad"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    for control, action, label in DPAD_BINDINGS:
        lines.append(
            '{}\"{}\"\t\t"{}"'.format(
                indent + "\t\t", control, game_action(action_set, action, label)
            )
        )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"requires_click\"\t\t"0"'.format(indent + "\t\t"))
    lines.append('{}\"layout\"\t\t"radial_top_down"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_trigger_group(
    lines: list[str],
    group_id: str,
    control: str,
    action_set: str,
    action: str,
    label: str,
    indent: str = "\t",
) -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"{}"'.format(indent + "\t", group_id))
    lines.append('{}\"mode\"\t\t"trigger"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append(
        '{}\"{}\"\t\t"{}"'.format(
            indent + "\t\t", control, game_action(action_set, action, label)
        )
    )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_analog_trigger_group(
    lines: list[str], group_id: str, action_set: str, action: str, label: str, indent: str = "\t"
) -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"{}"'.format(indent + "\t", group_id))
    lines.append('{}\"mode\"\t\t"trigger"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append(
        '{}\"pull\"\t\t"{}"'.format(
            indent + "\t\t", game_action(action_set, action, label)
        )
    )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"output_trigger\"\t\t"1"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_joystick_group(
    lines: list[str],
    group_id: str,
    action_set: str,
    action: str,
    label: str,
    *,
    sprint_action: str | None = None,
    indent: str = "\t",
) -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"{}"'.format(indent + "\t", group_id))
    lines.append('{}\"mode\"\t\t"joystick_move"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    if sprint_action:
        lines.append(
            '{}\"click\"\t\t"{}"'.format(
                indent + "\t\t", game_action(action_set, sprint_action, "Sprint")
            )
        )
    lines.append(
        '{}\"output\"\t\t"{}"'.format(
            indent + "\t\t", game_action(action_set, action, label)
        )
    )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"deadzone_inner_radius\"\t\t"0.100000"'.format(indent + "\t\t"))
    lines.append('{}\"deadzone_outer_radius\"\t\t"0.990000"'.format(indent + "\t\t"))
    lines.append('{}\"deadzone_shape\"\t\t"1"'.format(indent + "\t\t"))
    lines.append('{}\"edge_binding_radius\"\t\t"0.970000"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_absolute_mouse_group(
    lines: list[str],
    group_id: str,
    action_set: str,
    action: str,
    label: str,
    *,
    sensitivity: str,
    click_action: str | None = None,
    click_label: str = "Mouse Grab",
    gyro: bool = False,
    indent: str = "\t",
) -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"{}"'.format(indent + "\t", group_id))
    lines.append('{}\"mode\"\t\t"absolute_mouse"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append(
        '{}\"output\"\t\t"{}"'.format(
            indent + "\t\t", game_action(action_set, action, label)
        )
    )
    if click_action:
        lines.append(
            '{}\"click\"\t\t"{}"'.format(
                indent + "\t\t", game_action(action_set, click_action, click_label)
            )
        )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"sensitivity\"\t\t"{}"'.format(indent + "\t\t", sensitivity))
    lines.append('{}\"trackball\"\t\t"0"'.format(indent + "\t\t"))
    lines.append('{}\"rotation_offset\"\t\t"0"'.format(indent + "\t\t"))
    if gyro:
        lines.append('{}\"gyro_enable_mode\"\t\t"1"'.format(indent + "\t\t"))
        lines.append('{}\"acceleration\"\t\t"1"'.format(indent + "\t\t"))
        lines.append('{}\"natural_sensitivity\"\t\t"1"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_switch_group(lines: list[str], action_set: str, indent: str = "\t") -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"7"'.format(indent + "\t"))
    lines.append('{}\"mode\"\t\t"switches"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    for control, action, label in SWITCH_BINDINGS:
        lines.append(
            '{}\"{}\"\t\t"{}"'.format(
                indent + "\t\t", control, game_action(action_set, action, label)
            )
        )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_menu_nav_dpad(lines: list[str], indent: str = "\t") -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"1"'.format(indent + "\t"))
    lines.append('{}\"mode\"\t\t"dpad"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append(
        '{}\"dpad_north\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuUp", "Menu Up")
        )
    )
    lines.append(
        '{}\"dpad_south\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuDown", "Menu Down")
        )
    )
    lines.append(
        '{}\"dpad_west\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuLeft", "Menu Left")
        )
    )
    lines.append(
        '{}\"dpad_east\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuRight", "Menu Right")
        )
    )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"requires_click\"\t\t"0"'.format(indent + "\t\t"))
    lines.append('{}\"layout\"\t\t"radial_top_down"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_menu_face(lines: list[str], indent: str = "\t") -> None:
    lines.append('{}group'.format(indent))
    lines.append("{}".format(indent) + "{")
    lines.append('{}\"id\"\t\t"0"'.format(indent + "\t"))
    lines.append('{}\"mode\"\t\t"four_buttons"'.format(indent + "\t"))
    lines.append('{}\"bindings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append(
        '{}\"button_a\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuConfirm", "Confirm")
        )
    )
    lines.append(
        '{}\"button_b\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "MenuCancel", "Cancel")
        )
    )
    lines.append(
        '{}\"button_x\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "SwitchWeapon", "Switch Weapon")
        )
    )
    lines.append(
        '{}\"button_y\"\t\t"{}"'.format(
            indent + "\t\t", game_action("Menu", "AlternativeView", "Alt View")
        )
    )
    lines.append("{}".format(indent + "\t") + "}")
    lines.append('{}\"settings\"'.format(indent + "\t"))
    lines.append("{}".format(indent + "\t") + "{")
    lines.append('{}\"requires_click\"\t\t"0"'.format(indent + "\t\t"))
    lines.append("{}".format(indent + "\t") + "}")
    lines.append("{}".format(indent) + "}")


def emit_preset(lines: list[str], action_set: str) -> None:
    preset_indent = "\t\t"
    lines.append('\t"preset"')
    lines.append("\t{")
    lines.append('\t\t"id"\t\t"{}"'.format(ACTION_SETS.index(action_set)))
    lines.append('\t\t"name"\t\t"{}"'.format(action_set))

    if action_set == "Menu":
        emit_menu_face(lines, preset_indent)
        emit_menu_nav_dpad(lines, preset_indent)
        emit_absolute_mouse_group(
            lines, "2", "Menu", "MenuCursor", "Menu Cursor", sensitivity="100", indent=preset_indent
        )
        emit_switch_group(lines, action_set, preset_indent)
    elif action_set == "Map":
        emit_face_group(lines, action_set, preset_indent)
        emit_dpad_group(lines, action_set, preset_indent)
        emit_absolute_mouse_group(
            lines,
            "2",
            "Map",
            "MenuCursor",
            "Map Cursor",
            sensitivity="100",
            click_action="PlaceMapMarker",
            click_label="Place Marker",
            indent=preset_indent,
        )
        emit_trigger_group(lines, "4", "click", action_set, "Fire", "Fire", preset_indent)
        emit_trigger_group(lines, "5", "click", action_set, "Gun", "Gun", preset_indent)
        emit_switch_group(lines, action_set, preset_indent)
    elif action_set == "Ground":
        emit_face_group(lines, action_set, preset_indent)
        emit_dpad_group(lines, action_set, preset_indent)
        emit_absolute_mouse_group(
            lines,
            "2",
            action_set,
            "Aim",
            "Aim",
            sensitivity="100",
            click_action="CamFire",
            click_label="Mouse Grab",
            indent=preset_indent,
        )
        emit_absolute_mouse_group(
            lines, "3", action_set, "Aim", "Aim", sensitivity="120", indent=preset_indent
        )
        emit_trigger_group(lines, "4", "click", action_set, "Fire", "Fire", preset_indent)
        emit_trigger_group(lines, "5", "click", action_set, "Gun", "Gun", preset_indent)
        emit_joystick_group(
            lines, "6", action_set, "DriveDir", "Drive", sprint_action="Sprint", indent=preset_indent
        )
        emit_switch_group(lines, action_set, preset_indent)
        emit_absolute_mouse_group(
            lines,
            "8",
            action_set,
            "Aim",
            "Aim Gyro",
            sensitivity="60",
            gyro=True,
            indent=preset_indent,
        )
        emit_analog_trigger_group(
            lines, "10", action_set, "DriveSpeed", "Drive Speed", indent=preset_indent
        )
    elif action_set in ("Air", "Host"):
        emit_face_group(lines, action_set, preset_indent)
        emit_dpad_group(lines, action_set, preset_indent)
        emit_absolute_mouse_group(
            lines,
            "2",
            action_set,
            "Aim",
            "Aim",
            sensitivity="100",
            click_action="CamFire",
            click_label="Mouse Grab",
            indent=preset_indent,
        )
        emit_trigger_group(lines, "4", "click", action_set, "Fire", "Fire", preset_indent)
        emit_trigger_group(lines, "5", "click", action_set, "Gun", "Gun", preset_indent)
        emit_joystick_group(lines, "6", action_set, "FlyDir", "Fly Direction", indent=preset_indent)
        emit_joystick_group(lines, "3", action_set, "FlyHeight", "Fly Height", indent=preset_indent)
        emit_switch_group(lines, action_set, preset_indent)
        emit_analog_trigger_group(
            lines, "10", action_set, "FlySpeed", "Fly Speed", indent=preset_indent
        )
    else:
        raise RuntimeError("unknown action set: {}".format(action_set))

    lines.append('\t\t"group_source_bindings"')
    lines.append("\t\t{")
    if action_set == "Menu":
        lines.append('\t\t\t"0"\t\t"button_diamond active"')
        lines.append('\t\t\t"1"\t\t"left_trackpad inactive"')
        lines.append('\t\t\t"2"\t\t"right_trackpad active"')
        lines.append('\t\t\t"7"\t\t"switch active"')
    elif action_set == "Map":
        lines.append('\t\t\t"0"\t\t"button_diamond active"')
        lines.append('\t\t\t"1"\t\t"left_trackpad inactive"')
        lines.append('\t\t\t"2"\t\t"right_trackpad active"')
        lines.append('\t\t\t"4"\t\t"right_trigger active"')
        lines.append('\t\t\t"5"\t\t"left_trigger active"')
        lines.append('\t\t\t"7"\t\t"switch active"')
    elif action_set in ("Ground", "Air", "Host"):
        lines.append('\t\t\t"0"\t\t"button_diamond active"')
        lines.append('\t\t\t"1"\t\t"left_trackpad inactive"')
        lines.append('\t\t\t"2"\t\t"right_trackpad active"')
        lines.append('\t\t\t"3"\t\t"right_joystick active"')
        lines.append('\t\t\t"4"\t\t"right_trigger active"')
        lines.append('\t\t\t"5"\t\t"left_trigger active"')
        lines.append('\t\t\t"6"\t\t"joystick active"')
        lines.append('\t\t\t"7"\t\t"switch active"')
        if action_set == "Ground":
            lines.append('\t\t\t"8"\t\t"gyro active"')
            lines.append('\t\t\t"10"\t\t"left_trigger active"')
        if action_set in ("Air", "Host"):
            lines.append('\t\t\t"10"\t\t"left_trigger active"')
    lines.append("\t\t}")
    lines.append("\t}")


def build_vdf() -> str:
    lines: list[str] = []
    lines.append('"controller_mappings"')
    lines.append("{")
    lines.append('\t"version"\t\t"3"')
    lines.append('\t"title"\t\t"OpenNeoUA Deck IGA"')
    lines.append(
        '\t"description"\t\t"OpenNeoUA native Steam Input layout for Steam Deck (Spacewar 480 POC)."'
    )
    lines.append('\t"controller_type"\t\t"controller_neptune"')
    lines.append('\t"controller_capacitor"\t\t"1"')

    for action_set in ACTION_SETS:
        emit_preset(lines, action_set)

    lines.append("\t\"settings\"")
    lines.append("\t{")
    lines.append('\t\t"left_trackpad_mode"\t\t"0"')
    lines.append('\t\t"right_trackpad_mode"\t\t"0"')
    lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_vdf(), encoding="utf-8")
    print("Wrote {}".format(args.output))


if __name__ == "__main__":
    main()
