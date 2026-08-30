#!/usr/bin/env python3
"""Asset-free regressions for campaign-map mouse input after Steam menu focus."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
YW_FUNC2 = REPO_ROOT / "src" / "yw_func2.cpp"
MENU_FOCUS = REPO_ROOT / "src" / "system" / "menu_focus.cpp"


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

    def test_menu_cursor_delta_preserves_mouse_when_idle(self) -> None:
        source = MENU_FOCUS.read_text(encoding="utf-8")
        self.assertIn(
            "if ( deltaX == 0.0f && deltaY == 0.0f )",
            source,
            "ApplyCursorDelta must not overwrite ClickInf.move when MenuCursor is idle",
        )
        self.assertIn(
            "if ( !_cursorInitialized )",
            source,
            "virtual menu cursor must seed from the current mouse position on first analog input",
        )


if __name__ == "__main__":
    unittest.main()
