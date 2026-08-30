#include <cstdarg>
#include <cstdio>

#include "action_backend.h"

namespace Input
{

void ActionFrame::Reset()
{
    for ( ActionSample &sample : Samples )
        sample = ActionSample();

    HotKeys.clear();
    Passthrough = LegacyInputPrimitives();
    HasPassthrough = false;
}

void KeyboardExpressionBackend::Contribute(ActionFrame *frame)
{
    if ( !frame || !_primitives )
        return;

    const LegacyInputPrimitives &p = *_primitives;

    // The unmapped engine channels have no action equivalent yet, so the frame
    // keeps a verbatim copy for PopulateLegacyState to pass through.
    frame->Passthrough = p;
    frame->HasPassthrough = true;

    if ( !p.HasFocus )
        return;

    for ( std::size_t i = 0; i < World::ActionTable::ENTRY_COUNT; i++ )
    {
        const World::ActionTable::Entry &entry = World::ActionTable::Entries[i];
        if ( entry.Binding <= 0 || entry.Binding >= World::INPUT_BIND_MAX )
            continue;

        ActionSample &sample = frame->Samples[entry.Binding];

        switch ( entry.Channel )
        {
        case World::INPUT_BIND_TYPE_BUTTON:
            if ( entry.Slot >= 0 && (std::size_t)entry.Slot < p.ButtonState.size() &&
                 p.ButtonState[entry.Slot] )
                sample.active = true;
            break;

        case World::INPUT_BIND_TYPE_SLIDER:
            if ( entry.Slot >= 0 && (std::size_t)entry.Slot < p.SliderPos.size() &&
                 p.SliderValid[entry.Slot] )
            {
                // Slider expressions are single-axis, so the engine value maps
                // onto the X position channel.  Deltas stay untouched: the
                // mouse-look slots that produce them are not actions yet.
                sample.posX += p.SliderPos[entry.Slot];
            }
            break;

        default:
            break;
        }
    }

    // The engine resolves at most one hotkey per frame.
    if ( p.HotKeyID >= 0 )
    {
        const int binding = World::ActionTable::BindingForSlot(
            World::INPUT_BIND_TYPE_HOTKEY, p.HotKeyID);

        frame->HotKeys.push_back(HotKeyActivation(p.HotKeyID, binding));

        if ( binding > 0 && binding < World::INPUT_BIND_MAX )
            frame->Samples[binding].active = true;
    }
}

void BuildLegacyInputState(const LegacyInputPrimitives &primitives, TInputState *state)
{
    if ( !state )
        return;

    *state = TInputState();
    state->Period = primitives.Period;

    if ( !primitives.HasFocus )
        return;

    state->KbdLastDown = primitives.KbdLastDown;
    state->KbdLastHit = primitives.KbdLastHit;
    state->chr = primitives.Chr;
    state->HotKeyID = primitives.HotKeyID;
    state->ClickInf = primitives.ClickInf;

    for ( std::size_t i = 0; i < primitives.ButtonState.size(); i++ )
    {
        if ( primitives.ButtonState[i] )
            state->Buttons.Set(i);
    }

    for ( std::size_t i = 0; i < primitives.SliderPos.size(); i++ )
    {
        if ( primitives.SliderValid[i] )
            state->Sliders[i] = primitives.SliderPos[i];
    }
}

namespace
{

void Report(std::string *report, const char *format, ...)
{
    if ( !report )
        return;

    char buffer[256];
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(buffer, sizeof(buffer), format, arguments);
    va_end(arguments);

    report->append(buffer);
    report->append("\n");
}

bool SameMouse(const TMousePos &a, const TMousePos &b)
{
    return a.ScreenPos == b.ScreenPos && a.BoxPos == b.BoxPos && a.BtnPos == b.BtnPos;
}

}

int DiffLegacyInputState(const TInputState &reference,
                         const TInputState &candidate,
                         std::string *report)
{
    int differences = 0;

    if ( reference.Period != candidate.Period )
    {
        differences++;
        Report(report, "Period: reference %u, candidate %u",
               reference.Period, candidate.Period);
    }

    if ( reference.KbdLastDown != candidate.KbdLastDown )
    {
        differences++;
        Report(report, "KbdLastDown: reference %d, candidate %d",
               (int)reference.KbdLastDown, (int)candidate.KbdLastDown);
    }

    if ( reference.KbdLastHit != candidate.KbdLastHit )
    {
        differences++;
        Report(report, "KbdLastHit: reference %d, candidate %d",
               (int)reference.KbdLastHit, (int)candidate.KbdLastHit);
    }

    if ( reference.HotKeyID != candidate.HotKeyID )
    {
        differences++;
        Report(report, "HotKeyID: reference %d, candidate %d",
               (int)reference.HotKeyID, (int)candidate.HotKeyID);
    }

    if ( reference.chr != candidate.chr )
    {
        differences++;
        Report(report, "chr: reference %u, candidate %u",
               (unsigned)reference.chr, (unsigned)candidate.chr);
    }

    if ( reference.HandBrakePressed != candidate.HandBrakePressed )
    {
        differences++;
        Report(report, "HandBrakePressed: reference %d, candidate %d",
               (int)reference.HandBrakePressed, (int)candidate.HandBrakePressed);
    }

    for ( std::size_t i = 0; i < reference.Sliders.size(); i++ )
    {
        if ( reference.Sliders[i] != candidate.Sliders[i] )
        {
            differences++;
            Report(report, "Sliders[%u]: reference %.9g, candidate %.9g",
                   (unsigned)i, (double)reference.Sliders[i], (double)candidate.Sliders[i]);
        }
    }

    for ( uint32_t bit = 0; bit < reference.Buttons.GetSize(); bit++ )
    {
        if ( reference.Buttons.Is(bit) != candidate.Buttons.Is(bit) )
        {
            differences++;
            Report(report, "Buttons[%u]: reference %d, candidate %d",
                   (unsigned)bit, (int)reference.Buttons.Is(bit),
                   (int)candidate.Buttons.Is(bit));
        }
    }

    const TClickBoxInf &a = reference.ClickInf;
    const TClickBoxInf &b = candidate.ClickInf;

    if ( a.flag != b.flag )
    {
        differences++;
        Report(report, "ClickInf.flag: reference 0x%x, candidate 0x%x", a.flag, b.flag);
    }

    if ( a.selected_btn != b.selected_btn )
    {
        differences++;
        Report(report, "ClickInf.selected_btn differs");
    }

    if ( a.selected_btnID != b.selected_btnID )
    {
        differences++;
        Report(report, "ClickInf.selected_btnID: reference %d, candidate %d",
               a.selected_btnID, b.selected_btnID);
    }

    if ( a.wheel != b.wheel )
    {
        differences++;
        Report(report, "ClickInf.wheel: reference %d, candidate %d", a.wheel, b.wheel);
    }

    if ( !SameMouse(a.move, b.move) )
    {
        differences++;
        Report(report, "ClickInf.move differs");
    }

    if ( !SameMouse(a.ldw_pos, b.ldw_pos) )
    {
        differences++;
        Report(report, "ClickInf.ldw_pos differs");
    }

    if ( !SameMouse(a.lup_pos, b.lup_pos) )
    {
        differences++;
        Report(report, "ClickInf.lup_pos differs");
    }

    return differences;
}

}
