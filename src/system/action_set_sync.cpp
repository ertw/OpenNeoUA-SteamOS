#include "action_set_sync.h"

#include <algorithm>

#include "action_backend.h"
#include "action_input.h"
#include "steam_api_loader.h"
#include "../global.h"
#include "../log.h"
#include "../yw_internal.h"

extern tehMap robo_map;
extern squadMan squadron_manager;

namespace Input
{

namespace
{

InputContext Context;
bool SteamContextApplied = false;
ACTION_SET AppliedBase = ACTION_SET_MENU;
ACTION_LAYER AppliedLayer = ACTION_LAYER_NONE;
int AppliedControllerCount = 0;
Steam::InputHandle AppliedControllers[Steam::STEAM_INPUT_MAX_COUNT] = {0};

bool Visible(const GuiBase &window)
{
    return !window.IsClosed() && !(window.flags & GuiBase::FLAG_ICONIFED);
}

ACTION_LAYER StrategicLayerFor(ACTION_SET base)
{
    switch ( base )
    {
    case ACTION_SET_GROUND: return ACTION_LAYER_GROUND_STRATEGIC;
    case ACTION_SET_AIR: return ACTION_LAYER_AIR_STRATEGIC;
    case ACTION_SET_HOST: return ACTION_LAYER_HOST_STRATEGIC;
    default: return ACTION_LAYER_NONE;
    }
}

void ActivateSteamContext(const InputContext &context)
{
    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    if ( !steam.Ready() )
        return;

    const Steam::ApiTable &api = steam.Api();
    if ( !api.GetActionSetHandle || !api.ActivateActionSet )
        return;

    const Steam::InputActionSetHandle base =
        api.GetActionSetHandle(steam.InputInterface(), ActionSetName(context.BaseSet));
    const Steam::InputActionSetHandle layer = context.Layer == ACTION_LAYER_NONE ? 0 :
        api.GetActionSetHandle(steam.InputInterface(), ActionLayerName(context.Layer));

    bool sameControllers = AppliedControllerCount == steam.ControllerCount();
    for ( int i = 0; sameControllers && i < steam.ControllerCount(); ++i )
        sameControllers = AppliedControllers[i] == steam.Controllers()[i];
    if ( SteamContextApplied && sameControllers && AppliedBase == context.BaseSet &&
         AppliedLayer == context.Layer )
        return;

    for ( int i = 0; i < steam.ControllerCount(); i++ )
    {
        const Steam::InputHandle controller = steam.Controllers()[i];
        if ( base )
            api.ActivateActionSet(steam.InputInterface(), controller, base);
        if ( api.DeactivateAllActionSetLayers )
            api.DeactivateAllActionSetLayers(steam.InputInterface(), controller);
        if ( layer && api.ActivateActionSetLayer )
            api.ActivateActionSetLayer(steam.InputInterface(), controller, layer);
    }
    SteamContextApplied = true;
    AppliedBase = context.BaseSet;
    AppliedLayer = context.Layer;
    AppliedControllerCount = steam.ControllerCount();
    for ( int i = 0; i < AppliedControllerCount; ++i )
        AppliedControllers[i] = steam.Controllers()[i];
}

}

InputContext ResolveInputContext(int screenMode, bool hasWorld, bool hasUnit,
                                 int unitType, bool playerInHostGun,
                                 bool mapVisible, bool squadVisible)
{
    InputContext result;
    result.UnitType = unitType;
    result.MapVisible = mapVisible;
    result.SquadVisible = squadVisible;

    if ( screenMode == GAME_SCREEN_MODE_MENU || screenMode == GAME_SCREEN_MODE_REPLAY ||
         !hasWorld || !hasUnit )
        return result;

    if ( playerInHostGun || unitType == BACT_TYPES_ROBO || unitType == BACT_TYPES_GUN )
        result.BaseSet = ACTION_SET_HOST;
    else if ( unitType == BACT_TYPES_TANK || unitType == BACT_TYPES_CAR )
        result.BaseSet = ACTION_SET_GROUND;
    else if ( unitType == BACT_TYPES_BACT || unitType == BACT_TYPES_FLYER ||
              unitType == BACT_TYPES_UFO || unitType == BACT_TYPES_ZEPP )
        result.BaseSet = ACTION_SET_AIR;
    else
        return result;

    if ( mapVisible || squadVisible )
        result.Layer = StrategicLayerFor(result.BaseSet);
    return result;
}

int ResolveControlledUnitType(int unitType, int parentUnitType)
{
    return unitType == BACT_TYPES_MISSLE && parentUnitType >= 0 ? parentUnitType : unitType;
}

const InputContext &CurrentInputContext() { return Context; }

const char *ActionLayerName(ACTION_LAYER layer)
{
    switch ( layer )
    {
    case ACTION_LAYER_GROUND_STRATEGIC: return "GroundStrategic";
    case ACTION_LAYER_AIR_STRATEGIC: return "AirStrategic";
    case ACTION_LAYER_HOST_STRATEGIC: return "HostStrategic";
    default: return "None";
    }
}

bool StrategicLayerActive() { return Context.Layer != ACTION_LAYER_NONE; }

void CloseFrontStrategicWindow()
{
    if ( !ypaworld )
        return;
    // GuiWinToFront appends, so the later of the two visible windows is the
    // frontmost. Prefer the squad window when both have equal/unknown order.
    for ( GuiBaseList::reverse_iterator it = ypaworld->_guiActive.rbegin();
          it != ypaworld->_guiActive.rend(); ++it )
    {
        if ( (*it == &robo_map || *it == &squadron_manager) && Visible(**it) )
        {
            ypaworld->GuiWinClose(*it);
            return;
        }
    }
}

void SyncSteamActionSet()
{
    const int unitType = ypaworld && ypaworld->_userUnit ? ypaworld->_userUnit->_bact_type : -1;
    const int parentUnitType = ypaworld && ypaworld->_userUnit && ypaworld->_userUnit->_parent
        ? ypaworld->_userUnit->_parent->_bact_type : -1;
    const int contextUnitType = ResolveControlledUnitType(unitType, parentUnitType);
    const InputContext target = ResolveInputContext(
        GameScreenMode, ypaworld != nullptr, ypaworld && ypaworld->_userUnit,
        contextUnitType, ypaworld && ypaworld->_playerInHSGun,
        Visible(robo_map), Visible(squadron_manager));
    InputContext diagnosedTarget = target;
    diagnosedTarget.UnitType = unitType;
    const bool changed = Context.BaseSet != target.BaseSet || Context.Layer != target.Layer;
    Context = diagnosedTarget;

    if ( Actions.CurrentActionSet() != target.BaseSet || Actions.ActionSetDepth() == 0 )
    {
        while ( Actions.ActionSetDepth() > 0 )
            Actions.PopActionSet();
        Actions.PushActionSet(target.BaseSet);
    }
    if ( changed )
    {
        Actions.ClearPendingHotKeys();
        ypa_log_out("Steam Input context: base=%s layer=%s unit=%d control_unit=%d map=%d squad=%d\n",
                    ActionSetName(target.BaseSet), ActionLayerName(target.Layer), unitType,
                    contextUnitType,
                    target.MapVisible, target.SquadVisible);
    }

    ActivateSteamContext(target);

    static unsigned mismatchFrames = 0;
    static bool mismatchReported = false;
    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    bool mismatch = false;
    if ( steam.Ready() && steam.ControllerCount() > 0 )
    {
        const Steam::ApiTable &api = steam.Api();
        const Steam::InputHandle controller = steam.Controllers()[0];
        if ( api.GetCurrentActionSet )
        {
            const Steam::InputActionSetHandle expected = api.GetActionSetHandle(
                steam.InputInterface(), ActionSetName(target.BaseSet));
            mismatch = api.GetCurrentActionSet(steam.InputInterface(), controller) != expected;
        }
        if ( !mismatch && target.Layer != ACTION_LAYER_NONE && api.GetActiveActionSetLayers )
        {
            Steam::InputActionSetHandle layers[16] = {0};
            const int count = api.GetActiveActionSetLayers(steam.InputInterface(), controller, layers);
            const Steam::InputActionSetHandle expected = api.GetActionSetHandle(
                steam.InputInterface(), ActionLayerName(target.Layer));
            mismatch = std::find(layers, layers + count, expected) == layers + count;
        }
    }
    mismatchFrames = mismatch ? mismatchFrames + 1 : 0;
    if ( !mismatch ) mismatchReported = false;
    if ( mismatchFrames >= 120 && !mismatchReported )
    {
        ypa_log_out("Steam Input context mismatch persisted: expected %s + %s\n",
                    ActionSetName(target.BaseSet), ActionLayerName(target.Layer));
        mismatchReported = true;
        SteamContextApplied = false;
    }
}

bool SteamInputControlsJoystick()
{
    if ( SteamBackend().SmokeModeActive() )
        return true;

    return Steam::ApiLoader::Instance.Ready() && Steam::ApiLoader::Instance.ControllerCount() > 0;
}

}
