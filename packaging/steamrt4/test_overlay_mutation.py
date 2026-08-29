#!/usr/bin/env python3
"""Exercise copy-on-write overlay mutations while directory iterators are live."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

HARNESS = r'''
#include "system/fsmgr.h"

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <set>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

// fsmgr.cpp only needs the project case-insensitive comparison helper.  Keep
// this harness's link closure limited to the filesystem manager itself rather
// than pulling utils.cpp (which also owns the full engine's parser/GUI globals).
int StriCmp(const std::string &left, const std::string &right)
{
    const size_t count = std::min(left.size(), right.size());
    for (size_t index = 0; index < count; ++index)
    {
        const unsigned char a = static_cast<unsigned char>(left[index]);
        const unsigned char b = static_cast<unsigned char>(right[index]);
        const int difference = std::tolower(a) - std::tolower(b);
        if (difference != 0)
            return difference;
    }
    if (left.size() == right.size())
        return 0;
    return left.size() < right.size() ? -1 : 1;
}

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

static void write_file(const std::string &path, const std::string &contents)
{
    std::ofstream output(path.c_str(), std::ios::binary | std::ios::trunc);
    require(output.good(), "cannot create test file: " + path);
    output << contents;
    require(output.good(), "cannot write test file: " + path);
}

static std::string read_file(const std::string &path)
{
    std::ifstream input(path.c_str(), std::ios::binary);
    require(input.good(), "cannot read test file: " + path);
    return std::string((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
}

int main()
{
    char temporary[] = "/tmp/openneoua-overlay-mutation-XXXXXX";
    require(mkdtemp(temporary) != NULL, "cannot create overlay test directory");

    const std::string root(temporary);
    const std::string assets = root + "/assets";
    const std::string user = root + "/user";
    make_directory(assets);
    make_directory(user);
    make_directory(assets + "/Env");
    make_directory(assets + "/Levels");
    make_directory(assets + "/Levels/single");
    make_directory(assets + "/packaged-empty");
    write_file(assets + "/keep.txt", "packaged keep\n");
    write_file(assets + "/delete-a.txt", "delete a\n");
    write_file(assets + "/delete-b.txt", "delete b\n");
    write_file(assets + "/copy-on-write.txt", "original\n");
    write_file(assets + "/Levels/single/L01.LEV", "level 1\n");
    write_file(assets + "/Levels/single/L02.LEV", "level 2\n");
    write_file(assets + "/Levels/single/L03.LEV", "level 3\n");
    write_file(assets + "/Levels/single/L04.LEV", "level 4\n");

    FSMgr::iDir::setRoots(assets, user);
    require(FSMgr::iDir::overlayActive(), "overlay was not enabled");
    require(FSMgr::iDir::fileExist("keep.txt"), "packaged file is not visible");

    // Updating a packaged file must copy it into the writable tree and keep a
    // live directory iterator usable while the merged node is retargeted.
    FSMgr::DirIter write_iter = FSMgr::iDir::readDir("");
    FSMgr::FileHandle *updated = FSMgr::iDir::openFileAlloc("copy-on-write.txt", "r+");
    require(updated != NULL, "copy-on-write open failed");
    require(updated->seek(0, SEEK_SET) == 0, "copy-on-write seek failed");
    const char replacement[] = "updated!\n";
    require(updated->write(replacement, sizeof(replacement) - 1) == sizeof(replacement) - 1,
            "copy-on-write write failed");
    delete updated;
    require(read_file(user + "/copy-on-write.txt") == "updated!\n",
            "copy-on-write did not write the user tree");
    bool write_iter_completed = false;
    FSMgr::iNode *node = NULL;
    while (write_iter.getNext(&node))
        require(node != NULL, "iterator returned a null node");
    write_iter_completed = true;
    require(write_iter_completed, "iterator did not complete after an in-place write");

    // Delete two packaged files through the same live iterator.  The files
    // remain in the immutable tree but disappear from the merged view via
    // tombstones, without rebuilding or invalidating the iterator.
    FSMgr::DirIter delete_iter = FSMgr::iDir::readDir("");
    bool saw_keep = false;
    bool saw_a = false;
    bool saw_b = false;
    while (delete_iter.getNext(&node))
    {
        const std::string name = node->getName();
        if (name == "keep.txt")
            saw_keep = true;
        else if (name == "delete-a.txt")
        {
            saw_a = true;
            require(FSMgr::iDir::deleteFile(name), "delete-a failed");
        }
        else if (name == "delete-b.txt")
        {
            saw_b = true;
            require(FSMgr::iDir::deleteFile(name), "delete-b failed");
        }
    }
    require(saw_keep && saw_a && saw_b, "live iterator missed expected packaged entries");
    require(!FSMgr::iDir::findNode("delete-a.txt") && !FSMgr::iDir::findNode("delete-b.txt"),
            "deleted packaged entries remain in the merged view");
    require(access((assets + "/delete-a.txt").c_str(), F_OK) == 0 &&
            access((assets + "/delete-b.txt").c_str(), F_OK) == 0,
            "delete mutated the immutable asset tree");

    // This mirrors the engine's level scan: a Levels iterator remains live
    // while the scan emits repeated append records to Env/ypa_log.txt.  The
    // old overlay implementation rebuilt the complete merged tree for every
    // append and left this iterator pointing at freed nodes.  Keep the exact
    // expected level set and reject both duplicates and missing entries.
    const std::set<std::string> expected_levels = {
        "L01.LEV", "L02.LEV", "L03.LEV", "L04.LEV"
    };
    FSMgr::DirIter levels_iter = FSMgr::iDir::readDir("Levels/single");
    std::set<std::string> seen_levels;
    for (int pass = 0; pass < 64; ++pass)
    {
        FSMgr::FileHandle *log = FSMgr::iDir::openFileAlloc("Env/ypa_log.txt", "a");
        require(log != NULL, "append log open failed");
        const std::string line = "level scan pass " + std::to_string(pass) + "\n";
        require(log->write(line.data(), line.size()) == line.size(), "append log write failed");
        delete log;
    }
    while (levels_iter.getNext(&node))
    {
        require(node != NULL, "level iterator returned a null node");
        const std::string name = node->getName();
        require(seen_levels.insert(name).second, "level iterator returned a duplicate entry");
    }
    require(seen_levels == expected_levels, "level iterator did not return the complete expected set");
    require(read_file(user + "/Env/ypa_log.txt").find("level scan pass 63") != std::string::npos,
            "append log did not retain the complete write sequence");

    // A writable directory is also removed in place while its parent is being
    // enumerated.  The iterator must continue safely after deleting its
    // current entry.
    require(FSMgr::iDir::createDir("user-only"), "user-only directory creation failed");
    FSMgr::DirIter directory_iter = FSMgr::iDir::readDir("");
    bool saw_user_only = false;
    while (directory_iter.getNext(&node))
    {
        if (node->getName() == "user-only")
        {
            saw_user_only = true;
            require(FSMgr::iDir::deleteDir("user-only"), "user-only directory delete failed");
        }
    }
    require(saw_user_only && !FSMgr::iDir::findNode("user-only"),
            "in-place user directory delete was not reflected");

    // Deleting an asset-only empty directory must create a tombstone and hide
    // the node immediately, then remain hidden after a fresh merged scan.
    require(FSMgr::iDir::deleteDir("packaged-empty"), "packaged directory delete failed");
    require(!FSMgr::iDir::findNode("packaged-empty"),
            "deleted packaged directory remains in the merged view");
    FSMgr::iDir::setRoots(assets, user);
    require(!FSMgr::iDir::findNode("packaged-empty"),
            "packaged directory tombstone was not persistent");

    std::puts("overlay mutation iterator tests passed");
    return 0;
}
'''


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, check=False, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    cflags = subprocess.check_output(["pkg-config", "--cflags", "sdl2", "lua5.4"], text=True).split()
    libs = subprocess.check_output(["pkg-config", "--libs", "sdl2"], text=True).split()
    with tempfile.TemporaryDirectory(prefix="OpenNeoUA overlay mutation test ") as temporary:
        temporary_root = Path(temporary)
        harness = temporary_root / "overlay_mutation.cpp"
        executable = temporary_root / "overlay_mutation"
        harness.write_text(HARNESS, encoding="utf-8")
        run(
            [
                "g++",
                "-std=c++14",
                "-O0",
                "-fsanitize=address",
                "-fno-omit-frame-pointer",
                "-ffunction-sections",
                "-fdata-sections",
                "-I",
                str(SRC),
                *cflags,
                str(harness),
                str(SRC / "system/fsmgr.cpp"),
                "-Wl,--gc-sections",
                "-fsanitize=address",
                *libs,
                "-o",
                str(executable),
            ],
            cwd=ROOT,
        )
        runtime_environment = dict(os.environ)
        runtime_environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1:abort_on_error=1"
        run([str(executable)], cwd=ROOT, env=runtime_environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
