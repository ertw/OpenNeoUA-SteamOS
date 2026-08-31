#!/usr/bin/env python3
"""Generate openneoua_deck_iga.vdf — Neptune preset bindings for IGA action sets."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from generate_iga_vdf import ACTION_SETS, ACTION_LAYERS
except ImportError:  # pragma: no cover
    from packaging.steamrt4.generate_iga_vdf import ACTION_SETS, ACTION_LAYERS


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


class SourceMap:
    """Unique top-level group ids plus the source each preset should bind."""

    def __init__(self) -> None:
        self.next_id = 0
        self.by_set: dict[str, list[tuple[str, str]]] = {
            name: [] for name in (*ACTION_SETS, *ACTION_LAYERS.values())
        }

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


def emit_face_group(lines: list[str], gid: str, action_set: str) -> None:
    emit_group_open(lines, gid, "four_buttons")
    for control, action, label in FACE_BINDINGS:
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
    sprint_action: str | None = None,
) -> None:
    emit_group_open(lines, gid, "joystick_move")
    if sprint_action:
        emit_binding(lines, "click", game_action(action_set, sprint_action, "Sprint"))
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


def emit_radial_group(lines: list[str], gid: str, action_set: str, strategic: bool = False) -> None:
    gameplay = (("ControlUnit", "Control Unit"), ("Autopilot", "Autopilot"),
                ("Hud", "HUD"), ("LogWindow", "Log"), ("SquadNew", "New Squad"),
                ("SquadAdd", "Add Unit"), ("SetCommander", "Set Commander"),
                ("Analyzer", "Analyzer"))
    strategic_actions = (("Map", "Map"), ("SquadManager", "Squad Manager"),
                         ("ZoomIn", "Zoom In"), ("ZoomOut", "Zoom Out"),
                         ("MapLandLayer", "Landscape"), ("MapOwnerLayer", "Owner"),
                         ("MapHeightLayer", "Height"), ("MapLockView", "Lock View"))
    emit_group_open(lines, gid, "radial_menu")
    for index, (action, label) in enumerate(strategic_actions if strategic else gameplay):
        emit_binding(lines, "button_{}".format(index), game_action(action_set, action, label))
    lines.append("\t\t}")
    emit_group_close(lines)


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
        emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)
        return

    emit_face_group(lines, sources.add(action_set, "button_diamond active"), action_set)
    emit_dpad_group(lines, sources.add(action_set, "dpad active"), action_set)
    emit_radial_group(lines, sources.add(action_set, "left_trackpad active"), action_set)
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
    if action_set == "Ground":
        emit_absolute_mouse_group(
            lines,
            sources.add(action_set, "right_joystick active"),
            action_set,
            "Aim",
            "Aim",
            sensitivity="120",
        )
        emit_joystick_group(
            lines,
            sources.add(action_set, "joystick active"),
            action_set,
            "GroundMove",
            "Drive / Reverse",
            sprint_action="Sprint",
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
        return

    emit_joystick_group(
        lines, sources.add(action_set, "joystick active"), action_set,
        "AirMove" if action_set == "Air" else "HostView",
        "Air Movement" if action_set == "Air" else "Host View"
    )
    emit_switch_group(lines, sources.add(action_set, "switch active"), action_set)


def emit_strategic_layer(lines: list[str], sources: SourceMap, parent: str, layer: str) -> None:
    emit_radial_group(lines, sources.add(layer, "left_trackpad active"), parent, strategic=True)
    emit_absolute_mouse_group(lines, sources.add(layer, "right_trackpad active"), parent,
                              "StrategicCursor", "Strategic Cursor", sensitivity="100",
                              click_action="UiMiddle", click_label="Pan")
    emit_absolute_mouse_group(lines, sources.add(layer, "right_joystick active"), parent,
                              "StrategicCursor", "Strategic Cursor", sensitivity="100")
    emit_trigger_group(lines, sources.add(layer, "right_trigger active"), "click", parent, "UiPrimary", "Select / Drag")
    emit_trigger_group(lines, sources.add(layer, "left_trigger active"), "click", parent, "UiSecondary", "Context Action")
    emit_group_open(lines, sources.add(layer, "button_diamond active"), "four_buttons")
    emit_binding(lines, "button_b", game_action(parent, "UiCancel", "Close"))
    lines.append("\t\t}")
    emit_group_close(lines)


def emit_preset(lines: list[str], sources: SourceMap, action_set: str) -> None:
    lines.append('\t"preset"')
    lines.append("\t{")
    contexts = (*ACTION_SETS, *ACTION_LAYERS.values())
    lines.append('\t\t"id"\t\t"{}"'.format(contexts.index(action_set)))
    lines.append('\t\t"name"\t\t"{}"'.format(action_set))
    if action_set in ACTION_LAYERS.values():
        parent = next(parent for parent, layer in ACTION_LAYERS.items() if layer == action_set)
        lines.append('\t\t"set_layer"\t\t"1"')
        lines.append('\t\t"parent_set_name"\t\t"{}"'.format(parent))
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
    for parent, layer in ACTION_LAYERS.items():
        emit_strategic_layer(lines, sources, parent, layer)
    for action_set in ACTION_SETS:
        emit_preset(lines, sources, action_set)
    for layer in ACTION_LAYERS.values():
        emit_preset(lines, sources, layer)
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
