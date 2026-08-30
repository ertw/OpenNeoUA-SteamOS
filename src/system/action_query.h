#ifndef SYSTEM_ACTION_QUERY_H_INCLUDED
#define SYSTEM_ACTION_QUERY_H_INCLUDED

#include "action_input.h"

// OpenNeoUA: thin query helpers for migrated consumers.

namespace Input
{

inline bool ActionHeld(int binding)
{
    return Actions.Active(binding);
}

inline bool ActionPressed(int binding)
{
    return Actions.Pressed(binding);
}

inline float ActionAxisX(int binding)
{
    return Actions.AnalogX(binding);
}

inline float ActionAxisY(int binding)
{
    return Actions.AnalogY(binding);
}

}

#endif // SYSTEM_ACTION_QUERY_H_INCLUDED
