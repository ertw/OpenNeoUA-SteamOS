#ifndef SYSTEM_ACTION_INPUT_H_INCLUDED
#define SYSTEM_ACTION_INPUT_H_INCLUDED

#include <array>
#include <cstddef>
#include <deque>
#include <string>
#include <vector>

#include "action_backend.h"

// OpenNeoUA: the action facade.
//
// Consumers today read raw engine slots out of TInputState.  This facade
// exposes the same input as INPUT_BIND_* actions with proper edges, which is
// what Steam Input can drive and what Phase 6 will migrate consumers onto.
//
// The facade owns an action-set stack mirroring the real game modes and a FIFO
// of pending hotkey activations.  The FIFO exists because TInputState carries
// exactly one HotKeyID per frame while Steam Input can report several digital
// actions in the same frame.

namespace Input
{

enum ACTION_SET
{
    ACTION_SET_MENU = 0,
    ACTION_SET_GROUND,
    ACTION_SET_AIR,
    ACTION_SET_HOST,
    ACTION_SET_MAP,

    ACTION_SET_COUNT
};

const char *ActionSetName(ACTION_SET set);

class ActionInput
{
public:
    ActionInput();

    void Reset();

    // Backends are combined, never switched.  Ownership stays with the caller.
    void AddBackend(IActionBackend *backend);
    void ClearBackends();
    std::size_t BackendCount() const { return _backends.size(); }

    // Runs every available backend for one frame, combines their output and
    // derives edges from the combined state.
    void Update(const LegacyInputPrimitives &primitives);

    // Writes a TInputState from the facade.  Action-mapped engine slots come
    // from the samples; every other slot is carried through verbatim.
    void PopulateLegacyState(TInputState *state) const;

    const ActionSample &Sample(int binding) const;
    bool Active(int binding) const;
    bool Pressed(int binding) const;
    bool Released(int binding) const;

    void PushActionSet(ACTION_SET set);
    void PopActionSet();
    ACTION_SET CurrentActionSet() const;
    std::size_t ActionSetDepth() const { return _actionSets.size(); }

    // Pending hotkey activations, oldest first.  Drains one per call so the
    // one-HotKeyID-per-frame consumers can be fed without losing activations.
    bool PeekPendingHotKey(HotKeyActivation *activation) const;
    bool PopPendingHotKey(HotKeyActivation *activation);
    std::size_t PendingHotKeyCount() const { return _pendingHotKeys.size(); }
    void ClearPendingHotKeys();

    static ActionInput Instance;

private:
    void CombineSample(ActionSample *target, const ActionSample &source);
    void ApplyEdges();

    std::vector<IActionBackend *> _backends;
    ActionFrame _frame;
    std::array<ActionSample, World::INPUT_BIND_MAX> _samples;
    std::array<bool, World::INPUT_BIND_MAX> _wasActive;
    std::vector<ACTION_SET> _actionSets;
    std::deque<HotKeyActivation> _pendingHotKeys;
    // Retained so unmapped engine slots stay bit-identical through the facade.
    LegacyInputPrimitives _passthrough;
    bool _hasPassthrough = false;
};

static constexpr ActionInput &Actions = ActionInput::Instance;

// OpenNeoUA: debug-only parity harness.
//
// Phase 3 lets the facade populate TInputState.  That is only safe because
// this harness proves, frame by frame, that the facade reproduces the legacy
// result exactly.  It stays available behind a flag for regression triage.
namespace ActionParity
{

// Enabled by OPENNEOUA_INPUT_PARITY=1 in the environment.
bool Enabled();
void SetEnabled(bool enabled);

// Compares a facade-produced state against the legacy reference for the same
// primitives.  Logs and counts any divergence; asserts in debug builds.
void Check(const LegacyInputPrimitives &primitives, const TInputState &candidate);

unsigned long FrameCount();
unsigned long MismatchCount();
const std::string &LastReport();
void ResetCounters();

}

}

#endif // SYSTEM_ACTION_INPUT_H_INCLUDED
