#!/usr/bin/env python3
"""Exercise the resolver's legacy write destinations in a filesystem fixture."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

HARNESS = r'''
#include "utils.h"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

static void require(bool condition, const std::string &message)
{
    if (!condition)
    {
        std::fprintf(stderr, "%s\n", message.c_str());
        std::exit(1);
    }
}

static void make_directory(const std::string &path)
{
    if (mkdir(path.c_str(), 0755) != 0)
        require(errno == EEXIST, "cannot create test directory: " + path);
}

static std::string expected(const std::string &path)
{
    return correctSeparatorAndExt(path);
}

int main()
{
    char temporary[] = "/tmp/openneoua-resolver-write-XXXXXX";
    require(mkdtemp(temporary) != NULL, "cannot create resolver test directory");
    require(chdir(temporary) == 0, "cannot enter resolver test directory");

    const std::vector<std::string> read_only_roots = {
        "Database", "Filters", "Interface", "Scripts", "Sounds", "Wireless"
    };
    const std::vector<std::string> legacy_write_roots = {"Env", "Save"};

    make_directory("Data");
    for (const std::string &root : read_only_roots)
    {
        make_directory(root);
        make_directory("Data/" + root);
    }
    for (const std::string &root : legacy_write_roots)
    {
        make_directory(root);
        make_directory("Data/" + root);
    }

    FSMgr::iDir::setBaseDir("");
    for (const std::string &root : read_only_roots)
    {
        const std::string logical = root + "/write-probe.tmp";
        require(
            uaDataFirstResolvedWritePath(logical) == expected(logical),
            "new read-only root changed write destination: " + root
        );

        const std::string data_prefixed = "Data/" + logical;
        require(
            uaDataFirstResolvedWritePath(data_prefixed) == expected(data_prefixed),
            "Data-prefixed write destination changed: " + root
        );
    }
    for (const std::string &root : legacy_write_roots)
    {
        const std::string logical = root + "/write-probe.tmp";
        const std::string data_path = "Data/" + logical;
        require(
            uaDataFirstResolvedWritePath(logical) == expected(data_path),
            "legacy Data-first write destination changed: " + root
        );

        require(rmdir(("Data/" + root).c_str()) == 0, "cannot remove Data directory: " + root);
        FSMgr::iDir::setBaseDir("");
        require(
            uaDataFirstResolvedWritePath(logical) == expected(logical),
            "legacy root write fallback changed: " + root
        );
        make_directory("Data/" + root);
        FSMgr::iDir::setBaseDir("");
    }

    std::puts("resolver write destination tests passed");
    return 0;
}
'''


def run(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, check=False, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    cflags = []
    for package in ("sdl2", "lua5.4"):
        cflags.extend(subprocess.check_output(["pkg-config", "--cflags", package], text=True).split())
    libs = subprocess.check_output(["pkg-config", "--libs", "sdl2"], text=True).split()
    with tempfile.TemporaryDirectory(prefix="OpenNeoUA resolver write test ") as temporary:
        temporary_root = Path(temporary)
        harness = temporary_root / "resolver_write_paths.cpp"
        executable = temporary_root / "resolver_write_paths"
        harness.write_text(HARNESS, encoding="utf-8")
        run(
            [
                "g++",
                "-std=c++14",
                "-O0",
                "-ffunction-sections",
                "-fdata-sections",
                "-I",
                str(SRC),
                *cflags,
                str(harness),
                str(SRC / "utils.cpp"),
                str(SRC / "system/fsmgr.cpp"),
                str(SRC / "env.cpp"),
                "-Wl,--gc-sections",
                *libs,
                "-o",
                str(executable),
            ],
            cwd=ROOT,
        )
        run([str(executable)], cwd=ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
