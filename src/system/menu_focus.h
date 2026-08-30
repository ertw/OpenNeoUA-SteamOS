#ifndef SYSTEM_MENU_FOCUS_H_INCLUDED
#define SYSTEM_MENU_FOCUS_H_INCLUDED

#include <vector>

class NC_STACK_button;
struct TInputState;

// OpenNeoUA: controller-first menu navigation for NC_STACK_button screens.
//
// When Steam Input (or keyboard menu-nav fallbacks) is active, this layer
// enumerates focusable widgets, moves focus spatially and synthesizes the
// ClickInf transitions ProcessWidgetsEvents already understands.  Mouse input
// remains available as a complement via absolute MenuCursor deltas.

namespace Input
{

class MenuFocusController
{
public:
    void Reset(NC_STACK_button *screen);
    void Apply(TInputState *state);

    bool HasFocus() const { return _focusIndex >= 0; }
    int FocusIndex() const { return _focusIndex; }
    NC_STACK_button *Screen() const { return _screen; }

private:
    struct FocusEntry
    {
        int Index = -1;
        int CenterX = 0;
        int CenterY = 0;
    };

    void RebuildFocusList();
    void MoveFocus(int dx, int dy);
    void ActivateFocused(TInputState *state);
    void ApplyCursorDelta(TInputState *state);

    NC_STACK_button *_screen = nullptr;
    std::vector<FocusEntry> _entries;
    int _focusIndex = -1;
    float _cursorX = 0.0f;
    float _cursorY = 0.0f;
};

// Applies menu focus for the active button screen when appropriate.
void ApplyMenuFocusInput(NC_STACK_button *screen, TInputState *state);

}

#endif // SYSTEM_MENU_FOCUS_H_INCLUDED
