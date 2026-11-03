"""Check the rendered smoke-test contract without requiring original game data."""

from pathlib import Path
import tempfile
import unittest

from smoke_test import (
    HEIGHT,
    WIDTH,
    SmokeTestError,
    _find_screenshots,
    parse_ppm,
    validate_screenshots,
    validate_smoke_report,
)


class SmokeTestTests(unittest.TestCase):
    def test_current_menu_flow_and_clean_shutdown(self) -> None:
        report = {
            "version": 1,
            "milestones": [
                {"mode": "ENVMODE_TITLE"},
                {"mode": "ENVMODE_SETTINGS"},
                {"mode": "ENVMODE_TITLE"},
            ],
            "final_mode": "ENVMODE_TITLE",
            "clean_teardown": True,
            "resolution": [WIDTH, HEIGHT],
            "asset_provenance": {"iso_sha256": "a" * 64},
        }
        validate_smoke_report(report)
        for field, value in (
            ("clean_teardown", False),
            ("milestones", [{"mode": "ENVMODE_TITLE"}]),
            ("final_mode", "ENVMODE_SETTINGS"),
            ("asset_provenance", {}),
        ):
            with self.subTest(field=field), self.assertRaises(SmokeTestError):
                validate_smoke_report({**report, field: value})

    def test_ppm_preserves_whitespace_valued_pixels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pixel.ppm"
            for first in (9, 10, 13, 32):
                with self.subTest(first=first):
                    pixels = bytes((first, 0, 255))
                    path.write_bytes(b"P6\n# screenshot\n1 1\n255\n" + pixels)
                    self.assertEqual(parse_ppm(path), (1, 1, pixels))
            path.write_bytes(b"P6\n1 1\n255\n\x00")
            with self.assertRaises(SmokeTestError):
                parse_ppm(path)

    def test_current_screenshots_must_include_a_distinct_options_screen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = f"P6\n{WIDTH} {HEIGHT}\n255\n".encode("ascii")
            title = bytes((0, 100, 255)) * (WIDTH * HEIGHT)
            options = bytes((32, 200, 50)) * (WIDTH * HEIGHT)
            for name, pixels in (("title-before", title), ("options", options), ("title-after", title)):
                (root / f"menu-{name}0000.ppm").write_bytes(header + pixels)
            screenshots = _find_screenshots(root)
            self.assertEqual(set(screenshots), {"title-before", "options", "title-after"})
            validate_screenshots(screenshots)
            screenshots["options"].write_bytes(header + title)
            with self.assertRaisesRegex(SmokeTestError, "identical"):
                validate_screenshots(screenshots)
            screenshots["options"].write_bytes(header + bytes(WIDTH * HEIGHT * 3))
            with self.assertRaisesRegex(SmokeTestError, "blank"):
                validate_screenshots(screenshots)
            screenshots["options"].unlink()
            with self.assertRaises(SmokeTestError):
                _find_screenshots(root)


if __name__ == "__main__":
    unittest.main()
