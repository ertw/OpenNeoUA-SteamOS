#include <cstdio>

#include "sleepnotify.h"

#if defined(OPENNEOUA_HAVE_SYSTEMD)
#include <systemd/sd-bus.h>
#endif

namespace System
{
namespace SleepNotifications
{
namespace
{
State notificationState;

#if defined(OPENNEOUA_HAVE_SYSTEMD)
sd_bus *systemBus = nullptr;
sd_bus_slot *prepareForSleepSlot = nullptr;

void CloseBackend()
{
    prepareForSleepSlot = sd_bus_slot_unref(prepareForSleepSlot);
    systemBus = sd_bus_flush_close_unref(systemBus);
}

int HandlePrepareForSleep(sd_bus_message *message, void *userdata, sd_bus_error *)
{
    int preparing = 0;
    const int result = sd_bus_message_read(message, "b", &preparing);
    if (result < 0)
        return result;

    static_cast<State *>(userdata)->RecordPrepareForSleep(preparing != 0);
    return 0;
}

void Pump()
{
    if (!systemBus)
        return;

    int result = 0;
    do
    {
        result = sd_bus_process(systemBus, nullptr);
    }
    while (result > 0);

    if (result < 0)
    {
        std::fprintf(stderr,
                     "OpenNeoUA: system sleep notification bus failed (%d); disabling listener\n",
                     result);
        CloseBackend();
    }
}
#else
void Pump()
{}
#endif
}

void State::RecordPrepareForSleep(bool preparing)
{
    if (preparing)
        _prepareForSleepPending = true;
}

bool State::ConsumePrepareForSleep()
{
    const bool pending = _prepareForSleepPending;
    _prepareForSleepPending = false;
    return pending;
}

void State::Reset()
{
    _prepareForSleepPending = false;
}

void Init()
{
    notificationState.Reset();

#if defined(OPENNEOUA_HAVE_SYSTEMD)
    if (systemBus)
        return;

    int result = sd_bus_default_system(&systemBus);
    if (result < 0)
    {
        std::fprintf(stderr,
                     "OpenNeoUA: system bus unavailable (%d); sleep notifications disabled\n",
                     result);
        systemBus = nullptr;
        return;
    }

    result = sd_bus_match_signal(systemBus,
                                 &prepareForSleepSlot,
                                 "org.freedesktop.login1",
                                 "/org/freedesktop/login1",
                                 "org.freedesktop.login1.Manager",
                                 "PrepareForSleep",
                                 HandlePrepareForSleep,
                                 &notificationState);
    if (result < 0)
    {
        std::fprintf(stderr,
                     "OpenNeoUA: cannot subscribe to PrepareForSleep (%d); sleep notifications disabled\n",
                     result);
        CloseBackend();
    }
#endif
}

void Deinit()
{
#if defined(OPENNEOUA_HAVE_SYSTEMD)
    CloseBackend();
#endif
    notificationState.Reset();
}

bool Consume()
{
    Pump();
    return notificationState.ConsumePrepareForSleep();
}
}

bool ConsumePrepareForSleep()
{
    return SleepNotifications::Consume();
}
}
