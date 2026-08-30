#include "action_set_sync.h"

#include "action_backend.h"
#include "action_input.h"
#include "steam_api_loader.h"
#include "../global.h"
#include "../yw_internal.h"

extern tehMap robo_map;

namespace Input
{

namespace
{

ACTION_SET ActionSetForGameState()
{
    if ( GameScreenMode == GAME_SCREEN_MODE_MENU ||
         GameScreenMode == GAME_SCREEN_MODE_REPLAY )
        return ACTION_SET_MENU;

    if ( !ypaworld || !ypaworld->_userUnit )
        return ACTION_SET_MENU;

    if ( !robo_map.IsClosed() )
        return ACTION_SET_MAP;

    switch ( ypaworld->_userUnit->_bact_type )
    {
    case BACT_TYPES_ROBO:
        return ACTION_SET_HOST;

    case BACT_TYPES_FLYER:
    case BACT_TYPES_UFO:
    case BACT_TYPES_BACT:
    case BACT_TYPES_ZEPP:
        return ACTION_SET_AIR;

    default:
        return ACTION_SET_GROUND;
    }
}

void ActivateSteamActionSet(ACTION_SET set)
{
    Steam::ApiLoader &steam = Steam::ApiLoader::Instance;
    if ( !steam.Ready() )
        return;

    const Steam::ApiTable &api = steam.Api();
    if ( !api.GetActionSetHandle || !api.ActivateActionSet )
        return;

    const Steam::InputActionSetHandle handle =
        api.GetActionSetHandle(steam.InputInterface(), ActionSetName(set));
    if ( !handle )
        return;

    for ( int i = 0; i < steam.ControllerCount(); i++ )
        api.ActivateActionSet(steam.InputInterface(), steam.Controllers()[i], handle);
}

}

void SyncSteamActionSet()
{
    const ACTION_SET target = ActionSetForGameState();

    if ( Actions.CurrentActionSet() != target || Actions.ActionSetDepth() == 0 )
    {
        Actions.ClearPendingHotKeys();
        while ( Actions.ActionSetDepth() > 0 )
            Actions.PopActionSet();
        Actions.PushActionSet(target);
    }

    ActivateSteamActionSet(target);
}

bool SteamInputControlsJoystick()
{
    if ( SteamBackend().SmokeModeActive() )
        return true;

    return Steam::ApiLoader::Instance.Ready() && Steam::ApiLoader::Instance.ControllerCount() > 0;
}

}
