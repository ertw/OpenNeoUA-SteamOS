// Program entry point: engine start-up, the main loop and the switch between
// menu (game shell), gameplay and replay screens.
#define GLOBAL
#include <fstream>
#include "system/fsmgr.h"
#include "common/utils.h"
#include "system/system.h"
#include "common/env.h"

#include "common/includes.h"
#include "system/gfx.h"
#include "system/inpt.h"
#include "system/framepacer.h"
#include "platform/winp.h"
#include "platform/wintimer.h"
#include "system/action_input.h"
#include "system/action_backend.h"
#include "system/steam_api_loader.h"

#include "nucleus/ade.h"
#include "nucleus/area.h"
#include "nucleus/amesh.h"
#include "nucleus/bitmap.h"
#include "nucleus/bmpAnm.h"
#include "nucleus/base.h"
#include "nucleus/ilbm.h"
#include "nucleus/particle.h"
#include "nucleus/embed.h"
#include "nucleus/3ds.h"
#include "nucleus/image.h"
#include "nucleus/obj3d.h"
#include "platform/network.h"
#include "platform/windp.h"
#include "game/ypabact.h"
#include "game/ypatank.h"
#include "game/ypacar.h"
#include "game/ypaflyer.h"
#include "game/yparobo.h"
#include "game/ypaufo.h"
#include "game/yw.h"
#include "gui/font.h"
#include "gui/button.h"
#include "gui/widget.h"
#include "gui/uawidgets.h"
#include "gui/uamsgbox.h"
#include "gui/uaempty.h"
#include "system/movie.h"
#include "system/inivals.h"
#include "system/steam_api_loader.h"
#include "world/blacksecttint.h"
#include "world/energyfx.h"
#include "common/crashdiag.h"

#include <sstream>
#include <csignal>
#include <sys/stat.h>
#include <cerrno>
#include <cstring>
#ifndef _WIN32
#include <limits.h>
#include <unistd.h>
#endif

namespace
{
int ProcessNextFrame();
extern UserData userdata;

namespace
{
volatile std::sig_atomic_t QuitSignalReceived = 0;

void HandleQuitSignal(int)
{
    QuitSignalReceived = 1;
}
}

static bool MenuSmokeEnabled()
{
    return System::FindCmdLineArg("--menu-smoke-dir") >= 0;
}

static std::string MenuSmokeDirectory()
{
    const std::vector<std::string> &cmdl = System::GetCmdLineArray();
    int32_t index = System::FindCmdLineArg("--menu-smoke-dir");
    if (index < 0 || index + 1 >= (int32_t)cmdl.size() || cmdl[index + 1].empty())
        return std::string();
    return cmdl[index + 1];
}

static std::string MenuSmokeJsonEscape(const std::string &value)
{
    std::string result;
    result.reserve(value.size() + 8);
    for (unsigned char ch : value)
    {
        switch (ch)
        {
        case '\\': result += "\\\\"; break;
        case '"': result += "\\\""; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if (ch < 0x20)
            {
                char buf[8];
                snprintf(buf, sizeof(buf), "\\u%04x", ch);
                result += buf;
            }
            else
                result += (char)ch;
            break;
        }
    }
    return result;
}

static bool MenuSmokeEnsureDir(const std::string &input)
{
    if (input.empty())
        return false;
    std::string path = input;
    while (path.size() > 1 && path.back() == '/')
        path.pop_back();
    std::string current;
    if (!path.empty() && path.front() == '/')
        current = "/";
    size_t start = current.empty() ? 0 : 1;
    while (start <= path.size())
    {
        size_t end = path.find('/', start);
        std::string part = end == std::string::npos ? path.substr(start) : path.substr(start, end - start);
        if (!part.empty())
        {
            if (!current.empty() && current.back() != '/')
                current += '/';
            current += part;
            struct stat info;
            if (stat(current.c_str(), &info) == 0)
            {
                if (!S_ISDIR(info.st_mode))
                    return false;
            }
            else if (mkdir(current.c_str(), 0755) != 0 && errno != EEXIST)
                return false;
        }
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    return true;
}

static std::string MenuSmokeProvenance()
{
    std::string filename = FSMgr::iDir::getAssetRoot();
    if (filename.empty())
        return std::string();
    if (filename.back() != '/')
        filename += '/';
    filename += "PROVENANCE.json";
    std::ifstream stream(filename.c_str());
    if (!stream)
        return std::string();
    std::stringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

static std::string MenuSmokeProvenanceValue(const std::string &json, const std::string &key)
{
    const std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos)
        return std::string();
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos)
        return std::string();
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos)
        return std::string();
    size_t end = json.find('"', pos + 1);
    if (end == std::string::npos)
        return std::string();
    return json.substr(pos + 1, end - pos - 1);
}

static bool MenuSmokePushMouse(Uint32 type, int x, int y, Uint8 button = 0)
{
    SDL_Event event;
    SDL_zero(event);
    event.type = type;
    if (type == SDL_MOUSEMOTION)
    {
        event.motion.x = x;
        event.motion.y = y;
        event.motion.xrel = 0;
        event.motion.yrel = 0;
    }
    else
    {
        event.button.x = x;
        event.button.y = y;
        event.button.button = button;
        event.button.clicks = 1;
    }
    return SDL_PushEvent(&event) == 1;
}

static bool MenuSmokePushEscape()
{
    SDL_Event event;
    SDL_zero(event);
    event.type = SDL_KEYDOWN;
    event.key.keysym.scancode = SDL_SCANCODE_ESCAPE;
    event.key.keysym.sym = SDLK_ESCAPE;
    event.key.repeat = 0;
    if (SDL_PushEvent(&event) != 1)
        return false;
    SDL_zero(event);
    event.type = SDL_KEYUP;
    event.key.keysym.scancode = SDL_SCANCODE_ESCAPE;
    event.key.keysym.sym = SDLK_ESCAPE;
    return SDL_PushEvent(&event) == 1;
}

static bool MenuSmokeRenderFrames(int count, int *frameCount)
{
    for (int i = 0; i < count; ++i)
    {
        if (!ProcessNextFrame())
            return false;
        if (frameCount)
            ++*frameCount;
    }
    return true;
}

// The smoke report is deliberately held in memory until the complete normal
// shutdown sequence has finished.  A report written before SDL/Nucleus
// teardown could claim success for a process that subsequently crashed.
static std::string g_menuSmokeReport;
static std::string g_menuSmokeReportPath;

static bool MenuSmokeWriteReportAfterShutdown()
{
    if (g_menuSmokeReport.empty() || g_menuSmokeReportPath.empty())
        return false;

    std::string report = g_menuSmokeReport;
    const size_t closingBrace = report.rfind("\n}");
    if (closingBrace == std::string::npos)
        return false;
    report.insert(closingBrace, ",\n  \"clean_teardown\": true");

    const std::string temporary = g_menuSmokeReportPath + ".tmp";
    {
        std::ofstream output(temporary.c_str(), std::ios::binary | std::ios::trunc);
        if (!output)
            return false;
        output << report;
        output.flush();
        if (!output)
        {
            output.close();
            remove(temporary.c_str());
            return false;
        }
    }

    if (rename(temporary.c_str(), g_menuSmokeReportPath.c_str()) != 0)
    {
        remove(temporary.c_str());
        return false;
    }
    return true;
}

static bool MenuSmokeFindEnabledRegionPoint(int *outX, int *outY)
{
    if ( !ypaworld || !outX || !outY )
        return false;

    TMapRegionsNet &regions = ypaworld->_globalMapRegions;
    const Common::Point screenSize = ypaworld->_screenSize;

    int bestIndex = 0;
    float bestArea = 0.0f;
    for ( int i = 1; i < 256; ++i )
    {
        const TMapRegionInfo &info = regions.MapRegions[i];
        if ( info.Status != TMapRegionInfo::STATUS_ENABLED &&
             info.Status != TMapRegionInfo::STATUS_COMPLETED )
            continue;

        const Common::FRect &rect = info.Rect;
        if ( rect.right <= rect.left || rect.bottom <= rect.top )
            continue;

        const float area = (rect.right - rect.left) * (rect.bottom - rect.top);
        if ( area > bestArea )
        {
            bestArea = area;
            bestIndex = i;
        }
    }

    if ( bestIndex > 0 )
    {
        const Common::FRect &rect = regions.MapRegions[bestIndex].Rect;
        const float centerX = (rect.left + rect.right) * 0.5f;
        const float centerY = (rect.top + rect.bottom) * 0.5f;
        *outX = (int)((centerX + 1.0f) * 0.5f * screenSize.x);
        *outY = (int)((centerY + 1.0f) * 0.5f * screenSize.y);
        return true;
    }

    if ( !regions.MaskImage )
        return false;

    ResBitmap *bitmap = regions.MaskImage->GetBitmap();
    if ( !bitmap || !bitmap->swTex )
        return false;

    SDL_LockSurface(bitmap->swTex);
    const int width = bitmap->swTex->w;
    const int height = bitmap->swTex->h;
    const int pitch = bitmap->swTex->pitch;
    const uint8_t *pixels = (const uint8_t *)bitmap->swTex->pixels;

    bool found = false;
    for ( int y = 0; y < height && !found; ++y )
    {
        for ( int x = 0; x < width; ++x )
        {
            const uint8_t regionIndex = pixels[y * pitch + x];
            if ( regionIndex == 0 || regionIndex >= 256 )
                continue;

            const int status = regions.MapRegions[regionIndex].Status;
            if ( status != TMapRegionInfo::STATUS_ENABLED &&
                 status != TMapRegionInfo::STATUS_COMPLETED )
                continue;

            *outX = x * screenSize.x / width;
            *outY = y * screenSize.y / height;
            found = true;
            break;
        }
    }

    SDL_UnlockSurface(bitmap->swTex);
    return found;
}

static void MenuSmokeSetPointerPhysical(int x, int y)
{
    NC_STACK_winp::SmokeSetPointerPhysical(Common::Point(x, y));
}

static bool MenuSmokePushSteamMenuNav(Input::MENU_NAV_ACTION action)
{
    Input::SteamBackend().PulseMenuNav(action);
    return true;
}

static bool MenuSmokePushSteamMenuConfirmRelease()
{
    Input::SteamBackend().PulseMenuConfirmRelease();
    return true;
}

static bool RunMenuSmoke()
{
    g_menuSmokeReport.clear();
    g_menuSmokeReportPath.clear();
    const std::string smokeDir = MenuSmokeDirectory();
    if (smokeDir.empty() || !MenuSmokeEnsureDir(smokeDir))
    {
        ypa_log_out("menu smoke: invalid output directory\n");
        return false;
    }
    if (!ypaworld || userdata.EnvMode != ENVMODE_TITLE || !userdata.titel_button)
    {
        ypa_log_out("menu smoke: title menu is not initialized\n");
        return false;
    }
    if (!uaCreateDir("env:snaps") && !uaOpenDir("env:snaps"))
    {
        ypa_log_out("menu smoke: unable to create screenshot directory\n");
        return false;
    }

    Input::SteamBackend().EnableSmokeMode();

    int frameCount = 0;
    if (!MenuSmokeRenderFrames(3, &frameCount))
        return false;
    GFX::Engine.SaveScreenshot("env:snaps/menu-title-before");

    const Common::Point physical = GFX::Engine.GetScreenSize();
    const Common::Point logical = GFX::Engine.GetVirtualUIResolution();
    if (physical.x != 1280 || physical.y != 800 || logical.x <= 0 || logical.y <= 0)
    {
        ypa_log_out("menu smoke: renderer did not select 1280x800\n");
        return false;
    }

    // Single Player is the first focusable title widget; confirm via Steam Input.
    if (!MenuSmokePushSteamMenuNav(Input::MENU_NAV_CONFIRM))
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount) || System::ProcessEvents())
        return false;
    if (!MenuSmokePushSteamMenuConfirmRelease())
        return false;
    if (!MenuSmokeRenderFrames(2, &frameCount) || userdata.EnvMode != ENVMODE_SINGLEPLAY)
    {
        ypa_log_out("menu smoke: Steam MenuConfirm did not enter campaign map select\n");
        return false;
    }

    if (!MenuSmokeRenderFrames(15, &frameCount))
        return false;

    if (!ypaworld->_globalMapRegions.MaskImage)
    {
        ypa_log_out("menu smoke: campaign map mask image is not loaded\n");
        return false;
    }

    int mapClickX = 0;
    int mapClickY = 0;
    if (!MenuSmokeFindEnabledRegionPoint(&mapClickX, &mapClickY))
    {
        ypa_log_out("menu smoke: no enabled campaign map region found on mask bitmap\n");
        return false;
    }

    const int physicalClickX = mapClickX * physical.x / logical.x;
    const int physicalClickY = mapClickY * physical.y / logical.y;
    int selectedRegion = 0;

    for (int attempt = 0; attempt < 3; ++attempt)
    {
        MenuSmokeSetPointerPhysical(physicalClickX, physicalClickY);
        if (!MenuSmokePushMouse(SDL_MOUSEMOTION, physicalClickX, physicalClickY) || System::ProcessEvents())
            return false;
        MenuSmokeSetPointerPhysical(physicalClickX, physicalClickY);
        if (!MenuSmokeRenderFrames(2, &frameCount))
            return false;
        selectedRegion = ypaworld->_globalMapRegions.SelectedRegion;
        if (selectedRegion > 0)
            break;
    }
    if (selectedRegion <= 0)
    {
        ypa_log_out("menu smoke: campaign map hover did not select a region\n");
        return false;
    }

    GFX::Engine.SaveScreenshot("env:snaps/menu-campaign-map");

    // Stop at campaign map select.  A left click would start InitBriefing or
    // ACTION_PLAY and can stall headless smoke runs for minutes.
    if (userdata.EnvMode != ENVMODE_SINGLEPLAY)
    {
        ypa_log_out("menu smoke: left campaign map select before report\n");
        return false;
    }

    const char *renderer = (const char *)glGetString(GL_RENDERER);
    const char *version = (const char *)glGetString(GL_VERSION);
    const char *vendor = (const char *)glGetString(GL_VENDOR);
    const std::string provenance = MenuSmokeProvenance();
    const std::string isoSha = MenuSmokeProvenanceValue(provenance, "iso_sha256");
    const std::string sourceId = MenuSmokeProvenanceValue(provenance, "source_id");

    std::string report;
    report += "{\n  \"version\": 2,\n";
    report += "  \"steam_input\": true,\n";
    report += "  \"milestones\": [\n";
    report += "    {\"event\": \"title-before\", \"mode\": \"ENVMODE_TITLE\", \"frames\": 3},\n";
    report += "    {\"event\": \"campaign-map\", \"mode\": \"ENVMODE_SINGLEPLAY\", \"frames\": 10}\n  ],\n";
    report += fmt::sprintf("  \"frame_count\": %d,\n", frameCount);
    report += fmt::sprintf("  \"selected_region\": %d,\n", selectedRegion);
    report += fmt::sprintf("  \"map_probe\": [%d, %d],\n", mapClickX, mapClickY);
    report += fmt::sprintf("  \"resolution\": [%d, %d],\n", physical.x, physical.y);
    report += "  \"renderer\": {\"gl_renderer\": \"" + MenuSmokeJsonEscape(renderer ? renderer : "") +
             "\", \"gl_version\": \"" + MenuSmokeJsonEscape(version ? version : "") +
             "\", \"gl_vendor\": \"" + MenuSmokeJsonEscape(vendor ? vendor : "") + "\"},\n";
    report += "  \"final_mode\": \"ENVMODE_SINGLEPLAY\",\n";
    report += "  \"asset_provenance\": {\"asset_root\": \"" + MenuSmokeJsonEscape(FSMgr::iDir::getAssetRoot()) +
             "\", \"source_id\": \"" + MenuSmokeJsonEscape(sourceId) +
             "\", \"iso_sha256\": \"" + MenuSmokeJsonEscape(isoSha) + "\"}\n}\n";
    g_menuSmokeReport = report;
    g_menuSmokeReportPath = smokeDir + "/menu-smoke.json";
    return true;
}



UserData userdata;

// Netplay and replays change the player settings; when they end, the copy
// saved in settings.tmp is restored.
bool restoreSettingsOnExit = false;
// The menu demo loop chains the next demo replay when the current one ends.
bool chainDemoReplays = false;
// Index of the demo replay shown last, so the loop does not repeat it.
int lastDemoIndex = 0;

bool tformInited = false;
bool audioInited = false;
bool inputInited = false;

int DiagnosticLevelId()
{
    return ypaworld ? ypaworld->GetLevelInfo().LevelID : -1;
}

bool RestoreSavedSettings()
{
    if ( !restoreSettingsOnExit )
        return true;

    if ( !ypaworld->LoadSettings("settings.tmp", userdata.UserName,
                                 World::SDF_BUDDY | World::SDF_PROTO | World::SDF_USER,
                                 false) )
        return false;

    restoreSettingsOnExit = false;
    return true;
}

// Opens the game shell again after a level or a replay. Returns false when the
// shell cannot be opened (fatal).
bool ReturnToMenu()
{
    GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
    world_update_arg.TimeStamp = 0;
    userdata.lastInputEvent = 0;

    if ( !ypaworld->OpenGameShell() )
    {
        ypa_log_out("GameShell-Error!!!\n");
        ypaworld->DeinitGameShell();
        return false;
    }

    GameScreenMode = GAME_SCREEN_MODE_MENU;
    return true;
}

// Picks a demo replay from env:snaps, avoiding the one shown last time.
std::string PickDemoReplay(uint32_t seed)
{
    if ( userdata.snaps.empty() )
        return std::string();

    int index = seed % userdata.snaps.size();

    if ( index == lastDemoIndex )
    {
        if ( index )
            index--;
        else if ( userdata.snaps.size() > 1 )
            index = 1;
    }

    lastDemoIndex = index;
    return userdata.snaps[index];
}

int ProcessGameplayFrame()
{
    CrashDiag::SetPhase("GameplayWorldProcess");
    ypaworld->Process(&world_update_arg);
    CrashDiag::SetPhase("GameplayStateTransition");

    const TLevelInfo &levelInfo = ypaworld->GetLevelInfo();

    switch ( levelInfo.State )
    {
    case TLevelInfo::STATE_QUIT_GAME:
        CrashDiag::Breadcrumb("LEVEL", "quit requested level=%d", levelInfo.LevelID);
        return 0;

    case TLevelInfo::STATE_COMPLETED:
    case TLevelInfo::STATE_ABORTED:
    {
        CrashDiag::Breadcrumb("LEVEL", "leave level=%d state=%d", levelInfo.LevelID, levelInfo.State);
        CrashDiag::SetPhase("DeleteLevel");
        const bool aborted = levelInfo.State == TLevelInfo::STATE_ABORTED;
        ypaworld->DeleteLevel();

        if ( aborted )
            restoreSettingsOnExit = true;
        if ( !RestoreSavedSettings() )
            return 0;

        // A remote-mode session quits after its level instead of returning to the menu.
        const bool keepRunning = !userdata.remoteMode;

        if ( userdata.EnvMode == ENVMODE_NETPLAY )
        {
            userdata.returnToTitle = true;
            userdata.EnvMode = ENVMODE_SINGLEPLAY;
        }
        else
        {
            userdata.returnToTitle = false;
        }

        userdata.GameIsOver = true;

        if ( !ReturnToMenu() )
            return 0;

        Input::Engine.QueryInput(&input_states);
        if ( !keepRunning )
            return 0;
    }
    break;

    case TLevelInfo::STATE_RESTART:
    {
        CrashDiag::Breadcrumb("LEVEL", "restart level=%d", levelInfo.LevelID);
        const int levelId = levelInfo.LevelID;
        const int tacticalMapZoom = ypaworld->GetTacticalMapZoomLevel();

        CrashDiag::SetPhase("RestartDeleteLevel");
        ypaworld->DeleteLevel();

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.rst", userdata.UserName, levelId) ) )
            ypa_log_out("Warning, load error\n");
        else
            ypaworld->SetTacticalMapZoomLevel(tacticalMapZoom); // Restart keeps the player's zoom.

        Input::Engine.QueryInput(&input_states);
    }
    break;

    case TLevelInfo::STATE_SAVE:
        if ( !ypaworld->SaveGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
            ypa_log_out("Warning, Save error\n");

        Input::Engine.QueryInput(&input_states);
        break;

    case TLevelInfo::STATE_LOAD:
        CrashDiag::Breadcrumb("LEVEL", "load save from level=%d", levelInfo.LevelID);
        CrashDiag::SetPhase("LoadDeleteLevel");
        ypaworld->DeleteLevel();

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
            ypa_log_out("Warning, load error\n");

        Input::Engine.QueryInput(&input_states);
        break;

    default:
        break;
    }

    return 1;
}

// Advances replay playback and handles its keys. Returns false when the
// player leaves the replay (or the next demo cannot be loaded).
bool UpdateReplayPlayback(base_64arg *arg)
{
    TGameRecorder *player = userdata.p_YW->_replayPlayer;

    if ( chainDemoReplays && player->field_74 - 3 <= player->frame_id )
    {
        ypaworld->ypaworld_func164();

        if ( !ypaworld->ypaworld_func162( PickDemoReplay(arg->TimeStamp) ) )
        {
            GameScreenMode = GAME_SCREEN_MODE_MENU;
            Input::Engine.QueryInput(&input_states);
            return false;
        }

        GameScreenMode = GAME_SCREEN_MODE_REPLAY;
    }

    ypaworld->ypaworld_func163(arg);

    // Replay control keys: field_0 is the replay command, frame the step size.
    yw_arg165 control;
    control.field_0 = 0;
    control.frame = 0;

    switch ( arg->field_8->KbdLastHit )
    {
    case Input::KC_S: control.field_0 = 1; break;
    case Input::KC_P: control.field_0 = 2; break;
    case Input::KC_R: control.field_0 = 3; break;
    case Input::KC_N: control.field_0 = 4; break;
    case Input::KC_B: control.field_0 = 5; break;
    case Input::KC_V: control.field_0 = 7; control.frame = -10; break;
    case Input::KC_M: control.field_0 = 7; control.frame = 10; break;
    case Input::KC_SPACE:
    case Input::KC_ESCAPE:
        return false;
    default:
        break;
    }

    if ( control.field_0 )
        ypaworld->ypaworld_func165(&control);

    return true;
}

int ProcessReplayFrame()
{
    if ( UpdateReplayPlayback(&world_update_arg) )
        return 1;

    ypaworld->ypaworld_func164();

    if ( !RestoreSavedSettings() )
        return 0;

    if ( !ReturnToMenu() )
        return 0;

    userdata.p_YW->_levelInfo.State = TLevelInfo::STATE_MENU;
    input_states = TInputState();
    Input::Engine.QueryInput(&input_states);
    return 1;
}

// Closes the shell before a level, a saved game or a replay starts.
bool LeaveMenu()
{
    userdata.SaveSettings();
    ypaworld->CloseGameShell();
    GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
    return userdata.SaveBuildProtoState();
}

int ProcessMenuFrame()
{
    userdata.GlobalTime = world_update_arg.TimeStamp;
    userdata.DTime = world_update_arg.DTime;
    userdata.Input = &input_states;

    ypaworld->ProcessGameShell();

    switch ( userdata.envAction.action )
    {
    case EnvAction::ACTION_QUIT:
        return 0;

    case EnvAction::ACTION_PLAY:
    case EnvAction::ACTION_RESTART_MISSION:
    {
        CrashDiag::Breadcrumb("LEVEL", "start requested level=%d", userdata.envAction.params[0]);
        CrashDiag::SetPhase("LevelStart");
        if ( !LeaveMenu() )
            return 0;

        yw_arg161 level;
        level.lvlID = userdata.envAction.params[0];
        level.field_4 = 0;
        level.freshStart = userdata.envAction.action == EnvAction::ACTION_RESTART_MISSION;

        if ( !ypaworld->ypaworld_func183(&level) )
        {
            ypa_log_out("Sorry, unable to init this level!\n");
            ypaworld->DeinitGameShell();
            return 0;
        }
        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    break;

    case EnvAction::ACTION_LOAD:
    {
        CrashDiag::Breadcrumb("LEVEL", "load save requested");
        CrashDiag::SetPhase("LevelLoad");
        const int levelId = ypaworld->GetLevelInfo().LevelID;
        if ( !LeaveMenu() )
            return 0;

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
        {
            ypa_log_out("Error while loading level (level %d, User %s\n", levelId, userdata.UserName.c_str());
            ypaworld->DeinitGameShell();
            return 0;
        }
        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    break;

    case EnvAction::ACTION_NETPLAY:
    {
        CrashDiag::Breadcrumb("LEVEL", "netplay start requested level=%d", userdata.envAction.params[0]);
        CrashDiag::SetPhase("NetLevelStart");
        if ( !LeaveMenu() )
            return 0;

        restoreSettingsOnExit = true;

        yw_arg161 level;
        level.lvlID = userdata.envAction.params[0];
        level.field_4 = 0;

        if ( !ypaworld->ypaworld_func179(&level) )
        {
            ypa_log_out("Sorry, unable to init this level for network!\n");
            ypaworld->DeinitGameShell();
            return 0;
        }

        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    break;

    case EnvAction::ACTION_REPLAY:
    {
        std::string replayName = PickDemoReplay(world_update_arg.TimeStamp);
        if ( replayName.empty() )
        {
            userdata.lastInputEvent = world_update_arg.TimeStamp;
            return 1;
        }

        if ( !userdata.SaveBuildProtoState() )
            return 0;

        restoreSettingsOnExit = true;
        ypaworld->CloseGameShell();
        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;

        if ( ypaworld->ypaworld_func162(replayName) )
        {
            chainDemoReplays = true;
            GameScreenMode = GAME_SCREEN_MODE_REPLAY;
        }
        else
        {
            ypa_log_out("Sorry, unable to init player!\n");
            if ( !ReturnToMenu() )
                return 0;
        }

        Input::Engine.QueryInput(&input_states);
    }
    break;

    default:
        break;
    }

    return 1;
}

// Game clock units (1024 per second) that this frame advances.
//
// The clock always follows real time: the simulation steps once per rendered
// frame with the measured delta, so the game runs at the same speed at 60 or
// 240 FPS and every extra frame only adds fluidity. The delta is at least one
// unit (some code divides by it) and at most 256 units (1/4 s), so a stall
// such as alt-tab cannot become one giant physics step.
//
// Netplay keeps the original +1 bias per frame: the network flush and sync
// code was written around it.
int32_t FrameClockDelta(int32_t measured)
{
    const bool netGame = GameScreenMode == GAME_SCREEN_MODE_GAME && ypaworld && ypaworld->_isNetGame;
    if ( netGame )
        return measured + 1;

    return std::max(1, std::min(measured, 256));
}

} // namespace

int ProcessNextFrame()
{
    CrashDiag::FrameBegin(world_update_arg.TimeStamp, GameScreenMode, DiagnosticLevelId());
    CrashDiag::SetPhase("InputQuery");

    input_states = TInputState();
    Input::Engine.QueryInput(&input_states);

    if ( userdata.ResetInputPeriod )
    {
        input_states.Period = 1;
        userdata.ResetInputPeriod = false;
    }

    input_states.Period = FrameClockDelta(input_states.Period);

    world_update_arg.DTime = input_states.Period;
    world_update_arg.field_8 = &input_states;
    world_update_arg.TimeStamp += input_states.Period;

    System::SetReleativeMouse(ypaworld->_mouseGrabbed);

    CrashDiag::SetPhase("GuiTimers");
    // In-game and replay GUI timers follow the game clock (with time scale)
    // and are advanced inside the world frame; menus use platform time.
    if ( GameScreenMode != GAME_SCREEN_MODE_GAME &&
         GameScreenMode != GAME_SCREEN_MODE_REPLAY )
        Gui::Root::Instance.TimersUpdate(input_states.Period);

    int result = 1;
    switch ( GameScreenMode )
    {
    case GAME_SCREEN_MODE_MENU:
        CrashDiag::SetPhase("MenuFrame");
        result = ProcessMenuFrame();
        break;

    case GAME_SCREEN_MODE_GAME:
        CrashDiag::SetPhase("GameplayFrame");
        result = ProcessGameplayFrame();
        break;

    case GAME_SCREEN_MODE_REPLAY:
        CrashDiag::SetPhase("ReplayFrame");
        result = ProcessReplayFrame();
        break;

    default:
        break;
    }

    CrashDiag::SetPhase("FrameComplete");
    CrashDiag::FrameEnd(world_update_arg.TimeStamp, GameScreenMode, DiagnosticLevelId());
    return result;
}

int RegisterNucleusClasses()
{
    ypa_log__ypa_general_log();
    init_d3dlog();
    init_dinputlog();

    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_nucleus>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_rsrc>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_bitmap>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_skeleton>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ilbm>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_sklt>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ade>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_area>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_base>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_bmpanim>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_amesh>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_particle>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_embed>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_idev>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_itimer>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_sample>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_wav>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_button>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_network>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_winp>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_wintimer>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_windp>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypaworld>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypabact>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypatank>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_yparobo>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypamissile>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypaflyer>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypacar>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypaufo>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_ypagun>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_3ds>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_image>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_Obj3D>() );

    return 1;
}

namespace
{

void DeinitEngines()
{
    if ( tformInited )
        TF::Engine.Deinit();
    if ( inputInited )
        Input::Engine.Deinit();
    // Input deinit sends a final zero-vibration command. Keep Steam Input
    // alive until that controller state has been cleared.
    Steam::ApiLoader::Instance.Shutdown();
    if ( audioInited )
        SFXEngine::SFXe.deinit();

    ypa_log_out("Nucleus shutdown:\n");
}

// Registers the Nucleus classes and starts the audio, input and transform engines.
bool InitEngines()
{
    ypaworld = nullptr;
    GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
    userdata.clear();
    input_states = TInputState();
    world_update_arg = base_64arg();

    RegisterNucleusClasses();

    Common::Env.AddGlobalIniKey("gfx.display  = win3d.class");
    Common::Env.AddGlobalIniKey("gfx.display2 = windd.class");
    Common::Env.AddGlobalIniKey("gfx.engine     = gfx.engine");
    Common::Env.AddGlobalIniKey("tform.engine   = tform_ng.engine");
    Common::Env.AddGlobalIniKey("input.engine   = input.engine");
    Common::Env.AddGlobalIniKey("input.wimp     = winp");
    Common::Env.AddGlobalIniKey("input.keyboard = winp");
    Common::Env.AddGlobalIniKey("input.slider[10] = winp:mousex");
    Common::Env.AddGlobalIniKey("input.slider[11] = winp:mousey");
    Common::Env.AddGlobalIniKey("input.slider[12] = winp:joyx winp:joyrudder");
    Common::Env.AddGlobalIniKey("input.slider[13] = winp:joyy");
    Common::Env.AddGlobalIniKey("input.slider[14] = winp:joythrottle");
    Common::Env.AddGlobalIniKey("input.slider[15] = winp:joyhatx");
    Common::Env.AddGlobalIniKey("input.slider[16] = winp:joyhaty");
    Common::Env.AddGlobalIniKey("input.button[16] = winp:joyb0");
    Common::Env.AddGlobalIniKey("input.button[17] = winp:joyb1");
    Common::Env.AddGlobalIniKey("input.button[18] = winp:joyb2");
    Common::Env.AddGlobalIniKey("input.button[19] = winp:joyb3");
    Common::Env.AddGlobalIniKey("input.button[20] = winp:joyb4");
    Common::Env.AddGlobalIniKey("input.button[21] = winp:joyb5");
    Common::Env.AddGlobalIniKey("input.button[22] = winp:joyb6");
    Common::Env.AddGlobalIniKey("input.button[23] = winp:joyb7");

    audioInited = SFXEngine::SFXe.init();
    inputInited = Input::Engine.Init();
    tformInited = TF::Engine.Init();

    Steam::ApiLoader::Instance.Initialize();
    Input::Actions.AddBackend(&Input::SteamBackend());

    const char *failed = !audioInited ? "audio" : !tformInited ? "tform" : !inputInited ? "input" : nullptr;
    if ( failed )
    {
        ypa_log_out("Couldn't open %s engine!\n", failed);
        DeinitEngines();
        return false;
    }

    return true;
}

// Reads the default player from env:user.def and loads that player's settings
// (SDU7 when the file or the player is missing).
bool LoadDefaultUserSettings()
{
    std::string settingsFileName = "sdu7/user.txt";
    userdata.UserName = "SDU7";

    if ( FSMgr::FileHandle *userDef = uaOpenFileAlloc("env:user.def", "r") )
    {
        std::string line;
        userDef->ReadLine(&line);
        delete userDef;

        if ( FSMgr::FileHandle *userTxt = uaOpenFileAlloc(fmt::sprintf("save:%s/user.txt", line), "r") )
        {
            delete userTxt;
            userdata.UserName = line;
            settingsFileName = fmt::sprintf("%s/user.txt", line);
        }
        else
        {
            ypa_log_out("Warning: default user file doesn't exist (save:%s/user.txt)\n", line.c_str());
        }
    }
    else
    {
        ypa_log_out("Warning: No default user set\n");
    }

    userdata.diskListActiveElement = -1;

    int element = 1;
    for ( const auto &profile : userdata.profiles )
    {
        if ( !StriCmp(profile.name, userdata.UserName) )
        {
            userdata.diskListActiveElement = element;
            break;
        }
        element++;
    }

    return ypaworld->LoadSettings(settingsFileName,
                                  userdata.UserName,
                                  World::SDF_ALL,
                                  true, !MenuSmokeEnabled()) != 0;
}

void ReadSnapsDir()
{
    FSMgr::DirIter dir = uaOpenDir("env:snaps/");
    if ( !dir )
        return;

    FSMgr::iNode *entry;
    while ( dir.getNext(&entry) )
    {
        if ( entry->getType() == FSMgr::iNode::NTYPE_FILE && !StriCmp(entry->getName().substr(0, 4), "demo") )
            userdata.snaps.push_back( fmt::sprintf("env:snaps/%s", entry->getName()) );
    }
}

// Creates the world object and opens the game shell on the default player.
bool InitWorld()
{
    // The original 1998 build date: the world class and save files expect it.
    const std::string buildDate = "Jul 09 1998  23:52:47";

    ypaworld = Nucleus::CInit<NC_STACK_ypaworld>( { {NC_STACK_ypaworld::YW_ATT_BUILD_DATE, buildDate} } );
    Gui::UA::yw = ypaworld;

    if ( !ypaworld )
    {
        ypa_log_out("Unable to init ypaworld.class\n");
        return false;
    }
    if ( !ypaworld->InitGameShell(&userdata) )
    {
        ypa_log_out("Unable to init shell structure\n");
        return false;
    }
    if ( !LoadDefaultUserSettings() )
    {
        ypa_log_out("Unable to init game with default settings\n");
        return false;
    }
    if (MenuSmokeEnabled())
    {
        ypaworld->PrepareMenuSmokeResolution();
        if (!ypaworld->SetGameShellVideoMode(true))
            return false;
    }
    if ( !userdata.HasInited && !ypaworld->OpenGameShell() )
    {
        ypa_log_out("Error: Unable to open Gameshell\n");
        return false;
    }

    GameScreenMode = GAME_SCREEN_MODE_MENU;
    ReadSnapsDir();
    return true;
}

bool InitGame()
{
    if ( !InitEngines() )
        return false;

    if ( InitWorld() )
        return true;

    DeinitEngines();
    return false;
}

void ShutdownWorld()
{
    if ( ypaworld )
    {
        if ( GameScreenMode == GAME_SCREEN_MODE_GAME )
        {
            ypaworld->DeleteLevel();
            ypaworld->DeinitGameShell();
        }
        else if ( GameScreenMode == GAME_SCREEN_MODE_MENU )
        {
            if (!MenuSmokeEnabled())
                userdata.SaveSettings();
            ypaworld->CloseGameShell();
            ypaworld->DeinitGameShell();
        }

        ypaworld->Delete();
    }

    DeinitEngines();
}

} // namespace

#ifndef _WIN32
static std::string ResolveNativeGameRoot()
{
    char exe[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof(exe) - 1);
    if (n <= 0)
        return std::string();
    exe[n] = '\0';
    std::string path(exe);
    std::string::size_type slash = path.find_last_of('/');
    if (slash == std::string::npos || slash == 0)
        return std::string();
    std::string dir = path.substr(0, slash);
    std::string::size_type slash2 = dir.find_last_of('/');
    std::string leaf = (slash2 == std::string::npos) ? dir : dir.substr(slash2 + 1);
    // Overlay install layout is <game-root>/bin/OpenNeoUA.
    if (leaf == "bin" && slash2 != std::string::npos)
        return dir.substr(0, slash2);
    return dir;
}
#endif

static bool IsSteamCompatVerb(const char *arg)
{
    return arg && (std::strcmp(arg, "waitforexitandrun") == 0 || std::strcmp(arg, "run") == 0);
}

int main(int argc, char *argv[])
{
    const int dumpWriter = CrashDiag::RunDumpWriter(argc, argv);
    if (dumpWriter >= 0)
        return dumpWriter;
    // Steam's Stop command may terminate the AppImage through SIGTERM rather
    // than an SDL_QUIT event. Keep the handler async-signal-safe and let the
    // normal loop perform engine/Steam shutdown.
    std::signal(SIGTERM, HandleQuitSignal);
    std::signal(SIGINT, HandleQuitSignal);

    System::AddCmdLine(argv[0] ? argv[0] : "");
    int argi = 1;
    while (argi < argc && IsSteamCompatVerb(argv[argi]))
        argi++;
    for (int i = argi; i < argc; ++i)
        System::AddCmdLine(argv[i] ? argv[i] : "");

    System::IniConf::Init();
    std::string assetRoot;
    std::string userRoot;
    const std::vector<std::string> &cmdl = System::GetCmdLineArray();
    int32_t assetArg = System::FindCmdLineArg("--asset-root");
    int32_t userArg = System::FindCmdLineArg("--user-dir");
    if (assetArg >= 0 && assetArg + 1 < (int32_t)cmdl.size())
        assetRoot = cmdl[assetArg + 1];
    else if (assetArg >= 0)
    {
        ypa_log_out("--asset-root requires a path\n");
        return 2;
    }
    if (userArg >= 0 && userArg + 1 < (int32_t)cmdl.size())
        userRoot = cmdl[userArg + 1];
    else if (userArg >= 0)
    {
        ypa_log_out("--user-dir requires a path\n");
        return 2;
    }
    if (assetArg >= 0 && assetRoot.empty())
    {
        ypa_log_out("--asset-root requires a non-empty path\n");
        return 2;
    }
    if (userArg >= 0 && userRoot.empty())
    {
        ypa_log_out("--user-dir requires a non-empty path\n");
        return 2;
    }
    if (!assetRoot.empty())
    {
        if (userRoot.empty())
        {
            const char *xdgData = getenv("XDG_DATA_HOME");
            const char *home = getenv("HOME");
            if (xdgData && xdgData[0])
                userRoot = std::string(xdgData) + "/OpenNeoUA";
            else if (home && home[0])
                userRoot = std::string(home) + "/.local/share/OpenNeoUA";
            else
                userRoot = "OpenNeoUA-user";
        }
        FSMgr::iDir::setRoots(assetRoot, userRoot);
    }
    else if (!userRoot.empty())
    {
        FSMgr::iDir::setRoots(".", userRoot);
    }
    else
    {
#ifndef _WIN32
        std::string gameRoot = ResolveNativeGameRoot();
        if (!gameRoot.empty())
        {
            if (chdir(gameRoot.c_str()) != 0)
                ypa_log_out("unable to chdir to game root %s\n", gameRoot.c_str());
            FSMgr::iDir::setBaseDir(gameRoot);
        }
        else
            FSMgr::iDir::setBaseDir("");
#else
        FSMgr::iDir::setBaseDir("");
#endif
    }

    // OpenNeoUA.ini is required: it carries the shipped configuration of the game.
    {
        const std::string openNeoUAIni = uaDataFirstOpenNeoUAIniPath();
        if ( !std::ifstream(openNeoUAIni).good() )
        {
            const std::string message = "OpenNeoUA.ini was not found (" + openNeoUAIni +
                                        ").\nPut it in the Data folder and start the game again.";
            SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "OpenNeoUA", message.c_str(), nullptr);
            return 1;
        }
    }

    System::IniConf::ReadFromNucleusIni();
    const int32_t envArgument = System::FindCmdLineArg("-env");
    if (envArgument >= 0 && envArgument + 1 < static_cast<int32_t>(cmdl.size()))
        Common::Env.SetPrefix("env", cmdl[envArgument + 1]);
    CrashDiag::Init(System::IniConf::GameCrashDiagnostics.Get<bool>(),
                    std::string("OpenNeoUA ") + __DATE__ + " " + __TIME__);
    CrashDiag::SetPhase("SystemInit");
    System::Init(!System::IniConf::GfxVBO.Get<bool>());

    CrashDiag::SetPhase("GraphicsInit");
    GFX::Engine.Init();
    CrashDiag::SetPhase("MovieInit");
    System::Movie.Init();
    Gui::UA::Init();

    CrashDiag::SetPhase("GameInit");
    if ( !InitGame() )
    {
        CrashDiag::Breadcrumb("STARTUP", "game initialization failed");
        CrashDiag::Shutdown();
        return MenuSmokeEnabled() ? 2 : 0;
    }

    System::IniConf::ReadFromNucleusIni();

    CrashDiag::Breadcrumb("STARTUP", "runtime initialized");

    // Cache global runtime configuration after Nucleus.ini is parsed.
    World::BlackSectTint::Init();
    World::EnergyFX::Init();

    Gui::Root::Instance.SetHwCompose(true);
    ypaworld->LoadGuiFonts();
    ypaworld->CreateNewGuiElements();

    if (MenuSmokeEnabled())
    {
        bool smokePassed = RunMenuSmoke();
        CrashDiag::DisarmWatchdog();
        CrashDiag::SetPhase("Shutdown");
        ypaworld->DeleteNewGuiElements();
        ShutdownWorld();
        Gui::UA::Deinit();
        CrashDiag::Shutdown();
        System::Deinit();
        if (smokePassed && !MenuSmokeWriteReportAfterShutdown())
            smokePassed = false;
        return smokePassed ? 0 : 2;
    }


    while ( !QuitSignalReceived && ProcessNextFrame() && !System::ProcessEvents() )
        System::Frames.EndFrame();

    CrashDiag::DisarmWatchdog();
    CrashDiag::SetPhase("Shutdown");
    ypaworld->DeleteNewGuiElements();

    ShutdownWorld();
    Gui::UA::Deinit();

    System::Deinit();
    CrashDiag::Shutdown();

    return 0;
}
