#include <cstdio>
#include <cstring>

#include <SDL2/SDL.h>

#include "system/joy_util.h"

static int fail(const char *message)
{
    std::fprintf(stderr, "test_sdl_virtual_controller: %s\n", message);
    return 1;
}

static int test_axis_scaling()
{
    if (JoyUtil::ScaleJoystickAxis(0) != 0)
        return fail("deadzone should zero the origin");
    if (JoyUtil::ScaleJoystickAxis(6553) != 0)
        return fail("deadzone should include the 20% threshold");
    if (JoyUtil::ScaleJoystickAxis(6554) <= 0)
        return fail("values above the deadzone must be positive");
    if (JoyUtil::ScaleJoystickAxis(32767) != 300)
        return fail("full deflection must clamp to 300");
    if (JoyUtil::ScaleJoystickAxis(-32768) != -300)
        return fail("full negative deflection must clamp to -300");

    SDL_JoystickGUID zero;
    std::memset(&zero, 0, sizeof(zero));
    if (!JoyUtil::GuidIsZero(zero))
        return fail("zero GUID detection failed");
    return 0;
}

static int test_virtual_controller()
{
#if !SDL_VERSION_ATLEAST(2, 0, 14)
    std::fprintf(stderr,
                 "test_sdl_virtual_controller: SDL virtual joystick API unavailable; skipping\n");
    return 0;
#else
    if (SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER) < 0)
        return fail(SDL_GetError());

    const int virtual_index = SDL_JoystickAttachVirtual(
        SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 16, 1);
    if (virtual_index < 0)
    {
        std::fprintf(stderr,
                     "test_sdl_virtual_controller: AttachVirtual failed (%s); skipping\n",
                     SDL_GetError());
        SDL_Quit();
        return 0;
    }

    SDL_Joystick *joystick = SDL_JoystickOpen(virtual_index);
    if (!joystick)
    {
        SDL_JoystickDetachVirtual(virtual_index);
        SDL_Quit();
        return fail(SDL_GetError());
    }

    const SDL_JoystickID instance = SDL_JoystickInstanceID(joystick);
    if (SDL_JoystickSetVirtualAxis(joystick, 0, 20000) != 0)
    {
        SDL_JoystickClose(joystick);
        SDL_JoystickDetachVirtual(virtual_index);
        SDL_Quit();
        return fail(SDL_GetError());
    }
    SDL_JoystickUpdate();
    const int raw = SDL_JoystickGetAxis(joystick, 0);
    const int scaled = JoyUtil::ScaleJoystickAxis(raw);
    if (scaled <= 0)
    {
        SDL_JoystickClose(joystick);
        SDL_JoystickDetachVirtual(virtual_index);
        SDL_Quit();
        return fail("virtual left-stick axis did not scale positively");
    }

    SDL_JoystickClose(joystick);
    if (SDL_JoystickDetachVirtual(virtual_index) != 0)
    {
        SDL_Quit();
        return fail(SDL_GetError());
    }

    if (SDL_JoystickFromInstanceID(instance) != NULL)
    {
        SDL_Quit();
        return fail("detached virtual joystick instance remained reachable");
    }

    SDL_Quit();
    std::printf("test_sdl_virtual_controller: ok (scaled axis=%d)\n", scaled);
    return 0;
#endif
}

int main()
{
    if (test_axis_scaling() != 0)
        return 1;
    return test_virtual_controller();
}
