#ifndef SYSTEM_ACTION_BACKEND_H_INCLUDED
#define SYSTEM_ACTION_BACKEND_H_INCLUDED

#include <array>
#include <string>
#include <vector>

#include "action_table.h"
#include "inpt.h"

// OpenNeoUA: producers of action state for the ActionInput facade.
//
// Both backends run every frame and are combined rather than switched, so a
// keyboard and a Steam Input controller work simultaneously, which Valve
// requires.  Backends never compute edges: they report only what is held this
// frame, and ActionInput derives pressed/released from the combined result so
// an edge cannot be counted twice.

namespace Input
{

enum
{
    // The engine reconstructs 32 button and 32 slider slots every frame.
    LEGACY_BUTTON_SLOTS = 32,
    LEGACY_SLIDER_SLOTS = 32
};

// One frame of already-evaluated legacy input expressions, as produced by
// INPEngine from the winp keyboard, mouse and joystick drivers.
//
// This is the raw primitive layer and sits below the facade: the ±300 clamp,
// the ±37/frame keyboard ramp and the ×0.8 decay have already been applied by
// NC_STACK_winp::GetSlider, so the values here are the final ±1.0 axes.
struct LegacyInputPrimitives
{
    uint32_t Period = 0;
    // False when the window lost focus.  The engine then reports no input at
    // all, but still advances slider ramps so nothing is left latched.
    bool HasFocus = true;

    int16_t KbdLastDown = 0;
    int16_t KbdLastHit = 0;
    uint8_t Chr = 0;
    // Engine hotkey slot resolved from KbdLastHit, or -1.  This is a slot
    // index, not an INPUT_BIND, and only one can be reported per frame.
    int16_t HotKeyID = -1;

    std::array<bool, LEGACY_BUTTON_SLOTS> ButtonState =
        Common::ArrayInit<bool, LEGACY_BUTTON_SLOTS>(false);
    // A slider is only published when the non-slider part of its expression
    // evaluates true; otherwise the engine leaves the slot at zero.
    std::array<bool, LEGACY_SLIDER_SLOTS> SliderValid =
        Common::ArrayInit<bool, LEGACY_SLIDER_SLOTS>(false);
    std::array<float, LEGACY_SLIDER_SLOTS> SliderPos =
        Common::ArrayInit<float, LEGACY_SLIDER_SLOTS>(0.0f);

    TClickBoxInf ClickInf;
};

// One activation of a digital action, carrying both representations because
// they are not interchangeable: hotkey slots that are holes in the action
// table have no INPUT_BIND, yet the engine can still report them.
struct HotKeyActivation
{
    int Slot = -1;
    int Binding = -1;

    HotKeyActivation() = default;
    HotKeyActivation(int slot, int binding) : Slot(slot), Binding(binding) {}
};

struct ActionSample
{
    bool active   = false;  // held this frame
    bool pressed  = false;  // rising edge
    bool released = false;  // falling edge

    float posX = 0.0f, posY = 0.0f;  // joystick_move, -1..1 position
    float delX = 0.0f, delY = 0.0f;  // absolute_mouse, per-frame delta
};

// What backends accumulate into for one frame.
struct ActionFrame
{
    std::array<ActionSample, World::INPUT_BIND_MAX> Samples;
    std::vector<HotKeyActivation> HotKeys;

    // Engine channels with no INPUT_BIND: raw joystick buttons 16-23 and the
    // mouse-look and raw joystick axes 10-16.  They are carried verbatim until
    // Phase 6 migrates their consumers, which keeps TInputState bit-identical.
    LegacyInputPrimitives Passthrough;
    bool HasPassthrough = false;

    void Reset();
};

class IActionBackend
{
public:
    virtual ~IActionBackend() {}

    virtual const char *Name() const = 0;
    virtual bool Available() const = 0;
    virtual void Contribute(ActionFrame *frame) = 0;
};

// Reads INPEngine's already-evaluated button, slider and hotkey results and
// maps engine slots onto INPUT_BIND_* through the action table.
class KeyboardExpressionBackend : public IActionBackend
{
public:
    const char *Name() const override { return "keyboard-expression"; }
    bool Available() const override { return _primitives != nullptr; }
    void Contribute(ActionFrame *frame) override;

    // Valid for the current frame only; ActionInput sets this before running
    // the backends and clears it afterwards.
    void SetPrimitives(const LegacyInputPrimitives *primitives) { _primitives = primitives; }

private:
    const LegacyInputPrimitives *_primitives = nullptr;
};

// Builds TInputState exactly as INPEngine::QueryInput did before the facade
// existed.  Kept as the parity reference and as the one-line revert path.
void BuildLegacyInputState(const LegacyInputPrimitives &primitives, TInputState *state);

// Field-by-field comparison used by the parity harness.  Returns the number of
// differing fields and, when report is non-null, appends one line per
// difference.
int DiffLegacyInputState(const TInputState &reference,
                         const TInputState &candidate,
                         std::string *report);

}

#endif // SYSTEM_ACTION_BACKEND_H_INCLUDED
