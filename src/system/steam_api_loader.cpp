#include <cstdlib>
#include <cstring>
#include <string>

#include "steam_api_loader.h"
#include "../log.h"

#if defined(OPENNEOUA_ENABLE_STEAMWORKS) && !defined(_WIN32)
#include <dlfcn.h>
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

}

const char *ApiLoader::SteamInputInterfaceVersion()
{
    return "SteamAPI_SteamInput_v006";
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
        "SteamUtils010"
        "\0"
        "SteamInput006"
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

    // Optional: only needed by later phases, so their absence is not fatal.
    Resolve(_library, "SteamAPI_ISteamInput_SetInputActionManifestFilePath",
            &_api.SetActionManifestPath, &optional);
    Resolve(_library, "SteamAPI_ISteamInput_GetCurrentActionSet",
            &_api.GetCurrentActionSet, &optional);

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
    _api = ApiTable();
    _status = STEAM_STATUS_IDLE;
    _statusText = "not initialised";
    _controllerCount = 0;
}

}
