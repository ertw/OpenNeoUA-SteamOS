"""Temporary Git repository used by source and packaging regressions."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


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


