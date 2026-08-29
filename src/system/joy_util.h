#ifndef SYSTEM_JOY_UTIL_H_INCLUDED
#define SYSTEM_JOY_UTIL_H_INCLUDED

#include <cstdlib>
#include <cstring>
#include <SDL2/SDL_joystick.h>

namespace JoyUtil
{

inline bool GuidIsZero(const SDL_JoystickGUID &guid)
{
    SDL_JoystickGUID zero;
    std::memset(&zero, 0, sizeof(zero));
    return std::memcmp(&guid, &zero, sizeof(SDL_JoystickGUID)) == 0;
}

// Legacy OpenNeoUA axis scaling: 20% deadzone, then map to +-300.
inline int ScaleJoystickAxis(int raw)
{
    if (std::abs(raw) <= 6553)
        return 0;

    int tmp = raw / 109;
    if (tmp > 300)
        tmp = 300;
    else if (tmp < -300)
        tmp = -300;
    return tmp;
}

}

#endif
