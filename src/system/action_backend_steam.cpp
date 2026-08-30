#include "action_backend.h"

#include "../log.h"
#include "steam_api_loader.h"

namespace Input
{

namespace
{

enum ANALOG_KIND
{
    ANALOG_KIND_NONE = 0,
    ANALOG_KIND_JOYSTICK,
    ANALOG_KIND_TRIGGER,
    ANALOG_KIND_ABSOLUTE_MOUSE
};

ANALOG_KIND AnalogKindForName(const char *name)
{
    if ( !name || !name[0] )
        return ANALOG_KIND_NONE;

    if ( std::strcmp(name, "FlySpeed") == 0 || std::strcmp(name, "DriveSpeed") == 0 )
        return ANALOG_KIND_TRIGGER;

    if ( std::strcmp(name, "Aim") == 0 || std::strcmp(name, "MenuCursor") == 0 )
        return ANALOG_KIND_ABSOLUTE_MOUSE;

    if ( std::strcmp(name, "FlyDir") == 0 || std::strcmp(name, "FlyHeight") == 0 ||
         std::strcmp(name, "DriveDir") == 0 || std::strcmp(name, "GunHeight") == 0 )
        return ANALOG_KIND_JOYSTICK;

    return ANALOG_KIND_NONE;
}

bool UsesVerticalAxisAsPrimary(const char *name)
{
    return name && (std::strcmp(name, "FlyHeight") == 0 || std::strcmp(name, "GunHeight") == 0);
}

SteamInputBackend &BackendInstance()
{
    static SteamInputBackend backend;
    return backend;
}

}

SteamInputBackend::SteamInputBackend()
{
    ResetHandles();
}

void SteamInputBackend::ResetHandles()
{
    _resolved.fill(SteamInputBackend::ResolvedAction());
    _menuNavResolved.fill(0);
    _menuNavActive.fill(false);
    _menuCursorDelX = 0.0f;
    _menuCursorDelY = 0.0f;
    _aimDelX = 0.0f;
    _aimDelY = 0.0f;
    _aimHandle = 0;
    _handlesReady = false;
    _nativeBindingState = NATIVE_BINDING_UNKNOWN;
    _nativeBindingProbeFrames = 0;
}

void SteamInputBackend::EnsureHandles()
{
    if ( _handlesReady )
        return;

    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    if ( !steam.Ready() )
        return;

    const Steam::ApiTable &api = steam.Api();
    void *iface = steam.InputInterface();
    if ( !iface || !api.GetDigitalActionHandle || !api.GetAnalogActionHandle )
        return;

    for ( std::size_t i = 0; i < World::ActionTable::ENTRY_COUNT; i++ )
    {
        const World::ActionTable::Entry &entry = World::ActionTable::Entries[i];
        if ( entry.Binding <= 0 || entry.Binding >= World::INPUT_BIND_MAX )
            continue;

        SteamInputBackend::ResolvedAction &resolved = _resolved[entry.Binding];
        resolved.Binding = entry.Binding;
        resolved.IgaName = entry.IgaName;
        resolved.HotKeySlot = entry.Channel == World::INPUT_BIND_TYPE_HOTKEY ? entry.Slot : -1;

        if ( entry.Kind == World::ActionTable::ACTION_KIND_DIGITAL )
        {
            resolved.Digital = api.GetDigitalActionHandle(iface, entry.IgaName);
        }
        else
        {
            resolved.Analog = api.GetAnalogActionHandle(iface, entry.IgaName);
            resolved.AnalogKind = (int)AnalogKindForName(entry.IgaName);
        }
    }

    static const char *const kMenuNavNames[] = {
        "MenuUp", "MenuDown", "MenuLeft", "MenuRight", "MenuConfirm", "MenuCancel"
    };

    for ( std::size_t i = 0; i < _menuNavResolved.size(); i++ )
        _menuNavResolved[i] = api.GetDigitalActionHandle(iface, kMenuNavNames[i]);

    _aimHandle = api.GetAnalogActionHandle(iface, "Aim");

    _handlesReady = true;
}

bool SteamInputBackend::Available() const
{
    if ( _smokeMode )
        return true;

    return Steam::ApiLoader::Instance.Ready() &&
           Steam::ApiLoader::Instance.ControllerCount() > 0;
}

void SteamInputBackend::EnableSmokeMode()
{
    _smokeMode = true;
    _handlesReady = true;
    ResetHandles();
    _nativeBindingState = NATIVE_BINDING_NATIVE;
}

void SteamInputBackend::PulseMenuNav(MENU_NAV_ACTION action)
{
    const std::size_t index = (std::size_t)action;
    if ( index < _smokeMenuNavPulse.size() )
        _smokeMenuNavPulse[index] = true;
}

void SteamInputBackend::PulseMenuConfirmRelease()
{
    _smokeMenuConfirmRelease = true;
}

bool SteamInputBackend::ConsumeMenuConfirmRelease()
{
    const bool release = _smokeMenuConfirmRelease;
    _smokeMenuConfirmRelease = false;
    return release;
}

void SteamInputBackend::ProbeNativeBindings()
{
    if ( _nativeBindingState != NATIVE_BINDING_UNKNOWN )
        return;

    _nativeBindingProbeFrames++;

    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    if ( !steam.Ready() || steam.ControllerCount() <= 0 )
        return;

    const Steam::ApiTable &api = steam.Api();
    if ( !api.GetAnalogActionOrigins || !api.GetDigitalActionOrigins ||
         !api.GetAnalogActionHandle || !api.GetDigitalActionHandle ||
         !api.GetActionSetHandle )
    {
        if ( _nativeBindingProbeFrames >= 60 )
            _nativeBindingState = NATIVE_BINDING_LEGACY;
        return;
    }

    void *iface = steam.InputInterface();
    const Steam::InputHandle controller = steam.Controllers()[0];

    struct Probe
    {
        const char *ActionSet;
        const char *Action;
        bool Analog;
    };

    static const Probe kProbes[] = {
        { "Ground", "DriveDir", true },
        { "Air",    "FlyDir",   true },
        { "Ground", "Fire",     false },
    };

    for ( const Probe &probe : kProbes )
    {
        const Steam::InputActionSetHandle set =
            api.GetActionSetHandle(iface, probe.ActionSet);
        if ( !set )
            continue;

        uint32_t origins[4] = {};
        int count = 0;

        if ( probe.Analog )
        {
            const Steam::InputAnalogActionHandle action =
                api.GetAnalogActionHandle(iface, probe.Action);
            if ( action )
            {
                count = api.GetAnalogActionOrigins(iface, controller, action, set,
                                                   origins, 4);
            }
        }
        else
        {
            const Steam::InputDigitalActionHandle action =
                api.GetDigitalActionHandle(iface, probe.Action);
            if ( action )
            {
                count = api.GetDigitalActionOrigins(iface, controller, action, set,
                                                    origins, 4);
            }
        }

        if ( count > 0 )
        {
            _nativeBindingState = NATIVE_BINDING_NATIVE;
            ypa_log_out("steam.input: native game_action layout detected\n");
            return;
        }
    }

    if ( _nativeBindingProbeFrames >= 180 )
    {
        _nativeBindingState = NATIVE_BINDING_LEGACY;
        ypa_log_out("steam.input: legacy layout detected; SDL joystick merge enabled\n");
    }
}

void SteamInputBackend::ContributeSmoke(ActionFrame *frame)
{
    if ( !frame )
        return;

    _menuCursorDelX = 0.0f;
    _menuCursorDelY = 0.0f;
    _aimDelX = 0.0f;
    _aimDelY = 0.0f;

    for ( std::size_t i = 0; i < _menuNavActive.size(); i++ )
    {
        _menuNavActive[i] = _smokeMenuNavPulse[i];
        _smokeMenuNavPulse[i] = false;
    }

    if ( _menuNavActive[(std::size_t)MENU_NAV_CONFIRM] )
        frame->Samples[World::INPUT_BIND_FIRE].active = true;
    if ( _menuNavActive[(std::size_t)MENU_NAV_CANCEL] )
        frame->Samples[World::INPUT_BIND_BRAKE].active = true;
}

void SteamInputBackend::Contribute(ActionFrame *frame)
{
    if ( !frame || !Available() )
        return;

    if ( _smokeMode )
    {
        ContributeSmoke(frame);
        return;
    }

    EnsureHandles();

    _menuCursorDelX = 0.0f;
    _menuCursorDelY = 0.0f;
    _aimDelX = 0.0f;
    _aimDelY = 0.0f;

    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    const Steam::ApiTable &api = steam.Api();
    void *iface = steam.InputInterface();
    const Steam::InputHandle controller = steam.Controllers()[0];

    for ( int binding = 1; binding < World::INPUT_BIND_MAX; binding++ )
    {
        const SteamInputBackend::ResolvedAction &resolved = _resolved[binding];
        ActionSample &sample = frame->Samples[binding];

        if ( resolved.Digital )
        {
            const Steam::DigitalActionData data =
                api.GetDigitalActionData(iface, controller, resolved.Digital);

            if ( data.Active && data.State )
                sample.active = true;

            if ( resolved.HotKeySlot >= 0 && data.Active && data.State && !resolved.WasHotKeyActive )
                frame->HotKeys.push_back(HotKeyActivation(resolved.HotKeySlot, binding));
        }
        else if ( resolved.Analog )
        {
            const Steam::AnalogActionData data =
                api.GetAnalogActionData(iface, controller, resolved.Analog);

            if ( !data.Active )
                continue;

            switch ( (ANALOG_KIND)resolved.AnalogKind )
            {
            case ANALOG_KIND_ABSOLUTE_MOUSE:
                sample.delX += data.X;
                sample.delY += data.Y;
                sample.active = sample.active || (data.X != 0.0f || data.Y != 0.0f);
                break;

            case ANALOG_KIND_TRIGGER:
                sample.posX = CombineTrigger(sample.posX, data.X);
                sample.active = sample.active || data.X != 0.0f;
                break;

            case ANALOG_KIND_JOYSTICK:
            default:
                if ( UsesVerticalAxisAsPrimary(resolved.IgaName) )
                    sample.posX = data.Y;
                else
                    sample.posX = data.X;
                sample.posY = data.Y;
                sample.active = sample.active || (data.X != 0.0f || data.Y != 0.0f);
                break;
            }
        }
    }

    for ( std::size_t i = 0; i < _menuNavResolved.size(); i++ )
    {
        if ( !_menuNavResolved[i] )
            continue;

        const Steam::DigitalActionData data =
            api.GetDigitalActionData(iface, controller, _menuNavResolved[i]);

        _menuNavActive[i] = data.Active && data.State;
    }

    if ( api.GetAnalogActionHandle && api.GetAnalogActionData )
    {
        const Steam::InputAnalogActionHandle menuCursor =
            api.GetAnalogActionHandle(iface, "MenuCursor");
        if ( menuCursor )
        {
            const Steam::AnalogActionData cursor =
                api.GetAnalogActionData(iface, controller, menuCursor);
            if ( cursor.Active )
            {
                _menuCursorDelX = cursor.X;
                _menuCursorDelY = cursor.Y;
            }
        }
    }

    if ( _aimHandle )
    {
        const Steam::AnalogActionData aim =
            api.GetAnalogActionData(iface, controller, _aimHandle);
        if ( aim.Active )
        {
            _aimDelX = aim.X;
            _aimDelY = aim.Y;
        }
    }

    for ( int binding = 1; binding < World::INPUT_BIND_MAX; binding++ )
    {
        const SteamInputBackend::ResolvedAction &resolved = _resolved[binding];
        if ( resolved.HotKeySlot < 0 )
            continue;

        const bool active = frame->Samples[binding].active;
        _resolved[binding].WasHotKeyActive = active;
    }

    ProbeNativeBindings();
}

bool SteamInputBackend::MenuNavActive(MENU_NAV_ACTION action) const
{
    const std::size_t index = (std::size_t)action;
    if ( index >= _menuNavActive.size() )
        return false;

    return _menuNavActive[index];
}

float SteamInputBackend::CombineTrigger(float current, float incoming)
{
    if ( current == 0.0f )
        return incoming;

    if ( incoming == 0.0f )
        return current;

    return ( current < 0.0f ? -current : current ) >= ( incoming < 0.0f ? -incoming : incoming )
         ? current : incoming;
}

SteamInputBackend &SteamBackend()
{
    return BackendInstance();
}

}
