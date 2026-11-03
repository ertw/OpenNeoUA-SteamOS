#ifndef OPENNEOUA_MENU_SMOKE_H
#define OPENNEOUA_MENU_SMOKE_H

struct UserData;

namespace MenuSmoke
{
bool Enabled();
bool Run(UserData &userdata, int (*processNextFrame)());
// Publish success only after the engine has completed normal shutdown.
bool WriteReportAfterShutdown();
}

#endif
