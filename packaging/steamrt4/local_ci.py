#!/usr/bin/env python3
"""Run the complete OpenNeoUA SteamRT4 CI pipeline with Docker."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import parse_qsl, urlsplit
import uuid


STEAMRT4_VERSION = "4.0.20260805.254769"
STEAMRT4_IMAGE = (
    "registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:" + STEAMRT4_VERSION
)
LOCAL_IMAGE = "openneoua-steamrt4-local-ci:" + STEAMRT4_VERSION
DEFAULT_REPOSITORY = "https://github.com/ertw/OpenNeoUA-SteamOS"
WORKFLOW_PATH = ".github/workflows/linux-steamrt4.yml"
PROGRESS_PATH = "Progressi OpenNeoUA/Linux SteamOS Steam Deck e Bazzite.md"
FONT_PATHS = {
    "Fonts/LiberationMono-Regular.ttf",
    "Fonts/LiberationSans-Regular.ttf",
    "Fonts/LiberationSerif-Regular.ttf",
    "Fonts/PressStart2P.ttf",
    "Fonts/Xolonium-Bold.otf",
    "Fonts/Xolonium-Regular.otf",
    "Fonts/textar.ttf",
    "Fonts/SHA256SUMS",
    "Fonts/SOURCES.md",
    "Fonts/licenses/FONT-ATTRIBUTIONS.txt",
    "Fonts/licenses/IPA-Font-License-Agreement-v1.0.txt",
    "Fonts/licenses/OFL-1.1.txt",
}
GAME_DATA_ROOTS = {
    "3ds",
    "Database",
    "Env",
    "Filters",
    "Interface",
    "Locale",
    "Res",
    "Scripts",
    "Sounds",
    "Wireless",
}


class LocalCIError(RuntimeError):
    """The local CI input or execution is unsafe or invalid."""


@dataclass(frozen=True)
class UntrackedFile:
    path: str
    mode: int
    data: bytes

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class SourceCapture:
    head: str
    staged_patch: bytes
    unstaged_patch: bytes
    status: bytes
    untracked: tuple[UntrackedFile, ...]
    repository_url: str
    base_timestamp: str

    @property
    def dirty(self) -> bool:
        return bool(self.staged_patch or self.unstaged_patch or self.untracked)


@dataclass(frozen=True)
class Snapshot:
    path: Path
    base_commit: str
    commit: str
    dirty: bool

    @property
    def artifact_identifier(self) -> str:
        if self.dirty:
            return "{}-dirty-{}".format(self.base_commit[:7], self.commit[:7])
        return self.commit[:7]


def display_path(path: str) -> str:
    return repr(path)


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_data: bytes | None = None,
    capture: bool = True,
    env: dict[str, str] | None = None,
    phase: str,
) -> bytes:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            input=input_data,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env=env,
            check=False,
        )
    except OSError as exc:
        raise LocalCIError("{}: unable to run {}: {}".format(phase, command[0], exc)) from exc
    if result.returncode != 0:
        details = b""
        if capture:
            details = (result.stderr or result.stdout or b"").strip()
        suffix = ""
        if details:
            suffix = ": " + details.decode("utf-8", errors="replace").splitlines()[-1]
        raise LocalCIError(
            "{}: command failed with exit status {}{}".format(
                phase, result.returncode, suffix
            )
        )
    return result.stdout if capture else b""


def git(repo: Path, arguments: list[str], *, phase: str, input_data: bytes | None = None) -> bytes:
    return run(
        ["git", "-C", str(repo)] + arguments,
        input_data=input_data,
        phase=phase,
    )


def decode_git_paths(data: bytes, label: str) -> list[str]:
    result: list[str] = []
    for item in data.split(b"\0"):
        if not item:
            continue
        try:
            result.append(item.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise LocalCIError("{} contains a non-UTF-8 path".format(label)) from exc
    return result


def validate_relative_path(path: str) -> None:
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or path.startswith("/")
        or ".." in candidate.parts
        or "." in candidate.parts
        or not candidate.parts
        or candidate.as_posix() != path
        or candidate.parts[0] == ".git"
        or "\0" in path
    ):
        raise LocalCIError("unsafe repository path: {}".format(display_path(path)))


def normalized_component(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def validate_casefold_paths(paths: list[str]) -> None:
    observed: dict[tuple[str, ...], tuple[str, ...]] = {}
    for path in paths:
        parts = PurePosixPath(path).parts
        for length in range(1, len(parts) + 1):
            actual = tuple(parts[:length])
            folded = tuple(normalized_component(part) for part in actual)
            previous = observed.get(folded)
            if previous is not None and previous != actual:
                raise LocalCIError(
                    "case-fold path collision: {} and {}".format(
                        display_path("/".join(previous)),
                        display_path("/".join(actual)),
                    )
                )
            observed[folded] = actual


def remote_contains_credentials(url: str) -> bool:
    if not url or any(character in url for character in "\r\n\0"):
        return True
    parsed = urlsplit(url)
    if parsed.scheme:
        if parsed.password is not None:
            return True
        if parsed.username is not None and parsed.scheme.lower() not in ("ssh", "git"):
            return True
        sensitive = re.compile(
            r"(?:token|key|secret|signature|credential|password|passwd|auth)", re.I
        )
        if any(sensitive.search(key) for key, _value in parse_qsl(parsed.query)):
            return True
    return False


def repository_url(repo: Path) -> str:
    remotes = git(repo, ["remote"], phase="validate remotes").decode("utf-8").splitlines()
    urls: dict[str, list[str]] = {}
    for remote in remotes:
        fetch_values = (
            git(repo, ["remote", "get-url", "--all", remote], phase="validate remotes")
            .decode("utf-8")
            .splitlines()
        )
        push_values = (
            git(
                repo,
                ["remote", "get-url", "--push", "--all", remote],
                phase="validate remotes",
            )
            .decode("utf-8")
            .splitlines()
        )
        urls[remote] = fetch_values
        for value in fetch_values + push_values:
            if remote_contains_credentials(value):
                raise LocalCIError(
                    "credential-bearing or unsafe Git remote URL is forbidden for remote {}".format(
                        display_path(remote)
                    )
                )
    origin = urls.get("origin", [])
    return origin[0] if origin else DEFAULT_REPOSITORY


def ensure_repository_is_supported(repo: Path) -> None:
    sparse_result = subprocess.run(
        ["git", "-C", str(repo), "config", "--bool", "core.sparseCheckout"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if sparse_result.returncode not in (0, 1):
        raise LocalCIError("check sparse checkout: unable to inspect Git configuration")
    sparse = sparse_result.stdout.strip()
    if sparse == b"true":
        raise LocalCIError("sparse checkouts are not supported")
    conflicts = git(repo, ["ls-files", "-u", "-z"], phase="check merge conflicts")
    if conflicts:
        raise LocalCIError("merge conflicts must be resolved before local CI")
    entries = git(repo, ["ls-files", "--stage", "-z"], phase="check Git index")
    for raw in entries.split(b"\0"):
        if not raw:
            continue
        metadata, separator, raw_path = raw.partition(b"\t")
        if not separator:
            raise LocalCIError("unable to parse the Git index")
        fields = metadata.split()
        if len(fields) != 3:
            raise LocalCIError("unable to parse the Git index")
        mode, _object_id, stage = fields
        if stage != b"0":
            raise LocalCIError("merge conflicts must be resolved before local CI")
        if mode == b"160000":
            path = raw_path.decode("utf-8", errors="replace")
            raise LocalCIError("submodules are not supported: {}".format(display_path(path)))


def path_is_ignored(repo: Path, relative: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", "--", relative],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise LocalCIError(
            "inspect ignored paths: git check-ignore failed for {}".format(
                display_path(relative)
            )
        )
    return result.returncode == 0


def validate_worktree_file_types(repo: Path) -> None:
    for directory, directory_names, filenames in os.walk(repo, topdown=True, followlinks=False):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(repo)
        retained_directories: list[str] = []
        for name in directory_names:
            if relative_directory == Path(".") and name == ".git":
                continue
            path = directory_path / name
            relative = path.relative_to(repo).as_posix()
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode):
                if not path_is_ignored(repo, relative):
                    raise LocalCIError(
                        "symlinks are forbidden: {}".format(display_path(relative))
                    )
                continue
            if not stat.S_ISDIR(details.st_mode):
                if not path_is_ignored(repo, relative):
                    raise LocalCIError(
                        "special files are forbidden: {}".format(display_path(relative))
                    )
                continue
            if not path_is_ignored(repo, relative):
                retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in filenames:
            path = directory_path / name
            details = path.lstat()
            if stat.S_ISREG(details.st_mode):
                continue
            relative = path.relative_to(repo).as_posix()
            if path_is_ignored(repo, relative):
                continue
            if stat.S_ISLNK(details.st_mode):
                raise LocalCIError(
                    "symlinks are forbidden: {}".format(display_path(relative))
                )
            raise LocalCIError(
                "special files are forbidden: {}".format(display_path(relative))
            )


def allowed_untracked(path: str) -> bool:
    if path in {"OpenNeoUA.sh", WORKFLOW_PATH, PROGRESS_PATH} or path in FONT_PATHS:
        return True
    parts = PurePosixPath(path).parts
    return len(parts) > 1 and parts[0] in {"src", "svg", "packaging"} and (
        parts[0] != "packaging" or parts[1] == "steamrt4"
    )


def read_stable_regular_file(root: Path, relative: str) -> tuple[int, bytes]:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise LocalCIError(
            "source changed while reading untracked file {}".format(display_path(relative))
        ) from exc
    if stat.S_ISLNK(before.st_mode):
        raise LocalCIError("symlinks are forbidden: {}".format(display_path(relative)))
    if not stat.S_ISREG(before.st_mode):
        raise LocalCIError("special files are forbidden: {}".format(display_path(relative)))
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise LocalCIError(
            "unable to read untracked file {} safely".format(display_path(relative))
        ) from exc
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    after = path.lstat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_opened or identity_opened != identity_after:
        raise LocalCIError(
            "source changed while reading untracked file {}".format(display_path(relative))
        )
    return stat.S_IMODE(opened.st_mode), b"".join(chunks)


def capture_source(repo: Path) -> SourceCapture:
    ensure_repository_is_supported(repo)
    validate_worktree_file_types(repo)
    head = git(repo, ["rev-parse", "HEAD"], phase="capture source").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise LocalCIError("repository HEAD is not a full Git commit")
    staged_patch = git(
        repo,
        ["diff", "--cached", "--binary", "--full-index", "HEAD", "--"],
        phase="capture staged changes",
    )
    unstaged_patch = git(
        repo,
        ["diff", "--binary", "--full-index", "--"],
        phase="capture unstaged changes",
    )
    status_output = git(
        repo,
        ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
        phase="capture source status",
    )
    untracked_paths = decode_git_paths(
        git(
            repo,
            ["ls-files", "--others", "--exclude-standard", "-z"],
            phase="capture untracked files",
        ),
        "untracked file list",
    )
    untracked: list[UntrackedFile] = []
    for relative in sorted(untracked_paths):
        validate_relative_path(relative)
        parts = PurePosixPath(relative).parts
        if parts[0] in GAME_DATA_ROOTS:
            raise LocalCIError(
                "untracked game-data payload must be staged before local CI: {}".format(
                    display_path(relative)
                )
            )
        if not allowed_untracked(relative):
            raise LocalCIError(
                "untracked file is outside the local CI allowlist: {}".format(
                    display_path(relative)
                )
            )
        mode, data = read_stable_regular_file(repo, relative)
        untracked.append(UntrackedFile(relative, mode, data))
    index_paths = decode_git_paths(
        git(repo, ["ls-files", "-z"], phase="capture index paths"),
        "Git index path list",
    )
    unstaged_deletions = set(
        decode_git_paths(
            git(
                repo,
                ["diff", "--name-only", "--diff-filter=D", "-z", "--"],
                phase="capture unstaged deletions",
            ),
            "unstaged deletion list",
        )
    )
    final_paths = sorted(
        (set(index_paths) - unstaged_deletions).union(item.path for item in untracked)
    )
    for relative in final_paths:
        validate_relative_path(relative)
    validate_casefold_paths(final_paths)
    timestamp = (
        git(repo, ["show", "-s", "--format=%ct", head], phase="capture source timestamp")
        .decode("ascii")
        .strip()
    )
    if not timestamp.isdigit():
        raise LocalCIError("base commit has no valid timestamp")
    return SourceCapture(
        head=head,
        staged_patch=staged_patch,
        unstaged_patch=unstaged_patch,
        status=status_output,
        untracked=tuple(untracked),
        repository_url=repository_url(repo),
        base_timestamp=timestamp,
    )


def ensure_safe_parent_directories(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    current = root
    for part in parts[:-1]:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise LocalCIError(
                    "unsafe snapshot parent for {}".format(display_path(relative))
                )
        else:
            current.mkdir()
    return root.joinpath(*parts)


def snapshot_paths(repo: Path) -> list[str]:
    paths = decode_git_paths(
        git(repo, ["ls-files", "-z"], phase="validate snapshot paths"),
        "snapshot file list",
    )
    for path in paths:
        validate_relative_path(path)
    validate_casefold_paths(paths)
    return paths


def validate_snapshot_files(repo: Path) -> None:
    paths = snapshot_paths(repo)
    root = repo.resolve()
    for relative in paths:
        path = repo.joinpath(*PurePosixPath(relative).parts)
        try:
            details = path.lstat()
        except FileNotFoundError as exc:
            raise LocalCIError(
                "snapshot file is missing: {}".format(display_path(relative))
            ) from exc
        if stat.S_ISLNK(details.st_mode):
            raise LocalCIError("symlinks are forbidden: {}".format(display_path(relative)))
        if not stat.S_ISREG(details.st_mode):
            raise LocalCIError("special files are forbidden: {}".format(display_path(relative)))
        if path.resolve().parent != path.parent.resolve() or root not in path.resolve().parents:
            raise LocalCIError("snapshot path escapes its root: {}".format(display_path(relative)))


def create_snapshot(source: Path, capture: SourceCapture, destination: Path) -> Snapshot:
    run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-hardlinks",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
            source.as_uri(),
            str(destination),
        ],
        phase="clone source snapshot",
    )
    git(
        destination,
        ["config", "--local", "core.autocrlf", "false"],
        phase="configure source snapshot",
    )
    git(
        destination,
        ["checkout", "--quiet", "--detach", capture.head],
        phase="checkout source snapshot",
    )
    git(
        destination,
        ["remote", "set-url", "origin", capture.repository_url],
        phase="sanitize snapshot remote",
    )
    if capture.staged_patch:
        git(
            destination,
            ["apply", "--index", "--binary", "--whitespace=nowarn", "-"],
            phase="apply staged changes",
            input_data=capture.staged_patch,
        )
    if capture.unstaged_patch:
        git(
            destination,
            ["apply", "--index", "--binary", "--whitespace=nowarn", "-"],
            phase="apply unstaged changes",
            input_data=capture.unstaged_patch,
        )
    validate_snapshot_files(destination)
    added_paths: list[str] = []
    for item in capture.untracked:
        target = ensure_safe_parent_directories(destination, item.path)
        try:
            with target.open("xb") as stream:
                stream.write(item.data)
        except FileExistsError as exc:
            raise LocalCIError(
                "untracked file collides with snapshot content: {}".format(
                    display_path(item.path)
                )
            ) from exc
        target.chmod(item.mode)
        added_paths.append(item.path)
    if added_paths:
        pathspecs = b"\0".join(path.encode("utf-8") for path in added_paths) + b"\0"
        git(
            destination,
            ["add", "--pathspec-from-file=-", "--pathspec-file-nul"],
            phase="stage allowed untracked files",
            input_data=pathspecs,
        )
    commit = capture.head
    if capture.dirty:
        tree = (
            git(destination, ["write-tree"], phase="write synthetic tree")
            .decode("ascii")
            .strip()
        )
        deterministic_environment = os.environ.copy()
        deterministic_environment.update(
            {
                "GIT_AUTHOR_NAME": "OpenNeoUA Local CI",
                "GIT_AUTHOR_EMAIL": "local-ci@openneoua.invalid",
                "GIT_COMMITTER_NAME": "OpenNeoUA Local CI",
                "GIT_COMMITTER_EMAIL": "local-ci@openneoua.invalid",
                "GIT_AUTHOR_DATE": "@{} +0000".format(capture.base_timestamp),
                "GIT_COMMITTER_DATE": "@{} +0000".format(capture.base_timestamp),
                "LC_ALL": "C",
                "TZ": "UTC",
            }
        )
        commit = run(
            ["git", "-C", str(destination), "commit-tree", tree, "-p", capture.head],
            input_data=b"OpenNeoUA local CI synthetic snapshot\n",
            env=deterministic_environment,
            phase="commit synthetic snapshot",
        ).decode("ascii").strip()
        git(
            destination,
            ["update-ref", "HEAD", commit],
            phase="activate synthetic snapshot",
        )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise LocalCIError("synthetic snapshot commit is invalid")
    parents = (
        git(
            destination,
            ["show", "-s", "--format=%P", commit],
            phase="verify snapshot commit",
        )
        .decode("ascii")
        .strip()
        .split()
    )
    if capture.dirty and parents != [capture.head]:
        raise LocalCIError("synthetic snapshot does not have exactly one real-HEAD parent")
    if git(
        destination,
        ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
        phase="verify snapshot status",
    ):
        raise LocalCIError("synthetic snapshot is not clean after committing")
    validate_snapshot_files(destination)
    return Snapshot(destination, capture.head, commit, capture.dirty)


def verify_result_pair(directory: Path, snapshot: Snapshot) -> tuple[Path, Path]:
    archive_name = "OpenNeoUA-steamrt4-x86_64-{}.tar.xz".format(
        snapshot.artifact_identifier
    )
    checksum_name = archive_name + ".sha256"
    archive = directory / archive_name
    checksum = directory / checksum_name
    entries = sorted(path.name for path in directory.iterdir()) if directory.is_dir() else []
    if entries != sorted([archive_name, checksum_name]):
        raise LocalCIError("verify artifacts: output is not the exact archive/checksum pair")
    for path in (archive, checksum):
        if path.is_symlink() or not path.is_file():
            raise LocalCIError(
                "verify artifacts: result is not a regular file: {}".format(path.name)
            )
    line = checksum.read_text(encoding="ascii").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
    if match is None or match.group(2) != archive.name:
        raise LocalCIError("verify artifacts: external checksum record is invalid")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != match.group(1):
        raise LocalCIError("verify artifacts: archive checksum mismatch")
    return archive, checksum


def validate_local_dockerfile(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LocalCIError("build image: unable to read Dockerfile.local-ci") from exc
    from_lines = [
        line.strip()
        for line in lines
        if line.lstrip().lower().startswith("from ")
    ]
    expected = ["FROM {}".format(STEAMRT4_IMAGE)]
    if from_lines != expected:
        raise LocalCIError(
            "build image: Dockerfile.local-ci must derive only from the pinned SteamRT4 image"
        )


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_pair(archive: Path, checksum: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".local-ci-publish-", dir=output_dir))
    staged_archive = transaction / archive.name
    staged_checksum = transaction / checksum.name
    shutil.copy2(archive, staged_archive)
    shutil.copy2(checksum, staged_checksum)
    for path in (staged_archive, staged_checksum):
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    final_archive = output_dir / archive.name
    final_checksum = output_dir / checksum.name
    existing = (
        final_archive.exists() or final_archive.is_symlink(),
        final_checksum.exists() or final_checksum.is_symlink(),
    )
    if existing[0] != existing[1]:
        shutil.rmtree(transaction)
        raise LocalCIError("publish artifacts: an incomplete pair already exists for this revision")
    backup_archive = transaction / (archive.name + ".previous")
    backup_checksum = transaction / (checksum.name + ".previous")
    blocked_signals = {signal.SIGINT, signal.SIGTERM}
    previous_mask = None
    if hasattr(signal, "pthread_sigmask"):
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked_signals)
    replaced_archive = False
    replaced_checksum = False
    try:
        if existing[0]:
            if final_archive.is_symlink() or final_checksum.is_symlink():
                raise LocalCIError("publish artifacts: refusing to replace a symlink")
            os.replace(final_archive, backup_archive)
            os.replace(final_checksum, backup_checksum)
        os.replace(staged_archive, final_archive)
        replaced_archive = True
        os.replace(staged_checksum, final_checksum)
        replaced_checksum = True
        fsync_directory(output_dir)
    except BaseException:
        if replaced_checksum and final_checksum.exists():
            final_checksum.unlink()
        if replaced_archive and final_archive.exists():
            final_archive.unlink()
        if backup_archive.exists():
            os.replace(backup_archive, final_archive)
        if backup_checksum.exists():
            os.replace(backup_checksum, final_checksum)
        fsync_directory(output_dir)
        raise
    finally:
        if previous_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        shutil.rmtree(transaction, ignore_errors=True)
    return final_archive.resolve(), final_checksum.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--refresh-image",
        action="store_true",
        help="pull the base image and rebuild all local CI image layers",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="retain the sanitized snapshot and per-run work directory",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="clear the compiler cache before building",
    )
    return parser.parse_args(argv)


def acquire_lock(path: Path):
    stream = path.open("a+")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise LocalCIError(
            "acquire lock: another local SteamRT4 CI run is active"
        ) from exc
    return stream


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    script_root = Path(__file__).resolve().parents[2]
    try:
        repository = Path(
            git(script_root, ["rev-parse", "--show-toplevel"], phase="locate repository")
            .decode("utf-8")
            .strip()
        ).resolve()
        if repository != script_root:
            raise LocalCIError("local_ci.py is not running from its owning repository")
        local_root = repository / "build" / "local-ci"
        local_root.mkdir(parents=True, exist_ok=True)
        lock_path = local_root / "local_ci.lock"
        lock_stream = acquire_lock(lock_path)

        if shutil.which("docker") is None:
            raise LocalCIError("verify Docker: docker executable was not found")
        docker_server_version = run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            phase="verify Docker daemon",
        ).decode("utf-8").strip()
        if not docker_server_version:
            raise LocalCIError("verify Docker daemon: Docker returned no server version")

        snapshot_parent = Path(tempfile.mkdtemp(prefix="openneoua-local-ci-snapshot-"))
        snapshot_path = snapshot_parent / "source"
        run_id = "{}-{}".format(os.getpid(), uuid.uuid4().hex[:12])
        work_dir = local_root / "work" / run_id
        artifact_scratch = work_dir / "artifacts"
        work_dir.mkdir(parents=True)
        output_dir = (args.output_dir or (local_root / "artifacts")).expanduser().resolve()
        snapshot: Snapshot | None = None
        try:
            print("[local-ci] phase: capture sanitized source snapshot", flush=True)
            initial = capture_source(repository)
            snapshot = create_snapshot(repository, initial, snapshot_path)
            final = capture_source(repository)
            if final != initial:
                raise LocalCIError("capture source: source changed while creating the snapshot")

            dockerfile = snapshot.path / "packaging" / "steamrt4" / "Dockerfile.local-ci"
            if not dockerfile.is_file() or dockerfile.is_symlink():
                raise LocalCIError("build image: Dockerfile.local-ci is missing from the snapshot")
            validate_local_dockerfile(dockerfile)
            build_command = [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "--tag",
                LOCAL_IMAGE,
                "--file",
                str(dockerfile),
            ]
            if args.refresh_image:
                build_command.extend(["--pull", "--no-cache"])
            build_command.append(str(snapshot.path))
            print("[local-ci] phase: build cached SteamRT4 CI image", flush=True)
            run(build_command, capture=False, phase="build image")

            dirty_argument = snapshot.base_commit if snapshot.dirty else ""
            container_work = "/work/work/{}".format(run_id)
            docker_run = [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "--user",
                "{}:{}".format(os.getuid(), os.getgid()),
                "--mount",
                "type=bind,src={},dst=/src,readonly".format(snapshot.path),
                "--mount",
                "type=bind,src={},dst=/work".format(local_root.resolve()),
                "--env",
                "CI_SOURCE_ROOT=/src",
                "--env",
                "CI_WORK_ROOT={}".format(container_work),
                "--env",
                "CI_OUTPUT_DIR={}/artifacts".format(container_work),
                "--env",
                "CI_RUNTIME_DIR=/work/runtime/{}".format(STEAMRT4_VERSION),
                "--env",
                "CI_DIRTY_BASE_COMMIT={}".format(dirty_argument),
                "--env",
                "HOME={}/home".format(container_work),
                "--env",
                "PYTHONPYCACHEPREFIX={}/pycache".format(container_work),
                "--env",
                "CCACHE_DIR=/work/ccache",
                "--env",
                "CI_CLEAR_CACHE=1" if args.clear_cache else "CI_CLEAR_CACHE=0",
                LOCAL_IMAGE,
                "bash",
                "/src/packaging/steamrt4/run-ci.sh",
            ]
            print("[local-ci] phase: run shared in-container CI pipeline", flush=True)
            run(docker_run, capture=False, phase="run CI container")

            archive, checksum = verify_result_pair(artifact_scratch, snapshot)
            print("[local-ci] phase: publish verified artifact pair", flush=True)
            final_archive, final_checksum = publish_pair(archive, checksum, output_dir)
            print("Artifact: {}".format(final_archive))
            print("Checksum: {}".format(final_checksum))
            if args.keep_work:
                print("Work directory: {}".format(work_dir.resolve()))
                print("Sanitized snapshot: {}".format(snapshot.path.resolve()))
            return 0
        finally:
            if not args.keep_work:
                shutil.rmtree(work_dir, ignore_errors=True)
                shutil.rmtree(snapshot_parent, ignore_errors=True)
    except (LocalCIError, UnicodeError, OSError) as exc:
        print("local_ci.py: {}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("local_ci.py: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
