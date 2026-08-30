// OpenNeoUA: parity harness for the Steam Input action facade.
//
// Phase 3 lets ActionInput populate TInputState instead of the legacy
// assembly in INPEngine::QueryInput.  That is only safe if the facade
// reproduces the legacy result exactly, so this harness drives synthetic and
// pseudo-random input sequences through both paths and requires a
// field-by-field match on every frame.
//
// It also pins the action table against the literal channel/slot tables that
// UserData::InputIndexFromConfig used to hold, so lifting them out cannot have
// changed the mapping.

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>

#include "system/action_input.h"
#include "system/action_table.h"

// The facade logs through ypa_log_out, which lives in log.cpp and drags in the
// filesystem manager.  A stub keeps this test standalone.
void ypa_log_out(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    std::vfprintf(stderr, format, arguments);
    va_end(arguments);
}

namespace
{

int Failures = 0;

int Fail(const char *message)
{
    std::fprintf(stderr, "test_action_parity: %s\n", message);
    Failures++;
    return 1;
}

void Check(bool condition, const char *message)
{
    if ( !condition )
        Fail(message);
}

// ---------------------------------------------------------------------------
// The pre-refactor mapping, copied verbatim from UserData::InputIndexFromConfig
// as it stood before World::ActionTable existed.
// ---------------------------------------------------------------------------

const int LEGACY_BUTTON[8] = {
    World::INPUT_BIND_FIRE,       World::INPUT_BIND_SWITCH_WEAPON,
    World::INPUT_BIND_GUN,        World::INPUT_BIND_BRAKE,
    World::INPUT_BIND_WAPOINT,    World::INPUT_BIND_CAMFIRE,
    World::INPUT_BIND_CYCLE_TARGET, World::INPUT_BIND_ALTERNATIVE_VIEW
};

const int LEGACY_SLIDER[6] = {
    World::INPUT_BIND_FLY_DIR,    World::INPUT_BIND_FLY_HEIGHT,
    World::INPUT_BIND_FLY_SPEED,  World::INPUT_BIND_DRIVE_DIR,
    World::INPUT_BIND_DRIVE_SPEED,World::INPUT_BIND_GUN_HEIGHT,
};

const int LEGACY_HOTKEY[53] = {
    World::INPUT_BIND_ORDER,      World::INPUT_BIND_ATTACK,
    World::INPUT_BIND_NEW,        World::INPUT_BIND_ADD,
    World::INPUT_BIND_CONTROL,    -1,
    -1,                           World::INPUT_BIND_AUTOPILOT,
    World::INPUT_BIND_MAP,        World::INPUT_BIND_SQ_MANAGE,

    World::INPUT_BIND_LANDLAYER,  World::INPUT_BIND_OWNER,
    World::INPUT_BIND_HEIGHT,     -1,
    World::INPUT_BIND_LOCKVIEW,   -1,
    World::INPUT_BIND_ZOOMIN,     World::INPUT_BIND_ZOOMOUT,
    World::INPUT_BIND_MINIMAP,    -1,

    World::INPUT_BIND_NEXT_COMM,  World::INPUT_BIND_TO_HOST,
    World::INPUT_BIND_NEXT_UNIT,  World::INPUT_BIND_TO_COMM,
    World::INPUT_BIND_QUIT,       World::INPUT_BIND_HUD,
    -1,                           World::INPUT_BIND_LOG_WND,
    -1,                           -1,

    -1,                           World::INPUT_BIND_LAST_MSG,
    World::INPUT_BIND_PAUSE,      -1,
    -1,                           -1,
    -1,                           World::INPUT_BIND_TO_ALL,
    World::INPUT_BIND_AGGR_1,     World::INPUT_BIND_AGGR_2,

    World::INPUT_BIND_AGGR_3,     World::INPUT_BIND_AGGR_4,
    World::INPUT_BIND_AGGR_5,     World::INPUT_BIND_HELP,
    World::INPUT_BIND_LAST_SEAT,  World::INPUT_BIND_SET_COMM,
    World::INPUT_BIND_ANALYZER,   World::INPUT_BIND_COCKPIT_CAMERA,
    World::INPUT_BIND_SPRINT,     World::INPUT_BIND_PLACE_MAP_MARKER,

    -1,                           -1,
    World::INPUT_BIND_TOGGLE_UFO_SPY_UI
};

// Mirrors UserData::IsInputBindingRetired.
const int LEGACY_RETIRED[9] = {
    World::INPUT_BIND_GUN_HEIGHT, World::INPUT_BIND_WAPOINT,
    World::INPUT_BIND_LANDLAYER,  World::INPUT_BIND_OWNER,
    World::INPUT_BIND_HEIGHT,     World::INPUT_BIND_MINIMAP,
    World::INPUT_BIND_LOCKVIEW,   World::INPUT_BIND_HELP,
    World::INPUT_BIND_COCKPIT_CAMERA
};

int TestActionTable()
{
    using namespace World::ActionTable;

    Check(ENTRY_COUNT == (std::size_t)(World::INPUT_BIND_MAX - 1),
          "action table must carry 52 live bindings");
    Check(HOLE_COUNT == 15, "hotkey channel must have 15 explicit holes");

    // Every live binding appears exactly once.
    for ( int binding = 1; binding < World::INPUT_BIND_MAX; binding++ )
    {
        if ( CountBinding(binding) != 1 )
        {
            char message[128];
            std::snprintf(message, sizeof(message),
                          "binding %d is claimed %d times", binding, CountBinding(binding));
            Fail(message);
        }
    }

    // No engine slot is claimed twice, and no IGA name repeats.
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        const Entry &entry = Entries[i];

        if ( CountSlot(entry.Channel, entry.Slot) != 1 )
            Fail("an engine slot is claimed by more than one action");

        if ( CountName(entry.IgaName) != 1 )
            Fail("an IGA action name is duplicated");

        const ACTION_KIND expected = entry.Channel == World::INPUT_BIND_TYPE_SLIDER
                                   ? ACTION_KIND_ANALOG : ACTION_KIND_DIGITAL;
        if ( entry.Kind != expected )
            Fail("action kind does not match its engine channel");

        if ( IndexForBinding(entry.Binding) != (int)i )
            Fail("IndexForBinding disagrees with the table order");
    }

    // The reverse mapping must reproduce the pre-refactor tables exactly,
    // including out-of-range indices, which used to return -1.
    for ( int slot = 0; slot < 8; slot++ )
        Check(BindingForSlot(World::INPUT_BIND_TYPE_BUTTON, slot) == LEGACY_BUTTON[slot],
              "button slot mapping changed");
    for ( int slot = 8; slot < 64; slot++ )
        Check(BindingForSlot(World::INPUT_BIND_TYPE_BUTTON, slot) == -1,
              "out-of-range button slot must be unmapped");

    for ( int slot = 0; slot < 6; slot++ )
        Check(BindingForSlot(World::INPUT_BIND_TYPE_SLIDER, slot) == LEGACY_SLIDER[slot],
              "slider slot mapping changed");
    for ( int slot = 6; slot < 64; slot++ )
        Check(BindingForSlot(World::INPUT_BIND_TYPE_SLIDER, slot) == -1,
              "out-of-range slider slot must be unmapped");

    for ( int slot = 0; slot < 53; slot++ )
    {
        if ( BindingForSlot(World::INPUT_BIND_TYPE_HOTKEY, slot) != LEGACY_HOTKEY[slot] )
        {
            char message[128];
            std::snprintf(message, sizeof(message),
                          "hotkey slot %d maps to %d, expected %d", slot,
                          BindingForSlot(World::INPUT_BIND_TYPE_HOTKEY, slot),
                          LEGACY_HOTKEY[slot]);
            Fail(message);
        }

        // A hole in the legacy table must be a declared hole here.
        Check((LEGACY_HOTKEY[slot] < 0) == IsHotKeyHole(slot),
              "hotkey holes must match the legacy table");
    }
    for ( int slot = 53; slot < 96; slot++ )
        Check(BindingForSlot(World::INPUT_BIND_TYPE_HOTKEY, slot) == -1,
              "out-of-range hotkey slot must be unmapped");

    // Unknown channels were unmapped before and must stay unmapped.
    for ( int slot = 0; slot < 8; slot++ )
    {
        Check(BindingForSlot(0, slot) == -1, "channel 0 must be unmapped");
        Check(BindingForSlot(4, slot) == -1, "channel 4 must be unmapped");
    }

    // Retired flags must agree with the engine's retirement list.
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        bool expected = false;
        for ( int retired : LEGACY_RETIRED )
        {
            if ( Entries[i].Binding == retired )
                expected = true;
        }

        if ( Entries[i].Retired != expected )
            Fail("Retired flag disagrees with UserData::IsInputBindingRetired");
    }

    return Failures;
}

// ---------------------------------------------------------------------------
// Parity
// ---------------------------------------------------------------------------

// Drives one frame through the facade and diffs it against the legacy
// reference built from the same primitives.
bool ParityFrame(const Input::LegacyInputPrimitives &primitives, const char *label)
{
    Input::Actions.Update(primitives);

    TInputState candidate;
    Input::Actions.PopulateLegacyState(&candidate);

    TInputState reference;
    Input::BuildLegacyInputState(primitives, &reference);

    std::string report;
    const int differences = Input::DiffLegacyInputState(reference, candidate, &report);

    if ( differences != 0 )
    {
        std::fprintf(stderr,
                     "test_action_parity: %s diverged in %d field(s):\n%s",
                     label, differences, report.c_str());
        Failures++;
        return false;
    }

    return true;
}

// xorshift so the sequence is identical on every platform and every run.
uint32_t Random(uint32_t *state)
{
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

Input::LegacyInputPrimitives Quiet()
{
    Input::LegacyInputPrimitives primitives;
    primitives.Period = 20;
    primitives.HasFocus = true;
    primitives.HotKeyID = -1;
    return primitives;
}

int TestParityDeterministicCases()
{
    // A quiet frame. Note that unconfigured button slots evaluate true in the
    // engine, so this is not the same as "no buttons pressed"; the facade has
    // to reproduce that too.
    ParityFrame(Quiet(), "quiet frame");

    // Focus lost: the engine reports nothing but still advances ramps.
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.HasFocus = false;
        primitives.KbdLastHit = Input::KC_A;
        primitives.HotKeyID = 3;
        primitives.ButtonState[0] = true;
        primitives.SliderValid[0] = true;
        primitives.SliderPos[0] = 1.0f;
        ParityFrame(primitives, "focus lost");
    }

    // Every button slot on its own, including the raw joystick range 16-23 and
    // the unconfigured slots.
    for ( std::size_t slot = 0; slot < Input::LEGACY_BUTTON_SLOTS; slot++ )
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.ButtonState.fill(false);
        primitives.ButtonState[slot] = true;
        ParityFrame(primitives, "single button slot");
    }

    // All buttons high, then all low.
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.ButtonState.fill(true);
        ParityFrame(primitives, "all buttons high");

        primitives.ButtonState.fill(false);
        ParityFrame(primitives, "all buttons low");
    }

    // Slider extremes, negatives, and the valid/invalid distinction. An
    // invalid slot must read zero even when its position is non-zero.
    const float values[] = { 0.0f, 1.0f, -1.0f, 0.5f, -0.5f, 0.003921569f, 2.0f, -2.0f };
    for ( float value : values )
    {
        for ( int valid = 0; valid < 2; valid++ )
        {
            Input::LegacyInputPrimitives primitives = Quiet();
            for ( std::size_t slot = 0; slot < Input::LEGACY_SLIDER_SLOTS; slot++ )
            {
                primitives.SliderValid[slot] = valid != 0;
                primitives.SliderPos[slot] = value;
            }
            ParityFrame(primitives, "slider sweep");
        }
    }

    // Each slider slot alone, so a mapped slot cannot borrow a neighbour.
    for ( std::size_t slot = 0; slot < Input::LEGACY_SLIDER_SLOTS; slot++ )
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.SliderValid[slot] = true;
        primitives.SliderPos[slot] = -0.75f;
        ParityFrame(primitives, "single slider slot");
    }

    // Every hotkey slot, including the 15 holes, which have no INPUT_BIND but
    // which the engine can still report because ReloadInput never clears them.
    for ( int slot = -1; slot < 53; slot++ )
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.HotKeyID = (int16_t)slot;
        primitives.KbdLastHit = Input::KC_B;
        ParityFrame(primitives, "hotkey slot");
    }

    // Keyboard, character and pointer fields.
    {
        Input::LegacyInputPrimitives primitives = Quiet();
        primitives.Period = 12345;
        primitives.KbdLastDown = Input::KC_LSHIFT;
        primitives.KbdLastHit = Input::KC_RETURN;
        primitives.Chr = 'x';
        primitives.ClickInf.flag = TClickBoxInf::FLAG_OK | TClickBoxInf::FLAG_LM_DOWN;
        primitives.ClickInf.selected_btnID = 7;
        primitives.ClickInf.wheel = -3;
        primitives.ClickInf.move.ScreenPos = Common::Point(101, 202);
        primitives.ClickInf.ldw_pos.BoxPos = Common::Point(3, 4);
        primitives.ClickInf.lup_pos.BtnPos = Common::Point(5, 6);
        ParityFrame(primitives, "keyboard and pointer fields");
    }

    return Failures;
}

int TestParityFuzz()
{
    uint32_t seed = 0x5eed1234u;

    for ( int frame = 0; frame < 20000; frame++ )
    {
        Input::LegacyInputPrimitives primitives;

        primitives.Period = Random(&seed) % 64;
        primitives.HasFocus = (Random(&seed) & 15) != 0;
        primitives.KbdLastDown = (int16_t)(Random(&seed) % Input::KC_MAX);
        primitives.KbdLastHit = (int16_t)(Random(&seed) % Input::KC_MAX);
        primitives.Chr = (uint8_t)(Random(&seed) & 0xFF);

        // INPEngine::CheckHotKey() returns either -1 or an index into the
        // 53-entry _hotKeys array, so that is the whole reachable domain.
        // TestOutOfDomainHotKey() covers what the facade does outside it.
        primitives.HotKeyID =
            (int16_t)((int)(Random(&seed) % (World::ActionTable::HOTKEY_SLOTS + 1)) - 1);

        for ( std::size_t slot = 0; slot < Input::LEGACY_BUTTON_SLOTS; slot++ )
            primitives.ButtonState[slot] = (Random(&seed) & 1) != 0;

        for ( std::size_t slot = 0; slot < Input::LEGACY_SLIDER_SLOTS; slot++ )
        {
            primitives.SliderValid[slot] = (Random(&seed) & 3) != 0;
            primitives.SliderPos[slot] =
                (float)((int)(Random(&seed) % 601) - 300) / 300.0f;
        }

        primitives.ClickInf.flag = (int)(Random(&seed) & 0x3FFF);
        primitives.ClickInf.selected_btnID = (int32_t)(Random(&seed) % 17) - 1;
        primitives.ClickInf.wheel = (int32_t)(Random(&seed) % 11) - 5;
        primitives.ClickInf.move.ScreenPos =
            Common::Point((int)(Random(&seed) % 1280), (int)(Random(&seed) % 720));

        if ( !ParityFrame(primitives, "fuzz frame") )
            return Failures;
    }

    return Failures;
}

// The facade must expose edges the legacy path never had, without disturbing
// the legacy fields.
int TestEdgesAndHotKeyQueue()
{
    Input::Actions.Reset();

    Input::LegacyInputPrimitives primitives = Quiet();
    primitives.ButtonState.fill(false);

    // Rising edge on the Fire button slot.
    primitives.ButtonState[0] = true;
    Input::Actions.Update(primitives);
    Check(Input::Actions.Active(World::INPUT_BIND_FIRE), "Fire must be active");
    Check(Input::Actions.Pressed(World::INPUT_BIND_FIRE), "Fire must report a rising edge");
    Check(!Input::Actions.Released(World::INPUT_BIND_FIRE), "Fire must not report a release");

    // Held: no new edge.
    Input::Actions.Update(primitives);
    Check(Input::Actions.Active(World::INPUT_BIND_FIRE), "held Fire must stay active");
    Check(!Input::Actions.Pressed(World::INPUT_BIND_FIRE), "held Fire must not re-fire");

    // Falling edge.
    primitives.ButtonState[0] = false;
    Input::Actions.Update(primitives);
    Check(!Input::Actions.Active(World::INPUT_BIND_FIRE), "released Fire must be inactive");
    Check(Input::Actions.Released(World::INPUT_BIND_FIRE), "Fire must report a falling edge");

    // A hotkey activation reaches both the sample and the FIFO.
    primitives.HotKeyID = 32; // Pause
    Input::Actions.Update(primitives);
    Check(Input::Actions.Pressed(World::INPUT_BIND_PAUSE), "Pause must report a rising edge");
    Check(Input::Actions.PendingHotKeyCount() == 1, "one pending hotkey expected");

    Input::HotKeyActivation activation;
    Check(Input::Actions.PopPendingHotKey(&activation), "FIFO must yield the activation");
    Check(activation.Slot == 32, "activation slot must be preserved");
    Check(activation.Binding == World::INPUT_BIND_PAUSE, "activation binding must resolve");
    Check(Input::Actions.PendingHotKeyCount() == 0, "FIFO must drain");

    // A hole slot has no binding but must still be carried, so TInputState
    // stays bit-identical.
    primitives.HotKeyID = 5;
    Input::Actions.Update(primitives);
    Check(Input::Actions.PeekPendingHotKey(&activation), "hole activation must be queued");
    Check(activation.Slot == 5, "hole slot must be preserved");
    Check(activation.Binding == -1, "hole slot must have no binding");

    // Analog channels are distinct: a slider drives posX and leaves the
    // absolute_mouse delta channel untouched.
    primitives.HotKeyID = -1;
    primitives.SliderValid[2] = true;
    primitives.SliderPos[2] = -0.5f;
    Input::Actions.Update(primitives);
    const Input::ActionSample &flySpeed = Input::Actions.Sample(World::INPUT_BIND_FLY_SPEED);
    Check(flySpeed.posX == -0.5f, "FlySpeed must land on the position channel");
    Check(flySpeed.delX == 0.0f && flySpeed.delY == 0.0f,
          "FlySpeed must not touch the delta channel");

    // Action-set stack.
    Check(Input::Actions.CurrentActionSet() == Input::ACTION_SET_MENU,
          "an empty stack must report the menu set");
    Input::Actions.PushActionSet(Input::ACTION_SET_GROUND);
    Input::Actions.PushActionSet(Input::ACTION_SET_MAP);
    Check(Input::Actions.CurrentActionSet() == Input::ACTION_SET_MAP, "map set expected");
    Check(Input::Actions.ActionSetDepth() == 2, "stack depth must be 2");
    Input::Actions.PopActionSet();
    Check(Input::Actions.CurrentActionSet() == Input::ACTION_SET_GROUND, "ground set expected");
    Input::Actions.PopActionSet();
    Check(Input::Actions.CurrentActionSet() == Input::ACTION_SET_MENU, "menu set expected");

    Input::Actions.Reset();
    return Failures;
}

// A negative HotKeyID other than -1 is unreachable through CheckHotKey(), so
// the facade is free to fold it into "no hotkey". Pin that down, because it is
// the one place the facade is deliberately not a bit-identical pass-through and
// the fuzz domain above depends on it.
int TestOutOfDomainHotKey()
{
    Input::LegacyInputPrimitives primitives;
    primitives.HotKeyID = -2;

    Input::Actions.Reset();
    Input::Actions.Update(primitives);

    TInputState fromFacade;
    Input::Actions.PopulateLegacyState(&fromFacade);
    Check(fromFacade.HotKeyID == -1, "an out-of-domain hotkey must normalise to -1");

    Input::Actions.Reset();
    return Failures;
}

// The harness must actually detect a divergence; a parity test that cannot
// fail is worthless.
int TestHarnessDetectsDivergence()
{
    TInputState a;
    TInputState b;

    Check(Input::DiffLegacyInputState(a, b, NULL) == 0,
          "identical states must compare equal");

    b.Buttons.Set(19);
    Check(Input::DiffLegacyInputState(a, b, NULL) == 1, "a button difference must be seen");

    b = a;
    b.Sliders[11] = 0.25f;
    Check(Input::DiffLegacyInputState(a, b, NULL) == 1, "a slider difference must be seen");

    b = a;
    b.HotKeyID = 7;
    Check(Input::DiffLegacyInputState(a, b, NULL) == 1, "a hotkey difference must be seen");

    b = a;
    b.ClickInf.wheel = 1;
    b.ClickInf.move.ScreenPos = Common::Point(1, 1);
    Check(Input::DiffLegacyInputState(a, b, NULL) == 2, "pointer differences must be seen");

    b = a;
    b.chr = 'q';
    b.KbdLastHit = 3;
    b.Period = 9;
    b.HandBrakePressed = true;
    Check(Input::DiffLegacyInputState(a, b, NULL) == 4, "scalar differences must be seen");

    return Failures;
}

}

int main()
{
    Input::ActionParity::SetEnabled(false);

    TestActionTable();
    TestHarnessDetectsDivergence();
    TestParityDeterministicCases();
    TestEdgesAndHotKeyQueue();
    TestOutOfDomainHotKey();
    TestParityFuzz();

    if ( Failures != 0 )
    {
        std::fprintf(stderr, "test_action_parity: %d failure(s)\n", Failures);
        return 1;
    }

    std::printf("test_action_parity: ok (%d parity frames)\n", 20000);
    return 0;
}
