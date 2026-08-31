#!/usr/bin/env python3
"""Asset-free regressions for campaign-map mouse input after Steam menu focus."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
YW_FUNC2 = REPO_ROOT / "src" / "yw_func2.cpp"
YW_FUNCS = REPO_ROOT / "src" / "yw_funcs.cpp"
VIRTUAL_POINTER = REPO_ROOT / "src" / "system" / "virtual_pointer.cpp"
ACTION_SET_SYNC = REPO_ROOT / "src" / "system" / "action_set_sync.cpp"
STEAM_BACKEND = REPO_ROOT / "src" / "system" / "action_backend_steam.cpp"
DECK_IGA = REPO_ROOT / "packaging" / "steamrt4" / "steam_input" / "openneoua_deck_iga.vdf"


class MapMenuFocusRegressionTests(unittest.TestCase):
    def test_title_menu_focus_is_scoped_to_title_env_mode(self) -> None:
        source = YW_FUNC2.read_text(encoding="utf-8")
        pattern = re.compile(
            r"if\s*\(\s*EnvMode\s*==\s*ENVMODE_TITLE\s*\)\s*\n\s*Input::ApplyMenuFocusInput\(titel_button,\s*Input\);",
            re.MULTILINE,
        )
        self.assertRegex(
            source,
            pattern,
            "titel_button menu focus must run only on ENVMODE_TITLE so map mask picking keeps real mouse coords",
        )

    def test_campaign_map_uses_virtual_pointer(self) -> None:
        source = YW_FUNCS.read_text(encoding="utf-8")
        self.assertIn("ApplyCampaignMapVirtualPointer", source)
        self.assertIn("DrawVirtualPointer", source)

    def test_virtual_pointer_rehit_tests_clicks(self) -> None:
        source = VIRTUAL_POINTER.read_text(encoding="utf-8")
        self.assertIn("Engine.ClickCheck.CheckClick", source)
        self.assertIn("FLAG_DBL_CLICK", source)
        self.assertIn("SynthesizeClickAtCursor", source)

    def test_aim_y_is_inverted_for_vehicle_look(self) -> None:
        source = STEAM_BACKEND.read_text(encoding="utf-8")
        self.assertIn("_aimDelY = -aim.Y", source)

    def test_map_open_no_longer_forces_map_action_set(self) -> None:
        source = ACTION_SET_SYNC.read_text(encoding="utf-8")
        self.assertNotIn("ACTION_SET_MAP", source)

    def test_menu_right_trigger_clicks_at_cursor(self) -> None:
        layout = DECK_IGA.read_text(encoding="utf-8")
        self.assertIn('"name"\t\t"Menu"', layout)
        self.assertIn('game_action Menu Fire, Fire', layout)

    def test_ground_stick_click_is_brake_not_sprint(self) -> None:
        layout = DECK_IGA.read_text(encoding="utf-8")
        self.assertIn("game_action Ground Brake, Brake", layout)
        self.assertNotIn("game_action Ground Sprint, Sprint", layout)
        self.assertIn("game_action Ground GunHeight, Gun Height", layout)
        self.assertIn("game_action Ground CommandMode, Command Mode", layout)


if __name__ == "__main__":
    unittest.main()
