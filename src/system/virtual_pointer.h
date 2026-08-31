#ifndef SYSTEM_VIRTUAL_POINTER_H_INCLUDED
#define SYSTEM_VIRTUAL_POINTER_H_INCLUDED

class NC_STACK_bitmap;
class NC_STACK_button;
class NC_STACK_ypaworld;
struct TInputState;

// OpenNeoUA: Steam Deck virtual mouse cursor shared by menus and command mode.
//
// MenuCursor / Aim deltas move a logical pointer, re-hit-test click boxes, and
// synthesize LMB transitions (including double-click) without warping SDL mouse.

namespace Input
{

enum VIRTUAL_POINTER_CURSOR_SOURCE
{
    VIRTUAL_POINTER_CURSOR_MENU = 0,
    VIRTUAL_POINTER_CURSOR_AIM
};

void ResetVirtualPointer();
void SeedVirtualPointerCenter();
void WarpVirtualPointer(int x, int y);
bool VirtualPointerActive();
bool VirtualPointerVisible();

void ApplyVirtualPointer(
    TInputState *state,
    VIRTUAL_POINTER_CURSOR_SOURCE cursorSource,
    bool allowClickAtCursor);

// Gameplay command mode: Aim moves cursor; RT and trackpad click both LMB.
void ApplyCommandModePointer(TInputState *state);

void DrawVirtualPointer(NC_STACK_ypaworld *yw, int pointerIndex = 0);

}

#endif // SYSTEM_VIRTUAL_POINTER_H_INCLUDED
