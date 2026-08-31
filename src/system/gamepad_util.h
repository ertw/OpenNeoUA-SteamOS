#ifndef SYSTEM_GAMEPAD_UTIL_H_INCLUDED
#define SYSTEM_GAMEPAD_UTIL_H_INCLUDED

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <array>
#include <deque>

namespace Input
{
namespace GamepadUtil
{

struct Stick
{
    float X = 0.0f;
    float Y = 0.0f;
};

inline Stick NormalizeStick(int16_t x, int16_t y, float deadzone = 0.20f)
{
    const float fx = x < 0 ? (float)x / 32768.0f : (float)x / 32767.0f;
    const float fy = -(y < 0 ? (float)y / 32768.0f : (float)y / 32767.0f);
    const float magnitude = std::sqrt(fx * fx + fy * fy);
    if (magnitude <= deadzone || magnitude <= 0.0f)
        return Stick();

    const float scaled = std::min(1.0f,
                                  (magnitude - deadzone) / (1.0f - deadzone));
    Stick result;
    result.X = fx / magnitude * scaled;
    result.Y = fy / magnitude * scaled;
    return result;
}

inline bool TriggerPressed(int16_t value, bool wasPressed,
                           float pressAt = 0.55f, float releaseAt = 0.45f)
{
    const float normalized = std::max(0.0f, (float)value / 32767.0f);
    return wasPressed ? normalized > releaseAt : normalized >= pressAt;
}

inline float Strongest(float a, float b)
{
    return std::fabs(b) > std::fabs(a) ? b : a;
}

// Retained ground-drive command. Left-stick Y ramps the value over time;
// neutral holds it. This is command retention, not physical cruise control.
class StickyDriveAxis
{
public:
    static constexpr uint32_t kMaxPeriodMs = 100;

    void Update(float stickY, uint32_t periodMs)
    {
        if (periodMs > kMaxPeriodMs)
            periodMs = kMaxPeriodMs;

        const float deflection = std::max(-1.0f, std::min(1.0f, stickY));
        _value += deflection * (float)periodMs / 1000.0f;
        if (_value > 1.0f)
            _value = 1.0f;
        else if (_value < -1.0f)
            _value = -1.0f;
    }

    void Reset() { _value = 0.0f; }
    float Value() const { return _value; }

private:
    float _value = 0.0f;
};

// Gameplay owns one session, keyed to the controlled unit. Mouse-grab and
// map/UI interaction are not identity inputs and must not be passed here.
class StickyDriveSession
{
public:
    float Sync(uint32_t unitGid, bool controllingGround, bool unitAlive,
               bool joystickEnabled, bool controllerActive, bool brakeHeld,
               float stickY, uint32_t periodMs)
    {
        const bool live = joystickEnabled && controllerActive;
        const bool reconnect = live && !_live;
        const bool identityChanged = unitGid != _unitGid;
        _live = live;
        _unitGid = unitGid;

        const bool valid = controllingGround && unitAlive && live && unitGid != 0;
        if (!valid || reconnect || identityChanged || brakeHeld)
            _axis.Reset();

        if (valid && !brakeHeld)
            _axis.Update(stickY, periodMs);

        return _axis.Value();
    }

    void Reset()
    {
        _axis.Reset();
        _unitGid = 0;
        _live = false;
    }

    float Value() const { return _axis.Value(); }

private:
    StickyDriveAxis _axis;
    uint32_t _unitGid = 0;
    bool _live = false;
};

inline bool CombinedMouseButton(bool physical, bool controller)
{
    return physical || controller;
}

struct DigitalEdge
{
    bool Held = false;
    bool Pressed = false;
    bool Released = false;
};

template <std::size_t Count>
class DigitalActionTracker
{
public:
    DigitalEdge Update(std::size_t action, bool physical, bool controller,
                       int hotkeySlot = -1)
    {
        const bool combined = physical || controller;
        DigitalEdge edge;
        edge.Held = combined;
        edge.Pressed = combined && !_previous[action];
        edge.Released = !combined && _previous[action];
        if (hotkeySlot >= 0 && controller && !_previousController[action])
            _hotkeys.push_back(hotkeySlot);
        _previous[action] = combined;
        _previousController[action] = controller;
        return edge;
    }

    int DeliverHotkey(int physicalHotkey)
    {
        if (physicalHotkey >= 0 || _hotkeys.empty())
            return physicalHotkey;
        const int hotkey = _hotkeys.front();
        _hotkeys.pop_front();
        return hotkey;
    }

    std::size_t PendingHotkeys() const { return _hotkeys.size(); }

    void Reset()
    {
        _previous.fill(false);
        _previousController.fill(false);
        _hotkeys.clear();
    }

private:
    std::array<bool, Count> _previous = {{false}};
    std::array<bool, Count> _previousController = {{false}};
    std::deque<int> _hotkeys;
};

enum Context
{
    CONTEXT_GROUND,
    CONTEXT_AIR,
    CONTEXT_GUN_OR_HOST
};

struct ContextResult
{
    float DriveDir = 0.0f;
    float DriveSpeed = 0.0f;
    float GunHeight = 0.0f;
    float FlyDir = 0.0f;
    float FlyHeight = 0.0f;
    float FlySpeed = 0.0f;
    bool AnalogGround = false;
};

inline ContextResult ApplyContext(Context context, const Stick &left,
                                  const Stick &right,
                                  const ContextResult &existing = ContextResult())
{
    ContextResult result = existing;
    if (context == CONTEXT_GROUND)
    {
        result.DriveDir = Strongest(result.DriveDir,
                                    left.X == 0.0f ? right.X : left.X);
        result.DriveSpeed = Strongest(result.DriveSpeed, left.Y);
        result.GunHeight = Strongest(result.GunHeight, right.Y);
        result.AnalogGround = true;
    }
    else if (context == CONTEXT_AIR)
    {
        result.FlyDir = Strongest(result.FlyDir,
                                  left.X == 0.0f ? right.X : left.X);
        result.FlyHeight = Strongest(result.FlyHeight, left.Y);
        result.FlySpeed = Strongest(result.FlySpeed, right.Y);
    }
    else
    {
        result.FlyDir = Strongest(result.FlyDir, right.X);
        result.FlyHeight = Strongest(result.FlyHeight, right.Y);
    }
    return result;
}

}
}

#endif
