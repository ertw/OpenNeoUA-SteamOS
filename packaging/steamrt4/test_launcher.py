#!/usr/bin/env python3
"""Black-box tests for OpenNeoUA.sh path, environment, and signal handling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "OpenNeoUA.sh"


def fail(message: str) -> None:
    raise AssertionError(message)


def make_fixture(parent: Path) -> tuple[Path, Path, Path]:
    fixture = parent / "OpenNeoUA fixture with spaces"
    fixture.mkdir()
    (fixture / "bin").mkdir()
    (fixture / "lib").mkdir()
    launcher = fixture / "OpenNeoUA.sh"
    launcher.write_bytes(LAUNCHER.read_bytes())
    launcher.chmod(0o755)
    state = fixture / "state.json"
    fake = fixture / "bin" / "OpenNeoUA"
    fake.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            import json
            import os
            import signal
            import sys

            state_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump({
                    "cwd": os.getcwd(),
                    "argv": sys.argv[1:],
                    "ld_library_path": os.environ.get("LD_LIBRARY_PATH", ""),
                }, stream)
            if os.environ.get("OPENNEOUA_SIGNAL_TEST") == "1":
                signal.pause()
            raise SystemExit(37)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fixture, launcher, state


def run_and_read(launcher: Path, cwd: Path, state: Path, env: dict[str, str], args: list[str]) -> dict:
    result = subprocess.run([str(launcher)] + args, cwd=str(cwd), env=env, check=False)
    if result.returncode != 37:
        fail("launcher did not preserve exit status: {}".format(result.returncode))
    return json.loads(state.read_text(encoding="utf-8"))


def main() -> int:
    if not LAUNCHER.is_file() or not os.access(LAUNCHER, os.X_OK):
        fail("repository launcher is missing or not executable")

    with tempfile.TemporaryDirectory(prefix="OpenNeoUA launcher test ") as temporary:
        parent = Path(temporary)
        fixture, launcher, state = make_fixture(parent)
        other_cwd = parent / "different working directory"
        other_cwd.mkdir()
        environment = os.environ.copy()
        environment["LD_LIBRARY_PATH"] = "/existing/private/path"
        arguments = ["plain", "value with spaces", "", "unicode-✓"]

        observed = run_and_read(launcher, other_cwd, state, environment, arguments)
        if observed["cwd"] != str(fixture.resolve()):
            fail("launcher selected the wrong working directory: {}".format(observed["cwd"]))
        if observed["argv"] != arguments:
            fail("launcher changed arguments: {!r}".format(observed["argv"]))
        expected_library_path = str(fixture.resolve() / "lib") + os.pathsep + "/existing/private/path"
        if observed["ld_library_path"] != expected_library_path:
            fail("launcher did not prepend private lib/: {}".format(observed["ld_library_path"]))

        symlink_dir = parent / "symlink directory"
        symlink_dir.mkdir()
        symlink = symlink_dir / "OpenNeoUA symlink.sh"
        symlink.symlink_to(launcher)
        observed = run_and_read(symlink, other_cwd, state, environment, arguments)
        if observed["cwd"] != str(fixture.resolve()):
            fail("symlink invocation did not resolve physical launcher root")
        if observed["argv"] != arguments:
            fail("symlink invocation changed arguments")

        observed = run_and_read(
            launcher,
            other_cwd,
            state,
            environment,
            ["waitforexitandrun", "plain", "keep"],
        )
        if observed["argv"] != ["plain", "keep"]:
            fail("launcher did not strip Steam waitforexitandrun verb: {!r}".format(observed["argv"]))

        observed = run_and_read(
            launcher,
            other_cwd,
            state,
            environment,
            ["waitforexitandrun", str(launcher), "keep"],
        )
        if observed["argv"] != ["keep"]:
            fail("launcher did not drop duplicate script path after Steam verb: {!r}".format(observed["argv"]))

        rogue = parent / "wrong argv0"
        rogue.mkdir()
        compat_env = environment.copy()
        compat_env["STEAM_COMPAT_INSTALL_PATH"] = str(fixture.resolve())
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, sys; os.chdir(sys.argv[1]); os.execv(sys.argv[2], ['not-the-launcher'])",
                str(rogue),
                str(launcher),
            ],
            env=compat_env,
            check=False,
        )
        if result.returncode != 37:
            fail("STEAM_COMPAT_INSTALL_PATH fallback did not launch: {}".format(result.returncode))
        observed = json.loads(state.read_text(encoding="utf-8"))
        if observed["cwd"] != str(fixture.resolve()):
            fail("STEAM_COMPAT_INSTALL_PATH fallback used the wrong game root")

        environment["OPENNEOUA_SIGNAL_TEST"] = "1"
        process = subprocess.Popen([str(launcher), "signal"], cwd=str(other_cwd), env=environment)
        time.sleep(0.2)
        process.send_signal(signal.SIGTERM)
        return_code = process.wait(timeout=5)
        if return_code != -signal.SIGTERM:
            fail("launcher did not preserve SIGTERM: {}".format(return_code))

    print("launcher tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
