#include "system/fsmgr.h"
#include "filesystem_fixture.h"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <set>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

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
    FilesystemFixture fixture;
    const std::string root = fixture.Path();
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
    FSMgr::iNode *node = NULL;
    while (write_iter.getNext(&node))
        require(node != NULL, "iterator returned a null node");

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
