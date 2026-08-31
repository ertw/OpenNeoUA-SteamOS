#include <cstdlib>
#include <iostream>

#include "system/sleepnotify.h"

namespace
{
void Require(bool condition, const char *message)
{
    if (!condition)
    {
        std::cerr << "sleep notification test failed: " << message << '\n';
        std::exit(1);
    }
}
}

int main()
{
    System::SleepNotifications::State state;

    Require(!state.ConsumePrepareForSleep(), "new state must be empty");

    state.RecordPrepareForSleep(false);
    Require(!state.ConsumePrepareForSleep(), "resume must not request a pause");

    state.RecordPrepareForSleep(true);
    Require(state.ConsumePrepareForSleep(), "suspend must request a pause");
    Require(!state.ConsumePrepareForSleep(), "request must be consumed once");

    state.RecordPrepareForSleep(true);
    state.RecordPrepareForSleep(true);
    Require(state.ConsumePrepareForSleep(), "repeated suspend signals must coalesce");
    Require(!state.ConsumePrepareForSleep(), "coalesced request must be consumed once");

    state.RecordPrepareForSleep(true);
    state.RecordPrepareForSleep(false);
    Require(state.ConsumePrepareForSleep(), "resume must not clear a pending suspend request");

    state.RecordPrepareForSleep(true);
    state.Reset();
    Require(!state.ConsumePrepareForSleep(), "reset must clear pending state");

#if !defined(OPENNEOUA_HAVE_SYSTEMD)
    System::SleepNotifications::Init();
    Require(!System::ConsumePrepareForSleep(), "disabled backend must be a no-op");
    System::SleepNotifications::Deinit();
#endif

    std::cout << "sleep notification tests passed\n";
    return 0;
}
