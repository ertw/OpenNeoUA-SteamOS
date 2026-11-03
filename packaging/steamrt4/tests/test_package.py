"""The overlay follows upstream's tracked resource layout."""

from pathlib import Path
import tempfile
import unittest

from package import PackagingError, copy_tracked_assets, tracked_allowlist
from build_steamdeck import merge_overlay
from .support import RepositoryFixture


class PackageAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = RepositoryFixture()
        self.addCleanup(self.repo.cleanup)
        self.repo.write("OpenNeoUA.sh", b"#!/bin/sh\n", 0o755)
        self.repo.write("OpenNeoUA.ini", b"[OpenNeoUA]\n")
        self.repo.write("Models/3ds/Orb.3ds", b"model")
        self.repo.write("Collision/Scout.collision", b"collision")
        self.repo.write("Scripts/Startup.cfg", b"startup")
        self.repo.write("Levels/Bg/Workshop.png", b"workshop background")
        self.repo.write("src/main.cpp", b"source")
        self.repo.commit_base()

    def test_copies_current_models_and_config_but_only_tracked_assets(self) -> None:
        self.repo.write("Models/private.3ds", b"untracked")
        self.repo.write("vendor/ua.iso", b"private ISO")
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            copy_tracked_assets(self.repo.root, staging)
            files = {p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()}
            self.assertEqual(files, {
                "OpenNeoUA.sh", "OpenNeoUA.ini", "Models/3ds/Orb.3ds",
                "Collision/Scout.collision", "Scripts/Startup.cfg",
                "Levels/BG/Workshop.png",
            })
            self.assertEqual((staging / "Models/3ds/Orb.3ds").read_bytes(), b"model")
            self.assertTrue((staging / "OpenNeoUA.sh").stat().st_mode & 0o111)

    def test_workshop_background_merges_with_retail_bg_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay, assets = root / "overlay", root / "assets"
            overlay.mkdir()
            (assets / "Levels/BG").mkdir(parents=True)
            (assets / "Levels/BG/STARTUP.IFF").write_bytes(b"retail")
            copy_tracked_assets(self.repo.root, overlay)
            merge_overlay(assets, overlay)
            self.assertEqual((assets / "Levels/BG/Workshop.png").read_bytes(),
                             b"workshop background")
            self.assertEqual((assets / "Levels/BG/STARTUP.IFF").read_bytes(), b"retail")

    def test_missing_tracked_configuration_fails_before_packaging(self) -> None:
        self.repo.git("rm", "OpenNeoUA.ini")
        with self.assertRaisesRegex(PackagingError, "OpenNeoUA.ini is not tracked"):
            tracked_allowlist(self.repo.root)


if __name__ == "__main__":
    unittest.main()
