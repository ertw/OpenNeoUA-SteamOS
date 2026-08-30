#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <unistd.h>

#include "steam_api_loader.h"
#include "../log.h"

#if defined(OPENNEOUA_ENABLE_STEAMWORKS) && !defined(_WIN32)
#include <dirent.h>
#include <dlfcn.h>
#include <sys/stat.h>
#define OPENNEOUA_STEAM_DLOPEN 1
#endif

namespace Steam
{

ApiLoader ApiLoader::Instance;

namespace
{

const char *const LIBRARY_NAME = "libsteam_api.so";

// Set to opt out at runtime without rebuilding; useful when bisecting an input
// problem on device, where the Steam client is always present.
const char *const DISABLE_ENV = "OPENNEOUA_NO_STEAM_INPUT";
const char *const MANIFEST_NAME = "game_actions_480.vdf";
const char *const MANIFEST_SUBDIR = "SteamInput";

#ifdef OPENNEOUA_STEAM_DLOPEN
// Resolves one symbol and records the first failure.  Returning through a
// void* and memcpy avoids the ISO C++ warning about object-to-function-pointer
// casts while keeping every result explicitly checked.
template <typename T>
bool Resolve(void *library, const char *name, T *out, std::string *missing)
{
    void *symbol = dlsym(library, name);
    if ( !symbol )
    {
        if ( missing->empty() )
            *missing = name;
        *out = nullptr;
        return false;
    }

    std::memcpy(out, &symbol, sizeof(void *));
    return true;
}
#endif

const char *StatusName(LOADER_STATUS status)
{
    switch ( status )
    {
    case STEAM_STATUS_IDLE:                return "idle";
    case STEAM_STATUS_DISABLED_AT_BUILD:   return "disabled at build";
    case STEAM_STATUS_DISABLED_BY_ENV:     return "disabled by environment";
    case STEAM_STATUS_LIBRARY_ABSENT:      return "library absent";
    case STEAM_STATUS_SYMBOLS_INCOMPLETE:  return "symbols incomplete";
    case STEAM_STATUS_API_INIT_FAILED:     return "SteamAPI_Init failed";
    case STEAM_STATUS_INTERFACE_ABSENT:    return "ISteamInput absent";
    case STEAM_STATUS_INPUT_INIT_FAILED:   return "ISteamInput::Init failed";
    case STEAM_STATUS_READY:               return "ready";
    }
    return "unknown";
}

std::string DirectoryForExecutable()
{
    char buffer[4096];
    const ssize_t length = readlink("/proc/self/exe", buffer, sizeof(buffer) - 1);
    if ( length <= 0 )
        return std::string();

    buffer[length] = '\0';
    std::string path(buffer);
    const std::size_t slash = path.find_last_of('/');
    if ( slash == std::string::npos )
        return std::string();

    return path.substr(0, slash);
}

std::string ResolveManifestSourceDir()
{
    const std::string binDir = DirectoryForExecutable();
    if ( binDir.empty() )
        return std::string();

    return binDir + "/../" + MANIFEST_SUBDIR;
}

std::string ResolveManifestSourcePath()
{
    const std::string sourceDir = ResolveManifestSourceDir();
    if ( sourceDir.empty() )
        return std::string();

    return sourceDir + "/" + MANIFEST_NAME;
}

bool CopyRegularFile(const std::string &source, const std::string &destination)
{
    std::ifstream input(source, std::ios::binary);
    if ( !input )
        return false;

    std::ofstream output(destination, std::ios::binary | std::ios::trunc);
    if ( !output )
        return false;

    output << input.rdbuf();
    return output.good();
}

bool CopySteamInputAssets(const std::string &sourceDir, const std::string &destDir)
{
#ifdef OPENNEOUA_STEAM_DLOPEN
    DIR *dir = opendir(sourceDir.c_str());
    if ( !dir )
        return false;

    if ( mkdir(destDir.c_str(), 0755) != 0 && errno != EEXIST )
    {
        closedir(dir);
        return false;
    }

    bool copiedManifest = false;

    for ( dirent *entry = readdir(dir); entry; entry = readdir(dir) )
    {
        if ( !entry->d_name[0] || entry->d_name[0] == '.' )
            continue;

        const std::string sourcePath = sourceDir + "/" + entry->d_name;
        struct stat info = {};
        if ( stat(sourcePath.c_str(), &info) != 0 || !S_ISREG(info.st_mode) )
            continue;

        const std::string destPath = destDir + "/" + entry->d_name;
        if ( !CopyRegularFile(sourcePath, destPath) )
        {
            closedir(dir);
            return false;
        }

        if ( std::strcmp(entry->d_name, MANIFEST_NAME) == 0 )
            copiedManifest = true;
    }

    closedir(dir);
    return copiedManifest;
#else
    (void)sourceDir;
    (void)destDir;
    return false;
#endif
}

bool CopyManifestToRuntimeDir(const std::string &sourceDir, std::string *destinationDir)
{
    const char *tempRoot = std::getenv("TMPDIR");
    if ( !tempRoot || !tempRoot[0] )
        tempRoot = "/tmp";

    *destinationDir = std::string(tempRoot) + "/openneoua_steam_input";
    return CopySteamInputAssets(sourceDir, *destinationDir);
}

}

const char *ApiLoader::SteamInputInterfaceVersion()
{
    return "SteamAPI_SteamInput_v007";
}

bool ApiLoader::CompiledIn()
{
#ifdef OPENNEOUA_STEAM_DLOPEN
    return true;
#else
    return false;
#endif
}

void ApiLoader::Fail(LOADER_STATUS status, const std::string &reason)
{
    _status = status;
    _statusText = reason;

    ypa_log_out("steam.input: DISABLED (%s): %s\n", StatusName(status), reason.c_str());

#ifdef OPENNEOUA_STEAM_DLOPEN
    if ( _library )
    {
        dlclose(_library);
        _library = nullptr;
    }
#endif

    _inputInterface = nullptr;
    _utilsInterface = nullptr;
    _api = ApiTable();
    _controllerCount = 0;
}

bool ApiLoader::CallSteamApiInit()
{
    if ( _api.Init )
        return _api.Init();

    if ( !_api.InternalInit )
        return false;

    // Minimal interface set for Steam Input.  Extend when later phases need
    // ISteamUtils (text entry) or other interfaces.
    static const char kVersionCheck[] =
        "SteamUtils011"
        "\0"
        "SteamInput007"
        "\0"
        "\0";

    char errMsg[1024] = {};
    const int32_t result = _api.InternalInit(kVersionCheck, errMsg);
    if ( result != 0 )
    {
        Fail(STEAM_STATUS_API_INIT_FAILED,
             errMsg[0] != '\0' ? std::string(errMsg)
                               : std::string("SteamInternal_SteamAPI_Init returned ") +
                                     std::to_string(result));
        return false;
    }

    return true;
}

bool ApiLoader::ResolveSymbols()
{
#ifdef OPENNEOUA_STEAM_DLOPEN
    std::string missing;
    std::string optional;

    Resolve(_library, "SteamAPI_Init", &_api.Init, &optional);
    Resolve(_library, "SteamInternal_SteamAPI_Init", &_api.InternalInit, &optional);
    if ( !_api.Init && !_api.InternalInit )
        missing = "SteamAPI_Init or SteamInternal_SteamAPI_Init";

    Resolve(_library, "SteamAPI_RunCallbacks", &_api.RunCallbacks, &missing);
    Resolve(_library, "SteamAPI_Shutdown", &_api.Shutdown, &missing);
    Resolve(_library, SteamInputInterfaceVersion(), &_api.SteamInput, &missing);

    Resolve(_library, "SteamAPI_ISteamInput_Init", &_api.InputInit, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_Shutdown", &_api.InputShutdown, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_RunFrame", &_api.RunFrame, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetConnectedControllers",
            &_api.GetConnectedControllers, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetActionSetHandle",
            &_api.GetActionSetHandle, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_ActivateActionSet",
            &_api.ActivateActionSet, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetDigitalActionHandle",
            &_api.GetDigitalActionHandle, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetDigitalActionData",
            &_api.GetDigitalActionData, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetAnalogActionHandle",
            &_api.GetAnalogActionHandle, &missing);
    Resolve(_library, "SteamAPI_ISteamInput_GetAnalogActionData",
            &_api.GetAnalogActionData, &missing);

    // Optional: glyphs, binding panel and text entry are not required to play.
    Resolve(_library, "SteamAPI_ISteamInput_SetInputActionManifestFilePath",
            &_api.SetActionManifestPath, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_GetCurrentActionSet",
            &_api.GetCurrentActionSet, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_GetDigitalActionOrigins",
            &_api.GetDigitalActionOrigins, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_GetAnalogActionOrigins",
            &_api.GetAnalogActionOrigins, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_GetGlyphPNGForActionOrigin",
            &_api.GetGlyphForActionOrigin, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_ShowBindingPanel",
            &_api.ShowBindingPanel, &optional);
    Resolve(_library, "SteamAPI_SteamUtils_v011", &_api.SteamUtils, &optional);
    Resolve(_library, "SteamAPI_ISteamUtils_ShowGamepadTextInput",
            &_api.ShowGamepadTextInput, &optional);

    if ( !missing.empty() )
    {
        Fail(STEAM_STATUS_SYMBOLS_INCOMPLETE,
             LIBRARY_NAME + std::string(" does not export ") + missing);
        return false;
    }

    return true;
#else
    return false;
#endif
}

bool ApiLoader::InstallActionManifest()
{
#ifdef OPENNEOUA_STEAM_DLOPEN
    if ( !_api.SetActionManifestPath || !_inputInterface )
        return true;

    const std::string sourceDir = ResolveManifestSourceDir();
    if ( sourceDir.empty() )
    {
        ypa_log_out("steam.input: manifest source path could not be resolved\n");
        return false;
    }

    const std::string sourcePath = sourceDir + "/" + MANIFEST_NAME;
    std::ifstream probe(sourcePath);
    if ( !probe )
    {
        ypa_log_out("steam.input: manifest missing at %s\n", sourcePath.c_str());
        return false;
    }

    std::string manifestPath = sourcePath;
    std::string copiedDir;
    if ( CopyManifestToRuntimeDir(sourceDir, &copiedDir) )
        manifestPath = copiedDir + "/" + MANIFEST_NAME;

    if ( !_api.SetActionManifestPath(_inputInterface, manifestPath.c_str()) )
    {
        ypa_log_out("steam.input: SetInputActionManifestFilePath failed for %s\n",
                    manifestPath.c_str());
        return false;
    }

    ypa_log_out("steam.input: manifest installed from %s\n", manifestPath.c_str());
    return true;
#else
    return false;
#endif
}

bool ApiLoader::Initialize()
{
    if ( _status == STEAM_STATUS_READY )
        return true;

#ifndef OPENNEOUA_STEAM_DLOPEN
    Fail(STEAM_STATUS_DISABLED_AT_BUILD,
         "built without ENABLE_STEAMWORKS; keyboard, mouse and legacy joystick only");
    return false;
#else
    const char *disable = std::getenv(DISABLE_ENV);
    if ( disable && disable[0] != '\0' && std::strcmp(disable, "0") != 0 )
    {
        Fail(STEAM_STATUS_DISABLED_BY_ENV,
             std::string(DISABLE_ENV) + " is set; keyboard, mouse and legacy joystick only");
        return false;
    }

    // RTLD_NOW surfaces a truncated or mismatched library here rather than at
    // the first call.  The private lib/ directory is already on the RPATH.
    _library = dlopen(LIBRARY_NAME, RTLD_NOW | RTLD_LOCAL);
    if ( !_library )
    {
        const char *error = dlerror();
        Fail(STEAM_STATUS_LIBRARY_ABSENT,
             error ? std::string(error)
                   : std::string("dlopen(") + LIBRARY_NAME + ") failed");
        return false;
    }

    if ( !ResolveSymbols() )
        return false;

    if ( !CallSteamApiInit() )
    {
        if ( _status != STEAM_STATUS_API_INIT_FAILED )
        {
            Fail(STEAM_STATUS_API_INIT_FAILED,
                 "no Steam client, or this process is not registered to an app id "
                 "(see steam://forceinputappid)");
        }
        return false;
    }

    _inputInterface = _api.SteamInput();
    if ( !_inputInterface )
    {
        if ( _api.Shutdown )
            _api.Shutdown();
        Fail(STEAM_STATUS_INTERFACE_ABSENT,
             std::string(SteamInputInterfaceVersion()) + " returned no interface");
        return false;
    }

    // Explicit RunFrame: the engine pumps input from one place, so Steam must
    // not sample it on its own callback cadence.
    if ( !_api.InputInit(_inputInterface, true) )
    {
        if ( _api.Shutdown )
            _api.Shutdown();
        Fail(STEAM_STATUS_INPUT_INIT_FAILED, "ISteamInput::Init returned false");
        return false;
    }

    if ( !InstallActionManifest() )
    {
        if ( _api.InputShutdown )
            _api.InputShutdown(_inputInterface);
        if ( _api.Shutdown )
            _api.Shutdown();
        Fail(STEAM_STATUS_INPUT_INIT_FAILED, "action manifest could not be installed");
        return false;
    }

    _utilsInterface = _api.SteamUtils ? _api.SteamUtils() : nullptr;

    _status = STEAM_STATUS_READY;
    _statusText = "ready";
    _controllerCount = 0;

    ypa_log_out("steam.input: ENABLED via %s (%s)\n",
                LIBRARY_NAME, SteamInputInterfaceVersion());
    return true;
#endif
}

void ApiLoader::RunFrame()
{
    if ( _status != STEAM_STATUS_READY )
        return;

    if ( _api.RunCallbacks )
        _api.RunCallbacks();

    if ( _api.RunFrame )
        _api.RunFrame(_inputInterface, false);

    _controllerCount = 0;
    if ( _api.GetConnectedControllers )
    {
        int count = _api.GetConnectedControllers(_inputInterface, _controllers);
        if ( count < 0 )
            count = 0;
        else if ( count > STEAM_INPUT_MAX_COUNT )
            count = STEAM_INPUT_MAX_COUNT;
        _controllerCount = count;
    }
}

void ApiLoader::Shutdown()
{
#ifdef OPENNEOUA_STEAM_DLOPEN
    if ( _status == STEAM_STATUS_READY )
    {
        if ( _api.InputShutdown && _inputInterface )
            _api.InputShutdown(_inputInterface);
        if ( _api.Shutdown )
            _api.Shutdown();
    }

    if ( _library )
    {
        dlclose(_library);
        _library = nullptr;
    }
#endif

    _inputInterface = nullptr;
    _utilsInterface = nullptr;
    _api = ApiTable();
    _status = STEAM_STATUS_IDLE;
    _statusText = "not initialised";
    _controllerCount = 0;
}

void ApiLoader::OpenBindingPanel()
{
    if ( _status != STEAM_STATUS_READY || !_api.ShowBindingPanel || _controllerCount <= 0 )
        return;

    _api.ShowBindingPanel(_inputInterface, _controllers[0]);
}

bool ApiLoader::ShowGamepadTextInput(const char *description,
                                     uint32_t charMax,
                                     const char *existingText)
{
    if ( _status != STEAM_STATUS_READY || !_api.ShowGamepadTextInput || !_utilsInterface )
        return false;

    return _api.ShowGamepadTextInput(_utilsInterface,
                                     0,
                                     0,
                                     description ? description : "",
                                     charMax,
                                     existingText ? existingText : "");
}

}
