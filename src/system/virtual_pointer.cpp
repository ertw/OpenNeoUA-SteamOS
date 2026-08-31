#include "virtual_pointer.h"

#include "action_backend.h"
#include "action_input.h"
#include "action_set_sync.h"
#include "inpt.h"
#include "../bitmap.h"
#include "../global.h"
#include "../yw.h"
#include "gfx.h"

#include <SDL2/SDL.h>

namespace Input
{

namespace
{

constexpr float kCursorScale = 12.0f;
constexpr int kDoubleClickMs = 500;
constexpr int kDoubleClickMaxMovePx = 4;

float _cursorX = 0.0f;
float _cursorY = 0.0f;
bool _cursorInitialized = false;
bool _confirmHeld = false;
bool _altClickHeld = false;
bool _visible = false;
Uint32 _lastClickMs = 0;
int _lastClickX = 0;
int _lastClickY = 0;
int _clickCount = 0;

void ClampCursorToScreen()
{
    if ( !ypaworld )
        return;

    _cursorX = std::max(0.0f, std::min(_cursorX, (float)ypaworld->_screenSize.x));
    _cursorY = std::max(0.0f, std::min(_cursorY, (float)ypaworld->_screenSize.y));
}

void ApplyCursorDelta(float deltaX, float deltaY)
{
    if ( deltaX == 0.0f && deltaY == 0.0f )
        return;

    _visible = true;
    if ( !_cursorInitialized )
    {
        if ( ypaworld )
        {
            _cursorX = (float)ypaworld->_screenSize.x * 0.5f;
            _cursorY = (float)ypaworld->_screenSize.y * 0.5f;
        }
        _cursorInitialized = true;
    }

    _cursorX += deltaX * kCursorScale;
    _cursorY += deltaY * kCursorScale;
    ClampCursorToScreen();
}

float CursorDeltaX(VIRTUAL_POINTER_CURSOR_SOURCE source)
{
    if ( source == VIRTUAL_POINTER_CURSOR_MENU )
        return SteamBackend().MenuCursorDeltaX();

    return SteamBackend().AimDeltaX();
}

float CursorDeltaY(VIRTUAL_POINTER_CURSOR_SOURCE source)
{
    if ( source == VIRTUAL_POINTER_CURSOR_MENU )
        return SteamBackend().MenuCursorDeltaY();

    return SteamBackend().AimDeltaY();
}

bool ConfirmHeld()
{
    if ( SteamBackend().Available() )
    {
        if ( SteamBackend().SmokeModeActive() )
            return SteamBackend().MenuNavActive(MENU_NAV_CONFIRM);

        if ( SteamBackend().MenuNavActive(MENU_NAV_CONFIRM) )
            return true;
    }

    return Actions.Active(World::INPUT_BIND_FIRE);
}

void ApplyPointerToState(TInputState *state)
{
    if ( !state )
        return;

    state->ClickInf.move.ScreenPos.x = (int)_cursorX;
    state->ClickInf.move.ScreenPos.y = (int)_cursorY;
    state->ClickInf.flag |= TClickBoxInf::FLAG_OK;
    Engine.ClickCheck.CheckClick(&state->ClickInf);
}

void SynthesizeClickAtCursor(TInputState *state, bool pressed, bool released)
{
    if ( !state )
        return;

    ApplyPointerToState(state);

    if ( pressed )
    {
        state->ClickInf.ldw_pos = state->ClickInf.move;
        state->ClickInf.flag |= TClickBoxInf::FLAG_LM_DOWN | TClickBoxInf::FLAG_BTN_DOWN;
    }

    if ( released )
    {
        state->ClickInf.lup_pos = state->ClickInf.move;
        state->ClickInf.flag |= TClickBoxInf::FLAG_LM_UP | TClickBoxInf::FLAG_BTN_UP;

        const Uint32 now = SDL_GetTicks();
        const int x = state->ClickInf.move.ScreenPos.x;
        const int y = state->ClickInf.move.ScreenPos.y;
        if ( _clickCount > 0 &&
             now - _lastClickMs <= (Uint32)kDoubleClickMs &&
             abs(x - _lastClickX) < kDoubleClickMaxMovePx &&
             abs(y - _lastClickY) < kDoubleClickMaxMovePx )
        {
            state->ClickInf.flag |= TClickBoxInf::FLAG_DBL_CLICK;
            _clickCount = 0;
        }
        else
        {
            _clickCount = 1;
            _lastClickMs = now;
            _lastClickX = x;
            _lastClickY = y;
        }
    }

    if ( pressed || released )
        ApplyPointerToState(state);
}

}

void ResetVirtualPointer()
{
    _cursorInitialized = false;
    _confirmHeld = false;
    _altClickHeld = false;
    _visible = false;
    _lastClickMs = 0;
    _lastClickX = 0;
    _lastClickY = 0;
    _clickCount = 0;
}

void SeedVirtualPointerCenter()
{
    if ( !ypaworld )
        return;

    _cursorX = (float)ypaworld->_screenSize.x * 0.5f;
    _cursorY = (float)ypaworld->_screenSize.y * 0.5f;
    _cursorInitialized = true;
    _visible = true;
}

void WarpVirtualPointer(int x, int y)
{
    _cursorX = (float)x;
    _cursorY = (float)y;
    _cursorInitialized = true;
    _visible = true;
    ClampCursorToScreen();
}

bool VirtualPointerActive()
{
    return SteamInputControlsJoystick() && _cursorInitialized;
}

bool VirtualPointerVisible()
{
    return _visible && _cursorInitialized;
}

void ApplyVirtualPointer(
    TInputState *state,
    VIRTUAL_POINTER_CURSOR_SOURCE cursorSource,
    bool allowClickAtCursor)
{
    if ( !state || !SteamInputControlsJoystick() )
        return;

    ApplyCursorDelta(CursorDeltaX(cursorSource), CursorDeltaY(cursorSource));

    if ( !_cursorInitialized )
        return;

    ApplyPointerToState(state);

    if ( !allowClickAtCursor )
        return;

    const bool confirmHeld = ConfirmHeld();
    if ( confirmHeld && !_confirmHeld )
        SynthesizeClickAtCursor(state, true, false);
    else if ( !confirmHeld && _confirmHeld )
        SynthesizeClickAtCursor(state, false, true);
    _confirmHeld = confirmHeld;

    if ( SteamBackend().SmokeModeActive() && SteamBackend().ConsumeMenuConfirmRelease() )
        SynthesizeClickAtCursor(state, false, true);
}

void ApplyCommandModePointer(TInputState *state)
{
    if ( !state || !SteamInputControlsJoystick() )
        return;

    ApplyCursorDelta(CursorDeltaX(VIRTUAL_POINTER_CURSOR_AIM),
                     CursorDeltaY(VIRTUAL_POINTER_CURSOR_AIM));

    if ( !_cursorInitialized )
        return;

    ApplyPointerToState(state);

    const bool confirmHeld = ConfirmHeld();
    if ( confirmHeld && !_confirmHeld )
        SynthesizeClickAtCursor(state, true, false);
    else if ( !confirmHeld && _confirmHeld )
        SynthesizeClickAtCursor(state, false, true);
    _confirmHeld = confirmHeld;

    const bool altHeld = Actions.Active(World::INPUT_BIND_CAMFIRE);
    if ( altHeld && !_altClickHeld )
        SynthesizeClickAtCursor(state, true, false);
    else if ( !altHeld && _altClickHeld )
        SynthesizeClickAtCursor(state, false, true);
    _altClickHeld = altHeld;
}

void DrawVirtualPointer(NC_STACK_ypaworld *yw, int pointerIndex)
{
    if ( !yw || !VirtualPointerVisible() )
        return;

    if ( pointerIndex < 0 || pointerIndex >= (int)yw->_mousePointers.size() )
        pointerIndex = 0;

    NC_STACK_bitmap *pointer = yw->_mousePointers[(std::size_t)pointerIndex];
    if ( !pointer )
        return;

    ResBitmap *bitmap = pointer->GetBitmap();
    if ( !bitmap || !bitmap->swTex )
        return;

    SDL_Surface *screen = GFX::Engine.Screen();
    if ( !screen )
        return;

    SDL_Rect dst;
    dst.x = (int)_cursorX;
    dst.y = (int)_cursorY;
    dst.w = bitmap->swTex->w;
    dst.h = bitmap->swTex->h;
    SDL_BlitSurface(bitmap->swTex, NULL, screen, &dst);

    GFX::Engine.SetCursor(0, 1);
}

}
