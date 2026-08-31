#ifndef SYSTEM_STEAM_API_LOADER_H_INCLUDED
#define SYSTEM_STEAM_API_LOADER_H_INCLUDED

#include <cstdint>
#include <string>

// OpenNeoUA: runtime binding to libsteam_api.so.
//
// The Steamworks SDK is not vendored into this tree and is not required to
// build.  libsteam_api.so exports a flat C API, so the prototypes below are
// declared locally and resolved with dlsym().  Nothing here links against the
// SDK, so the executable runs unchanged with no Steam client and no library
// present, which is required for desktop development, the CTest suite and the
// AppImage path.
//
// Two names are version-sensitive and should be checked first against the
// vendored SDK binary (vendor/steamworks-sdk/redistributable_bin/linux64):
//   - SteamInternal_SteamAPI_Init (modern SDKs; no exported SteamAPI_Init)
//   - SteamAPI_SteamInput_vNNN and SteamAPI_SteamUtils_vNNN accessors
// Verify with: python3 packaging/steamrt4/verify_steam_api_symbols.py

namespace Steam
{

// Mirrors of the SDK's opaque handle typedefs.  All are 64-bit unsigned values.
typedef uint64_t InputHandle;
typedef uint64_t InputActionSetHandle;
typedef uint64_t InputDigitalActionHandle;
typedef uint64_t InputAnalogActionHandle;

enum
{
    STEAM_INPUT_MAX_COUNT = 16
};

// Layout-compatible copies of InputDigitalActionData_t and
// InputAnalogActionData_t.  Both are small PODs returned by value; keeping the
// member order and types identical keeps the SysV return-register
// classification identical too.
struct DigitalActionData
{
    bool State  = false;
    bool Active = false;
};

struct AnalogActionData
{
    int32_t Mode = 0;
    float   X    = 0.0f;
    float   Y    = 0.0f;
    bool    Active = false;
};

typedef bool (*PFN_SteamAPI_Init)();
// SDK 1.59+ exports this instead of SteamAPI_Init.  Returns 0 on success.
typedef int32_t (*PFN_SteamInternal_SteamAPI_Init)(const char *interfaceVersions, char *errMsg);
typedef void (*PFN_SteamAPI_RunCallbacks)();
typedef void (*PFN_SteamAPI_Shutdown)();
typedef void *(*PFN_SteamAPI_SteamInput)();

typedef bool (*PFN_ISteamInput_Init)(void *self, bool explicitlyCallRunFrame);
typedef bool (*PFN_ISteamInput_Shutdown)(void *self);
typedef bool (*PFN_ISteamInput_SetInputActionManifestFilePath)(void *self, const char *path);
typedef void (*PFN_ISteamInput_RunFrame)(void *self, bool reservedValue);
typedef int  (*PFN_ISteamInput_GetConnectedControllers)(void *self, InputHandle *handlesOut);
typedef InputActionSetHandle (*PFN_ISteamInput_GetActionSetHandle)(void *self, const char *actionSetName);
typedef void (*PFN_ISteamInput_ActivateActionSet)(void *self, InputHandle controller, InputActionSetHandle actionSet);
typedef InputActionSetHandle (*PFN_ISteamInput_GetCurrentActionSet)(void *self, InputHandle controller);
typedef void (*PFN_ISteamInput_ActivateActionSetLayer)(void *self, InputHandle controller, InputActionSetHandle layer);
typedef void (*PFN_ISteamInput_DeactivateActionSetLayer)(void *self, InputHandle controller, InputActionSetHandle layer);
typedef void (*PFN_ISteamInput_DeactivateAllActionSetLayers)(void *self, InputHandle controller);
typedef int (*PFN_ISteamInput_GetActiveActionSetLayers)(void *self, InputHandle controller, InputActionSetHandle *layersOut);
typedef InputDigitalActionHandle (*PFN_ISteamInput_GetDigitalActionHandle)(void *self, const char *actionName);
typedef DigitalActionData (*PFN_ISteamInput_GetDigitalActionData)(void *self, InputHandle controller, InputDigitalActionHandle action);
typedef InputAnalogActionHandle (*PFN_ISteamInput_GetAnalogActionHandle)(void *self, const char *actionName);
typedef AnalogActionData (*PFN_ISteamInput_GetAnalogActionData)(void *self, InputHandle controller, InputAnalogActionHandle action);
typedef int  (*PFN_ISteamInput_GetDigitalActionOrigins)(void *self, InputHandle controller, InputDigitalActionHandle action, InputActionSetHandle set, uint32_t *originsOut, uint32_t originsOutCount);
typedef int  (*PFN_ISteamInput_GetAnalogActionOrigins)(void *self, InputHandle controller, InputAnalogActionHandle action, InputActionSetHandle set, uint32_t *originsOut, uint32_t originsOutCount);
typedef const char *(*PFN_ISteamInput_GetGlyphPNGForActionOrigin)(void *self, uint32_t origin, int32_t flags, uint32_t *sizeOut);
typedef void (*PFN_ISteamInput_ShowBindingPanel)(void *self, InputHandle controller);
typedef void *(*PFN_SteamAPI_SteamUtils)();
typedef bool (*PFN_ISteamUtils_ShowGamepadTextInput)(void *self, uint32_t inputMode, uint32_t lineInputMode, const char *description, uint32_t charMax, const char *existingText);

// The resolved flat API.  Every pointer is either null or usable; callers must
// still check, because a library can export a subset of these symbols.
struct ApiTable
{
    PFN_SteamAPI_Init                  Init         = nullptr;
    PFN_SteamInternal_SteamAPI_Init    InternalInit = nullptr;
    PFN_SteamAPI_RunCallbacks RunCallbacks = nullptr;
    PFN_SteamAPI_Shutdown     Shutdown     = nullptr;
    PFN_SteamAPI_SteamInput   SteamInput   = nullptr;

    PFN_ISteamInput_Init                          InputInit                = nullptr;
    PFN_ISteamInput_Shutdown                      InputShutdown            = nullptr;
    PFN_ISteamInput_SetInputActionManifestFilePath SetActionManifestPath   = nullptr;
    PFN_ISteamInput_RunFrame                      RunFrame                 = nullptr;
    PFN_ISteamInput_GetConnectedControllers       GetConnectedControllers  = nullptr;
    PFN_ISteamInput_GetActionSetHandle            GetActionSetHandle       = nullptr;
    PFN_ISteamInput_ActivateActionSet             ActivateActionSet        = nullptr;
    PFN_ISteamInput_GetCurrentActionSet           GetCurrentActionSet      = nullptr;
    PFN_ISteamInput_ActivateActionSetLayer        ActivateActionSetLayer   = nullptr;
    PFN_ISteamInput_DeactivateActionSetLayer      DeactivateActionSetLayer = nullptr;
    PFN_ISteamInput_DeactivateAllActionSetLayers  DeactivateAllActionSetLayers = nullptr;
    PFN_ISteamInput_GetActiveActionSetLayers      GetActiveActionSetLayers = nullptr;
    PFN_ISteamInput_GetDigitalActionHandle        GetDigitalActionHandle   = nullptr;
    PFN_ISteamInput_GetDigitalActionData          GetDigitalActionData     = nullptr;
    PFN_ISteamInput_GetAnalogActionHandle         GetAnalogActionHandle    = nullptr;
    PFN_ISteamInput_GetAnalogActionData           GetAnalogActionData      = nullptr;
    PFN_ISteamInput_GetDigitalActionOrigins       GetDigitalActionOrigins  = nullptr;
    PFN_ISteamInput_GetAnalogActionOrigins        GetAnalogActionOrigins   = nullptr;
    PFN_ISteamInput_GetGlyphPNGForActionOrigin    GetGlyphForActionOrigin  = nullptr;
    PFN_ISteamInput_ShowBindingPanel              ShowBindingPanel         = nullptr;
    PFN_SteamAPI_SteamUtils                       SteamUtils               = nullptr;
    PFN_ISteamUtils_ShowGamepadTextInput          ShowGamepadTextInput     = nullptr;
};

enum LOADER_STATUS
{
    // Never attempted, or already shut down.
    STEAM_STATUS_IDLE = 0,
    // ENABLE_STEAMWORKS was off at build time.
    STEAM_STATUS_DISABLED_AT_BUILD,
    // OPENNEOUA_NO_STEAM_INPUT was set in the environment.
    STEAM_STATUS_DISABLED_BY_ENV,
    // dlopen() could not find or load libsteam_api.so.
    STEAM_STATUS_LIBRARY_ABSENT,
    // The library loaded but does not export the symbols we need.
    STEAM_STATUS_SYMBOLS_INCOMPLETE,
    // SteamAPI_Init() returned false; usually no Steam client is running.
    STEAM_STATUS_API_INIT_FAILED,
    // The ISteamInput accessor returned nothing.
    STEAM_STATUS_INTERFACE_ABSENT,
    // ISteamInput::Init() returned false.
    STEAM_STATUS_INPUT_INIT_FAILED,
    // Fully initialised and usable.
    STEAM_STATUS_READY
};

class ApiLoader
{
public:
    // Loads the library, resolves the flat API and brings ISteamInput up.
    // Always safe to call; never throws and never aborts.  Returns true only
    // when Status() becomes STEAM_STATUS_READY.  Logs one line describing the
    // outcome, which is the primary on-device diagnostic.
    bool Initialize();
    void Shutdown();

    // Must be pumped once per frame while Ready(), so Steam can dispatch its
    // callbacks and refresh action state.
    void RunFrame();

    bool Ready() const { return _status == STEAM_STATUS_READY; }
    LOADER_STATUS Status() const { return _status; }

    // Human-readable reason for the current status, for logging and for the
    // input settings UI in a later phase.
    const std::string &StatusText() const { return _statusText; }

    const ApiTable &Api() const { return _api; }
    void *InputInterface() const { return _inputInterface; }

    // Controllers seen by Steam Input on the last RunFrame().
    int ControllerCount() const { return _controllerCount; }
    const InputHandle *Controllers() const { return _controllers; }

    void *UtilsInterface() const { return _utilsInterface; }

    // Opens the Steam Input binding panel for the first connected controller.
    void OpenBindingPanel();

    // Requests the Big Picture overlay text field for gamepad name entry.
    bool ShowGamepadTextInput(const char *description,
                              uint32_t charMax,
                              const char *existingText = "");

    // The ISteamInput accessor this build expects to resolve.
    static const char *SteamInputInterfaceVersion();

    // True when the Steamworks path was compiled in at all.
    static bool CompiledIn();

    static ApiLoader Instance;

private:
    bool ResolveSymbols();
    bool CallSteamApiInit();
    bool InstallActionManifest();
    void Fail(LOADER_STATUS status, const std::string &reason);

    void *_library = nullptr;
    void *_inputInterface = nullptr;
    void *_utilsInterface = nullptr;
    ApiTable _api;
    LOADER_STATUS _status = STEAM_STATUS_IDLE;
    std::string _statusText = "not initialised";
    int _controllerCount = 0;
    InputHandle _controllers[STEAM_INPUT_MAX_COUNT] = {0};
};

}

#endif // SYSTEM_STEAM_API_LOADER_H_INCLUDED
