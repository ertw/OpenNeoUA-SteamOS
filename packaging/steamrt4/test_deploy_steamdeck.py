#!/usr/bin/env python3
"""Tests for the repeatable Steam Deck development deployer."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    import deploy_steamdeck as deployer
except ImportError:  # pragma: no cover
    from packaging.steamrt4 import deploy_steamdeck as deployer


class DeploySteamDeckTests(unittest.TestCase):
    def test_latest_appimage_uses_mtime_then_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.AppImage"
            new = root / "new.AppImage"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            old.touch()
            new.touch()
            old.chmod(0o755)
            new.chmod(0o755)
            old_mtime = old.stat().st_mtime_ns
            new_mtime = old_mtime + 10_000_000
            import os
            os.utime(new, ns=(new_mtime, new_mtime))
            self.assertEqual(deployer.find_latest_appimage(root), new)

    def test_remote_destination_rejects_escape_and_absolute_paths(self) -> None:
        for value in ("../escape.AppImage", "/tmp/escape.AppImage", "", "bin/x;touch-pwned"):
            with self.subTest(value=value), self.assertRaises(deployer.DeployError):
                deployer.remote_path_expression(value)

    def test_remote_install_verifies_before_atomic_rename(self) -> None:
        script = deployer.remote_script("Applications/OpenNeoUA-dev.AppImage", "abc123")
        self.assertLess(script.index("sha256sum"), script.index("mv -f"))
        self.assertIn("$HOME/Applications/OpenNeoUA-dev.AppImage.incoming", script)
        self.assertIn("$HOME/.local/share/applications/openneoua-dev.desktop", script)
        self.assertIn("--appimage-extract OpenNeoUA.png", script)
        self.assertIn("$HOME/.local/share/icons/hicolor/256x256/apps/openneoua.png", script)
        self.assertIn("Name=OpenNeoUA (Development)", script)
        self.assertIn("Icon=openneoua", script)
        self.assertNotIn("Icon=applications-games", script)
        self.assertIn("Exec=%s", script)
        self.assertNotIn("appid", script.lower())

    def test_scp_deploy_uses_stable_incoming_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "build.AppImage"
            app.write_bytes(b"appimage")
            app.chmod(0o755)
            commands: list[list[str]] = []
            with mock.patch.object(deployer, "run", side_effect=lambda command, **_kw: commands.append(command)):
                deployer.deploy(app, host="steamdeck", destination="Applications/OpenNeoUA-dev.AppImage")
            self.assertEqual(commands[0][0:2], ["ssh", "steamdeck"])
            self.assertIn("mkdir -p", commands[0][2])
            self.assertEqual(commands[1][0], "scp")
            self.assertEqual(commands[1][-1], "steamdeck:Applications/OpenNeoUA-dev.AppImage.incoming")
            self.assertEqual(commands[-1][:2], ["ssh", "steamdeck"])
            self.assertIn("openneoua-dev.desktop", commands[-1][2])

    def test_rsync_deploy_seeds_the_incoming_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "build.AppImage"
            app.write_bytes(b"appimage")
            commands: list[list[str]] = []
            with (mock.patch.object(deployer, "run", side_effect=lambda command, **_kw: commands.append(command)),
                  mock.patch.object(deployer.shutil, "which", return_value="/usr/bin/rsync")):
                deployer.deploy(app, use_rsync=True)
            self.assertTrue(any(command[0] == "rsync" for command in commands))
            self.assertTrue(any("cp -f" in command[-1] for command in commands if command[0] == "ssh"))


if __name__ == "__main__":
    unittest.main()
