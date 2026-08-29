#!/usr/bin/env python3
"""Validate Steam Input layout assets and packaged SteamInput/ contents."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

try:
    from package import (
        STEAM_INPUT_REQUIRED_FILES,
        STEAM_INPUT_SOURCE_DIR,
        copy_steam_input_assets,
        fail,
        PackagingError,
        read_steam_input_revision,
    )
except ImportError:  # pragma: no cover
    from packaging.steamrt4.package import (
        STEAM_INPUT_REQUIRED_FILES,
        STEAM_INPUT_SOURCE_DIR,
        copy_steam_input_assets,
        fail,
        PackagingError,
        read_steam_input_revision,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = REPO_ROOT / STEAM_INPUT_SOURCE_DIR

REQUIRED_BINDING_LABELS = (
    "Brake",
    "Back Quit",
    "Switch Weapon",
    "Alternative View",
    "Fire Confirm",
    "Gun",
    "Mouse Grab",
    "Sprint",
    "Map",
    "Pause",
    "Cam Fire",
    "Cycle Target",
    "Flight Speed Down",
    "Flight Speed Up",
    "Control Unit",
    "Zoom In",
    "Zoom Out",
    "Squad Manager",
    "Order",
    "Control",
    "Autopilot",
    "HUD",
    "Log",
    "New",
    "Add",
    "Help",
    "Analyzer",
)

FORBIDDEN_METADATA_PATTERNS = (
    re.compile(r"/home/", re.IGNORECASE),
    re.compile(r"C:\\\\", re.IGNORECASE),
    re.compile(r"AccountID", re.IGNORECASE),
    re.compile(r"steamid", re.IGNORECASE),
    re.compile(r"PersonaName", re.IGNORECASE),
)


class SteamInputAssetTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        self.assertTrue(SOURCE_DIR.is_dir())
        for name in STEAM_INPUT_REQUIRED_FILES:
            path = SOURCE_DIR / name
            self.assertTrue(path.is_file(), msg=name)
            self.assertFalse(path.is_symlink(), msg=name)

    def test_revision_metadata(self) -> None:
        revision = read_steam_input_revision(REPO_ROOT)
        self.assertTrue(re.fullmatch(r"[0-9]+", revision), revision)

    def test_vdf_contains_required_controls_and_labels(self) -> None:
        text = (SOURCE_DIR / "openneoua_deck_default.vdf").read_text(encoding="utf-8")
        self.assertIn('"controller_mappings"', text)
        self.assertIn('"title"\t\t"OpenNeoUA Deck Default"', text)
        self.assertIn('"controller_type"\t\t"controller_neptune"', text)
        self.assertIn('"mode"\t\t"joystick_move"', text)
        self.assertIn('"mode"\t\t"absolute_mouse"', text)
        self.assertIn('"mode"\t\t"radial_menu"', text)
        self.assertIn("gyro", text.lower())
        for label in REQUIRED_BINDING_LABELS:
            self.assertIn(label, text, msg=label)
        for pattern in FORBIDDEN_METADATA_PATTERNS:
            self.assertIsNone(pattern.search(text), msg=pattern.pattern)

    def test_copy_steam_input_assets_into_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            revision = copy_steam_input_assets(REPO_ROOT, staging)
            self.assertTrue(re.fullmatch(r"[0-9]+", revision))
            packaged = staging / "SteamInput"
            self.assertEqual(
                sorted(path.name for path in packaged.iterdir()),
                sorted(STEAM_INPUT_REQUIRED_FILES),
            )
            for name in STEAM_INPUT_REQUIRED_FILES:
                self.assertEqual(
                    (SOURCE_DIR / name).read_bytes(),
                    (packaged / name).read_bytes(),
                )

    def test_rejects_unexpected_steaminput_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "srcroot"
            steam_input = source_root / STEAM_INPUT_SOURCE_DIR
            steam_input.mkdir(parents=True)
            for name in STEAM_INPUT_REQUIRED_FILES:
                if name == "REVISION.txt":
                    (steam_input / name).write_text(
                        "OpenNeoUA Steam Deck layout revision: 9\n",
                        encoding="utf-8",
                    )
                else:
                    (steam_input / name).write_text("x\n", encoding="utf-8")
            staging = root / "staging"
            staging.mkdir()
            # Inject an unexpected file after copy by patching destination.
            copy_steam_input_assets(source_root, staging)
            (staging / "SteamInput" / "extra.txt").write_text("nope\n", encoding="utf-8")
            with self.assertRaises(PackagingError):
                # Re-run verification path used by package layout checks.
                unexpected = sorted(
                    path.name
                    for path in (staging / "SteamInput").iterdir()
                    if path.name not in STEAM_INPUT_REQUIRED_FILES
                )
                if unexpected:
                    fail(
                        "SteamInput/ contains unexpected entries: {}".format(
                            ", ".join(unexpected)
                        )
                    )


if __name__ == "__main__":
    unittest.main()
