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

# Gameplay face buttons: A is intentionally unbound (Brake moved to stick click).
GAMEPLAY_FACE_BINDINGS = (
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

# Steam Deck 4-way radial order: E, N, W, S.
VEHICLE_RADIAL_BINDINGS = (
    ("Touch_Menu_Button_0", "SquadManager", "Squad Manager"),
    ("Touch_Menu_Button_1", "CommandMode", "Command Mode"),
    ("Touch_Menu_Button_2", "Map", "Map"),
)


class SourceMap:
    """Unique top-level group ids plus the source each preset should bind."""

    def __init__(self) -> None:
        self.next_id = 0
        self.by_set: dict[str, list[tuple[str, str]]] = {name: [] for name in ACTION_SETS}

    def add(self, action_set: str, source: str) -> str:
        gid = str(self.next_id)
        self.next_id += 1
        self.by_set[action_set].append((gid, source))
        return gid


def game_action(action_set: str, action: str, label: str) -> str:
    return "game_action {} {}, {}".format(action_set, action, label)


def emit_group_open(lines: list[str], gid: str, mode: str) -> None:
    lines.append('\t"group"')
    lines.append("\t{")
    lines.append('\t\t"id"\t\t"{}"'.format(gid))
    lines.append('\t\t"mode"\t\t"{}"'.format(mode))
    lines.append('\t\t"bindings"')
    lines.append("\t\t{")


def emit_group_close(lines: list[str]) -> None:
    lines.append("\t}")


def emit_binding(lines: list[str], control: str, value: str) -> None:
    lines.append('\t\t\t"{}"\t\t"{}"'.format(control, value))


def emit_gameplay_face_group(lines: list[str], gid: str, action_set: str) -> None:
    emit_group_open(lines, gid, "four_buttons")
    for control, action, label in GAMEPLAY_FACE_BINDINGS:
        emit_binding(lines, control, game_action(action_set, action, label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"requires_click"\t\t"0"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_menu_face(lines: list[str], gid: str) -> None:
    emit_group_open(lines, gid, "four_buttons")
    emit_binding(lines, "button_a", game_action("Menu", "MenuConfirm", "Confirm"))
    emit_binding(lines, "button_b", game_action("Menu", "MenuCancel", "Cancel"))
    emit_binding(lines, "button_x", game_action("Menu", "SwitchWeapon", "Switch Weapon"))
    emit_binding(lines, "button_y", game_action("Menu", "AlternativeView", "Alt View"))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"requires_click"\t\t"0"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_dpad_group(lines: list[str], gid: str, action_set: str) -> None:
    emit_group_open(lines, gid, "dpad")
    for control, action, label in DPAD_BINDINGS:
        emit_binding(lines, control, game_action(action_set, action, label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"requires_click"\t\t"0"')
    lines.append('\t\t\t"layout"\t\t"radial_top_down"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_menu_nav_dpad(lines: list[str], gid: str) -> None:
    emit_group_open(lines, gid, "dpad")
    emit_binding(lines, "dpad_north", game_action("Menu", "MenuUp", "Menu Up"))
    emit_binding(lines, "dpad_south", game_action("Menu", "MenuDown", "Menu Down"))
    emit_binding(lines, "dpad_west", game_action("Menu", "MenuLeft", "Menu Left"))
    emit_binding(lines, "dpad_east", game_action("Menu", "MenuRight", "Menu Right"))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"requires_click"\t\t"0"')
    lines.append('\t\t\t"layout"\t\t"radial_top_down"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_trigger_group(
    lines: list[str], gid: str, control: str, action_set: str, action: str, label: str
) -> None:
    emit_group_open(lines, gid, "trigger")
    emit_binding(lines, control, game_action(action_set, action, label))
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_analog_trigger_group(
    lines: list[str], gid: str, action_set: str, action: str, label: str
) -> None:
    emit_group_open(lines, gid, "trigger")
    emit_binding(lines, "pull", game_action(action_set, action, label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"output_trigger"\t\t"1"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_joystick_group(
    lines: list[str],
    gid: str,
    action_set: str,
    action: str,
    label: str,
    *,
    click_action: str | None = None,
    click_label: str = "Brake",
) -> None:
    emit_group_open(lines, gid, "joystick_move")
    if click_action:
        emit_binding(lines, "click", game_action(action_set, click_action, click_label))
    emit_binding(lines, "output", game_action(action_set, action, label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"deadzone_inner_radius"\t\t"0.100000"')
    lines.append('\t\t\t"deadzone_outer_radius"\t\t"0.990000"')
    lines.append('\t\t\t"deadzone_shape"\t\t"1"')
    lines.append('\t\t\t"edge_binding_radius"\t\t"0.970000"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_absolute_mouse_group(
    lines: list[str],
    gid: str,
    action_set: str,
    action: str,
    label: str,
    *,
    sensitivity: str,
    click_action: str | None = None,
    click_label: str = "Mouse Grab",
    gyro: bool = False,
) -> None:
    emit_group_open(lines, gid, "absolute_mouse")
    emit_binding(lines, "output", game_action(action_set, action, label))
    if click_action:
        emit_binding(lines, "click", game_action(action_set, click_action, click_label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"sensitivity"\t\t"{}"'.format(sensitivity))
    lines.append('\t\t\t"trackball"\t\t"0"')
    lines.append('\t\t\t"rotation_offset"\t\t"0"')
    if gyro:
        lines.append('\t\t\t"gyro_enable_mode"\t\t"1"')
        lines.append('\t\t\t"acceleration"\t\t"1"')
        lines.append('\t\t\t"natural_sensitivity"\t\t"1"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_switch_group(lines: list[str], gid: str, action_set: str) -> None:
    emit_group_open(lines, gid, "switches")
    for control, action, label in SWITCH_BINDINGS:
        emit_binding(lines, control, game_action(action_set, action, label))
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_vehicle_radial_menu(lines: list[str], gid: str, action_set: str) -> None:
    emit_group_open(lines, gid, "radial_menu")
    for control, action, label in VEHICLE_RADIAL_BINDINGS:
        emit_binding(lines, control, game_action(action_set, action, label))
    lines.append("\t\t}")
    lines.append('\t\t"settings"')
    lines.append("\t\t{")
    lines.append('\t\t\t"touch_menu_button_count"\t\t"4"')
    lines.append('\t\t\t"touch_menu_opacity"\t\t"100"')
    lines.append('\t\t\t"touch_menu_inner_radius"\t\t"0.300000"')
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_vehicle_radial_sources(lines: list[str], sources: SourceMap, action_set: str) -> None:
    emit_vehicle_radial_menu(lines, sources.add(action_set, "left_trackpad active"), action_set)


def emit_groups_for_set(lines: list[str], sources: SourceMap, action_set: str) -> None:
    if action_set == "Menu":
        emit_menu_face(lines, sources.add(action_set, "button_diamond active"))
        emit_menu_nav_dpad(lines, sources.add(action_set, "dpad active"))
        emit_absolute_mouse_group(
            lines,
            sources.add(action_set, "right_trackpad active"),
            "Menu",
            "MenuCursor",
            "Menu Cursor",
            sensitivity="100",
        )
        emit_trigger_group(
            lines, sources.add(action_set, "right_trigger active"), "click", "Menu", "Fire", "Fire"
        )
        emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)
        return

    if action_set == "Map":
        emit_gameplay_face_group(lines, sources.add(action_set, "button_diamond active"), action_set)
        emit_dpad_group(lines, sources.add(action_set, "dpad active"), action_set)
        emit_absolute_mouse_group(
            lines,
            sources.add(action_set, "right_trackpad active"),
            "Map",
            "MenuCursor",
            "Map Cursor",
            sensitivity="100",
            click_action="PlaceMapMarker",
            click_label="Place Marker",
        )
        emit_trigger_group(
            lines, sources.add(action_set, "right_trigger active"), "click", action_set, "Fire", "Fire"
        )
        emit_trigger_group(
            lines, sources.add(action_set, "left_trigger active"), "click", action_set, "Gun", "Gun"
        )
        emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)
        return

    emit_gameplay_face_group(lines, sources.add(action_set, "button_diamond active"), action_set)
    emit_dpad_group(lines, sources.add(action_set, "dpad active"), action_set)
    emit_absolute_mouse_group(
        lines,
        sources.add(action_set, "right_trackpad active"),
        action_set,
        "Aim",
        "Aim",
        sensitivity="100",
        click_action="CamFire",
        click_label="Mouse Grab",
    )
    emit_trigger_group(
        lines, sources.add(action_set, "right_trigger active"), "click", action_set, "Fire", "Fire"
    )
    emit_trigger_group(
        lines, sources.add(action_set, "left_trigger active"), "click", action_set, "Gun", "Gun"
    )
    emit_vehicle_radial_sources(lines, sources, action_set)
    if action_set == "Ground":
        emit_joystick_group(
            lines,
            sources.add(action_set, "right_joystick active"),
            action_set,
            "GunHeight",
            "Gun Height",
        )
        emit_joystick_group(
            lines,
            sources.add(action_set, "joystick active"),
            action_set,
            "DriveDir",
            "Drive",
            click_action="Brake",
        )
        emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)
        emit_absolute_mouse_group(
            lines,
            sources.add(action_set, "gyro active"),
            action_set,
            "Aim",
            "Aim Gyro",
            sensitivity="60",
            gyro=True,
        )
        emit_analog_trigger_group(
            lines,
            sources.add(action_set, "left_trigger active"),
            action_set,
            "DriveSpeed",
            "Drive Speed",
        )
        return

    emit_joystick_group(
        lines,
        sources.add(action_set, "joystick active"),
        action_set,
        "FlyDir",
        "Fly Direction",
        click_action="Brake",
    )
    emit_joystick_group(
        lines, sources.add(action_set, "right_joystick active"), action_set, "FlyHeight", "Fly Height"
    )
    emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)
    emit_analog_trigger_group(
        lines, sources.add(action_set, "left_trigger active"), action_set, "FlySpeed", "Fly Speed"
    )


def emit_preset(lines: list[str], sources: SourceMap, action_set: str) -> None:
    lines.append('\t"preset"')
    lines.append("\t{")
    lines.append('\t\t"id"\t\t"{}"'.format(ACTION_SETS.index(action_set)))
    lines.append('\t\t"name"\t\t"{}"'.format(action_set))
    lines.append('\t\t"group_source_bindings"')
    lines.append("\t\t{")
    for gid, source in sources.by_set[action_set]:
        lines.append('\t\t\t"{}"\t\t"{}"'.format(gid, source))
    lines.append("\t\t}")
    lines.append("\t}")


def build_vdf() -> str:
    sources = SourceMap()
    lines: list[str] = [
        '"controller_mappings"',
        "{",
        '\t"version"\t\t"3"',
        '\t"title"\t\t"OpenNeoUA Deck IGA"',
        '\t"description"\t\t"OpenNeoUA native Steam Input layout for Steam Deck (Spacewar 480 POC)."',
        '\t"creator"\t\t"0"',
        '\t"controller_type"\t\t"controller_neptune"',
        '\t"controller_capacitor"\t\t"1"',
        '\t"revision"\t\t"5"',
    ]
    for action_set in ACTION_SETS:
        emit_groups_for_set(lines, sources, action_set)
    for action_set in ACTION_SETS:
        emit_preset(lines, sources, action_set)
    lines.extend(
        [
            '\t"settings"',
            "\t{",
            '\t\t"left_trackpad_mode"\t\t"0"',
            '\t\t"right_trackpad_mode"\t\t"0"',
            "\t}",
            "}",
        ]
    )
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
