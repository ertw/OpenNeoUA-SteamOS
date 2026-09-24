#ifndef YW_COMMAND_WHEEL_H_INCLUDED
#define YW_COMMAND_WHEEL_H_INCLUDED

struct TInputState;
class NC_STACK_ypaworld;

// OpenNeoUA: controller-only, two-press radial command overlay.
// L3 opens, the left stick aims, and a second L3 press activates the selection;
// confirming with the stick centered cancels. All input except the left stick
// stays live while the overlay is open.
namespace CommandWheel
{
constexpr int kSliceCount = 8;

class State
{
public:
    void Reset();
    void Close();
    // Returns true when controller left-stick input must be suppressed for
    // this frame, including a frame that closes or confirms the overlay.
    bool UpdateInput(NC_STACK_ypaworld *yw, TInputState *inpt);
    void ApplyPending(NC_STACK_ypaworld *yw, TInputState *inpt);
    bool IsOpen() const { return _open; }
    void Draw(NC_STACK_ypaworld *yw) const;

private:
    void CloseOverlay(bool clearPending);

    bool _open = false;
    bool _commandWheelHeld = false;
    int _highlight = -1;
    int _pendingSlice = -1;
};
}

#endif
