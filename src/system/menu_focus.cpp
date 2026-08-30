#include "menu_focus.h"

#include "action_backend.h"
#include "action_input.h"
#include "action_set_sync.h"
#include "../button.h"
#include "../global.h"

namespace Input
{

namespace
{

MenuFocusController &Controller()
{
    static MenuFocusController instance;
    return instance;
}

bool MenuNavPressed(MENU_NAV_ACTION action)
{
    if ( SteamBackend().Available() && SteamBackend().MenuNavActive(action) )
        return true;

    switch ( action )
    {
    case MENU_NAV_UP:      return Actions.Pressed(World::INPUT_BIND_ZOOMIN);
    case MENU_NAV_DOWN:    return Actions.Pressed(World::INPUT_BIND_ZOOMOUT);
    case MENU_NAV_LEFT:    return Actions.Pressed(World::INPUT_BIND_SQ_MANAGE);
    case MENU_NAV_RIGHT:   return Actions.Pressed(World::INPUT_BIND_ORDER);
    case MENU_NAV_CONFIRM: return Actions.Pressed(World::INPUT_BIND_FIRE);
    case MENU_NAV_CANCEL:  return Actions.Pressed(World::INPUT_BIND_BRAKE);
    default:               return false;
    }
}

bool MenuNavHeld(MENU_NAV_ACTION action)
{
    if ( SteamBackend().Available() && SteamBackend().MenuNavActive(action) )
        return true;

    switch ( action )
    {
    case MENU_NAV_UP:      return Actions.Active(World::INPUT_BIND_ZOOMIN);
    case MENU_NAV_DOWN:    return Actions.Active(World::INPUT_BIND_ZOOMOUT);
    case MENU_NAV_LEFT:    return Actions.Active(World::INPUT_BIND_SQ_MANAGE);
    case MENU_NAV_RIGHT:   return Actions.Active(World::INPUT_BIND_ORDER);
    case MENU_NAV_CONFIRM: return Actions.Active(World::INPUT_BIND_FIRE);
    case MENU_NAV_CANCEL:  return Actions.Active(World::INPUT_BIND_BRAKE);
    default:               return false;
    }
}

bool WidgetFocusable(const NC_STACK_button::button_str2 &widget)
{
    if ( !(widget.flags & NC_STACK_button::FLAG_DRAW) )
        return false;

    if ( widget.flags & NC_STACK_button::FLAG_DISABLED )
        return false;

    switch ( widget.button_type )
    {
    case NC_STACK_button::TYPE_BUTTON:
    case NC_STACK_button::TYPE_CHECKBX:
    case NC_STACK_button::TYPE_RADIOBTN:
        return true;

    default:
        return false;
    }
}

}

void MenuFocusController::Reset(NC_STACK_button *screen)
{
    _screen = screen;
    _focusIndex = -1;
    _entries.clear();
    _cursorInitialized = false;
    _confirmHeld = false;

    if ( _screen )
        RebuildFocusList();
}

void MenuFocusController::RebuildFocusList()
{
    _entries.clear();

    if ( !_screen )
        return;

    for ( std::size_t i = 0; i < _screen->field_d8.size(); i++ )
    {
        const NC_STACK_button::button_str2 &widget = _screen->field_d8[i];
        if ( !WidgetFocusable(widget) )
            continue;

        FocusEntry entry;
        entry.Index = (int)i;
        entry.CenterX = widget.xpos + widget.width / 2;
        entry.CenterY = widget.ypos + widget.height / 2;
        _entries.push_back(entry);
    }

    if ( !_entries.empty() )
        _focusIndex = 0;
}

void MenuFocusController::MoveFocus(int dx, int dy)
{
    if ( _entries.empty() || _focusIndex < 0 )
        return;

    const FocusEntry &current = _entries[(std::size_t)_focusIndex];
    int bestIndex = _focusIndex;
    int bestScore = 0;

    for ( std::size_t i = 0; i < _entries.size(); i++ )
    {
        if ( (int)i == _focusIndex )
            continue;

        const FocusEntry &candidate = _entries[i];
        const int cx = candidate.CenterX - current.CenterX;
        const int cy = candidate.CenterY - current.CenterY;

        if ( dx < 0 && cx >= 0 )
            continue;
        if ( dx > 0 && cx <= 0 )
            continue;
        if ( dy < 0 && cy >= 0 )
            continue;
        if ( dy > 0 && cy <= 0 )
            continue;

        const int score = (cx * cx + cy * cy) + 1;
        if ( !bestScore || score < bestScore )
        {
            bestScore = score;
            bestIndex = (int)i;
        }
    }

    _focusIndex = bestIndex;
}

void MenuFocusController::ActivateFocused(TInputState *state)
{
    if ( !state || !_screen || _focusIndex < 0 || _focusIndex >= (int)_entries.size() )
        return;

    const int widgetIndex = _entries[(std::size_t)_focusIndex].Index;
    if ( widgetIndex < 0 || widgetIndex >= (int)_screen->field_d8.size() )
        return;

    NC_STACK_button::button_str2 &widget = _screen->field_d8[(std::size_t)widgetIndex];
    widget.flags |= NC_STACK_button::FLAG_DOWN | NC_STACK_button::FLAG_PRESSED;

    state->ClickInf.flag |= TClickBoxInf::FLAG_OK | TClickBoxInf::FLAG_LM_DOWN |
                            TClickBoxInf::FLAG_BTN_DOWN;
    state->ClickInf.selected_btn = _screen;
    state->ClickInf.selected_btnID = widgetIndex;
}

void MenuFocusController::ReleaseFocused(TInputState *state)
{
    if ( !state || !_screen || _focusIndex < 0 || _focusIndex >= (int)_entries.size() )
        return;

    const int widgetIndex = _entries[(std::size_t)_focusIndex].Index;
    if ( widgetIndex < 0 || widgetIndex >= (int)_screen->field_d8.size() )
        return;

    NC_STACK_button::button_str2 &widget = _screen->field_d8[(std::size_t)widgetIndex];
    if ( !(widget.flags & NC_STACK_button::FLAG_DOWN) )
        return;

    state->ClickInf.flag |= TClickBoxInf::FLAG_OK | TClickBoxInf::FLAG_LM_UP |
                            TClickBoxInf::FLAG_BTN_UP;
    state->ClickInf.selected_btn = _screen;
    state->ClickInf.selected_btnID = widgetIndex;
}

void MenuFocusController::ApplyCursorDelta(TInputState *state)
{
    if ( !state )
        return;

    const float deltaX = SteamBackend().MenuCursorDeltaX();
    const float deltaY = SteamBackend().MenuCursorDeltaY();
    if ( deltaX == 0.0f && deltaY == 0.0f )
        return;

    if ( !_cursorInitialized )
    {
        _cursorX = (float)state->ClickInf.move.ScreenPos.x;
        _cursorY = (float)state->ClickInf.move.ScreenPos.y;
        _cursorInitialized = true;
    }

    const float scale = 12.0f;
    _cursorX += deltaX * scale;
    _cursorY += deltaY * scale;

    if ( GameScreenMode == GAME_SCREEN_MODE_MENU && ypaworld )
    {
        _cursorX = std::max(0.0f, std::min(_cursorX, (float)ypaworld->_screenSize.x));
        _cursorY = std::max(0.0f, std::min(_cursorY, (float)ypaworld->_screenSize.y));
    }

    state->ClickInf.move.ScreenPos.x = (int)_cursorX;
    state->ClickInf.move.ScreenPos.y = (int)_cursorY;
    state->ClickInf.flag |= TClickBoxInf::FLAG_OK;
}

void MenuFocusController::Apply(TInputState *state)
{
    if ( !state || !_screen )
        return;

    ApplyCursorDelta(state);

    if ( MenuNavPressed(MENU_NAV_UP) )
        MoveFocus(0, -1);
    if ( MenuNavPressed(MENU_NAV_DOWN) )
        MoveFocus(0, 1);
    if ( MenuNavPressed(MENU_NAV_LEFT) )
        MoveFocus(-1, 0);
    if ( MenuNavPressed(MENU_NAV_RIGHT) )
        MoveFocus(1, 0);

    const bool confirmHeld = MenuNavHeld(MENU_NAV_CONFIRM);
    if ( confirmHeld && !_confirmHeld )
        ActivateFocused(state);
    else if ( !confirmHeld && _confirmHeld )
        ReleaseFocused(state);
    _confirmHeld = confirmHeld;

    if ( MenuNavPressed(MENU_NAV_CANCEL) )
        state->ClickInf.flag |= TClickBoxInf::FLAG_RM_DOWN;

    if ( _focusIndex >= 0 && _focusIndex < (int)_entries.size() )
    {
        const FocusEntry &entry = _entries[(std::size_t)_focusIndex];
        if ( entry.Index >= 0 && entry.Index < (int)_screen->field_d8.size() )
            _screen->field_d8[(std::size_t)entry.Index].flags |= NC_STACK_button::FLAG_BORDER;
    }
}

void ApplyMenuFocusInput(NC_STACK_button *screen, TInputState *state)
{
    if ( !screen || !state )
        return;

    if ( GameScreenMode != GAME_SCREEN_MODE_MENU && !SteamBackend().Available() )
        return;

    MenuFocusController &controller = Controller();
    if ( controller.FocusIndex() < 0 || screen != controller.Screen() )
        controller.Reset(screen);

    controller.Apply(state);
}

}
