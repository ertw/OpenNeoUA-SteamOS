#!/usr/bin/env python3
"""Asset-free policy tests for the private Steam Deck packager."""

from __future__ import annotations

import tempfile
from pathlib import Path
import stat
import unittest

try:
    from build_steamdeck import (
        ArchiveEntry,
        AssetBuildError,
        REQUIRED_MENU_ASSETS,
        extract_base_payload,
        select_base_game_entries,
        validate_iso_listing,
        validate_menu_assets,
        write_sha256_manifest,
        verify_sha256_manifest,
    )
except ImportError:  # pragma: no cover - package execution fallback
    from packaging.steamrt4.build_steamdeck import (
        ArchiveEntry,
        AssetBuildError,
        REQUIRED_MENU_ASSETS,
        extract_base_payload,
        select_base_game_entries,
        validate_iso_listing,
        validate_menu_assets,
        write_sha256_manifest,
        verify_sha256_manifest,
    )


def base_listing() -> list[ArchiveEntry]:
    entries = [
        ArchiveEntry("GAME/DATA/SET46/FONTPAGE.ILB"),
        ArchiveEntry("GAME/DATA/SET46/GADGSHLL.ILB"),
        ArchiveEntry("GAME/DATA/SET46/GADGSHLO.ILB"),
        ArchiveEntry("GAME/DATA/SET46/ICONPAGE.ILB"),
        ArchiveEntry("GAME/DATA/SET46/MB.ILB"),
        ArchiveEntry("GAME/ENV/STARTUP.DEF"),
        ArchiveEntry("GAME/LEVELS/BG/STARTUP.IFF"),
        ArchiveEntry("GAME/LEVELS/BG/SETTINGS.IFF"),
        ArchiveEntry("GAME/LOCALE/ENGLISH.LNG"),
        ArchiveEntry("GAME/SAVE/.keep"),
        ArchiveEntry("GAME/NUCLEUS.INI"),
    ]
    return entries


class SteamDeckPolicyTests(unittest.TestCase):
    def test_selects_only_base_game_and_canonicalizes_roots(self) -> None:
        selected = select_base_game_entries(
            base_listing()
            + [
                ArchiveEntry("GAME/METROPOLIS DAWN/LEVELS/EXTRA.IFF"),
                ArchiveEntry("GAME/DUNGEON.TTF"),
                ArchiveEntry("GAME/MSS32.DLL"),
                ArchiveEntry("GAME/UA.EXE"),
            ]
        )
        paths = {canonical for _source, canonical in selected.files}
        self.assertIn("Data/SET46/FONTPAGE.ILB", paths)
        self.assertIn("Nucleus.ini", paths)
        self.assertNotIn("GAME/METROPOLIS DAWN/LEVELS/EXTRA.IFF", paths)
        self.assertNotIn("DUNGEON.TTF", paths)
        self.assertNotIn("MSS32.DLL", paths)
        self.assertNotIn("UA.EXE", paths)
        self.assertEqual(selected.excluded_expansion, ("GAME/METROPOLIS DAWN/LEVELS/EXTRA.IFF",))

    def test_rejects_traversal_links_and_case_collisions(self) -> None:
        with self.assertRaises(AssetBuildError):
            validate_iso_listing([ArchiveEntry("GAME/DATA/../escape")])
        with self.assertRaises(AssetBuildError):
            validate_iso_listing([ArchiveEntry("GAME/DATA/A"), ArchiveEntry("game/data/a")])
        with self.assertRaises(AssetBuildError):
            validate_iso_listing([ArchiveEntry("GAME/DATA/LINK", "link", "TARGET")])
        with self.assertRaises(AssetBuildError):
            select_base_game_entries(base_listing() + [ArchiveEntry("GAME/UNEXPECTED", "dir")])

    def test_rejects_unexpected_member_root_without_directory_record(self) -> None:
        # ISO9660 listings are allowed to omit directory records.  The member
        # itself must still make an unknown immediate GAME root fatal.
        with self.assertRaises(AssetBuildError):
            select_base_game_entries(base_listing() + [ArchiveEntry("GAME/UNEXPECTED/payload.dat")])

    def test_extracts_only_validated_members_and_never_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            iso = root / "Urban Assault.iso"
            iso.write_bytes(b"test archive")
            fake_7z = root / "fake-7z.py"
            fake_7z.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "if any('*' in item for item in args):\n"
                "    raise SystemExit('wildcard extraction is forbidden')\n"
                "output = pathlib.Path(next(item[2:] for item in args if item.startswith('-o')))\n"
                "members = pathlib.Path(next(item[3:] for item in args if item.startswith('-i@'))).read_text().splitlines()\n"
                "for member in members:\n"
                "    target = output.joinpath(*member.split('/'))\n"
                "    target.parent.mkdir(parents=True, exist_ok=True)\n"
                "    target.write_bytes(b'selected')\n",
                encoding="utf-8",
            )
            fake_7z.chmod(fake_7z.stat().st_mode | stat.S_IXUSR)
            listing = base_listing() + [
                ArchiveEntry("GAME/METROPOLIS DAWN/LEVELS/EXTRA.IFF"),
                ArchiveEntry("GAME/METROPOLIS DAWN/INSTALL.EXE"),
            ]
            destination = root / "base"
            selection = extract_base_payload(iso, destination, seven_zip=str(fake_7z), listing=listing)
            self.assertIn("Levels/BG/STARTUP.IFF", {canonical for _source, canonical in selection.files})
            self.assertTrue((destination / "Levels/BG/STARTUP.IFF").is_file())
            self.assertFalse((destination / "METROPOLIS DAWN").exists())
            self.assertFalse(any("EXTRA.IFF" in path.name for path in destination.rglob("*")))

    def test_menu_asset_validation_and_complete_manifest(self) -> None:
        validate_menu_assets(REQUIRED_MENU_ASSETS)
        with self.assertRaises(AssetBuildError):
            validate_menu_assets(REQUIRED_MENU_ASSETS[:-1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Data").mkdir()
            (root / "Data" / "x y").write_bytes("ü".encode("utf-8"))
            (root / "Nucleus.ini").write_text("[x]\n", encoding="utf-8")
            manifest = write_sha256_manifest(root)
            verify_sha256_manifest(root, manifest)
            (root / "Data" / "x y").write_bytes(b"tampered")
            with self.assertRaises(AssetBuildError):
                verify_sha256_manifest(root, manifest)

    def test_overlay_steam_input_directory_is_copied_into_asset_root(self) -> None:
        # Private AppImage assembly copies every overlay top-level directory
        # except bin/lib/launcher/manifest into usr/share/openneoua.  SteamInput
        # must therefore remain a regular package top-level directory.
        from pathlib import Path as _Path
        try:
            from package import PACKAGE_TOP_LEVEL, STEAM_INPUT_REQUIRED_FILES
        except ImportError:  # pragma: no cover
            from packaging.steamrt4.package import (
                PACKAGE_TOP_LEVEL,
                STEAM_INPUT_REQUIRED_FILES,
            )
        self.assertIn("SteamInput", PACKAGE_TOP_LEVEL)
        for name in STEAM_INPUT_REQUIRED_FILES:
            self.assertTrue(
                (
                    _Path(__file__).resolve().parent / "steam_input" / name
                ).is_file(),
                msg=name,
            )

    def test_appdir_payload_copies_steam_appid_next_to_binary(self) -> None:
        try:
            from build_steamdeck import _copy_overlay_payload
        except ImportError:  # pragma: no cover
            from packaging.steamrt4.build_steamdeck import _copy_overlay_payload

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = root / "overlay"
            (overlay / "bin").mkdir(parents=True)
            (overlay / "bin" / "OpenNeoUA").write_bytes(b"\x7fELF")
            (overlay / "bin" / "steam_appid.txt").write_text("480\n", encoding="utf-8")
            (overlay / "SteamInput").mkdir()
            (overlay / "SteamInput" / "game_actions_480.vdf").write_text("actions\n", encoding="utf-8")

            appdir = root / "AppDir"
            asset_root = appdir / "usr" / "share" / "openneoua"
            _copy_overlay_payload(overlay, appdir, asset_root)

            self.assertTrue((appdir / "usr" / "bin" / "OpenNeoUA").is_file())
            self.assertEqual(
                (appdir / "usr" / "bin" / "steam_appid.txt").read_text(encoding="utf-8"),
                "480\n",
            )
            self.assertTrue(
                (asset_root / "SteamInput" / "game_actions_480.vdf").is_file()
            )


if __name__ == "__main__":
    unittest.main()
