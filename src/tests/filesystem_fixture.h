#ifndef OPENNEOUA_TEST_FILESYSTEM_FIXTURE_H
#define OPENNEOUA_TEST_FILESYSTEM_FIXTURE_H

#include <cstdio>
#include <cstdlib>
#include <ftw.h>
#include <string>
#include <unistd.h>

// POSIX filesystem tests own their scratch tree and restore the working directory.
class FilesystemFixture
{
public:
    FilesystemFixture()
    {
        char *cwd = getcwd(nullptr, 0);
        char temporary[] = "/tmp/openneoua-test-XXXXXX";
        if (!cwd || !mkdtemp(temporary))
        {
            std::perror("filesystem fixture");
            std::exit(1);
        }
        _cwd = cwd;
        std::free(cwd);
        _path = temporary;
    }

    ~FilesystemFixture()
    {
        chdir(_cwd.c_str());
        nftw(_path.c_str(), Remove, 16, FTW_DEPTH | FTW_PHYS);
    }

    FilesystemFixture(const FilesystemFixture &) = delete;
    FilesystemFixture &operator=(const FilesystemFixture &) = delete;
    const std::string &Path() const { return _path; }

private:
    static int Remove(const char *path, const struct stat *, int, struct FTW *)
    {
        return std::remove(path);
    }

    std::string _cwd;
    std::string _path;
};

#endif
