#ifndef SYSTEM_ACTION_TABLE_H_INCLUDED
#define SYSTEM_ACTION_TABLE_H_INCLUDED

#include <cstddef>

#include "../yw.h"

// OpenNeoUA: the single source of truth linking a remappable action
// (World::INPUT_BIND_*) to the engine channel and slot that carries it, and to
// the Steam Input action name a later phase will publish in the IGA file.
//
// Before this table the mapping existed twice: forwards in
// NC_STACK_ypaworld::sub_46B3B0's default assignments (src/yw.cpp) and
// backwards in UserData::InputIndexFromConfig (src/yw_func2.cpp).  Both are now
// derived from here, so they cannot drift apart.
//
// The mapping is total and injective over the live bindings, but deliberately
// NOT surjective onto the engine slots: the hotkey channel has 53 slots and
// only 38 carry an action.  The unclaimed slots are listed explicitly in
// HOTKEY_HOLES so a hole can never appear by accident.

namespace World
{
namespace ActionTable
{

enum ACTION_KIND
{
    ACTION_KIND_DIGITAL = 0,
    ACTION_KIND_ANALOG  = 1
};

struct Entry
{
    // World::INPUT_BIND_*
    int Binding;
    ACTION_KIND Kind;
    // World::INPUT_BIND_TYPE_BUTTON / _SLIDER / _HOTKEY
    int Channel;
    // Index within that channel.
    int Slot;
    // Steam Input action name, authored into the IGA file in a later phase.
    const char *IgaName;
    // Kept for user.txt compatibility but no longer bindable or processed;
    // mirrors UserData::IsInputBindingRetired.
    bool Retired;
};

constexpr int BUTTON_SLOTS = 8;
constexpr int SLIDER_SLOTS = 6;
constexpr int HOTKEY_SLOTS = 53;

// Hotkey slots with no OpenNeoUA action.  Slots 5, 6, 13, 15, 19, 26, 28, 29
// and 30 are original-engine controls that were never reimplemented (build
// mode, the map lock/maximize variants, window cycling, the submenu item
// stepper and the energy window).  Slot 33 carries CommandMode; 34-36 remain holes.
// Slots 50 and 51 held the short-lived split Camera Zoom bindings.
constexpr int HOTKEY_HOLES[] = {
    5, 6, 13, 15, 19, 26, 28, 29, 30, 34, 35, 36, 50, 51
};

constexpr Entry Entries[] = {
    // Buttons: digital gameplay actions, engine slots 0-7.
    { INPUT_BIND_FIRE,             ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 0,  "Fire",            false },
    { INPUT_BIND_SWITCH_WEAPON,    ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 1,  "SwitchWeapon",    false },
    { INPUT_BIND_GUN,              ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 2,  "Gun",             false },
    { INPUT_BIND_BRAKE,            ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 3,  "Brake",           false },
    { INPUT_BIND_WAPOINT,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 4,  "Waypoint",        true  },
    { INPUT_BIND_CAMFIRE,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 5,  "CamFire",         false },
    { INPUT_BIND_CYCLE_TARGET,     ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 6,  "CycleTarget",     false },
    { INPUT_BIND_ALTERNATIVE_VIEW, ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_BUTTON, 7,  "AlternativeView", false },

    // Sliders: analog axes, engine slots 0-5.
    { INPUT_BIND_FLY_DIR,          ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 0,  "FlyDir",          false },
    { INPUT_BIND_FLY_HEIGHT,       ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 1,  "FlyHeight",       false },
    { INPUT_BIND_FLY_SPEED,        ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 2,  "FlySpeed",        false },
    { INPUT_BIND_DRIVE_DIR,        ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 3,  "DriveDir",        false },
    { INPUT_BIND_DRIVE_SPEED,      ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 4,  "DriveSpeed",      false },
    { INPUT_BIND_GUN_HEIGHT,       ACTION_KIND_ANALOG,  INPUT_BIND_TYPE_SLIDER, 5,  "GunHeight",       true  },

    // Hotkeys: digital one-shot actions, engine slots 0-52 with holes.
    { INPUT_BIND_ORDER,            ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 0,  "Order",           false },
    { INPUT_BIND_ATTACK,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 1,  "Attack",          false },
    { INPUT_BIND_NEW,              ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 2,  "SquadNew",        false },
    { INPUT_BIND_ADD,              ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 3,  "SquadAdd",        false },
    { INPUT_BIND_CONTROL,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 4,  "ControlUnit",     false },
    { INPUT_BIND_AUTOPILOT,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 7,  "Autopilot",       false },
    { INPUT_BIND_MAP,             ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 8,  "Map",             false },
    { INPUT_BIND_SQ_MANAGE,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 9,  "SquadManager",    false },
    { INPUT_BIND_LANDLAYER,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 10, "MapLandLayer",    true  },
    { INPUT_BIND_OWNER,            ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 11, "MapOwnerLayer",   true  },
    { INPUT_BIND_HEIGHT,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 12, "MapHeightLayer",  true  },
    { INPUT_BIND_LOCKVIEW,         ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 14, "MapLockView",     true  },
    { INPUT_BIND_ZOOMIN,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 16, "ZoomIn",          false },
    { INPUT_BIND_ZOOMOUT,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 17, "ZoomOut",         false },
    { INPUT_BIND_MINIMAP,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 18, "MapMinimize",     true  },
    { INPUT_BIND_NEXT_COMM,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 20, "NextCommander",   false },
    { INPUT_BIND_TO_HOST,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 21, "ControlToHost",   false },
    { INPUT_BIND_NEXT_UNIT,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 22, "NextUnit",        false },
    { INPUT_BIND_TO_COMM,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 23, "ControlToComm",   false },
    { INPUT_BIND_QUIT,             ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 24, "Quit",            false },
    { INPUT_BIND_HUD,              ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 25, "Hud",             false },
    { INPUT_BIND_LOG_WND,          ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 27, "LogWindow",       false },
    { INPUT_BIND_LAST_MSG,         ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 31, "LastMessage",     false },
    { INPUT_BIND_PAUSE,            ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 32, "Pause",           false },
    { INPUT_BIND_TO_ALL,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 37, "OrderToAll",      false },
    { INPUT_BIND_AGGR_1,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 38, "Aggressiveness1", false },
    { INPUT_BIND_AGGR_2,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 39, "Aggressiveness2", false },
    { INPUT_BIND_AGGR_3,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 40, "Aggressiveness3", false },
    { INPUT_BIND_AGGR_4,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 41, "Aggressiveness4", false },
    { INPUT_BIND_AGGR_5,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 42, "Aggressiveness5", false },
    { INPUT_BIND_HELP,             ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 43, "Help",            true  },
    { INPUT_BIND_LAST_SEAT,        ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 44, "LastSeat",        false },
    { INPUT_BIND_SET_COMM,         ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 45, "SetCommander",    false },
    { INPUT_BIND_ANALYZER,         ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 46, "Analyzer",        false },
    { INPUT_BIND_COCKPIT_CAMERA,   ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 47, "CockpitCamera",   true  },
    { INPUT_BIND_SPRINT,           ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 48, "Sprint",          false },
    { INPUT_BIND_PLACE_MAP_MARKER, ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 49, "PlaceMapMarker",  false },
    { INPUT_BIND_TOGGLE_UFO_SPY_UI,ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 52, "ToggleUfoSpyUi",  false },
    { INPUT_BIND_COMMAND_MODE,     ACTION_KIND_DIGITAL, INPUT_BIND_TYPE_HOTKEY, 33, "CommandMode",     false },
};

constexpr std::size_t ENTRY_COUNT = sizeof(Entries) / sizeof(Entries[0]);
constexpr std::size_t HOLE_COUNT = sizeof(HOTKEY_HOLES) / sizeof(HOTKEY_HOLES[0]);

constexpr int SlotsForChannel(int channel)
{
    return channel == INPUT_BIND_TYPE_BUTTON ? BUTTON_SLOTS
         : channel == INPUT_BIND_TYPE_SLIDER ? SLIDER_SLOTS
         : channel == INPUT_BIND_TYPE_HOTKEY ? HOTKEY_SLOTS
         : 0;
}

// Reverse lookup: engine channel and slot to binding, -1 when the slot carries
// no action.  This is what UserData::InputIndexFromConfig now returns.
constexpr int BindingForSlot(int channel, int slot)
{
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].Channel == channel && Entries[i].Slot == slot )
            return Entries[i].Binding;
    }
    return -1;
}

// Forward lookup: binding to table index, -1 when the binding has no slot.
constexpr int IndexForBinding(int binding)
{
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].Binding == binding )
            return (int)i;
    }
    return -1;
}

constexpr int CountBinding(int binding)
{
    int count = 0;
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].Binding == binding )
            count++;
    }
    return count;
}

constexpr int CountSlot(int channel, int slot)
{
    int count = 0;
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].Channel == channel && Entries[i].Slot == slot )
            count++;
    }
    return count;
}

constexpr bool NamesEqual(const char *a, const char *b)
{
    return ( *a == *b ) && ( *a == '\0' || NamesEqual(a + 1, b + 1) );
}

constexpr int CountName(const char *name)
{
    int count = 0;
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( NamesEqual(Entries[i].IgaName, name) )
            count++;
    }
    return count;
}

constexpr bool IsHotKeyHole(int slot)
{
    for ( std::size_t i = 0; i < HOLE_COUNT; i++ )
    {
        if ( HOTKEY_HOLES[i] == slot )
            return true;
    }
    return false;
}

// Every binding in 1..INPUT_BIND_MAX-1 is claimed exactly once.
constexpr bool BindingsAreTotalAndInjective()
{
    for ( int binding = 1; binding < INPUT_BIND_MAX; binding++ )
    {
        if ( CountBinding(binding) != 1 )
            return false;
    }
    return true;
}

// No engine slot is claimed twice, and no slot outside a channel's range is
// claimed at all.
constexpr bool SlotsAreInjective()
{
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].Slot < 0 || Entries[i].Slot >= SlotsForChannel(Entries[i].Channel) )
            return false;
        if ( CountSlot(Entries[i].Channel, Entries[i].Slot) != 1 )
            return false;
    }
    return true;
}

constexpr bool NamesAreUnique()
{
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        if ( Entries[i].IgaName[0] == '\0' || CountName(Entries[i].IgaName) != 1 )
            return false;
    }
    return true;
}

// Sliders are the analog channel; buttons and hotkeys are digital.
constexpr bool KindsMatchChannels()
{
    for ( std::size_t i = 0; i < ENTRY_COUNT; i++ )
    {
        const ACTION_KIND expected = Entries[i].Channel == INPUT_BIND_TYPE_SLIDER
                                   ? ACTION_KIND_ANALOG
                                   : ACTION_KIND_DIGITAL;
        if ( Entries[i].Kind != expected )
            return false;
    }
    return true;
}

// The button and slider channels are fully claimed; the hotkey channel is not,
// and its unclaimed slots must be exactly HOTKEY_HOLES.
constexpr bool HolesAreExplicit()
{
    for ( int slot = 0; slot < BUTTON_SLOTS; slot++ )
    {
        if ( BindingForSlot(INPUT_BIND_TYPE_BUTTON, slot) < 0 )
            return false;
    }
    for ( int slot = 0; slot < SLIDER_SLOTS; slot++ )
    {
        if ( BindingForSlot(INPUT_BIND_TYPE_SLIDER, slot) < 0 )
            return false;
    }
    for ( int slot = 0; slot < HOTKEY_SLOTS; slot++ )
    {
        const bool claimed = BindingForSlot(INPUT_BIND_TYPE_HOTKEY, slot) >= 0;
        if ( claimed == IsHotKeyHole(slot) )
            return false;
    }
    return true;
}

static_assert(ENTRY_COUNT == (std::size_t)(INPUT_BIND_MAX - 1),
              "action table must carry every INPUT_BIND exactly once");
static_assert(ENTRY_COUNT == BUTTON_SLOTS + SLIDER_SLOTS + HOTKEY_SLOTS - HOLE_COUNT,
              "action table size must equal the claimed engine slot count");
static_assert(BindingsAreTotalAndInjective(),
              "every live INPUT_BIND must map to exactly one engine slot");
static_assert(SlotsAreInjective(),
              "no engine slot may be claimed by two actions");
static_assert(NamesAreUnique(),
              "IGA action names must be non-empty and unique");
static_assert(KindsMatchChannels(),
              "sliders must be analog and buttons/hotkeys digital");
static_assert(HolesAreExplicit(),
              "unclaimed hotkey slots must be listed in HOTKEY_HOLES");

}
}

#endif // SYSTEM_ACTION_TABLE_H_INCLUDED
