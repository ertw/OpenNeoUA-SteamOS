#include <algorithm>
#include <cctype>

#ifndef _WIN32
#include <strings.h>
#endif

#include "includes.h"
#include "utils.h"
#include "inttypes.h"
#include "crc32.h"
#include "env.h"
#include <SDL2/SDL_timer.h>


int read_yes_no_status(const std::string &file, int result)
{
    FSMgr::FileHandle *fil = uaOpenFileAlloc(file, "r");
    if ( fil )
    {
        std::string line;
        if ( fil->ReadLine(&line) )
        {
            size_t en = line.find_first_of("; \n\r");
            if (en != std::string::npos)
                line.erase(en);

            result = StrGetBool(line);
        }
        delete fil;
    }
    return result;
}

float SWAP32F(float f)
{
    uint32_t tmp = *(uint32_t *)&f;
    tmp = SWAP32(tmp);
    return *(float *)&tmp;
}



#ifndef strnicmp
int strnicmp (const char *s1, const char *s2, size_t n)
{
    const char *s2end = s2 + n;

    while (s2 < s2end && *s2 != 0 && toupper(*s1) == toupper(*s2))
        s1++, s2++;
    if (s2end == s2)
        return 0;
    return (int) (toupper(*s1) - toupper(*s2));
}
#endif

int dround(float val)
{
    return val + 0.5;
}

int dround(double val)
{
    return val + 0.5;
}

uint32_t fileCrc32(const std::string &filename, uint32_t _crc)
{
    uint32_t crc = _crc;

    FSMgr::FileHandle *fil = uaOpenFileAlloc(filename, "rb");
    if (fil)
    {
        const size_t BUFSZ = 4 * 1024;
        void *tmp = malloc(BUFSZ); //4K block

        size_t readed = fil->read(tmp, BUFSZ);
        while(readed != 0)
        {
            crc = crc32(crc, tmp, readed);
            readed = fil->read(tmp, BUFSZ);
        }
        free(tmp);
        delete fil;
    }
    return crc;
}


int DO = 0; //Shutup "MAKE ME" screams

void dprintf(const char *fmt, ...)
{
    if (DO)
    {
        va_list args;
        va_start (args, fmt);

        vprintf(fmt, args);

        va_end(args);
    }
}

uint32_t profiler_begin()
{
    Uint64 freq = SDL_GetPerformanceFrequency();

    if ( !freq )
        return 0;

    Uint64 cnt = SDL_GetPerformanceCounter();
    return cnt / (freq / 10000);
}

uint32_t profiler_end(uint32_t prev)
{
    Uint64 freq = SDL_GetPerformanceFrequency();

    if ( !freq )
        return 0 - prev;

    Uint64 cnt = SDL_GetPerformanceCounter();
    return cnt / (freq / 10000) - prev;
}



std::string correctSeparatorAndExt(std::string str)
{
    std::replace(str.begin(), str.end(), '/', '\\');

    size_t pos = str.rfind('.');
    if (pos != std::string::npos && (str.length() - pos - 1) > 3)
        str.resize(pos + 3 + 1);
    return str;
}

static bool uaNodeExistsAs(const std::string &path, int type)
{
    FSMgr::iNode *node = FSMgr::iDir::findNode(correctSeparatorAndExt(path));
    return node && node->getType() == type;
}

static bool uaFileExistsDirect(const std::string &path)
{
    return uaNodeExistsAs(path, FSMgr::iNode::NTYPE_FILE);
}

static bool uaDirExistsDirect(const std::string &path)
{
    return uaNodeExistsAs(path, FSMgr::iNode::NTYPE_DIR);
}

static std::string uaJoinPath(const std::string &base, const std::string &rest)
{
    if (rest.empty())
        return base;
    return base + "/" + rest;
}

static bool uaStandaloneRootDir(const std::string &first, std::string *canonical)
{
    static const char *dirs[] = {"3DS", "Env", "Fonts", "Levels", "Locale", "Music", "Res", "Save"};

    for (const char *dir : dirs)
    {
        if (!StriCmp(first, dir))
        {
            if (canonical)
                *canonical = dir;
            return true;
        }
    }

    return false;
}

static bool uaStandaloneReadRootDir(const std::string &first, std::string *canonical)
{
    static const char *dirs[] = {
        "3DS", "Database", "Env", "Filters", "Fonts", "Interface", "Levels",
        "Locale", "Music", "Res", "Save", "Scripts", "Sounds", "Wireless"
    };

    for (const char *dir : dirs)
    {
        if (!StriCmp(first, dir))
        {
            if (canonical)
                *canonical = dir;
            return true;
        }
    }

    return false;
}

static bool uaSplitSetDirectoryPath(std::string path, std::string *setDir, std::string *rest)
{
    std::replace(path.begin(), path.end(), '\\', '/');

    while (!path.empty() && path.front() == '/')
        path.erase(path.begin());

    const size_t firstSlash = path.find('/');
    if (firstSlash == std::string::npos || StriCmp(path.substr(0, firstSlash), "Data"))
        return false;

    const size_t secondSlash = path.find('/', firstSlash + 1);
    const std::string component = secondSlash == std::string::npos
                                      ? path.substr(firstSlash + 1)
                                      : path.substr(firstSlash + 1, secondSlash - firstSlash - 1);

    if (component.size() <= 3 || strnicmp(component.c_str(), "Set", 3))
        return false;

    for (size_t i = 3; i < component.size(); ++i)
    {
        if (!std::isdigit((unsigned char)component[i]))
            return false;
    }

    if (setDir)
        *setDir = component;
    if (rest)
        *rest = secondSlash == std::string::npos ? std::string() : path.substr(secondSlash + 1);

    return true;
}

static std::string uaOrganizedSetDirectoryPath(std::string path)
{
    std::string setDir;
    std::string rest;

    if (!uaSplitSetDirectoryPath(path, &setDir, &rest))
        return path;

    return uaJoinPath("Data/Sets/" + setDir, rest);
}

static std::string uaResolveSetDirectoryContainer(std::string path, bool directory)
{
    const std::string organizedPath = uaOrganizedSetDirectoryPath(path);
    if (organizedPath == path)
        return path;

    const bool organizedExists = directory ? uaDirExistsDirect(organizedPath)
                                           : uaFileExistsDirect(organizedPath);
    return organizedExists ? organizedPath : path;
}

static std::string uaResolveStandaloneDataFirst(std::string path, bool directory, bool forWrite)
{
    std::replace(path.begin(), path.end(), '\\', '/');

    while (!path.empty() && path.front() == '/')
        path.erase(path.begin());

    if (path.empty())
        return path;

    size_t slash = path.find('/');
    std::string first = slash == std::string::npos ? path : path.substr(0, slash);
    std::string rest = slash == std::string::npos ? std::string() : path.substr(slash + 1);
    std::string inputRoot = first;
    std::string canonical;

    // Read-only callers can arrive here through either a direct root path
    // (Scripts/foo) or an already expanded data: prefix (Data/Scripts/foo).
    // Normalize both spellings to the same Data-first candidate pair.  The
    // write path deliberately remains on the historical branch below.
    if (!forWrite && !StriCmp(first, "Data"))
    {
        if (rest.empty())
            return path;

        const size_t nestedSlash = rest.find('/');
        const std::string nestedRoot = nestedSlash == std::string::npos
                                           ? rest
                                           : rest.substr(0, nestedSlash);
        if (!uaStandaloneReadRootDir(nestedRoot, &canonical))
            return path;

        rest = nestedSlash == std::string::npos ? std::string() : rest.substr(nestedSlash + 1);
        inputRoot = nestedRoot;
        first = canonical;
    }

    if (forWrite ? !uaStandaloneRootDir(first, &canonical)
                 : !uaStandaloneReadRootDir(first, &canonical))
        return path;

    std::string dataDir = uaJoinPath("Data", canonical);
    std::string dataPath = uaJoinPath(dataDir, rest);
    std::string dataAliasDir = uaJoinPath("Data", inputRoot);
    std::string dataAliasPath = uaJoinPath(dataAliasDir, rest);
    std::string rootPath = uaJoinPath(inputRoot, rest);
    std::string canonicalRootPath = uaJoinPath(canonical, rest);
    std::string legacy3DSPath = uaJoinPath("3ds", rest);

    if (directory)
    {
        if (uaDirExistsDirect(dataPath))
            return dataPath;
        if (!forWrite && dataAliasDir != dataDir && uaDirExistsDirect(dataAliasPath))
            return dataAliasPath;
        if (forWrite && uaDirExistsDirect(dataDir))
            return dataPath;
        if (!forWrite && uaDirExistsDirect(canonicalRootPath))
            return canonicalRootPath;
        if (!forWrite && !StriCmp(canonical, "3DS") && uaDirExistsDirect(legacy3DSPath))
            return legacy3DSPath;
        return rootPath;
    }

    if (!StriCmp(canonical, "Save"))
    {
        if (uaDirExistsDirect(dataDir))
            return dataPath;
        if (!forWrite && dataAliasDir != dataDir && uaDirExistsDirect(dataAliasDir))
            return dataAliasPath;
        if (!forWrite && uaDirExistsDirect(canonicalRootPath))
            return canonicalRootPath;
        if (!forWrite && !StriCmp(canonical, "3DS") && uaDirExistsDirect(legacy3DSPath))
            return legacy3DSPath;
        return rootPath;
    }

    if (forWrite)
    {
        if (uaDirExistsDirect(dataDir))
            return dataPath;
        return rootPath;
    }

    if (uaFileExistsDirect(dataPath))
        return dataPath;
    if (dataAliasPath != dataPath && uaFileExistsDirect(dataAliasPath))
        return dataAliasPath;
    if (uaFileExistsDirect(canonicalRootPath))
        return canonicalRootPath;
    if (!StriCmp(canonical, "3DS") && uaFileExistsDirect(legacy3DSPath))
        return legacy3DSPath;

    return rootPath;
}

static std::string uaResolvePath(const std::string &path, bool directory, bool forWrite)
{
    std::string resolved = correctSeparatorAndExt(Common::Env.ApplyPrefix(path));
    if (!forWrite)
        resolved = uaResolveSetDirectoryContainer(resolved, directory);
    return correctSeparatorAndExt(uaResolveStandaloneDataFirst(resolved, directory, forWrite));
}

std::string uaSetDirectoryOrganizedPath(const std::string &path)
{
    std::string resolved = Common::Env.ApplyPrefix(path);
    std::replace(resolved.begin(), resolved.end(), '\\', '/');
    return uaOrganizedSetDirectoryPath(resolved);
}

std::string uaSetDirectoryResolvedReadPath(const std::string &path, bool directory)
{
    std::string resolved = correctSeparatorAndExt(Common::Env.ApplyPrefix(path));
    return correctSeparatorAndExt(uaResolveSetDirectoryContainer(resolved, directory));
}

std::string uaDataFirstNucleusIniPath()
{
    const char *candidates[] = {
        "Data/Nucleus.ini",
        "Data/nucleus.ini",
        "Nucleus.ini",
        "nucleus.ini"
    };

    for (const char *candidate : candidates)
    {
        if (uaFileExistsDirect(candidate))
            return correctSeparatorAndExt(candidate);
    }

    return "nucleus.ini";
}

std::string uaDataFirstResolvedReadPath(const std::string &path)
{
    return uaResolvePath(path, false, false);
}

std::string uaDataFirstResolvedWritePath(const std::string &path)
{
    return uaResolvePath(path, false, true);
}

std::vector<std::string> uaDataFirstRootDirCandidates(const std::string &dirname)
{
    std::vector<std::string> result;
    std::string canonical;

    if (!uaStandaloneReadRootDir(dirname, &canonical))
    {
        if (uaDirExistsDirect(dirname))
            result.push_back(correctSeparatorAndExt(dirname));
        return result;
    }

    std::string dataDir = uaJoinPath("Data", canonical);
    if (uaDirExistsDirect(dataDir))
        result.push_back(correctSeparatorAndExt(dataDir));

    if (uaDirExistsDirect(dirname))
        result.push_back(correctSeparatorAndExt(dirname));

    return result;
}

bool uaFileExist(const std::string &src_path)
{
    return FSMgr::iDir::fileExist(uaDataFirstResolvedReadPath(src_path));
}

//FSMgr::FileHandle *uaOpenFile(const char *src_path, const char *mode)
//{
//    std::string path;
//    file_path_copy_manipul(src_path, path);
//    correctSeparatorAndExt(path);
//
//    FSMgr::FileHandle *v4 = FSMgr::iDir::openFile(path.c_str(), mode);
//
//    if ( v4 )
//        engines.file_handles++;
//    else
//        ypa_log_out("uaOpenFile('%s','%s') failed!\n", path.c_str(), mode);
//
//    return v4;
//}

FSMgr::FileHandle *uaOpenFileAlloc(const std::string &src_path, const std::string &mode)
{
    bool forWrite = mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos;
    std::string path = forWrite ? uaDataFirstResolvedWritePath(src_path) : uaDataFirstResolvedReadPath(src_path);

    FSMgr::FileHandle *v4 = FSMgr::iDir::openFileAlloc(path, mode);

    if ( !v4 )
        ypa_log_out("uaOpenFile('%s','%s') failed!\n", path.c_str(), mode.c_str());

    return v4;
}

FSMgr::FileHandle uaOpenFile(const std::string &src_path, const std::string &mode)
{
    bool forWrite = mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos;
    std::string path = forWrite ? uaDataFirstResolvedWritePath(src_path) : uaDataFirstResolvedReadPath(src_path);

    return FSMgr::iDir::openFile(path, mode);
}

FSMgr::DirIter uaOpenDir(const std::string &dir)
{
    std::string dst = uaResolvePath(dir, true, false);
    return FSMgr::iDir::readDir(dst);
}

bool uaDeleteFile(const std::string &path)
{
    std::string dst = uaDataFirstResolvedWritePath(path);
    return FSMgr::iDir::deleteFile(dst);
}

bool uaDeleteDir(const std::string &path)
{
    std::string dst = uaResolvePath(path, true, true);
    return FSMgr::iDir::deleteDir(dst);
}

bool uaCreateDir(const std::string &path)
{
    std::string dst = uaResolvePath(path, true, true);
    return FSMgr::iDir::createDir(dst);
}

int StriCmp(const std::string &a, const std::string &b)
{
	return strcasecmp(a.c_str(), b.c_str());
}

bool StrGetBool(const std::string &str)
{
    return !StriCmp(str, "yes") || !StriCmp(str, "true") || !StriCmp(str, "on") || !StriCmp(str, "1");
}
