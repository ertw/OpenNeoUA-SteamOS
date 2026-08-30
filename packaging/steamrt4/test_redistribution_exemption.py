#!/usr/bin/env python3
"""Validate the non-Debian redistribution exemption table and staging path."""

from __future__ import annotations

import hashlib
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath

try:
    from package import (
        REDISTRIBUTABLE_SOURCE_DIR,
        REDISTRIBUTION_EXEMPTION_RECORDS,
        REDISTRIBUTION_EXEMPTIONS,
        REDISTRIBUTION_PLACEHOLDER_SHA256,
        STEAM_API_LIBRARY_NAME,
        PackagingError,
        RedistributionExemption,
        forbidden_soname,
        index_redistribution_exemptions,
        parse_args,
        redistribution_exemption,
        safe_redistribution_name,
        verify_redistribution_exemption,
        verify_redistribution_records,
    )
except ImportError:  # pragma: no cover
    from packaging.steamrt4.package import (
        REDISTRIBUTABLE_SOURCE_DIR,
        REDISTRIBUTION_EXEMPTION_RECORDS,
        REDISTRIBUTION_EXEMPTIONS,
        REDISTRIBUTION_PLACEHOLDER_SHA256,
        STEAM_API_LIBRARY_NAME,
        PackagingError,
        RedistributionExemption,
        forbidden_soname,
        index_redistribution_exemptions,
        parse_args,
        redistribution_exemption,
        safe_redistribution_name,
        verify_redistribution_exemption,
        verify_redistribution_records,
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
STEAM_API_LICENSE = REPO_ROOT / "vendor" / "steamworks-sdk" / "Readme.txt"
VENDOR_STEAM_API = (
    REPO_ROOT / "vendor" / "steamworks-sdk" / "redistributable_bin" / "linux64" / STEAM_API_LIBRARY_NAME
)
PINNED_STEAM_API_SHA256 = "eb2dd015b84177cf4f4326fe578aab375fd8931bbbd719c7492420d9777007fe"

PAYLOAD = b"\x7fELF-not-really-an-elf-but-hashable\n"
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def make_roots(parent: Path, license_relative: str) -> tuple[Path, Path]:
    source_root = parent / "srcroot"
    license_path = source_root / PurePosixPath(license_relative)
    license_path.parent.mkdir(parents=True, exist_ok=True)
    license_path.write_text("synthetic redistribution terms\n", encoding="utf-8")
    staging_root = parent / "staging"
    (staging_root / "lib").mkdir(parents=True)
    return source_root, staging_root


def make_table(
    name: str = "libexample.so",
    sha256: str = PAYLOAD_SHA256,
    license_relative: str = "third_party/EXAMPLE-LICENSE.txt",
    origin: str = "Example vendor redistributable",
):
    return index_redistribution_exemptions(
        (
            RedistributionExemption(
                name=name,
                sha256=sha256,
                license_path=license_relative,
                origin=origin,
            ),
        )
    )


class ExemptionTableTests(unittest.TestCase):
    def test_declared_records_are_well_formed(self) -> None:
        self.assertTrue(REDISTRIBUTION_EXEMPTION_RECORDS)
        for record in REDISTRIBUTION_EXEMPTION_RECORDS:
            if record.sha256 != REDISTRIBUTION_PLACEHOLDER_SHA256:
                self.assertRegex(record.sha256, r"^[0-9a-f]{64}$", msg=record.name)
            self.assertNotIn("/", record.name)
            self.assertFalse(forbidden_soname(record.name), msg=record.name)
            self.assertTrue(record.origin.strip(), msg=record.name)
            relative = PurePosixPath(record.license_path)
            self.assertFalse(relative.is_absolute(), msg=record.name)
            self.assertNotIn("..", relative.parts)
            license_path = REPO_ROOT / relative
            self.assertTrue(license_path.is_file(), msg=record.license_path)
            self.assertFalse(license_path.is_symlink(), msg=record.license_path)

    def test_table_has_no_duplicate_keys(self) -> None:
        self.assertEqual(
            len(REDISTRIBUTION_EXEMPTIONS), len(REDISTRIBUTION_EXEMPTION_RECORDS)
        )
        record = REDISTRIBUTION_EXEMPTION_RECORDS[0]
        with self.assertRaises(PackagingError):
            index_redistribution_exemptions((record, record))

    def test_table_is_immutable(self) -> None:
        with self.assertRaises(TypeError):
            REDISTRIBUTION_EXEMPTIONS["libinjected.so"] = REDISTRIBUTION_EXEMPTION_RECORDS[0]

    def test_index_rejects_non_lowercase_hex_pins(self) -> None:
        for bad in ("ABC", PAYLOAD_SHA256.upper(), "0" * 63):
            with self.assertRaises(PackagingError, msg=bad):
                make_table(sha256=bad)

    def test_index_rejects_escaping_license_paths(self) -> None:
        with self.assertRaises(PackagingError):
            make_table(license_relative="../outside/LICENSE.txt")
        with self.assertRaises(PackagingError):
            make_table(license_relative="/etc/LICENSE.txt")

    def test_steam_api_exemption_is_declared(self) -> None:
        exemption = REDISTRIBUTION_EXEMPTIONS[STEAM_API_LIBRARY_NAME]
        self.assertEqual(
            exemption.license_path,
            "vendor/steamworks-sdk/Readme.txt",
        )
        self.assertIn("Steamworks", exemption.origin)


class VendorSteamApiTests(unittest.TestCase):
    def test_vendored_sdk_license_is_present(self) -> None:
        self.assertTrue(STEAM_API_LICENSE.is_file())
        self.assertFalse(STEAM_API_LICENSE.is_symlink())
        text = STEAM_API_LICENSE.read_text(encoding="latin-1")
        self.assertIn("Valve Corporation", text)

    def test_steam_api_pin_matches_vendored_binary(self) -> None:
        if not VENDOR_STEAM_API.is_file():
            self.skipTest("vendored libsteam_api.so is not present")
        digest = hashlib.sha256(VENDOR_STEAM_API.read_bytes()).hexdigest()
        self.assertEqual(
            REDISTRIBUTION_EXEMPTIONS[STEAM_API_LIBRARY_NAME].sha256,
            digest,
        )
        self.assertEqual(digest, PINNED_STEAM_API_SHA256)


class PolicyTests(unittest.TestCase):
    def test_undeclared_library_is_rejected(self) -> None:
        with self.assertRaises(PackagingError):
            redistribution_exemption("libundeclared.so", make_table())

    def test_exemption_does_not_bypass_forbidden_soname(self) -> None:
        table = make_table(name="libc.so.6")
        with self.assertRaises(PackagingError):
            redistribution_exemption("libc.so.6", table)

    def test_forbidden_soname_is_rejected_even_when_the_pin_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            library = parent / "libc.so.6"
            library.write_bytes(PAYLOAD)
            table = make_table(name="libc.so.6")
            with self.assertRaises(PackagingError):
                verify_redistribution_exemption(
                    source_root, staging_root, "libc.so.6", library, table
                )


class VerifyExemptionTests(unittest.TestCase):
    def test_matching_digest_is_accepted_and_license_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            library = parent / "libexample.so"
            library.write_bytes(PAYLOAD)
            table = make_table()

            digest = verify_redistribution_exemption(
                source_root, staging_root, "libexample.so", library, table
            )
            self.assertEqual(digest, PAYLOAD_SHA256)

            license_dir = staging_root / "licenses" / "redistributable" / "libexample.so"
            self.assertTrue((license_dir / "LICENSE.txt").is_file())
            self.assertEqual(
                (license_dir / "LICENSE.txt").read_text(encoding="utf-8"),
                (source_root / "third_party" / "EXAMPLE-LICENSE.txt").read_text(
                    encoding="utf-8"
                ),
            )
            metadata = (license_dir / "metadata.txt").read_text(encoding="utf-8").splitlines()
            self.assertIn("Name: libexample.so", metadata)
            self.assertIn("Pinned SHA256: {}".format(PAYLOAD_SHA256), metadata)
            self.assertIn("Origin: Example vendor redistributable", metadata)
            self.assertIn("Staged libraries:", metadata)
            self.assertIn("  libexample.so", metadata)

    def test_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            library = parent / "libexample.so"
            library.write_bytes(PAYLOAD + b"tampered")
            table = make_table()

            with self.assertRaises(PackagingError) as context:
                verify_redistribution_exemption(
                    source_root, staging_root, "libexample.so", library, table
                )
            message = str(context.exception)
            self.assertIn("libexample.so", message)
            self.assertIn(PAYLOAD_SHA256, message)
            self.assertIn(hashlib.sha256(PAYLOAD + b"tampered").hexdigest(), message)
            self.assertFalse((staging_root / "licenses").exists())

    def test_placeholder_pin_is_rejected_when_the_library_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            library = parent / "libexample.so"
            library.write_bytes(PAYLOAD)
            table = make_table(sha256=REDISTRIBUTION_PLACEHOLDER_SHA256)

            with self.assertRaises(PackagingError) as context:
                verify_redistribution_exemption(
                    source_root, staging_root, "libexample.so", library, table
                )
            self.assertIn("placeholder", str(context.exception))
            self.assertFalse((staging_root / "licenses").exists())

    def test_missing_library_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            absent = parent / "does-not-exist" / "libexample.so"
            table = make_table(sha256=REDISTRIBUTION_PLACEHOLDER_SHA256)

            self.assertIsNone(
                verify_redistribution_exemption(
                    source_root, staging_root, "libexample.so", absent, table
                )
            )
            self.assertFalse((staging_root / "licenses").exists())
            self.assertEqual(list((staging_root / "lib").iterdir()), [])
            verify_redistribution_records(staging_root, {}, table)

    def test_missing_declared_license_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            (source_root / "third_party" / "EXAMPLE-LICENSE.txt").unlink()
            library = parent / "libexample.so"
            library.write_bytes(PAYLOAD)

            with self.assertRaises(PackagingError):
                verify_redistribution_exemption(
                    source_root, staging_root, "libexample.so", library, make_table()
                )

    def test_symlinked_library_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            real = parent / "real.so"
            real.write_bytes(PAYLOAD)
            library = parent / "libexample.so"
            library.symlink_to(real)

            with self.assertRaises(PackagingError):
                verify_redistribution_exemption(
                    source_root, staging_root, "libexample.so", library, make_table()
                )


class VerifyRecordsTests(unittest.TestCase):
    def stage(self, parent: Path):
        source_root, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
        library = parent / "libexample.so"
        library.write_bytes(PAYLOAD)
        table = make_table()
        digest = verify_redistribution_exemption(
            source_root, staging_root, "libexample.so", library, table
        )
        (staging_root / "lib" / "libexample.so").write_bytes(PAYLOAD)
        return staging_root, table, {"libexample.so": digest}

    def test_fully_staged_exemption_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, redistributed = self.stage(Path(directory))
            verify_redistribution_records(staging_root, redistributed, table)

    def test_missing_staged_library_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, redistributed = self.stage(Path(directory))
            (staging_root / "lib" / "libexample.so").unlink()
            with self.assertRaises(PackagingError):
                verify_redistribution_records(staging_root, redistributed, table)

    def test_tampered_staged_library_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, redistributed = self.stage(Path(directory))
            (staging_root / "lib" / "libexample.so").write_bytes(PAYLOAD + b"tampered")
            with self.assertRaises(PackagingError):
                verify_redistribution_records(staging_root, redistributed, table)

    def test_missing_staged_license_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, redistributed = self.stage(Path(directory))
            license_dir = staging_root / "licenses" / "redistributable" / "libexample.so"
            (license_dir / "LICENSE.txt").unlink()
            with self.assertRaises(PackagingError):
                verify_redistribution_records(staging_root, redistributed, table)

    def test_metadata_without_checksum_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, redistributed = self.stage(Path(directory))
            metadata = (
                staging_root / "licenses" / "redistributable" / "libexample.so" / "metadata.txt"
            )
            metadata.write_text("Name: libexample.so\n", encoding="utf-8")
            with self.assertRaises(PackagingError):
                verify_redistribution_records(staging_root, redistributed, table)

    def test_undeclared_staged_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            staging_root, table, _ = self.stage(Path(directory))
            with self.assertRaises(PackagingError):
                verify_redistribution_records(
                    staging_root, {"libghost.so": PAYLOAD_SHA256}, table
                )

    def test_placeholder_pin_cannot_be_recorded_as_staged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            _, staging_root = make_roots(parent, "third_party/EXAMPLE-LICENSE.txt")
            (staging_root / "lib" / "libexample.so").write_bytes(PAYLOAD)
            table = make_table(sha256=REDISTRIBUTION_PLACEHOLDER_SHA256)
            with self.assertRaises(PackagingError):
                verify_redistribution_records(
                    staging_root,
                    {"libexample.so": REDISTRIBUTION_PLACEHOLDER_SHA256},
                    table,
                )


class SafeNameTests(unittest.TestCase):
    def test_staged_license_directory_name_is_sanitized(self) -> None:
        self.assertEqual(safe_redistribution_name("libsteam_api.so"), "libsteam_api.so")
        self.assertEqual(safe_redistribution_name("lib/../evil.so"), "lib_.._evil.so")
        self.assertTrue(
            re.fullmatch(r"[A-Za-z0-9._+-]+", safe_redistribution_name("a b:c$d"))
        )


class ArgumentTests(unittest.TestCase):
    def test_steam_api_library_argument_defaults_to_none(self) -> None:
        args = parse_args(
            [
                "--build-dir",
                "build",
                "--staging-dir",
                "staging",
                "--output-dir",
                "out",
            ]
        )
        self.assertIsNone(args.steam_api_library)

    def test_steam_api_library_argument_is_accepted(self) -> None:
        args = parse_args(
            [
                "--build-dir",
                "build",
                "--staging-dir",
                "staging",
                "--output-dir",
                "out",
                "--steam-api-library",
                "/tmp/libsteam_api.so",
            ]
        )
        self.assertEqual(args.steam_api_library, Path("/tmp/libsteam_api.so"))

    def test_default_source_location_does_not_exist_in_tree(self) -> None:
        self.assertFalse(
            (REPO_ROOT / REDISTRIBUTABLE_SOURCE_DIR / STEAM_API_LIBRARY_NAME).exists()
        )


if __name__ == "__main__":
    unittest.main()
