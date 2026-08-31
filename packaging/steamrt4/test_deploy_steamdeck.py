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
        script = deployer.remote_script(".local/bin/OpenNeoUA-dev.AppImage", "abc123", True)
        self.assertLess(script.index("sha256sum"), script.index("mv -f"))
        self.assertIn("--install-steam-spacewar", script)
        self.assertIn("--input-debug", script)
        self.assertIn("$HOME/.local/bin/OpenNeoUA-dev.AppImage.incoming", script)

    def test_scp_deploy_uses_stable_incoming_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "build.AppImage"
            app.write_bytes(b"appimage")
            app.chmod(0o755)
            commands: list[list[str]] = []
            with mock.patch.object(deployer, "run", side_effect=lambda command, **_kw: commands.append(command)):
                deployer.deploy(app, host="steamdeck", destination=".local/bin/OpenNeoUA-dev.AppImage")
            self.assertEqual(commands[0][0:2], ["ssh", "steamdeck"])
            self.assertIn("pgrep -x steam", commands[0][2])
            self.assertEqual(commands[2][0], "scp")
            self.assertEqual(commands[2][-1], "steamdeck:.local/bin/OpenNeoUA-dev.AppImage.incoming")
            self.assertEqual(commands[-1][:2], ["ssh", "steamdeck"])
            self.assertIn("--install-steam-spacewar", commands[-1][2])

    def test_spacewar_configuration_can_be_explicitly_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "build.AppImage"
            app.write_bytes(b"appimage")
            commands: list[list[str]] = []
            with mock.patch.object(deployer, "run", side_effect=lambda command, **_kw: commands.append(command)):
                deployer.deploy(app, configure_spacewar=False)
            self.assertNotIn("--install-steam-spacewar", commands[-1][2])

    def test_running_steam_failure_happens_before_any_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "build.AppImage"
            app.write_bytes(b"appimage")
            app.chmod(0o755)
            commands: list[list[str]] = []

            def reject_first(command: list[str], **_kw: object) -> None:
                commands.append(command)
                raise deployer.DeployError("Steam is running")

            with mock.patch.object(deployer, "run", side_effect=reject_first):
                with self.assertRaisesRegex(deployer.DeployError, "Steam is running"):
                    deployer.deploy(app)
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][0], "ssh")


if __name__ == "__main__":
    unittest.main()
