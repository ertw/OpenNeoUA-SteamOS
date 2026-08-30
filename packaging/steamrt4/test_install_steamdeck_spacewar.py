#!/usr/bin/env python3
"""Tests for the Spacewar (480) Launch Options installer."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import textwrap
import unittest

try:
    from install_steamdeck_spacewar import (
        InstallError,
        build_launch_options,
        install,
        parse_vdf,
        patch_localconfig,
        serialize_vdf,
        set_spacewar_launch_options,
    )
except ImportError:  # pragma: no cover
    from packaging.steamrt4.install_steamdeck_spacewar import (
        InstallError,
        build_launch_options,
        install,
        parse_vdf,
        patch_localconfig,
        serialize_vdf,
        set_spacewar_launch_options,
    )


MINIMAL_LOCALCONFIG = textwrap.dedent(
    """\
    "UserLocalConfigStore"
    {
    \t"Software"
    \t{
    \t\t"Valve"
    \t\t{
    \t\t\t"Steam"
    \t\t\t{
    \t\t\t\t"apps"
    \t\t\t\t{
    \t\t\t\t\t"730"
    \t\t\t\t\t{
    \t\t\t\t\t\t"LaunchOptions"\t\t"-novid"
    \t\t\t\t\t}
    \t\t\t\t}
    \t\t\t}
    \t\t}
    \t}
    }
    """
)

EXISTING_480_LOCALCONFIG = textwrap.dedent(
    """\
    "UserLocalConfigStore"
    {
    \t"Software"
    \t{
    \t\t"Valve"
    \t\t{
    \t\t\t"Steam"
    \t\t\t{
    \t\t\t\t"apps"
    \t\t\t\t{
    \t\t\t\t\t"480"
    \t\t\t\t\t{
    \t\t\t\t\t\t"LaunchOptions"\t\t"old-payload # %command%"
    \t\t\t\t\t\t"CloudEnabled"\t\t"0"
    \t\t\t\t\t}
    \t\t\t\t}
    \t\t\t}
    \t\t}
    \t}
    }
    """
)


class SpacewarInstallerTests(unittest.TestCase):
    def test_build_launch_options_quotes_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA spacewar ") as directory:
            payload = Path(directory) / "OpenNeoUA with spaces.AppImage"
            payload.write_text("#!/bin/sh\n", encoding="utf-8")
            payload.chmod(0o755)
            options = build_launch_options(payload)
            self.assertTrue(options.startswith('"'))
            self.assertTrue(options.endswith(' # %command%'))
            self.assertIn("OpenNeoUA with spaces.AppImage", options)

    def test_patch_creates_480_block_when_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA spacewar ") as directory:
            config = Path(directory) / "localconfig.vdf"
            config.write_text(MINIMAL_LOCALCONFIG, encoding="utf-8")
            payload = Path(directory) / "OpenNeoUA.AppImage"
            payload.write_text("#!/bin/sh\n", encoding="utf-8")
            payload.chmod(0o755)
            options = build_launch_options(payload)
            patch_localconfig(config, options)
            data = parse_vdf(config.read_text(encoding="utf-8"))
            apps = data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
            self.assertEqual(apps["480"]["LaunchOptions"], options)
            self.assertEqual(apps["730"]["LaunchOptions"], "-novid")

    def test_patch_replaces_existing_480_launch_options(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA spacewar ") as directory:
            config = Path(directory) / "localconfig.vdf"
            config.write_text(EXISTING_480_LOCALCONFIG, encoding="utf-8")
            payload = Path(directory) / "OpenNeoUA.AppImage"
            payload.write_text("#!/bin/sh\n", encoding="utf-8")
            payload.chmod(0o755)
            options = build_launch_options(payload)
            patch_localconfig(config, options)
            data = parse_vdf(config.read_text(encoding="utf-8"))
            app = data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["480"]
            self.assertEqual(app["LaunchOptions"], options)
            self.assertEqual(app["CloudEnabled"], "0")

    def test_install_refuses_when_steam_running(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA spacewar ") as directory:
            home = Path(directory)
            steam = home / ".steam" / "steam"
            userdata = steam / "userdata" / "123456" / "config"
            userdata.mkdir(parents=True)
            (userdata / "localconfig.vdf").write_text(MINIMAL_LOCALCONFIG, encoding="utf-8")
            payload = home / "OpenNeoUA.AppImage"
            payload.write_text("#!/bin/sh\n", encoding="utf-8")
            payload.chmod(0o755)
            with self.assertRaises(InstallError) as raised:
                install(payload, home=home, force_steam_running=True)
            self.assertIn("Steam appears to be running", str(raised.exception))

    def test_install_patches_most_recent_localconfig(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA spacewar ") as directory:
            home = Path(directory)
            steam = home / ".local" / "share" / "Steam"
            older = steam / "userdata" / "111" / "config"
            newer = steam / "userdata" / "222" / "config"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            older_config = older / "localconfig.vdf"
            newer_config = newer / "localconfig.vdf"
            older_config.write_text(MINIMAL_LOCALCONFIG, encoding="utf-8")
            newer_config.write_text(MINIMAL_LOCALCONFIG, encoding="utf-8")
            # Ensure deterministic mtime ordering.
            os.utime(older_config, (1_700_000_000, 1_700_000_000))
            os.utime(newer_config, (1_800_000_000, 1_800_000_000))

            payload = home / "OpenNeoUA.sh"
            payload.write_text("#!/bin/sh\n", encoding="utf-8")
            payload.chmod(0o755)

            steam_root, config_path, account_id = install(
                payload, home=home, force_steam_running=False
            )
            self.assertEqual(steam_root, steam.resolve())
            self.assertEqual(account_id, "222")
            self.assertEqual(config_path, newer_config.resolve())
            data = parse_vdf(newer_config.read_text(encoding="utf-8"))
            options = data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["480"][
                "LaunchOptions"
            ]
            self.assertEqual(options, build_launch_options(payload))
            # Older account must remain untouched.
            older_data = parse_vdf(older_config.read_text(encoding="utf-8"))
            older_apps = older_data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
            self.assertNotIn("480", older_apps)

    def test_round_trip_preserves_nested_structure(self) -> None:
        data = parse_vdf(MINIMAL_LOCALCONFIG)
        set_spacewar_launch_options(data, '" /tmp/x " # %command%')
        again = parse_vdf(serialize_vdf(data))
        self.assertEqual(
            again["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["480"][
                "LaunchOptions"
            ],
            '" /tmp/x " # %command%',
        )


if __name__ == "__main__":
    unittest.main()
