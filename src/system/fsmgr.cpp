#include <string.h>
#include <stdarg.h>
#include <inttypes.h>
#include <algorithm>
#include <errno.h>
#include <limits.h>

#if defined(WIN32) && !defined(__WINE__)

#include <windows.h>

#else

#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <unistd.h>
#endif

#include "fsmgr.h"
#include "../utils.h"


namespace FSMgr
{
#if defined(WIN32) && !defined(__WINE__)
const static std::string FSD("\\");
#else
const static std::string FSD("/");
#endif

static iDir directories("", "");
bool iDir::_overlayEnabled = false;
std::string iDir::_assetRoot;
std::string iDir::_userRoot;
iDir iDir::_assetDirectories("", "");

static std::string fsNormalizeRoot(const std::string &input)
{
    std::string result = input;
    while (result.size() > 1 && (result.back() == '/' || result.back() == '\\'))
        result.pop_back();
    return result.empty() ? std::string(".") : result;
}

static bool fsPathInside(const std::string &root, const std::string &path)
{
    if (root.empty())
        return false;
    if (path == root)
        return true;
    if (path.size() <= root.size())
        return false;
    return path.compare(0, root.size(), root) == 0 &&
           (path[root.size()] == '/' || path[root.size()] == '\\');
}

iNode::iNode(const std::string &_name, const std::string &filepath)
{
    name = _name;
    path = filepath;
}

int iNode::getType()
{
    return type;
}

std::string iNode::getPath() const
{
    return path;
}

std::string iNode::getName() const
{
    return name;
}

std::string iNode::getVPath() const
{
    if (parent != NULL)
        return parent->getVPath() + FSD + name;
    else
        return name;
}

bool iNode::Detach()
{
    if (!parent)
        return true;

    return parent->Detach(this);
}




iFile::iFile(const std::string &_name, const std::string &filepath):
    iNode(_name, filepath)
{
    type = NTYPE_FILE;
}


iDir::iDir(const std::string &_name, const std::string &filepath):
    iNode(_name, filepath)
{
    type = NTYPE_DIR;
}

iDir::~iDir()
{
    flush();
}

iDir *iDir::GetRoot()
{
    return &directories;
}

std::string iDir::_normalizeVirtualPath(const std::string &value)
{
    std::string result = value;
    std::replace(result.begin(), result.end(), '\\', '/');
    while (!result.empty() && result.front() == '/')
        result.erase(result.begin());
    while (!result.empty() && result.back() == '/')
        result.pop_back();

    if (result.empty())
        return result;

    std::string part;
    size_t start = 0;
    while (start <= result.size())
    {
        size_t end = result.find('/', start);
        std::string component = end == std::string::npos
                              ? result.substr(start)
                              : result.substr(start, end - start);
        if (component.empty() || component == "." || component == ".." || component.find('\0') != std::string::npos)
            return std::string();
        if (start == 0)
            part = component;
        else
            part += "/" + component;
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    return part;
}

std::string iDir::_userPath(const std::string &path)
{
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return fsNormalizeRoot(_userRoot);
    return fsNormalizeRoot(_userRoot) + FSD + logical;
}

std::string iDir::_assetPath(const std::string &path)
{
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return fsNormalizeRoot(_assetRoot);
    return fsNormalizeRoot(_assetRoot) + FSD + logical;
}

bool iDir::_ensureDirectory(const std::string &path)
{
    std::string target = fsNormalizeRoot(path);
    if (target == ".")
        return true;

    std::string prefix;
#if defined(WIN32) && !defined(__WINE__)
    if (target.size() > 1 && target[1] == ':')
        prefix = target.substr(0, 2);
    else if (!target.empty() && (target[0] == '/' || target[0] == '\\'))
        prefix = target.substr(0, 1);
#else
    if (!target.empty() && target[0] == '/')
        prefix = "/";
#endif
    size_t start = prefix.empty() ? 0 : prefix.size();
    while (start <= target.size())
    {
        size_t end = target.find_first_of("/\\", start);
        std::string component = end == std::string::npos
                              ? target.substr(start)
                              : target.substr(start, end - start);
        if (!component.empty())
        {
            if (!prefix.empty() && prefix.back() != '/' && prefix.back() != '\\')
                prefix += FSD;
            prefix += component;
#if defined(WIN32) && !defined(__WINE__)
            DWORD attr = GetFileAttributes(prefix.c_str());
            if (attr == INVALID_FILE_ATTRIBUTES)
            {
                if (!CreateDirectory(prefix.c_str(), NULL))
                    return false;
            }
            else if (!(attr & FILE_ATTRIBUTE_DIRECTORY))
                return false;
#else
            struct stat info;
            if (lstat(prefix.c_str(), &info) == 0)
            {
                if (!S_ISDIR(info.st_mode))
                {
                    return false;
                }
            }
            else if (mkdir(prefix.c_str(), 0755) != 0 && errno != EEXIST)
            {
                return false;
            }
#endif
        }
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    return true;
}

bool iDir::_isTombstoned(const std::string &path)
{
    if (!_overlayEnabled)
        return false;
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return false;
    std::string marker = fsNormalizeRoot(_userRoot) + FSD + ".openneoua-deleted" + FSD + logical + ".delete";
#if defined(WIN32) && !defined(__WINE__)
    DWORD attr = GetFileAttributes(marker.c_str());
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
#else
    struct stat info;
    return lstat(marker.c_str(), &info) == 0 && S_ISREG(info.st_mode);
#endif
}

bool iDir::_writeTombstone(const std::string &path)
{
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return false;
    std::string markerDirectory = fsNormalizeRoot(_userRoot) + FSD + ".openneoua-deleted";
    size_t slash = logical.find_last_of('/');
    if (slash != std::string::npos)
        markerDirectory += FSD + logical.substr(0, slash);
    if (!_ensureDirectory(markerDirectory))
        return false;
    std::string marker = fsNormalizeRoot(_userRoot) + FSD + ".openneoua-deleted" + FSD + logical + ".delete";
#if !defined(WIN32) || defined(__WINE__)
    struct stat markerInfo;
    if (lstat(marker.c_str(), &markerInfo) == 0 && S_ISLNK(markerInfo.st_mode))
        return false;
#endif
    FILE *file = fopen(marker.c_str(), "wb");
    if (!file)
        return false;
    fputs("deleted\n", file);
    fclose(file);
    return true;
}

bool iDir::_removeTombstone(const std::string &path)
{
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return false;
    std::string marker = fsNormalizeRoot(_userRoot) + FSD + ".openneoua-deleted" + FSD + logical + ".delete";
#if defined(WIN32) && !defined(__WINE__)
    return DeleteFile(marker.c_str()) != 0 || GetLastError() == ERROR_FILE_NOT_FOUND;
#else
    return remove(marker.c_str()) == 0 || errno == ENOENT;
#endif
}

bool iDir::_isUpdateMode(const std::string &mode)
{
    return mode.find('+') != std::string::npos || mode.find('a') != std::string::npos;
}

bool iDir::_removeOverlayNode(iNode *node)
{
    if (!node || !node->parent)
        return false;

    iDir *parent = node->parent;
    if (!parent->Detach(node))
        return false;

    delete node;
    return true;
}

bool iDir::_copyAssetToUser(const std::string &path)
{
    if (!_overlayEnabled)
        return false;
    std::string logical = _normalizeVirtualPath(path);
    std::string remaining;
    iNode *asset = _assetDirectories._parseNodePath(logical, &remaining);
    if (!remaining.empty())
        asset = NULL;
    if (!asset || asset->getType() != NTYPE_FILE)
        return false;
    std::string source = asset->path;
    std::string destination = _userPath(logical);
    size_t slash = destination.find_last_of("/\\");
    if (slash != std::string::npos && !_ensureDirectory(destination.substr(0, slash)))
    {
        return false;
    }
#if !defined(WIN32) || defined(__WINE__)
    struct stat destinationInfo;
    if (lstat(destination.c_str(), &destinationInfo) == 0 && S_ISLNK(destinationInfo.st_mode))
        return false;
#endif
    FILE *in = fopen(source.c_str(), "rb");
    if (!in)
        return false;
    FILE *out = fopen(destination.c_str(), "wb");
    if (!out)
    {
        fclose(in);
        return false;
    }
    char buffer[64 * 1024];
    size_t readCount = 0;
    bool ok = true;
    while ((readCount = fread(buffer, 1, sizeof(buffer), in)) != 0)
    {
        if (fwrite(buffer, 1, readCount, out) != readCount)
        {
            ok = false;
            break;
        }
    }
    if (ferror(in))
        ok = false;
    if (fclose(out) != 0)
        ok = false;
    fclose(in);
    if (!ok)
    {
#if defined(WIN32) && !defined(__WINE__)
        DeleteFile(destination.c_str());
#else
        remove(destination.c_str());
#endif
    }
    return ok;
}

std::string iDir::_nodeVPath(iNode *node)
{
    if (!node)
        return std::string();
    std::string path = node->getVPath();
    return _normalizeVirtualPath(path);
}

std::string iDir::_writeLogicalPath(const std::string &path)
{
    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return logical;
    std::string remaining;
    iNode *node = directories._parseNodePath(logical, &remaining);
    if (node && remaining.empty())
        return _nodeVPath(node);
    if (node && node->getType() == NTYPE_DIR && !remaining.empty())
    {
        std::string parent = _nodeVPath(node);
        return parent.empty() ? _normalizeVirtualPath(remaining) : parent + "/" + remaining;
    }
    return logical;
}

static bool fsRegularPath(const std::string &path)
{
#if defined(WIN32) && !defined(__WINE__)
    DWORD attributes = GetFileAttributes(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
#else
    struct stat info;
    return lstat(path.c_str(), &info) == 0 && S_ISREG(info.st_mode);
#endif
}

std::string iDir::_readPhysicalPath(iNode *node)
{
    if (!node)
        return std::string();

    // A merged node may still carry the packaged path after a copy-on-write
    // operation (or after another process created an override).  Resolve the
    // user copy at the last possible moment so reads never fall back to the
    // immutable payload accidentally.
    if (_overlayEnabled && node->type == NTYPE_FILE)
    {
        std::string logical = _nodeVPath(node);
        std::string userPath = _userPath(logical);
        if (fsRegularPath(userPath))
            return userPath;
    }
    return node->path;
}

void iDir::_syncOverlayDirectory(const std::string &path, const std::string &diskPath)
{
    if (!_overlayEnabled)
        return;

    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return;

    iDir *current = &directories;
    std::string physical = fsNormalizeRoot(_userRoot);
    size_t start = 0;
    while (start < logical.size())
    {
        size_t end = logical.find('/', start);
        std::string component = end == std::string::npos
                              ? logical.substr(start)
                              : logical.substr(start, end - start);
        if (component.empty())
            return;

        physical += FSD + component;
        iNode *child = current->getNode(component);
        if (child)
        {
            if (child->type != NTYPE_DIR)
                return;
            current = static_cast<iDir *>(child);
            // The directory itself may have been copied from the asset tree.
            // Keep its physical path accurate for callers using getPath().
            current->path = physical;
        }
        else
        {
            iDir *created = new iDir(component, physical);
            current->addNode(created);
            current = created;
        }

        if (end == std::string::npos)
            break;
        start = end + 1;
    }

    // ``diskPath`` is the canonical physical path supplied by the caller;
    // prefer it over the spelling reconstructed above when available.
    if (current)
        current->path = diskPath;
}

void iDir::_syncOverlayFile(const std::string &path, const std::string &diskPath)
{
    if (!_overlayEnabled)
        return;

    std::string logical = _normalizeVirtualPath(path);
    if (logical.empty())
        return;

    size_t slash = logical.find_last_of('/');
    std::string parentPath = slash == std::string::npos ? std::string() : logical.substr(0, slash);
    std::string name = slash == std::string::npos ? logical : logical.substr(slash + 1);
    if (name.empty())
        return;

    iDir *parent = &directories;
    if (!parentPath.empty())
    {
        std::string remainder;
        iNode *parentNode = directories._parseNodePath(parentPath, &remainder);
        if (parentNode && remainder.empty() && parentNode->type == NTYPE_DIR)
            parent = static_cast<iDir *>(parentNode);
        else
        {
            std::string parentDisk = diskPath.substr(0, diskPath.find_last_of("/\\"));
            _syncOverlayDirectory(parentPath, parentDisk);
            parentNode = directories._parseNodePath(parentPath, &remainder);
            if (!parentNode || !remainder.empty() || parentNode->type != NTYPE_DIR)
                return;
            parent = static_cast<iDir *>(parentNode);
        }
    }

    iNode *node = parent->getNode(name);
    if (node)
    {
        if (node->type == NTYPE_FILE)
            node->path = diskPath;
        return;
    }
    parent->addNode(new iFile(name, diskPath));
}

iNode *iDir::_cloneNode(const iNode *node)
{
    if (!node)
        return NULL;
    if (node->type == NTYPE_DIR)
    {
        const iDir *source = static_cast<const iDir *>(node);
        iDir *result = new iDir(source->name, source->path);
        for (std::list<iNode *>::const_iterator it = source->nodes.begin(); it != source->nodes.end(); ++it)
            result->addNode(_cloneNode(*it));
        return result;
    }
    if (node->type == NTYPE_FILE)
        return new iFile(node->name, node->path);
    return NULL;
}

void iDir::_mergeAssetTree(iDir *dst, const iDir *src, const std::string &prefix)
{
    for (std::list<iNode *>::const_iterator it = src->nodes.begin(); it != src->nodes.end(); ++it)
    {
        iNode *assetNode = *it;
        std::string logical = prefix.empty() ? assetNode->name : prefix + "/" + assetNode->name;
        if (_isTombstoned(logical))
            continue;
        iNode *userNode = dst->getNode(assetNode->name);
        if (!userNode)
        {
            iNode *copy = _cloneNode(assetNode);
            if (copy)
                dst->addNode(copy);
            continue;
        }
        if (userNode->type == NTYPE_DIR && assetNode->type == NTYPE_DIR)
            _mergeAssetTree(static_cast<iDir *>(userNode), static_cast<const iDir *>(assetNode), logical);
        // A writable user file/dir wins a packaged node of the other type.
    }
}

void iDir::_rebuildOverlay()
{
    if (!_overlayEnabled)
        return;
    directories.flush();
    _assetDirectories.flush();
    _ensureDirectory(_userRoot);
    _scanDir(&directories, "", fsNormalizeRoot(_userRoot), NULL);
    _scanDir(&_assetDirectories, "", fsNormalizeRoot(_assetRoot), NULL);
    _mergeAssetTree(&directories, &_assetDirectories, std::string());
}

void iDir::setRoots(const std::string &assetRoot, const std::string &userDir)
{
    std::string assets = fsNormalizeRoot(assetRoot);
    std::string user = fsNormalizeRoot(userDir);
#if !defined(WIN32) || defined(__WINE__)
    // Resolve host aliases such as macOS /tmp -> /private/tmp once.  This
    // keeps the strict lstat checks in _ensureDirectory from rejecting a
    // harmless system alias while still rejecting symlinks inside user data.
    char resolved[PATH_MAX];
    if (realpath(assets.c_str(), resolved))
        assets = resolved;
    if (realpath(user.c_str(), resolved))
        user = resolved;
    else
    {
        size_t slash = user.find_last_of('/');
        if (slash != std::string::npos)
        {
            std::string parent = user.substr(0, slash);
            std::string leaf = user.substr(slash + 1);
            if (realpath(parent.c_str(), resolved))
                user = std::string(resolved) + "/" + leaf;
        }
        if (_ensureDirectory(user) && realpath(user.c_str(), resolved))
            user = resolved;
    }
#endif
    _assetRoot = assets;
    _userRoot = user;
    _overlayEnabled = true;
    _rebuildOverlay();
}

void iDir::setAssetRoot(const std::string &assetRoot)
{
    setRoots(assetRoot, _userRoot.empty() ? "." : _userRoot);
}

void iDir::setUserDir(const std::string &userDir)
{
    setRoots(_assetRoot.empty() ? "." : _assetRoot, userDir);
}

std::string iDir::getAssetRoot()
{
    return _assetRoot;
}

std::string iDir::getUserDir()
{
    return _userRoot;
}

std::string iDir::resolveUserPath(const std::string &path)
{
    if (!_overlayEnabled)
        return path;
    return _userPath(path);
}

bool iDir::overlayActive()
{
    return _overlayEnabled;
}

void iDir::addNode(iNode *nw)
{
    nw->Detach();
    nw->parent = this;
    nodes.push_back(nw);
}

iNode *iDir::getNode(const std::string &n)
{
    if ( n == "." )
        return this;
    else if ( n == ".." )
        return parent;
    else
    {
        for (const auto &i : nodes)
        {
            if ( !StriCmp(n, i->name) )
                return i;
        }
    }

    return NULL;
}

void iDir::flush()
{
    while(!nodes.empty())
    {
        iNode *n = nodes.front();
        nodes.pop_front();

        n->parent = NULL;
        delete n;
    }
}


void iDir::_dumpdir()
{
    std::string pth = getVPath();
    printf("%s \t(%s)\n", pth.c_str(), getPath().c_str());

    for (std::list<iNode *>::iterator it = nodes.begin(); it != nodes.end(); it++)
    {
        if ( (*it)->getType() == iNode::NTYPE_FILE )
        {
            printf("%s%s%s \t(%s)\n", pth.c_str(), FSD.c_str(), (*it)->getName().c_str(), (*it)->getPath().c_str());
        }
    }

    for (std::list<iNode *>::iterator it = nodes.begin(); it != nodes.end(); it++)
    {
        if ( (*it)->getType() == iNode::NTYPE_DIR )
        {
            ((iDir *) (*it) )->_dumpdir();
        }
    }
}


#if defined(WIN32) && !defined(__WINE__)
iDir *iDir::_scanDir(iDir *_node, const std::string &_name, const std::string &_path, iDir *_parent)
{
    std::string tmp = _path + "\\*";

    WIN32_FIND_DATA fdata;
    HANDLE hf = FindFirstFile(tmp.c_str(), &fdata);
    if (hf == INVALID_HANDLE_VALUE)
        return NULL;

    tmp.pop_back(); // delete *

    iDir *ndr;

    if ( !_node )
    {
        ndr = new iDir(_name, _path);
        ndr->parent = _parent;
    }
    else
    {
        _node->name = _name;
        _node->path = _path;
        _node->parent = _parent;

        ndr = _node;
    }

    do
    {
        if ( strcmp(fdata.cFileName, ".") != 0 && strcmp(fdata.cFileName, "..") != 0 )
        {
            if (strcmp(fdata.cFileName, ".openneoua-deleted") == 0)
                continue;
            std::string tmp2 = tmp + fdata.cFileName;

            if (fdata.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            {
                iNode *sub = _scanDir(NULL, fdata.cFileName, tmp2, ndr);
                if (sub)
                    ndr->addNode(sub);
            }
            else
            {
                ndr->addNode(new iFile(fdata.cFileName, tmp2));
            }
        }
    }
    while ( FindNextFile(hf, &fdata) != 0);

    FindClose(hf);

    return ndr;
}
#else
iDir *iDir::_scanDir(iDir *_node, const std::string &_name, const std::string &_path, iDir *_parent)
{
    DIR *dr = opendir(_path.c_str());
    if (!dr)
        return NULL;

    iDir *ndr;

    if ( !_node )
    {
        ndr = new iDir(_name, _path);
        ndr->parent = _parent;
    }
    else
    {
        _node->name = _name;
        _node->path = _path;
        _node->parent = _parent;

        ndr = _node;
    }

    std::string tmp = _path + "/";

    for (dirent *ent = readdir(dr); ent; ent = readdir(dr))
    {
        if (ent->d_type == DT_REG || ent->d_type == DT_DIR)
        {
            if ( strcmp(ent->d_name, ".") != 0 && strcmp(ent->d_name, "..") != 0 )
            {
                if (strcmp(ent->d_name, ".openneoua-deleted") == 0)
                    continue;
                std::string tmp2 = tmp + ent->d_name;

                if (ent->d_type == DT_REG)
                {
                    ndr->addNode(new iFile(ent->d_name, tmp2) );
                }
                else
                {
                    iNode *sub = _scanDir(NULL, ent->d_name, tmp2, ndr);
                    if (sub)
                        ndr->addNode(sub);
                }
            }
        }
    }

    closedir(dr);

    return ndr;
}
#endif // WIN32


void iDir::setBaseDir(const std::string &_path)
{
    _overlayEnabled = false;
    _assetRoot.clear();
    _userRoot.clear();
    _assetDirectories.flush();
    std::string tmp = _path;

    if (!tmp.empty() && (tmp.back() == '\\' || tmp.back() == '/') )
        tmp.pop_back();

    if (tmp.empty())
        tmp = ".";

    directories.flush();

    _scanDir(&directories, "", tmp, NULL);
}

iNode *iDir::_createNodeFromPath(const std::string &diskPath)
{
    iNode *node = NULL;

    std::string tmp = diskPath;
    if (!tmp.empty() && (tmp.back() == '\\' || tmp.back() == '/') )
        tmp.pop_back();

    if (tmp.empty())
        tmp = ".";

    std::string tmpName = tmp;

    size_t ps = tmpName.find_last_of("\\/");

    if (ps != std::string::npos)
        tmpName = tmpName.substr(ps + 1);

#if defined(WIN32) && !defined(__WINE__)
    DWORD attr = GetFileAttributes(diskPath.c_str());
    if ( attr != INVALID_FILE_ATTRIBUTES)
    {
        if ( attr & FILE_ATTRIBUTE_DIRECTORY )
            node = _scanDir(NULL, tmpName, tmp, NULL);
        else
            node = new iFile(tmpName, tmp);
    }
#else
    struct stat attr;

    if ( stat(diskPath.c_str(), &attr) == 0)
    {
        if ( S_ISDIR(attr.st_mode) )
            node = _scanDir(NULL, tmpName, tmp, NULL);
        else if ( S_ISREG(attr.st_mode) )
            node = new iFile(tmpName, tmp);
    }
#endif // WIN32

    return node;
}


bool iDir::replacePath(const std::string &path, const std::string &diskPath)
{
    std::string leaved;
    iNode *oldNode = directories._parseNodePath(path, &leaved);

    if (!oldNode || !leaved.empty())
        return false;

    if (oldNode->parent == NULL) //It's root node, we can't replace it
        return false;

    iNode *newNode = _createNodeFromPath(diskPath);

    if (!newNode)
        return false;

    iDir *upNode = oldNode->parent;

    for (std::list<iNode *>::iterator it = upNode->nodes.begin(); it != upNode->nodes.end(); it++)
    {
        if ( *it == oldNode )
        {
            newNode->name = oldNode->name;
            newNode->parent = upNode;
            *it = newNode;

            delete oldNode;
            return true;
        }
    }

    delete newNode;
    return false;
}





iNode *iDir::_parseNodePath(const std::string &vpath, std::string *out)
{
    iDir *curdir = this;
    iNode *node = this;
    out->clear();

    size_t pos = 0;
    while(pos != std::string::npos)
    {
        size_t start = pos;
        pos = vpath.find_first_of("/\\", start);

        std::string vname;
        if (pos == std::string::npos)
            vname = vpath.substr(start);
        else
        {
            vname = vpath.substr(start, pos - start);
            pos++; //Next symbol
        }

        if (!vname.empty())
        {
            iNode *nd = curdir->getNode( vname );

            if (!nd)
            {
                *out = vpath.substr(start);
                return node;
            }
            else
            {
                if (nd->getType() == iNode::NTYPE_DIR)
                {
                    curdir = (iDir *)nd;
                    node = nd;
                }
                else
                    return nd;
            }
        }
    }

    return node;
}


bool iDir::createDir(const std::string &path)
{
    if (_overlayEnabled)
    {
        std::string logical = _writeLogicalPath(path);
        if (logical.empty())
            return false;
        iNode *existing = findNode(logical);
        if (existing && existing->getType() != NTYPE_DIR)
            return false;
        std::string target = _userPath(existing ? _nodeVPath(existing) : logical);
        if (!_ensureDirectory(target))
            return false;
        _removeTombstone(existing ? _nodeVPath(existing) : logical);
        _syncOverlayDirectory(existing ? _nodeVPath(existing) : logical, target);
        return true;
    }
    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (node)
    {
        if ( node->getType() != NTYPE_DIR )
            return false;

        if ( !leaved.empty() ) //If not exist
        {
            if (leaved.length() > 1 && (leaved.back() == '\\' || leaved.back() == '/') )
                leaved.pop_back();

            if ( leaved.find_first_of("\\/") == std::string::npos )
            {
                std::string newPath = node->path + FSD + leaved;

                iDir *newDir = NULL;
#if defined(WIN32) && !defined(__WINE__)
                if (CreateDirectory(newPath.c_str(), NULL))
                    newDir = new iDir(leaved, newPath);
#else
                if (mkdir(newPath.c_str(), 0755) == 0)
                    newDir = new iDir(leaved, newPath);
#endif // WIN32

                if (!newDir)
                    return false;

                ((iDir *)node)->addNode(newDir);
            }
            else
                return false;
        }
    }
    else
        return false;

    return true;
}

iDir *iDir::MakeDir(const std::string &vname)
{
    if (vname.empty() || vname.find_first_of("\\/") != std::string::npos)
        return NULL;

    if (_overlayEnabled)
    {
        std::string logical = _nodeVPath(this);
        if (!logical.empty())
            logical += "/";
        logical += vname;
        if (!createDir(logical))
            return NULL;
        iNode *node = findNode(logical);
        return node && node->getType() == NTYPE_DIR ? static_cast<iDir *>(node) : NULL;
    }

    iNode *node = getNode(vname);
    if (node)
    {
        if ( node->getType() != NTYPE_DIR )
            return NULL;
        return (iDir *)node;
    }

    std::string newPath = path + FSD + vname;

    iDir *newDir = NULL;
#if defined(WIN32) && !defined(__WINE__)
    if (CreateDirectory(newPath.c_str(), NULL))
        newDir = new iDir(vname, newPath);
#else
    if (mkdir(newPath.c_str(), 0755) == 0)
        newDir = new iDir(vname, newPath);
#endif // WIN32

    if (!newDir)
        return NULL;

    addNode(newDir);
    return newDir;
}

bool iDir::deleteDir(const std::string &path)
{
    if (_overlayEnabled)
    {
        std::string logical = _writeLogicalPath(path);
        if (logical.empty())
            return false;
        iNode *node = findNode(logical);
        if (!node || node->getType() != NTYPE_DIR || node->parent == NULL)
            return false;
        std::string actual = _nodeVPath(node);
        std::string userPath = _userPath(actual);
        bool hasAsset = false;
        std::string remaining;
        iNode *assetNode = _assetDirectories._parseNodePath(actual, &remaining);
        if (!remaining.empty())
            assetNode = NULL;
        hasAsset = assetNode && assetNode->getType() == NTYPE_DIR;

        // Record the package deletion before touching the writable directory.
        // If the physical removal fails, roll the marker back so the merged
        // view and the two backing trees remain consistent.
        bool tombstoneWritten = false;
        if (hasAsset)
        {
            if (!_writeTombstone(actual))
                return false;
            tombstoneWritten = true;
        }
#if defined(WIN32) && !defined(__WINE__)
        DWORD userAttr = GetFileAttributes(userPath.c_str());
        if (userAttr != INVALID_FILE_ATTRIBUTES)
        {
            if (!(userAttr & FILE_ATTRIBUTE_DIRECTORY) || !RemoveDirectory(userPath.c_str()))
            {
                if (tombstoneWritten)
                    _removeTombstone(actual);
                return false;
            }
        }
#else
        struct stat userInfo;
        if (lstat(userPath.c_str(), &userInfo) == 0)
        {
            if (!S_ISDIR(userInfo.st_mode) || rmdir(userPath.c_str()) != 0)
            {
                if (tombstoneWritten)
                    _removeTombstone(actual);
                return false;
            }
        }
#endif
        if (!_removeOverlayNode(node))
        {
            if (tombstoneWritten)
                _removeTombstone(actual);
            return false;
        }
        return true;
    }
    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (node)
    {
        if ( node->getType() != NTYPE_DIR )
            return false;

        if ( !leaved.empty() ) //If not exist
            return false;

        if ( node->parent == NULL )
            return false;

#if defined(WIN32) && !defined(__WINE__)
        if ( !RemoveDirectory(node->path.c_str()) )
            return false;
#else
        if (rmdir(node->path.c_str()) == -1)
            return false;
#endif // WIN32

        node->parent->nodes.remove(node);
        delete node;
    }
    else
        return false;

    return true;
}

DirIter iDir::readDir(const std::string &path)
{
    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (!node)
        return DirIter();

    if ( node->getType() != NTYPE_DIR )
        return DirIter();

    if ( !leaved.empty() ) //If not exist
        return DirIter();

    return DirIter( (iDir *)node );
}

void iDir::Override(iDir *nod)
{
    if (!nod || nod == this)
        return;

    path = nod->path;

    // Move one source node at a time.  The old implementation advanced an
    // iterator from ``nod->nodes`` by erasing from ``this->nodes``; that is
    // undefined as soon as the destination already contains entries.  Erase
    // the source iterator before merging so both lists remain valid.
    while (!nod->nodes.empty())
    {
        std::list<iNode *>::iterator it = nod->nodes.begin();
        iNode *nev = *it;
        nod->nodes.erase(it);
        nev->parent = NULL;

        iNode *old = getNode(nev->name);

        if (old)
        {
            // Do mix by override
            if ( nev->type == NTYPE_DIR &&
                 nev->type == old->type )
            {
                dynamic_cast<iDir *>(old)->Override( dynamic_cast<iDir *>(nev) );
                delete nev;
            }
            else // Replace
            {
                Detach(old);
                delete old;

                addNode(nev);
            }
        }
        else
            addNode(nev);
    }
}


iNode *iDir::findNode(const std::string &path)
{
    if (path.empty())
        return &directories;

    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (!node)
        return NULL;

    if ( !leaved.empty() ) //If not exist
        return NULL;

    return node;
}

bool iDir::fileExist(const std::string &path)
{
    iNode *tmp = findNode(path);

    if (!tmp)
        return false;

    if (tmp->getType() != NTYPE_FILE)
        return false;

    return true;
}


FileHandle *iDir::openFileAlloc(iNode *nod, const std::string &mode)
{
    if (!nod)
        return NULL;

    if ( nod->getType() != NTYPE_FILE )
        return NULL;

    if (_overlayEnabled && (mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos))
        return openFileAlloc(_nodeVPath(nod), mode);

    FileHandle * fhnd = new FileHandle(_readPhysicalPath(nod), mode);
    if (!fhnd->OK())
    {
        delete fhnd;
        return NULL;
    }

    return fhnd;
}

FileHandle *iDir::openFileAlloc(const std::string &path, const std::string &mode)
{
    if (_overlayEnabled && (mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos))
    {
        std::string logical = _writeLogicalPath(path);
        if (logical.empty())
            return NULL;
        iNode *node = findNode(logical);
        std::string actual = node ? _nodeVPath(node) : logical;
        if (node && node->getType() != NTYPE_FILE)
            return NULL;
        std::string userPath = _userPath(actual);
        bool userExists = false;
#if defined(WIN32) && !defined(__WINE__)
        DWORD userAttr = GetFileAttributes(userPath.c_str());
        userExists = userAttr != INVALID_FILE_ATTRIBUTES && !(userAttr & FILE_ATTRIBUTE_DIRECTORY);
#else
        struct stat userInfo;
        if (lstat(userPath.c_str(), &userInfo) == 0 && S_ISLNK(userInfo.st_mode))
            return NULL;
        userExists = lstat(userPath.c_str(), &userInfo) == 0 && S_ISREG(userInfo.st_mode);
#endif
        bool assetOnly = node && !userExists && fsPathInside(fsNormalizeRoot(_assetRoot), node->path);
        if (assetOnly && _isUpdateMode(mode) && !_copyAssetToUser(actual))
            return NULL;
        std::string parent = userPath;
        size_t slash = parent.find_last_of("/\\");
        if (slash != std::string::npos && !_ensureDirectory(parent.substr(0, slash)))
            return NULL;
        _removeTombstone(actual);
        FileHandle *fhnd = new FileHandle(userPath, mode);
        if (!fhnd->OK())
        {
            delete fhnd;
            return NULL;
        }
        _syncOverlayFile(actual, userPath);
        return fhnd;
    }
    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (!node)
        return NULL;

    if ( !leaved.empty() ) // Not exists
    {
        if (mode.find('r') != std::string::npos) //it's must be exist for reading
            return NULL;

        if (node->getType() != NTYPE_DIR ) // If node not dir
            return NULL;

        if ( leaved.find_first_of("\\/") != std::string::npos ) // With path
            return NULL;

        if (node->getType() != NTYPE_DIR)
            return NULL;

        iDir *dr = (iDir *)node;

        std::string newPath = dr->path + FSD + leaved;

        FileHandle * fhnd = new FileHandle(newPath, mode);

        if (!fhnd->OK())
        {
            delete fhnd;
            return NULL;
        }

        dr->addNode( new iFile(leaved, newPath) );
        return fhnd;
    }
    else if ( node->getType() == NTYPE_FILE ) // if exist and file
    {
        FileHandle * fhnd = new FileHandle(node->path, mode);

        if (!fhnd->OK())
        {
            delete fhnd;
            return NULL;
        }

        return fhnd;
    }

    return NULL;
}

FileHandle iDir::openFile(iNode *nod, const std::string &mode)
{
    if (!nod)
        return NULL;

    if ( nod->getType() != NTYPE_FILE )
        return NULL;

    if (_overlayEnabled && (mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos))
        return openFile(_nodeVPath(nod), mode);
        return FileHandle(_readPhysicalPath(nod), mode);
}

FileHandle iDir::openFile(const std::string &path, const std::string &mode)
{
    if (_overlayEnabled && (mode.find('r') == std::string::npos || mode.find('+') != std::string::npos || mode.find('a') != std::string::npos))
    {
        std::string logical = _writeLogicalPath(path);
        if (logical.empty())
            return FileHandle();
        iNode *node = findNode(logical);
        std::string actual = node ? _nodeVPath(node) : logical;
        if (node && node->getType() != NTYPE_FILE)
            return FileHandle();
        std::string userPath = _userPath(actual);
        bool userExists = false;
#if defined(WIN32) && !defined(__WINE__)
        DWORD userAttr = GetFileAttributes(userPath.c_str());
        userExists = userAttr != INVALID_FILE_ATTRIBUTES && !(userAttr & FILE_ATTRIBUTE_DIRECTORY);
#else
        struct stat userInfo;
        if (lstat(userPath.c_str(), &userInfo) == 0 && S_ISLNK(userInfo.st_mode))
            return FileHandle();
        userExists = lstat(userPath.c_str(), &userInfo) == 0 && S_ISREG(userInfo.st_mode);
#endif
        if (node && !userExists && fsPathInside(fsNormalizeRoot(_assetRoot), node->path) && _isUpdateMode(mode) && !_copyAssetToUser(actual))
            return FileHandle();
        size_t slash = userPath.find_last_of("/\\");
        if (slash != std::string::npos && !_ensureDirectory(userPath.substr(0, slash)))
            return FileHandle();
        _removeTombstone(actual);
        FileHandle fhnd(userPath, mode);
        if (fhnd.OK())
            _syncOverlayFile(actual, userPath);
        return fhnd;
    }
    std::string leaved;
    iNode *node = directories._parseNodePath(path, &leaved);

    if (!node)
        return FileHandle();

    if ( !leaved.empty() ) // Not exists
    {
        if (mode.find('r') != std::string::npos) //it's must be exist for reading
            return FileHandle();

        if (node->getType() != NTYPE_DIR ) // If node not dir
            return FileHandle();

        if ( leaved.find_first_of("\\/") != std::string::npos ) // With path
            return FileHandle();

        if (node->getType() != NTYPE_DIR)
            return FileHandle();

        iDir *dr = (iDir *)node;

        std::string newPath = dr->path + FSD + leaved;

        FileHandle fhnd = FileHandle(newPath, mode);

        if (!fhnd.OK())
            return fhnd;

        dr->addNode( new iFile(leaved, newPath) );
        return fhnd;
    }
    else if ( node->getType() == NTYPE_FILE ) // if exist and file
    {
        return FileHandle(node->path, mode);
    }

    return FileHandle();
}


bool iDir::deleteFile(const std::string &path)
{
    if (_overlayEnabled)
    {
        std::string logical = _normalizeVirtualPath(path);
        if (logical.empty())
            return false;
        iNode *node = findNode(logical);
        if (!node || node->getType() != NTYPE_FILE)
            return false;
        std::string actual = _nodeVPath(node);
        std::string userPath = _userPath(actual);
        bool hasAsset = false;
        std::string remaining;
        iNode *assetNode = _assetDirectories._parseNodePath(actual, &remaining);
        if (!remaining.empty())
            assetNode = NULL;
        hasAsset = assetNode && assetNode->getType() == NTYPE_FILE;

        // Write the tombstone first.  This prevents a failed user-file
        // removal from exposing the packaged file again.  Roll it back if the
        // physical deletion or in-memory unlink cannot complete.
        bool tombstoneWritten = false;
        if (hasAsset)
        {
            if (!_writeTombstone(actual))
                return false;
            tombstoneWritten = true;
        }
#if defined(WIN32) && !defined(__WINE__)
        DWORD attr = GetFileAttributes(userPath.c_str());
        if (attr != INVALID_FILE_ATTRIBUTES && DeleteFile(userPath.c_str()) == 0)
        {
            if (tombstoneWritten)
                _removeTombstone(actual);
            return false;
        }
#else
        struct stat info;
        if (lstat(userPath.c_str(), &info) == 0 && remove(userPath.c_str()) != 0)
        {
            if (tombstoneWritten)
                _removeTombstone(actual);
            return false;
        }
#endif
        if (!_removeOverlayNode(node))
        {
            if (tombstoneWritten)
                _removeTombstone(actual);
            return false;
        }
        return true;
    }
    iNode *node = findNode(path);

    if (!node)
        return false;

    if (node->getType() != NTYPE_FILE)
        return false;

#if defined(WIN32) && !defined(__WINE__)
    if (DeleteFile(node->path.c_str()) == 0)
        return false;
#else
    if (remove(node->path.c_str()) != 0)
        return false;
#endif // WIN32

    if (node->parent)
        node->parent->nodes.remove(node);

    delete node;

    return true;
}

bool iDir::Detach(iNode *node)
{
    for(std::list<iNode *>::iterator nod = nodes.begin(); nod != nodes.end(); nod++)
    {
        if (*nod == node)
        {
            if (node->parent == this)
                node->parent = NULL;
            nodes.erase(nod);
            return true;
        }
    }

    return false;
}

bool iDir::Detach(const std::string &vname)
{
    for(std::list<iNode *>::iterator nod = nodes.begin(); nod != nodes.end(); nod++)
    {
        if (!StriCmp((*nod)->name, vname))
        {
            (*nod)->parent = NULL;
            delete *nod;
            nodes.erase(nod);
            return true;
        }
    }
    return false;
}

void dumpDir()
{
    directories._dumpdir();
}


DirIter::DirIter(iDir *dr)
: _d(dr), _index(0)
{
    if (_d)
    {
        for (std::list<iNode *>::const_iterator it = _d->nodes.begin(); it != _d->nodes.end(); ++it)
        {
            if (*it)
                _names.push_back((*it)->getName());
        }
    }
}

DirIter::DirIter()
: _d(NULL), _index(0)
{
}

iNode *DirIter::getNext()
{
    iNode *ret = NULL;
    return getNext(&ret) ? ret : NULL;
}

bool DirIter::getNext(iNode **node)
{
    if (node)
        *node = NULL;
    if (!_d)
        return false;

    while (_index < _names.size())
    {
        // Resolve the name on every call instead of retaining a list
        // iterator.  In-place overlay deletes can therefore remove the
        // previously returned node without invalidating this cursor; a node
        // deleted by another caller is simply skipped.
        const std::string name = _names[_index++];
        iNode *ret = _d->getNode(name);
        if (ret)
        {
            if (node)
                *node = ret;
            return true;
        }
    }

    return false;
}

DirIter::operator bool() const
{
    return _d != NULL;
}


FileHandle::FileHandle(const std::string &diskPath, const std::string &mode)
{
    hndl = __FPtr( fopen(diskPath.c_str(), mode.c_str()) );

    if (mode.find("w") != std::string::npos)
        _writeMode = true;
}

FileHandle::FileHandle(FileHandle *b, bool del)
{
    if (b)
    {
        *this = std::move(*b);

        if (del)
            delete b;
    }
}


FileHandle::~FileHandle()
{
}

bool FileHandle::OK() const
{
    if (hndl)
        return true;
    else
        return false;
}

bool FileHandle::eof() const
{
    if (!hndl)
        return true;

    return feof(hndl.get()) != 0;
}



size_t FileHandle::read(void *buf, size_t num)
{
    if (!hndl)
        return 0;

    size_t sz = fread(buf, 1, num, hndl.get());

    if (sz != num)
        _ReadERR = true;

    return sz;
}

size_t FileHandle::write(const void *buf, size_t num)
{
    if (!hndl)
        return 0;

    size_t sz = fwrite(buf, 1, num, hndl.get());
    if (sz != num)
        _WriteERR = true;

    return sz;
}

size_t FileHandle::tell() const
{
    if (!hndl)
        return 0;

    return ftell(hndl.get());
}

int FileHandle::seek(long int offset, int origin)
{
    if (!hndl)
        return -100;

    return fseek(hndl.get(), offset, origin);
}

void FileHandle::close()
{
    hndl.reset();
}

char *FileHandle::gets(char *str, int num)
{
    if (!hndl)
        return NULL;

    return fgets(str, num, hndl.get());
}

int FileHandle::puts(const std::string &str)
{
    if (!hndl)
        return -100;

    return fputs(str.c_str(), hndl.get());
}

int FileHandle::printf(const std::string &format, ...)
{
    if (!hndl)
        return -100;

    va_list args;
    va_start (args, format);

    int num = vfprintf(hndl.get(), format.c_str(), args);

    va_end (args);

    return num;
}

int FileHandle::vprintf(const std::string &format, va_list args)
{
    if (!hndl)
        return -100;

    int num = vfprintf(hndl.get(), format.c_str(), args);
    return num;
}


bool FileHandle::ReadLine(std::string *out)
{
	if (!hndl)
        return false;

	out->clear();
	char buf[256];
	bool ok = false;

	while(fgets(buf, 256, hndl.get()))
	{
		ok = true;
		(*out) += buf;
		if (out->back() == '\n' || out->back() == '\r')
			break;
	}
	return ok;
}

bool iFileHandle::readErr()
{
    bool tmp = _ReadERR;
    _ReadERR = false;
    return tmp;
}

uint8_t iFileHandle::readU8()
{
    if (!OK())
        return 0;

    uint8_t val = 0;
    if (read(&val, 1) != 1)
        _ReadERR = true;
    return val;
}

int8_t iFileHandle::readS8()
{
    if (!OK())
        return 0;

    int8_t val = 0;
    if (read(&val, 1) != 1)
        _ReadERR = true;
    return val;
}

uint16_t iFileHandle::readU16L()
{
    if (!OK())
        return 0;

    uint16_t val = 0;
    if (read(&val, 2) != 2)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return val;
#else
    return ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
}

int16_t iFileHandle::readS16L()
{
    if (!OK())
        return 0;

    int16_t val = 0;
    if (read(&val, 2) != 2)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return val;
#else
    return ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
}

uint16_t iFileHandle::readU16B()
{
    if (!OK())
        return 0;

    uint16_t val = 0;
    if (read(&val, 2) != 2)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#else
    return val;
#endif // BYTEORDER_LITTLE
}

int16_t iFileHandle::readS16B()
{
    if (!OK())
        return 0;

    int16_t val = 0;
    if (read(&val, 2) != 2)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#else
    return val;
#endif // BYTEORDER_LITTLE
}

uint32_t iFileHandle::readU32L()
{
    if (!OK())
        return 0;

    uint32_t val = 0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return val;
#else
    return ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
}

int32_t iFileHandle::readS32L()
{
    if (!OK())
        return 0;

    int32_t val = 0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return val;
#else
    return ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
}

uint32_t iFileHandle::readU32B()
{
    if (!OK())
        return 0;

    uint32_t val = 0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#else
    return val;
#endif // BYTEORDER_LITTLE
}

int32_t iFileHandle::readS32B()
{
    if (!OK())
        return 0;

    int32_t val = 0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    return ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#else
    return val;
#endif // BYTEORDER_LITTLE
}

float iFileHandle::readFloatL()
{
    if (!OK())
        return 0.0;

    float val = 0.0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifndef BYTEORDER_LITTLE
    uint32_t *p = (uint32_t *)&val;
    *p = ((*p & 0xFF000000) >> 24) | ((*p & 0xFF0000) >> 8) | ((*p & 0xFF00) << 8) | ((*p & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return val;
}

float iFileHandle::readFloatB()
{
    if (!OK())
        return 0.0;

    float val = 0.0;
    if (read(&val, 4) != 4)
        _ReadERR = true;

#ifdef BYTEORDER_LITTLE
    uint32_t *p = (uint32_t *)&val;
    *p = ((*p & 0xFF000000) >> 24) | ((*p & 0xFF0000) >> 8) | ((*p & 0xFF00) << 8) | ((*p & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return val;
}

bool iFileHandle::writeU8(uint8_t val)
{
    if (!OK())
        return false;

    return write(&val, 1) == 1;
}

bool iFileHandle::writeS8(int8_t val)
{
    if (!OK())
        return false;

    return write(&val, 1) == 1;
}

bool iFileHandle::writeU16L(uint16_t val)
{
    if (!OK())
        return false;

#ifndef BYTEORDER_LITTLE
    val = ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
    return write(&val, 2) == 2;
}

bool iFileHandle::writeS16L(int16_t val)
{
    if (!OK())
        return false;

#ifndef BYTEORDER_LITTLE
    val = ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
    return write(&val, 2) == 2;
}

bool iFileHandle::writeU16B(uint16_t val)
{
    if (!OK())
        return false;

#ifdef BYTEORDER_LITTLE
    val = ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
    return write(&val, 2) == 2;
}

bool iFileHandle::writeS16B(int16_t val)
{
    if (!OK())
        return false;

#ifdef BYTEORDER_LITTLE
    val = ((val & 0xFF00) >> 8) | ((val & 0xFF) << 8);
#endif // BYTEORDER_LITTLE
    return write(&val, 2) == 2;
}

bool iFileHandle::writeU32L(uint32_t val)
{
    if (!OK())
        return false;

#ifndef BYTEORDER_LITTLE
    val = ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

bool iFileHandle::writeS32L(int32_t val)
{
    if (!OK())
        return false;

#ifndef BYTEORDER_LITTLE
    val = ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

bool iFileHandle::writeU32B(uint32_t val)
{
    if (!OK())
        return false;

#ifdef BYTEORDER_LITTLE
    val = ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

bool iFileHandle::writeS32B(int32_t val)
{
    if (!OK())
        return false;

#ifdef BYTEORDER_LITTLE
    val = ((val & 0xFF000000) >> 24) | ((val & 0xFF0000) >> 8) | ((val & 0xFF00) << 8) | ((val & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

bool iFileHandle::writeFloatL(float val)
{
    if (!OK())
        return false;

#ifndef BYTEORDER_LITTLE
    uint32_t *p = (uint32_t *)&val;
    *p = ((*p & 0xFF000000) >> 24) | ((*p & 0xFF0000) >> 8) | ((*p & 0xFF00) << 8) | ((*p & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

bool iFileHandle::writeFloatB(float val)
{
    if (!OK())
        return false;

#ifdef BYTEORDER_LITTLE
    uint32_t *p = (uint32_t *)&val;
    *p = ((*p & 0xFF000000) >> 24) | ((*p & 0xFF0000) >> 8) | ((*p & 0xFF00) << 8) | ((*p & 0xFF) << 24);
#endif // BYTEORDER_LITTLE
    return write(&val, 4) == 4;
}

}
