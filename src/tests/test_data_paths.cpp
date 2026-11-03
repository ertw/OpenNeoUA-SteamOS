#include "common/utils.h"
#include "filesystem_fixture.h"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <fstream>
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
    FilesystemFixture fixture;
    require(chdir(fixture.Path().c_str()) == 0, "cannot enter resolver test directory");

    const std::vector<std::string> read_only_roots = {
        "Collision", "Database", "Filters", "Interface", "Models", "Scripts", "Sounds", "Wireless"
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

        // Packaged resources live beside Data, while upstream scripts use
        // Data/Models/... and other Data-first paths. Both spellings must work.
        const std::string read_path = root + "/read-probe.tmp";
        const std::string data_read_path = "Data/" + read_path;
        std::ofstream(read_path) << "legacy";
        std::ofstream(data_read_path) << "data-first";
        FSMgr::iDir::setBaseDir("");
        for (const std::string &input : {read_path, data_read_path})
            require(uaDataFirstResolvedReadPath(input) == expected(data_read_path),
                    "Data-first read did not take precedence: " + input);
        require(std::remove(data_read_path.c_str()) == 0, "cannot remove Data read fixture");
        FSMgr::iDir::setBaseDir("");
        for (const std::string &input : {read_path, data_read_path})
            require(uaDataFirstResolvedReadPath(input) == expected(read_path),
                    "packaged root read fallback failed: " + input);
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

    std::puts("data path resolution tests passed");
    return 0;
}
