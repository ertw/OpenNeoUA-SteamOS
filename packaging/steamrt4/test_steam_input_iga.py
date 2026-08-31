#!/usr/bin/env python3
"""Validate the Steam Input IGA file against action_table.h."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    from generate_iga_vdf import ACTION_SETS, ACTION_LAYERS, parse_action_table
except ImportError:  # pragma: no cover
    from packaging.steamrt4.generate_iga_vdf import ACTION_SETS, ACTION_LAYERS, parse_action_table


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TABLE = REPO_ROOT / "src" / "system" / "action_table.h"
IGA_PATH = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "game_actions_480.vdf"

ROOT_PATTERN = re.compile(r'^"In Game Actions"\s*$')
ACTION_SET_PATTERN = re.compile(r'^\t\t"([A-Za-z]+)"\s*$')
BUTTON_PATTERN = re.compile(r'^\t\t\t\t"([A-Za-z0-9_]+)"\s*(?:\t+"#Action_[A-Za-z0-9_]+")?\s*$')
STICK_NAME_PATTERN = re.compile(r'^\t\t\t\t"([A-Za-z0-9_]+)"\s*$')
TRIGGER_PATTERN = re.compile(r'^\t\t\t\t"([A-Za-z0-9_]+)"\s*\t+"#Action_[A-Za-z0-9_]+"\s*$')
INPUT_MODE_PATTERN = re.compile(r'^\t\t\t\t\t"input_mode"\s+"([a-z_]+)"\s*$')

MENU_NAV = frozenset(
    {"MenuUp", "MenuDown", "MenuLeft", "MenuRight", "MenuConfirm", "MenuCancel"}
)
EXTRA_STICK = frozenset({"Aim", "MenuCursor", "GroundMove", "AirMove", "HostView", "StrategicCursor"})


def parse_iga_actions(text: str) -> dict[str, set[str]]:
    actions_by_set: dict[str, set[str]] = {name: set() for name in ACTION_SETS}
    current_set: str | None = None
    section: str | None = None
    pending_stick: str | None = None

    for line in text.splitlines():
        set_match = ACTION_SET_PATTERN.match(line)
        if set_match and set_match.group(1) in actions_by_set:
            current_set = set_match.group(1)
            section = None
            pending_stick = None
            continue

        if current_set is None:
            continue

        if line.strip() == '"Button"':
            section = "button"
            pending_stick = None
            continue
        if line.strip() == '"AnalogTrigger"':
            section = "trigger"
            pending_stick = None
            continue
        if line.strip() == '"StickPadGyro"':
            section = "stick"
            pending_stick = None
            continue

        if section == "button":
            match = BUTTON_PATTERN.match(line)
            if match:
                actions_by_set[current_set].add(match.group(1))
        elif section == "trigger":
            match = TRIGGER_PATTERN.match(line)
            if match:
                actions_by_set[current_set].add(match.group(1))
        elif section == "stick":
            match = STICK_NAME_PATTERN.match(line)
            if match and not line.strip().startswith("title"):
                pending_stick = match.group(1)
            mode_match = INPUT_MODE_PATTERN.match(line)
            if pending_stick and mode_match:
                actions_by_set[current_set].add(pending_stick)
                pending_stick = None

    return actions_by_set


class SteamInputIgaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table_entries = parse_action_table(ACTION_TABLE.read_text(encoding="utf-8"))
        self.table_names = {str(entry["name"]) for entry in self.table_entries}
        self.iga_text = IGA_PATH.read_text(encoding="utf-8")
        self.iga_actions = parse_iga_actions(self.iga_text)

    def test_root_key_and_sections(self) -> None:
        lines = self.iga_text.splitlines()
        self.assertTrue(ROOT_PATTERN.match(lines[0]))
        self.assertIn('"actions"', self.iga_text)
        self.assertIn('"localization"', self.iga_text)
        self.assertIn('"english"', self.iga_text)

    def test_action_sets_present(self) -> None:
        for action_set in ACTION_SETS:
            self.assertIn('"{}"'.format(action_set), self.iga_text)
            self.assertGreater(len(self.iga_actions[action_set]), 0, msg=action_set)

    def test_all_table_actions_in_every_set(self) -> None:
        for action_set in ACTION_SETS:
            missing = sorted(self.table_names - self.iga_actions[action_set])
            self.assertEqual(missing, [], msg="{} missing in {}".format(missing, action_set))

    def test_analog_modes_present(self) -> None:
        self.assertIn('"input_mode"\t\t"joystick_move"', self.iga_text)
        self.assertIn('"input_mode"\t\t"absolute_mouse"', self.iga_text)

    def test_menu_navigation_actions(self) -> None:
        menu_actions = self.iga_actions["Menu"]
        self.assertTrue(MENU_NAV.issubset(menu_actions))

    def test_extra_stick_actions(self) -> None:
        self.assertIn("Aim", self.iga_actions["Ground"])
        self.assertIn("MenuCursor", self.iga_actions["Menu"])
        self.assertIn("GroundMove", self.iga_actions["Ground"])
        self.assertIn("AirMove", self.iga_actions["Air"])
        self.assertIn("HostView", self.iga_actions["Host"])

    def test_strategic_layers_have_valid_parents(self) -> None:
        for parent, layer in ACTION_LAYERS.items():
            self.assertIn('"{}"'.format(layer), self.iga_text)
            self.assertIn('"parent_set_name"\t\t"{}"'.format(parent), self.iga_text)

    def test_deck_layout_has_unique_sources_and_eight_segment_radials(self) -> None:
        layout = (REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "openneoua_deck_iga.vdf").read_text(encoding="utf-8")
        for name in (*ACTION_SETS, *ACTION_LAYERS.values()):
            preset = layout.split('\t\t"name"\t\t"{}"'.format(name), 1)[1].split('\t"preset"', 1)[0]
            sources = re.findall(r'^\t\t\t"\d+"\t\t"([^"]+)"$', preset, re.MULTILINE)
            self.assertEqual(len(sources), len(set(sources)), msg=name)
        radial_groups = layout.split('\t\t"mode"\t\t"radial_menu"')[1:]
        self.assertEqual(len(radial_groups), 6)
        for group in radial_groups:
            buttons = re.findall(r'"button_([0-7])"', group.split('\t}', 1)[0])
            self.assertEqual(buttons, [str(i) for i in range(8)])

    def test_trigger_bindings_do_not_emit_fake_click_haptics(self) -> None:
        layout = (REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "openneoua_deck_iga.vdf").read_text(encoding="utf-8")
        trigger_groups = layout.split('\t\t"mode"\t\t"trigger"')[1:]
        self.assertGreater(len(trigger_groups), 0)
        for group in trigger_groups:
            body = group.split('\t"group"', 1)[0]
            self.assertIn('"haptic_intensity"\t\t"0"', body)
            self.assertNotIn('"haptic_intensity"\t\t"2"', body)

    def test_localization_tokens(self) -> None:
        for name in sorted(self.table_names):
            self.assertIn('"Action_{}"'.format(name), self.iga_text, msg=name)

    def test_generated_action_coverage_is_complete(self) -> None:
        coverage = (REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "ACTION_COVERAGE.md").read_text(encoding="utf-8")
        classifications = ("directly bound", "radial-bound", "remappable-only", "intentionally retired")
        for name in sorted(self.table_names):
            rows = [line for line in coverage.splitlines() if line.startswith("| {} |".format(name))]
            self.assertEqual(len(rows), 1, msg=name)
            self.assertTrue(any(label in rows[0] for label in classifications), msg=rows[0])

    def test_configurations_reference_deck_iga(self) -> None:
        self.assertIn('"configurations"', self.iga_text)
        self.assertIn('"controller_neptune"', self.iga_text)
        self.assertIn('"openneoua_deck_iga.vdf"', self.iga_text)

    def test_deck_iga_groups_are_top_level(self) -> None:
        layout = (
            REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "openneoua_deck_iga.vdf"
        ).read_text(encoding="utf-8")
        self.assertIn('\t"group"', layout)
        self.assertNotRegex(
            layout,
            r'"preset"\s*\n\t\{\s*\n(?:\t\t"[^"]+"\t+"[^"]+"\s*\n)+\t\tgroup',
        )
        in_preset = False
        for line in layout.splitlines():
            if line == '\t"preset"':
                in_preset = True
            elif in_preset and line == "\t}":
                in_preset = False
            elif in_preset:
                self.assertFalse(
                    line.startswith('\t\t"group"') or line == "\t\tgroup",
                    "Steam ignores groups nested inside IGA presets",
                )


if __name__ == "__main__":
    unittest.main()
