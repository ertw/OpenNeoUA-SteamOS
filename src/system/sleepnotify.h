#ifndef UA_SYSTEM_SLEEPNOTIFY_H_INCLUDED
#define UA_SYSTEM_SLEEPNOTIFY_H_INCLUDED

namespace System
{
namespace SleepNotifications
{
    class State
    {
    public:
        void RecordPrepareForSleep(bool preparing);
        bool ConsumePrepareForSleep();
        void Reset();

    private:
        bool _prepareForSleepPending = false;
    };

    void Init();
    void Deinit();
}

// Pumps the optional platform backend and consumes one pending suspend request.
bool ConsumePrepareForSleep();
}

#endif
