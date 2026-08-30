#ifndef SYSTEM_ACTION_SET_SYNC_H_INCLUDED
#define SYSTEM_ACTION_SET_SYNC_H_INCLUDED

// OpenNeoUA: keeps the Steam Input action set aligned with game mode.

namespace Input
{

void SyncSteamActionSet();

// True when Steam Input is live and should own joystick merge semantics.
bool SteamInputControlsJoystick();

}

#endif // SYSTEM_ACTION_SET_SYNC_H_INCLUDED
