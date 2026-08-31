#ifndef SYSTEM_ACTION_SET_SYNC_H_INCLUDED
#define SYSTEM_ACTION_SET_SYNC_H_INCLUDED

#include "action_input.h"

namespace Input
{

enum ACTION_LAYER
{
    ACTION_LAYER_NONE = 0,
    ACTION_LAYER_GROUND_STRATEGIC,
    ACTION_LAYER_AIR_STRATEGIC,
    ACTION_LAYER_HOST_STRATEGIC
};

struct InputContext
{
    ACTION_SET BaseSet = ACTION_SET_MENU;
    ACTION_LAYER Layer = ACTION_LAYER_NONE;
    int UnitType = -1;
    bool MapVisible = false;
    bool SquadVisible = false;
};

InputContext ResolveInputContext(int screenMode, bool hasWorld, bool hasUnit,
                                 int unitType, bool playerInHostGun,
                                 bool mapVisible, bool squadVisible);
int ResolveControlledUnitType(int unitType, int parentUnitType);
const InputContext &CurrentInputContext();
const char *ActionLayerName(ACTION_LAYER layer);
bool StrategicLayerActive();
void CloseFrontStrategicWindow();

void SyncSteamActionSet();

// True when Steam Input is live and should own joystick merge semantics.
bool SteamInputControlsJoystick();

}

#endif // SYSTEM_ACTION_SET_SYNC_H_INCLUDED
