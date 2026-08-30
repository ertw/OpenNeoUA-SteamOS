#!/usr/bin/env python3
"""Asset-free regressions for the menu smoke-test sandbox policy."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

try:
    from test_game_menu import (
        SmokeTestError,
        _refresh_image_command,
        assert_no_external_writes,
        snapshot_tree,
    )
except ImportError:  # pragma: no cover - package execution fallback
    from packaging.steamrt4.test_game_menu import (
        SmokeTestError,
        _refresh_image_command,
        assert_no_external_writes,
        snapshot_tree,
    )


class GameMenuPolicyTests(unittest.TestCase):
    def test_payload_mutation_is_not_excluded_from_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            payload = work / "extract" / "squashfs-root"
            payload.mkdir(parents=True)
            asset = payload / "usr" / "share" / "openneoua" / "Data.bin"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"before")
            before = snapshot_tree(work)
            asset.write_bytes(b"after")
            after = snapshot_tree(work)
            with self.assertRaises(SmokeTestError):
                assert_no_external_writes(before, after)

    def test_refresh_command_uses_sanitized_context_and_pull(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            dockerfile = snapshot / "packaging" / "steamrt4" / "Dockerfile.smoketest"
            dockerfile.parent.mkdir(parents=True)
            dockerfile.write_text("FROM scratch\n", encoding="utf-8")
            command = _refresh_image_command(snapshot)
            self.assertEqual(command[-1], str(snapshot))
            self.assertIn("--pull", command)
            self.assertNotIn("UA-Complete", " ".join(command))
            self.assertNotIn("vendor/ua.iso", " ".join(command))
            (snapshot / "vendor" / "ua.iso").parent.mkdir(parents=True)
            (snapshot / "vendor" / "ua.iso").write_bytes(b"iso")
            with self.assertRaises(SmokeTestError):
                _refresh_image_command(snapshot)


if __name__ == "__main__":
    unittest.main()
