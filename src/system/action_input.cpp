#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <cstring>

#include "action_input.h"
#include "action_set_sync.h"
#include "../log.h"

#ifdef OPENNEOUA_ENABLE_STEAMWORKS
#include "action_backend.h"
#endif

namespace Input
{

namespace
{

// The legacy backend is owned here rather than by callers so QueryInput does
// not have to manage facade lifetime.  Defined before ActionInput::Instance so
// the singleton's constructor can register it without depending on static
// initialisation order.
KeyboardExpressionBackend LegacyBackend;

// Positions from different backends are not additive: taking the larger
// magnitude keeps a centred stick from cancelling a held key.  Because this
// returns one of its operands rather than a sum, the combined magnitude never
// exceeds the largest single contribution, so no clamp is needed and the
// legacy value survives untouched when only one backend is live.
float CombinePosition(float a, float b)
{
    if ( a == 0.0f )
        return b;
    if ( b == 0.0f )
        return a;
    return ( a < 0.0f ? -a : a ) >= ( b < 0.0f ? -b : b ) ? a : b;
}

}

ActionInput ActionInput::Instance;

const char *ActionSetName(ACTION_SET set)
{
    switch ( set )
    {
    case ACTION_SET_MENU:   return "Menu";
    case ACTION_SET_GROUND: return "Ground";
    case ACTION_SET_AIR:    return "Air";
    case ACTION_SET_HOST:   return "Host";
    case ACTION_SET_MAP:    return "Map";
    case ACTION_SET_COUNT:  break;
    }
    return "Unknown";
}

ActionInput::ActionInput()
{
    Reset();
}

void ActionInput::Reset()
{
    _backends.clear();
    _frame.Reset();

    for ( ActionSample &sample : _samples )
        sample = ActionSample();

    _wasActive.fill(false);
    _actionSets.clear();
    _pendingHotKeys.clear();
    _passthrough = LegacyInputPrimitives();
    _hasPassthrough = false;

    AddBackend(&LegacyBackend);
}

void ActionInput::AddBackend(IActionBackend *backend)
{
    if ( !backend )
        return;

    if ( std::find(_backends.begin(), _backends.end(), backend) == _backends.end() )
        _backends.push_back(backend);
}

void ActionInput::ClearBackends()
{
    _backends.clear();
}

void ActionInput::CombineSample(ActionSample *target, const ActionSample &source)
{
    target->active = target->active || source.active;

    target->posX = CombinePosition(target->posX, source.posX);
    target->posY = CombinePosition(target->posY, source.posY);

    // Deltas are naturally additive.
    target->delX = target->delX + source.delX;
    target->delY = target->delY + source.delY;
}

void ActionInput::ApplyEdges()
{
    for ( std::size_t binding = 0; binding < _samples.size(); binding++ )
    {
        ActionSample &sample = _samples[binding];
        const bool was = _wasActive[binding];

        sample.pressed = sample.active && !was;
        sample.released = !sample.active && was;

        _wasActive[binding] = sample.active;
    }
}

void ActionInput::Update(const LegacyInputPrimitives &primitives)
{
    LegacyBackend.SetPrimitives(&primitives);

    _frame.Reset();

    for ( IActionBackend *backend : _backends )
    {
        if ( !backend || !backend->Available() )
            continue;

        ActionFrame contribution;
        contribution.Reset();
        backend->Contribute(&contribution);

        for ( std::size_t binding = 0; binding < contribution.Samples.size(); binding++ )
            CombineSample(&_frame.Samples[binding], contribution.Samples[binding]);

        for ( const HotKeyActivation &activation : contribution.HotKeys )
            _frame.HotKeys.push_back(activation);

        if ( contribution.HasPassthrough && !_frame.HasPassthrough )
        {
            _frame.Passthrough = contribution.Passthrough;
            _frame.HasPassthrough = true;
        }
    }

    _samples = _frame.Samples;
    ApplyEdges();

    _passthrough = _frame.Passthrough;
    _hasPassthrough = _frame.HasPassthrough;

    _pendingHotKeys.clear();
    for ( const HotKeyActivation &activation : _frame.HotKeys )
        _pendingHotKeys.push_back(activation);

    LegacyBackend.SetPrimitives(nullptr);
}

void ActionInput::PopulateLegacyState(TInputState *state) const
{
    if ( !state )
        return;

    *state = TInputState();

    if ( !_hasPassthrough )
        return;

    state->Period = _passthrough.Period;

    if ( !_passthrough.HasFocus )
        return;

    state->KbdLastDown = _passthrough.KbdLastDown;
    state->KbdLastHit = _passthrough.KbdLastHit;
    state->chr = _passthrough.Chr;
    state->ClickInf = _passthrough.ClickInf;

    // Exactly one hotkey slot per frame, taken from the head of the FIFO so
    // the legacy consumers see what they saw before.
    state->HotKeyID = _pendingHotKeys.empty() ? -1 : (int16_t)_pendingHotKeys.front().Slot;

    for ( std::size_t slot = 0; slot < _passthrough.ButtonState.size(); slot++ )
    {
        const int binding = World::ActionTable::BindingForSlot(
            World::INPUT_BIND_TYPE_BUTTON, (int)slot);

        if ( binding > 0 && binding < World::INPUT_BIND_MAX )
        {
            if ( _samples[binding].active )
                state->Buttons.Set(slot);
        }
        else if ( _passthrough.ButtonState[slot] )
        {
            // Raw joystick buttons 16-23 and the unconfigured slots have no
            // action yet; they pass through until Phase 6.
            state->Buttons.Set(slot);
        }
    }

    for ( std::size_t slot = 0; slot < _passthrough.SliderPos.size(); slot++ )
    {
        const int binding = World::ActionTable::BindingForSlot(
            World::INPUT_BIND_TYPE_SLIDER, (int)slot);

        if ( binding > 0 && binding < World::INPUT_BIND_MAX )
        {
            state->Sliders[slot] = _samples[binding].posX;
        }
        else if ( _passthrough.SliderValid[slot] )
        {
            // Mouse-look slots 10-11 and raw joystick axes 12-16.
            state->Sliders[slot] = _passthrough.SliderPos[slot];
        }
    }

#ifdef OPENNEOUA_ENABLE_STEAMWORKS
    if ( SteamInputControlsJoystick() )
    {
        const float aimX = SteamBackend().AimDeltaX();
        const float aimY = SteamBackend().AimDeltaY();
        if ( aimX != 0.0f || aimY != 0.0f )
        {
            state->Sliders[10] = aimX;
            state->Sliders[11] = aimY;
        }
    }
#endif
}

const ActionSample &ActionInput::Sample(int binding) const
{
    static const ActionSample Empty;

    if ( binding <= 0 || binding >= World::INPUT_BIND_MAX )
        return Empty;

    return _samples[binding];
}

bool ActionInput::Active(int binding) const
{
    return Sample(binding).active;
}

bool ActionInput::Pressed(int binding) const
{
    return Sample(binding).pressed;
}

bool ActionInput::Released(int binding) const
{
    return Sample(binding).released;
}

float ActionInput::AnalogX(int binding) const
{
    return Sample(binding).posX;
}

float ActionInput::AnalogY(int binding) const
{
    return Sample(binding).posY;
}

bool ActionInput::SteamInputLive() const
{
#ifdef OPENNEOUA_ENABLE_STEAMWORKS
    return SteamInputControlsJoystick();
#else
    return false;
#endif
}

void ActionInput::PushActionSet(ACTION_SET set)
{
    if ( (int)set < 0 || (int)set >= (int)ACTION_SET_COUNT )
        return;

    _actionSets.push_back(set);
}

void ActionInput::PopActionSet()
{
    if ( !_actionSets.empty() )
        _actionSets.pop_back();
}

ACTION_SET ActionInput::CurrentActionSet() const
{
    if ( _actionSets.empty() )
        return ACTION_SET_MENU;

    return _actionSets.back();
}

bool ActionInput::PeekPendingHotKey(HotKeyActivation *activation) const
{
    if ( _pendingHotKeys.empty() )
        return false;

    if ( activation )
        *activation = _pendingHotKeys.front();

    return true;
}

bool ActionInput::PopPendingHotKey(HotKeyActivation *activation)
{
    if ( _pendingHotKeys.empty() )
        return false;

    if ( activation )
        *activation = _pendingHotKeys.front();

    _pendingHotKeys.pop_front();
    return true;
}

void ActionInput::ClearPendingHotKeys()
{
    _pendingHotKeys.clear();
}

void ActionInput::ApplyGrabbedAimLook(float aimX, float aimY)
{
    if ( aimX == 0.0f && aimY == 0.0f )
        return;

    _samples[World::INPUT_BIND_FLY_DIR].posX =
        CombinePosition(_samples[World::INPUT_BIND_FLY_DIR].posX, aimX);
    _samples[World::INPUT_BIND_DRIVE_DIR].posX =
        CombinePosition(_samples[World::INPUT_BIND_DRIVE_DIR].posX, aimX);
    _samples[World::INPUT_BIND_FLY_HEIGHT].posX =
        CombinePosition(_samples[World::INPUT_BIND_FLY_HEIGHT].posX, aimY);

    const float gunHeight = -aimY * 1.5f;
    _samples[World::INPUT_BIND_GUN_HEIGHT].posX =
        CombinePosition(_samples[World::INPUT_BIND_GUN_HEIGHT].posX, gunHeight);
}


namespace ActionParity
{

namespace
{

bool Initialized = false;
bool EnabledFlag = false;
unsigned long Frames = 0;
unsigned long Mismatches = 0;
std::string Report;

}

bool Enabled()
{
    if ( !Initialized )
    {
        Initialized = true;

        const char *value = std::getenv("OPENNEOUA_INPUT_PARITY");
        EnabledFlag = value && value[0] != '\0' && std::strcmp(value, "0") != 0;

        if ( EnabledFlag )
            ypa_log_out("input.actions: parity harness enabled\n");
    }

    return EnabledFlag;
}

void SetEnabled(bool enabled)
{
    Initialized = true;
    EnabledFlag = enabled;
}

void Check(const LegacyInputPrimitives &primitives, const TInputState &candidate)
{
#ifdef OPENNEOUA_ENABLE_STEAMWORKS
    if ( SteamInputControlsJoystick() )
        return;
#endif

    TInputState reference;
    BuildLegacyInputState(primitives, &reference);

    Report.clear();
    const int differences = DiffLegacyInputState(reference, candidate, &Report);

    Frames++;

    if ( differences <= 0 )
        return;

    Mismatches++;

    ypa_log_out("input.actions: PARITY MISMATCH on frame %lu (%d field(s)):\n%s",
                Frames, differences, Report.c_str());

    // The facade is only allowed to be authoritative because it reproduces the
    // legacy state exactly; a divergence is a facade bug, not a tolerance.
    assert(differences == 0 && "ActionInput diverged from the legacy input state");
}

unsigned long FrameCount()
{
    return Frames;
}

unsigned long MismatchCount()
{
    return Mismatches;
}

const std::string &LastReport()
{
    return Report;
}

void ResetCounters()
{
    Frames = 0;
    Mismatches = 0;
    Report.clear();
}

}

}
