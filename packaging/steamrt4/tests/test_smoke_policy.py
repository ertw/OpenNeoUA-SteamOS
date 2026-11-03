#!/usr/bin/env python3
"""Asset-free regressions for the menu smoke-test sandbox policy."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from build_smoketest_image import image_command
from smoke_test import (
    SmokeTestError,
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
            command = image_command(snapshot, pull=True)
            self.assertEqual(command[-1], str(snapshot))
            self.assertIn("--pull", command)
            self.assertNotIn("UA-Complete", " ".join(command))
            self.assertNotIn("vendor/ua.iso", " ".join(command))
            (snapshot / "vendor" / "ua.iso").parent.mkdir(parents=True)
            (snapshot / "vendor" / "ua.iso").write_bytes(b"iso")
            with self.assertRaises(ValueError):
                image_command(snapshot, pull=True)


if __name__ == "__main__":
    unittest.main()
