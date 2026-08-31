#include <cmath>
#include <cstdio>

#include <SDL.h>

#include "system/gamepad_util.h"

namespace
{
int Failures = 0;

void Check(bool condition, const char *message)
{
    if (!condition)
    {
        std::fprintf(stderr, "test_gamepad_input: %s\n", message);
        ++Failures;
    }
}

bool Near(float a, float b, float epsilon = 0.001f)
{
    return std::fabs(a - b) <= epsilon;
}

void TestSticksAndTriggers()
{
    using namespace Input::GamepadUtil;
    Check(Near(NormalizeStick(0, 0).X, 0.0f), "center must be neutral");
    Check(Near(NormalizeStick(6553, 0).X, 0.0f), "20% radial deadzone boundary");
    Check(NormalizeStick(6554, 0).X > 0.0f, "value outside deadzone must survive");
    Check(Near(NormalizeStick(32767, 0).X, 1.0f), "positive X must normalize to one");
    Check(Near(NormalizeStick(-32768, 0).X, -1.0f), "negative X must normalize to minus one");
    Check(NormalizeStick(0, -32768).Y > 0.999f, "SDL Y must be inverted");

    bool pressed = TriggerPressed((int16_t)(32767 * 0.54f), false);
    Check(!pressed, "trigger must not press below 55%");
    pressed = TriggerPressed((int16_t)(32767 * 0.56f), pressed);
    Check(pressed, "trigger must press above 55%");
    pressed = TriggerPressed((int16_t)(32767 * 0.50f), pressed);
    Check(pressed, "trigger must remain held in hysteresis band");
    pressed = TriggerPressed((int16_t)(32767 * 0.44f), pressed);
    Check(!pressed, "trigger must release below 45%");

    Check(Near(Strongest(0.8f, -0.6f), 0.8f), "strongest analog keeps larger existing source");
    Check(Near(Strongest(0.2f, -0.7f), -0.7f), "strongest analog accepts larger controller source");
}

void TestContexts()
{
    using namespace Input::GamepadUtil;
    Stick left = {0.7f, 0.4f};
    Stick right = {-0.3f, 0.8f};
    ContextResult ground = ApplyContext(CONTEXT_GROUND, left, right);
    Check(Near(ground.DriveDir, 0.7f), "ground left X steering");
    Check(Near(ground.DriveSpeed, 0.4f), "ground left Y drive speed");
    Check(Near(ground.GunHeight, 0.8f), "ground right Y gun elevation");
    Check(ground.AnalogGround, "ground analog marker");

    left = {0.0f, 0.0f};
    ground = ApplyContext(CONTEXT_GROUND, left, right);
    Check(Near(ground.DriveDir, -0.3f), "ground right X fallback");
    Check(Near(ground.DriveSpeed, 0.0f) && ground.AnalogGround,
          "neutral retained command coasts without synthetic brake");

    ContextResult keyboardDrive;
    keyboardDrive.DriveSpeed = 0.75f;
    ground = ApplyContext(CONTEXT_GROUND, left, right, keyboardDrive);
    Check(Near(ground.DriveSpeed, 0.75f), "neutral retained command keeps stronger keyboard drive");
    Check(ground.AnalogGround, "analog marker remains with keyboard arbitration");

    ContextResult air = ApplyContext(CONTEXT_AIR, left, right);
    Check(Near(air.FlyDir, -0.3f), "air right X fallback");
    Check(Near(air.FlyHeight, 0.0f), "air left Y height");
    Check(Near(air.FlySpeed, 0.8f), "air right Y speed");

    ContextResult host = ApplyContext(CONTEXT_GUN_OR_HOST, left, right);
    Check(Near(host.FlyDir, -0.3f) && Near(host.FlyHeight, 0.8f),
          "gun/host right-stick viewer channels");

    StickyDriveAxis sticky;
    for (int i = 0; i < 4; ++i)
        sticky.Update(1.0f, 100);
    left = {0.2f, sticky.Value()};
    ground = ApplyContext(CONTEXT_GROUND, left, right);
    Check(Near(ground.DriveSpeed, 0.4f) && ground.AnalogGround,
          "retained command feeds DriveSpeed and analog marker");

    Check(CombinedMouseButton(true, false), "physical mouse source");
    Check(CombinedMouseButton(false, true), "controller mouse source");
    Check(CombinedMouseButton(true, true), "overlapping mouse sources");
    Check(!CombinedMouseButton(false, false), "all mouse sources released");

    DigitalActionTracker<8> tracker;
    DigitalEdge edge = tracker.Update(1, false, true, 9);
    Check(edge.Held && edge.Pressed && !edge.Released, "controller action rising edge");
    edge = tracker.Update(1, false, true, 9);
    Check(edge.Held && !edge.Pressed, "controller action held edge suppression");
    edge = tracker.Update(1, false, false, 9);
    Check(!edge.Held && edge.Released, "controller action release edge");
    tracker.Update(2, false, true, 16);
    Check(tracker.PendingHotkeys() == 2, "simultaneous hotkeys queue without loss");
    Check(tracker.DeliverHotkey(32) == 32, "physical hotkey wins its frame");
    Check(tracker.PendingHotkeys() == 2, "physical hotkey does not discard controller FIFO");
    Check(tracker.DeliverHotkey(-1) == 9, "controller FIFO delivers oldest edge");
    Check(tracker.DeliverHotkey(-1) == 16, "controller FIFO delivers one edge per frame");
}

void TestStickyDriveAxis()
{
    using namespace Input::GamepadUtil;
    StickyDriveAxis axis;
    Check(Near(axis.Value(), 0.0f), "sticky drive starts at zero");

    axis.Update(0.0f, 40);
    Check(Near(axis.Value(), 0.0f), "neutral holds zero");

    for (int i = 0; i < 10; ++i)
        axis.Update(1.0f, 100);
    Check(Near(axis.Value(), 1.0f), "full forward reaches one in one second");

    axis.Update(0.0f, 50);
    Check(Near(axis.Value(), 1.0f), "neutral holds positive command");

    axis.Update(1.0f, 100);
    Check(Near(axis.Value(), 1.0f), "clamp at full forward");

    axis.Reset();
    for (int i = 0; i < 10; ++i)
        axis.Update(-1.0f, 100);
    Check(Near(axis.Value(), -1.0f), "full reverse reaches minus one in one second");
    axis.Update(0.0f, 16);
    Check(Near(axis.Value(), -1.0f), "neutral holds negative command");
    axis.Update(-1.0f, 200);
    Check(Near(axis.Value(), -1.0f), "clamp at full reverse");

    axis.Reset();
    for (int i = 0; i < 10; ++i)
        axis.Update(0.5f, 100);
    Check(Near(axis.Value(), 0.5f), "half deflection scales to half command");

    StickyDriveAxis a;
    StickyDriveAxis b;
    for (int i = 0; i < 20; ++i)
        a.Update(1.0f, 50);
    for (int i = 0; i < 50; ++i)
        b.Update(1.0f, 20);
    Check(Near(a.Value(), 1.0f) && Near(b.Value(), 1.0f),
          "full deflection is frame-rate independent");

    axis.Reset();
    axis.Update(1000.0f, 1000);
    Check(Near(axis.Value(), 0.1f), "period cap prevents stall jumps");

    axis.Reset();
    axis.Update(1.0f, 100);
    axis.Update(1.0f, 100);
    axis.Update(-1.0f, 100);
    axis.Update(-1.0f, 100);
    axis.Update(-1.0f, 100);
    Check(Near(axis.Value(), -0.1f), "command crosses zero into reverse");
}

void TestStickyDriveSession()
{
    using namespace Input::GamepadUtil;
    StickyDriveSession drive;
    for (int i = 0; i < 5; ++i)
        drive.Sync(11, true, true, true, true, false, 1.0f, 100);
    Check(Near(drive.Value(), 0.5f), "session accumulates for a live ground unit");

    drive.Sync(11, true, true, true, true, false, 0.0f, 16);
    Check(Near(drive.Value(), 0.5f), "same unit preserves command without grab or map inputs");

    drive.Sync(11, true, true, true, true, true, 1.0f, 40);
    Check(Near(drive.Value(), 0.0f), "explicit brake clears retained command");
    drive.Sync(11, true, true, true, true, true, 1.0f, 100);
    Check(Near(drive.Value(), 0.0f), "held brake blocks accumulation");

    drive.Sync(11, true, true, true, true, false, 1.0f, 100);
    Check(Near(drive.Value(), 0.1f), "command resumes after brake release");

    drive.Sync(12, true, true, true, true, false, 0.0f, 40);
    Check(Near(drive.Value(), 0.0f), "unit switch resets");

    drive.Sync(12, true, true, true, true, false, 1.0f, 200);
    drive.Sync(12, true, false, true, true, false, 1.0f, 40);
    Check(Near(drive.Value(), 0.0f), "death resets");

    drive.Sync(12, true, true, true, true, false, 1.0f, 200);
    drive.Sync(12, false, true, true, true, false, 1.0f, 40);
    Check(Near(drive.Value(), 0.0f), "leaving tank or car control resets");

    drive.Sync(12, true, true, true, true, false, 1.0f, 200);
    drive.Sync(12, true, true, false, true, false, 1.0f, 40);
    Check(Near(drive.Value(), 0.0f), "joystick disable resets");

    drive.Sync(12, true, true, true, true, false, 1.0f, 200);
    drive.Sync(12, true, true, true, false, false, 1.0f, 40);
    Check(Near(drive.Value(), 0.0f), "controller disconnect resets");
    drive.Sync(12, true, true, true, true, false, 0.0f, 16);
    Check(Near(drive.Value(), 0.0f), "controller reconnect starts from zero");
}

void TestVirtualController()
{
#if !SDL_VERSION_ATLEAST(2, 0, 14)
    std::fprintf(stderr, "test_gamepad_input: virtual controller API unavailable; skipping\n");
#else
    if (SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER | SDL_INIT_EVENTS) < 0)
    {
        Check(false, SDL_GetError());
        return;
    }
    const int first = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 16, 1);
    const int second = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 6, 16, 1);
    if (first < 0 || second < 0)
    {
        std::fprintf(stderr, "test_gamepad_input: virtual attach unavailable; skipping (%s)\n", SDL_GetError());
        SDL_Quit();
        return;
    }
    Check(SDL_IsGameController(first), "virtual device must be recognized semantically");
    SDL_GameController *controller = SDL_GameControllerOpen(first);
    Check(controller != NULL, "recognized virtual controller must open");
    SDL_Joystick *joystick = controller ? SDL_GameControllerGetJoystick(controller) : NULL;
    const SDL_JoystickID instance = joystick ? SDL_JoystickInstanceID(joystick) : -1;
    if (joystick)
    {
        SDL_JoystickSetVirtualAxis(joystick, SDL_CONTROLLER_AXIS_LEFTX, 24000);
        SDL_JoystickSetVirtualButton(joystick, SDL_CONTROLLER_BUTTON_A, 1);
        SDL_JoystickUpdate();
        Check(SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTX) > 0,
              "virtual semantic axis");
        Check(SDL_GameControllerGetButton(controller, SDL_CONTROLLER_BUTTON_A) != 0,
              "virtual semantic button");
    }
    if (controller)
        SDL_GameControllerClose(controller);
    SDL_JoystickDetachVirtual(first);
    SDL_JoystickUpdate();
    Check(SDL_JoystickFromInstanceID(instance) == NULL, "hot-plug removal releases instance");
    Check(SDL_IsGameController(0), "remaining controller is available for failover");
    SDL_JoystickDetachVirtual(0);
    SDL_Quit();
#endif
}
}

int main()
{
    TestSticksAndTriggers();
    TestContexts();
    TestStickyDriveAxis();
    TestStickyDriveSession();
    TestVirtualController();
    if (Failures)
        return 1;
    std::printf("test_gamepad_input: ok\n");
    return 0;
}
