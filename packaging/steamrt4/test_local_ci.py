#!/usr/bin/env python3
"""Focused regression tests for the sanitized local SteamRT4 CI snapshot."""

from __future__ import annotations

import os
from pathlib import Path
import hashlib
import shutil
import stat
import subprocess
import tempfile
import unittest

import local_ci


class RepositoryFixture:
    def __init__(self) -> None:
        self.parent = Path(tempfile.mkdtemp(prefix="OpenNeoUA local CI test "))
        self.root = self.parent / "repository"
        self.root.mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.name", "Local CI Test")
        self.git("config", "user.email", "local-ci-test@openneoua.invalid")

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        return result.stdout.strip()

    def write(self, relative: str, data: bytes, mode: int = 0o644) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def commit_base(self) -> str:
        self.git("add", "--all")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": "1700000000 +0000",
                "GIT_COMMITTER_DATE": "1700000000 +0000",
            }
        )
        result = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--quiet", "-m", "base"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        return self.git("rev-parse", "HEAD")

    def cleanup(self) -> None:
        shutil.rmtree(self.parent)


class LocalCISnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = RepositoryFixture()
        self.snapshot_parents: list[Path] = []

    def tearDown(self) -> None:
        for parent in self.snapshot_parents:
            shutil.rmtree(parent, ignore_errors=True)
        self.fixture.cleanup()

    def snapshot(self, capture: local_ci.SourceCapture) -> local_ci.Snapshot:
        parent = Path(tempfile.mkdtemp(prefix="OpenNeoUA local CI snapshot test "))
        self.snapshot_parents.append(parent)
        return local_ci.create_snapshot(self.fixture.root, capture, parent / "source")

    def seed_development_files(self) -> str:
        self.fixture.write(".gitignore", b"ignored-secret.bin\n")
        self.fixture.write("src/tracked.bin", b"before\x00binary\n")
        self.fixture.write("src/rename me.txt", b"rename\n")
        self.fixture.write("src/delete.txt", b"delete\n")
        self.fixture.write("src/mode.sh", b"#!/bin/sh\n", 0o644)
        return self.fixture.commit_base()

    def test_clean_snapshot_keeps_real_head(self) -> None:
        base = self.seed_development_files()
        capture = local_ci.capture_source(self.fixture.root)
        snapshot = self.snapshot(capture)
        self.assertFalse(capture.dirty)
        self.assertEqual(snapshot.commit, base)
        self.assertEqual(snapshot.artifact_identifier, base[:7])

    def test_dirty_snapshot_is_deterministic_and_preserves_full_git_delta(self) -> None:
        base = self.seed_development_files()
        self.fixture.write("src/tracked.bin", b"after\x00binary\xff\n")
        self.fixture.git("mv", "src/rename me.txt", "src/renamed ü.txt")
        (self.fixture.root / "src/delete.txt").unlink()
        (self.fixture.root / "src/mode.sh").chmod(0o755)
        self.fixture.write("Database/staged payload.dat", b"intentional payload\n")
        self.fixture.git("add", "Database/staged payload.dat")
        newline_path = "src/untracked unicode ü and newline\nfile.cpp"
        self.fixture.write(newline_path, b"allowed development file\n")

        capture = local_ci.capture_source(self.fixture.root)
        source_status = self.fixture.git("status", "--porcelain=v2", "--untracked-files=all")
        first = self.snapshot(capture)
        second = self.snapshot(capture)
        self.assertEqual(
            self.fixture.git("status", "--porcelain=v2", "--untracked-files=all"),
            source_status,
        )
        self.assertTrue(capture.dirty)
        self.assertEqual(first.commit, second.commit)
        self.assertEqual(
            first.artifact_identifier,
            "{}-dirty-{}".format(base[:7], first.commit[:7]),
        )
        self.assertEqual((first.path / "src/tracked.bin").read_bytes(), b"after\x00binary\xff\n")
        self.assertFalse((first.path / "src/rename me.txt").exists())
        self.assertEqual((first.path / "src/renamed ü.txt").read_bytes(), b"rename\n")
        self.assertFalse((first.path / "src/delete.txt").exists())
        self.assertTrue((first.path / "src/mode.sh").stat().st_mode & stat.S_IXUSR)
        self.assertEqual(
            (first.path / "Database/staged payload.dat").read_bytes(),
            b"intentional payload\n",
        )
        self.assertEqual((first.path / newline_path).read_bytes(), b"allowed development file\n")
        parents = subprocess.check_output(
            ["git", "-C", str(first.path), "show", "-s", "--format=%P", first.commit],
            text=True,
        ).strip().split()
        self.assertEqual(parents, [base])

    def test_ignored_file_is_not_captured(self) -> None:
        self.seed_development_files()
        self.fixture.write("ignored-secret.bin", b"proprietary\n")
        capture = local_ci.capture_source(self.fixture.root)
        self.assertFalse(capture.dirty)
        snapshot = self.snapshot(capture)
        self.assertFalse((snapshot.path / "ignored-secret.bin").exists())

    def test_untracked_game_payload_is_rejected_until_staged(self) -> None:
        self.seed_development_files()
        self.fixture.write("Res/new payload.dat", b"payload\n")
        with self.assertRaisesRegex(local_ci.LocalCIError, "must be staged"):
            local_ci.capture_source(self.fixture.root)
        self.fixture.git("add", "Res/new payload.dat")
        capture = local_ci.capture_source(self.fixture.root)
        snapshot = self.snapshot(capture)
        self.assertEqual((snapshot.path / "Res/new payload.dat").read_bytes(), b"payload\n")

    def test_untracked_file_outside_allowlist_is_rejected(self) -> None:
        self.seed_development_files()
        self.fixture.write("notes.txt", b"not allowed\n")
        with self.assertRaisesRegex(local_ci.LocalCIError, "outside the local CI allowlist"):
            local_ci.capture_source(self.fixture.root)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_tracked_symlink_is_rejected(self) -> None:
        self.fixture.write("src/target.txt", b"target\n")
        (self.fixture.root / "src/link.txt").symlink_to("target.txt")
        self.fixture.commit_base()
        with self.assertRaisesRegex(local_ci.LocalCIError, "symlinks are forbidden"):
            local_ci.capture_source(self.fixture.root)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "special files are unavailable")
    def test_untracked_special_file_is_rejected(self) -> None:
        self.seed_development_files()
        os.mkfifo(self.fixture.root / "src/probe.fifo")
        with self.assertRaisesRegex(local_ci.LocalCIError, "special files are forbidden"):
            local_ci.capture_source(self.fixture.root)

    def test_casefold_collision_detection_includes_parent_directories(self) -> None:
        with self.assertRaisesRegex(local_ci.LocalCIError, "case-fold path collision"):
            local_ci.validate_casefold_paths(["src/Foo/file.cpp", "src/foo/other.cpp"])

    def test_credential_bearing_remote_is_rejected(self) -> None:
        self.seed_development_files()
        self.fixture.git("remote", "add", "origin", "https://token@example.invalid/repo.git")
        with self.assertRaisesRegex(local_ci.LocalCIError, "credential-bearing"):
            local_ci.capture_source(self.fixture.root)

    def test_credential_bearing_push_remote_is_rejected(self) -> None:
        self.seed_development_files()
        self.fixture.git("remote", "add", "origin", "https://example.invalid/repo.git")
        self.fixture.git(
            "remote",
            "set-url",
            "--push",
            "origin",
            "https://token@example.invalid/repo.git",
        )
        with self.assertRaisesRegex(local_ci.LocalCIError, "credential-bearing"):
            local_ci.capture_source(self.fixture.root)

    def test_local_dockerfile_must_use_only_pinned_base(self) -> None:
        dockerfile = self.fixture.parent / "Dockerfile.local-ci"
        dockerfile.write_text("FROM debian:latest\n", encoding="utf-8")
        with self.assertRaisesRegex(local_ci.LocalCIError, "pinned SteamRT4"):
            local_ci.validate_local_dockerfile(dockerfile)
        dockerfile.write_text(
            "FROM {}\nRUN true\n".format(local_ci.STEAMRT4_IMAGE),
            encoding="utf-8",
        )
        local_ci.validate_local_dockerfile(dockerfile)

    def test_sparse_checkout_is_rejected(self) -> None:
        self.seed_development_files()
        self.fixture.git("config", "core.sparseCheckout", "true")
        with self.assertRaisesRegex(local_ci.LocalCIError, "sparse checkouts"):
            local_ci.capture_source(self.fixture.root)

    def test_merge_conflict_is_rejected(self) -> None:
        self.fixture.write("src/conflict.txt", b"base\n")
        self.fixture.commit_base()
        base_branch = self.fixture.git("branch", "--show-current")
        self.fixture.git("checkout", "-b", "other")
        self.fixture.write("src/conflict.txt", b"other\n")
        self.fixture.git("add", "src/conflict.txt")
        self.fixture.git("commit", "--quiet", "-m", "other")
        self.fixture.git("checkout", base_branch)
        self.fixture.write("src/conflict.txt", b"master\n")
        self.fixture.git("add", "src/conflict.txt")
        self.fixture.git("commit", "--quiet", "-m", "master")
        merge = subprocess.run(
            ["git", "-C", str(self.fixture.root), "merge", "other"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(merge.returncode, 0)
        with self.assertRaisesRegex(local_ci.LocalCIError, "merge conflicts"):
            local_ci.capture_source(self.fixture.root)

    def test_submodule_is_rejected(self) -> None:
        self.seed_development_files()
        submodule = self.fixture.parent / "submodule"
        submodule.mkdir()
        subprocess.run(["git", "-C", str(submodule), "init", "--quiet"], check=True)
        subprocess.run(
            ["git", "-C", str(submodule), "config", "user.name", "Local CI Test"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(submodule),
                "config",
                "user.email",
                "local-ci-test@openneoua.invalid",
            ],
            check=True,
        )
        (submodule / "file.txt").write_text("submodule\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(submodule), "add", "file.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(submodule), "commit", "--quiet", "-m", "base"],
            check=True,
        )
        self.fixture.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "--quiet",
            str(submodule),
            "vendor/submodule",
        )
        with self.assertRaisesRegex(local_ci.LocalCIError, "submodules are not supported"):
            local_ci.capture_source(self.fixture.root)

    def test_source_mutation_changes_capture_fingerprint(self) -> None:
        self.seed_development_files()
        first = local_ci.capture_source(self.fixture.root)
        self.fixture.write("src/tracked.bin", b"mutated\n")
        second = local_ci.capture_source(self.fixture.root)
        self.assertNotEqual(first, second)

    def test_lock_rejects_concurrent_run(self) -> None:
        lock_path = self.fixture.parent / "local-ci.lock"
        first = local_ci.acquire_lock(lock_path)
        try:
            with self.assertRaisesRegex(local_ci.LocalCIError, "another local"):
                local_ci.acquire_lock(lock_path)
        finally:
            first.close()

    def test_invalid_result_is_not_published_and_other_revisions_survive(self) -> None:
        scratch = self.fixture.parent / "scratch"
        output = self.fixture.parent / "output"
        scratch.mkdir()
        snapshot = local_ci.Snapshot(
            self.fixture.root,
            "a" * 40,
            "b" * 40,
            False,
        )
        archive = scratch / "OpenNeoUA-steamrt4-x86_64-bbbbbbb.tar.xz"
        checksum = scratch / (archive.name + ".sha256")
        archive.write_bytes(b"archive")
        checksum.write_text("0" * 64 + "  " + archive.name + "\n", encoding="ascii")
        with self.assertRaisesRegex(local_ci.LocalCIError, "checksum mismatch"):
            local_ci.verify_result_pair(scratch, snapshot)
        self.assertFalse(output.exists())

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum.write_text(digest + "  " + archive.name + "\n", encoding="ascii")
        verified = local_ci.verify_result_pair(scratch, snapshot)
        output.mkdir()
        other = output / "OpenNeoUA-steamrt4-x86_64-aaaaaaa.tar.xz"
        other.write_bytes(b"other revision")
        local_ci.publish_pair(*verified, output)
        self.assertEqual(other.read_bytes(), b"other revision")
        self.assertEqual((output / archive.name).read_bytes(), b"archive")


if __name__ == "__main__":
    unittest.main(verbosity=2)
