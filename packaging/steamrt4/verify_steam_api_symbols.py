#!/usr/bin/env python3
"""Verify vendored libsteam_api.so exports the flat symbols OpenNeoUA dlopen()s."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STEAM_API = (
    REPO_ROOT
    / "vendor"
    / "steamworks-sdk"
    / "redistributable_bin"
    / "linux64"
    / "libsteam_api.so"
)

REQUIRED_SYMBOLS = (
    "SteamInternal_SteamAPI_Init",
    "SteamAPI_RunCallbacks",
    "SteamAPI_Shutdown",
    "SteamAPI_SteamInput_v007",
    "SteamAPI_ISteamInput_Init",
    "SteamAPI_ISteamInput_Shutdown",
    "SteamAPI_ISteamInput_RunFrame",
    "SteamAPI_ISteamInput_GetConnectedControllers",
    "SteamAPI_ISteamInput_GetActionSetHandle",
    "SteamAPI_ISteamInput_ActivateActionSet",
    "SteamAPI_ISteamInput_GetDigitalActionHandle",
    "SteamAPI_ISteamInput_GetDigitalActionData",
    "SteamAPI_ISteamInput_GetAnalogActionHandle",
    "SteamAPI_ISteamInput_GetAnalogActionData",
)

OPTIONAL_SYMBOLS = (
    "SteamAPI_ISteamInput_SetInputActionManifestFilePath",
    "SteamAPI_ISteamInput_GetCurrentActionSet",
    "SteamAPI_ISteamInput_GetDigitalActionOrigins",
    "SteamAPI_ISteamInput_GetAnalogActionOrigins",
    "SteamAPI_ISteamInput_GetGlyphPNGForActionOrigin",
    "SteamAPI_ISteamInput_ShowBindingPanel",
    "SteamAPI_SteamUtils_v011",
    "SteamAPI_ISteamUtils_ShowGamepadTextInput",
)


def exported_symbols(library: Path) -> set[str]:
    output = subprocess.check_output(
        ["nm", "-D", "--defined-only", str(library)],
        text=True,
    )
    names: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in {"T", "W"}:
            names.add(parts[2])
    return names


class SteamApiSymbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not STEAM_API.is_file():
            raise unittest.SkipTest("vendored libsteam_api.so is not present")
        cls.symbols = exported_symbols(STEAM_API)

    def test_required_symbols_are_exported(self) -> None:
        missing = [name for name in REQUIRED_SYMBOLS if name not in self.symbols]
        self.assertEqual(missing, [])

    def test_optional_symbols_are_exported(self) -> None:
        missing = [name for name in OPTIONAL_SYMBOLS if name not in self.symbols]
        self.assertEqual(
            missing,
            [],
            "optional Steam Input / Utils symbols missing from vendored SDK",
        )


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SteamApiSymbolTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
