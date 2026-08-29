#!/usr/bin/env python3
"""Asset-free AppRun contract tests."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from build_steamdeck import create_apprun
except ImportError:  # pragma: no cover
    from packaging.steamrt4.build_steamdeck import create_apprun


class AppRunTests(unittest.TestCase):
    def test_forwards_arguments_and_uses_custom_xdg_data_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="OpenNeoUA AppRun ") as directory:
            root = Path(directory)
            (root / "usr" / "bin").mkdir(parents=True)
            binary = root / "usr" / "bin" / "OpenNeoUA"
            binary.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TEST_CAPTURE\"\nprintf '%s\\n' \"$LD_LIBRARY_PATH\" >> \"$TEST_CAPTURE\"\n",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            apprun = root / "AppRun"
            create_apprun(apprun)
            capture = root / "captured args.txt"
            xdg = root / "xdg data"
            env = os.environ.copy()
            env.update({"APPDIR": str(root), "XDG_DATA_HOME": str(xdg), "TEST_CAPTURE": str(capture)})
            result = subprocess.run([str(apprun), "--flag", "path with spaces"], env=env, check=False)
            self.assertEqual(result.returncode, 0)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:2], ["--asset-root", str(root / "usr" / "share" / "openneoua")])
            self.assertIn("--user-dir", lines)
            self.assertEqual(lines[4:6], ["--flag", "path with spaces"])
            self.assertTrue((xdg / "OpenNeoUA").is_dir())


if __name__ == "__main__":
    unittest.main()
