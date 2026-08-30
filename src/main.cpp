#define GLOBAL
#include "system/fsmgr.h"
#include "system/system.h"
#include "env.h"

#include "includes.h"
#include "system/gfx.h"
#include "system/inpt.h"
#include "system/action_input.h"
#include "system/action_backend.h"
#include "system/steam_api_loader.h"
#include "winp.h"
#include "wintimer.h"

#include "ade.h"
#include "area.h"
#include "amesh.h"
#include "bitmap.h"
#include "bmpAnm.h"
#include "base.h"
#include "ilbm.h"
#include "particle.h"
#include "embed.h"
#include "network.h"
#include "windp.h"
#include "ypabact.h"
#include "ypatank.h"
#include "ypacar.h"
#include "ypaflyer.h"
#include "yparobo.h"
#include "ypaufo.h"
#include "3ds.h"
#include "image.h"


#include "font.h"
#include "yw.h"

#include "button.h"



#include "gui/widget.h"
#include "gui/uawidgets.h"
#include "gui/uamsgbox.h"
#include "gui/uaempty.h"
#include "system/movie.h"
#include "system/inivals.h"
#include "system/steam_api_loader.h"
#include "world/blacksecttint.h"
#include "world/energyfx.h"
#include "obj3d.h"
#include "crashdiag.h"

#include <fstream>
#include <sstream>
#include <sys/stat.h>
#include <cerrno>
#include <cstring>
#ifndef _WIN32
#include <limits.h>
#include <unistd.h>
#endif

int ProcessNextFrame();
extern UserData userdata;

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
    NC_STACK_winp::_mPos = Common::Point(x, y);
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

    if (!MenuSmokePushMouse(SDL_MOUSEBUTTONDOWN, physicalClickX, physicalClickY, SDL_BUTTON_LEFT) || System::ProcessEvents())
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount))
        return false;
    if (!MenuSmokePushMouse(SDL_MOUSEBUTTONUP, physicalClickX, physicalClickY, SDL_BUTTON_LEFT) || System::ProcessEvents())
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount))
        return false;

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


int dword_513638 = 0;
int dword_51362C = 0;
int dword_513630 = 0;
std::string buildDate;

int tform_inited = 0;
int audio_inited = 0;
int input_inited = 0;

UserData userdata;

static int DiagnosticLevelId()
{
    return ypaworld ? ypaworld->GetLevelInfo().LevelID : -1;
}

int ProcessGameplayFrame()
{
    CrashDiag::SetPhase("GameplayWorldProcess");
    ypaworld->Process(&world_update_arg);
    CrashDiag::SetPhase("GameplayStateTransition");

    const TLevelInfo &levelInfo = ypaworld->GetLevelInfo();

    switch( levelInfo.State )
    {
    case TLevelInfo::STATE_QUIT_GAME:
        CrashDiag::Breadcrumb("LEVEL", "quit requested level=%d", levelInfo.LevelID);
        return 0;

    case TLevelInfo::STATE_COMPLETED:
    case TLevelInfo::STATE_ABORTED:
    {
        CrashDiag::Breadcrumb("LEVEL", "leave level=%d state=%d", levelInfo.LevelID, levelInfo.State);
        CrashDiag::SetPhase("DeleteLevel");
        ypaworld->DeleteLevel();

        if ( dword_513638 || levelInfo.State == TLevelInfo::STATE_ABORTED )
        {
            if ( !ypaworld->LoadSettings("settings.tmp",
                                         userdata.UserName,
                                         (World::SDF_BUDDY | World::SDF_PROTO | World::SDF_USER),
                                         false))
                return 0;

            dword_513638 = 0;
        }

        int v0 = 1;

        if ( userdata.remoteMode )
            v0 = 0;

        if ( userdata.EnvMode == ENVMODE_NETPLAY )
        {
            userdata.returnToTitle = true;
            userdata.EnvMode = ENVMODE_SINGLEPLAY;
        }
        else
        {
            userdata.returnToTitle = false;
        }

        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
        world_update_arg.TimeStamp = 0;

        userdata.lastInputEvent = 0;
        userdata.GameIsOver = true;

        if ( ypaworld->OpenGameShell() )
        {
            GameScreenMode = GAME_SCREEN_MODE_MENU;
            Input::Engine.QueryInput(&input_states);

            if (!v0)
                return 0;
        }
        else
        {
            ypa_log_out("GameShell-Error!!!\n");
            ypaworld->DeinitGameShell();
            return 0;
        }
    }
    break;

    case TLevelInfo::STATE_RESTART:
    {
        CrashDiag::Breadcrumb("LEVEL", "restart level=%d", levelInfo.LevelID);
        CrashDiag::SetPhase("RestartDeleteLevel");
        ypaworld->DeleteLevel();

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.rst", userdata.UserName, levelInfo.LevelID) ) )
        {
            ypa_log_out("Warning, load error\n");
        }

        Input::Engine.QueryInput(&input_states);
    }
    break;

    case TLevelInfo::STATE_SAVE:
    {
        if ( !ypaworld->SaveGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
        {
            ypa_log_out("Warning, Save error\n");
        }

        Input::Engine.QueryInput(&input_states);
    }
    break;

    case TLevelInfo::STATE_LOAD:
    {
        CrashDiag::Breadcrumb("LEVEL", "load save from level=%d", levelInfo.LevelID);
        CrashDiag::SetPhase("LoadDeleteLevel");
        ypaworld->DeleteLevel();

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
        {
            ypa_log_out("Warning, load error\n");
        }

        Input::Engine.QueryInput(&input_states);
    }
    break;

    default:
        break;
    }

    return 1;
}

std::string sub_4107A0(uint32_t a1)
{
    if ( userdata.snaps.empty() )
        return std::string();

    int v2 = a1 % userdata.snaps.size();

    if ( dword_51362C == v2 )
    {
        if ( v2 )
        {
            v2 = v2 - 1;
        }
        else if ( (userdata.snaps.size() - 1) > 0 )
        {
            v2 = 1;
        }
    }

    dword_51362C = v2;
    return userdata.snaps[v2];
}

int sb_0x411324__sub2__sub0(base_64arg *arg)
{
    if ( (userdata.p_YW->_replayPlayer->field_74 - 3) <= userdata.p_YW->_replayPlayer->frame_id  &&  dword_513630 )
    {
        ypaworld->ypaworld_func164();

        if ( !ypaworld->ypaworld_func162( sub_4107A0(arg->TimeStamp) ) )
        {
            GameScreenMode = GAME_SCREEN_MODE_MENU;

            Input::Engine.QueryInput(&input_states);

            return 0;
        }

        dword_513630 = 1;
        GameScreenMode = GAME_SCREEN_MODE_REPLAY;
    }

    ypaworld->ypaworld_func163(arg);

    yw_arg165 arg165;
    arg165.field_0 = 0;
    arg165.frame = 0;

    int cont_play = 1;

    if ( arg->field_8->KbdLastHit == Input::KC_N )
    {
        arg165.field_0 = 4;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_P )
    {
        arg165.field_0 = 2;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_R )
    {
        arg165.field_0 = 3;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_S )
    {
        arg165.field_0 = 1;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_V )
    {
        arg165.frame = -10;
        arg165.field_0 = 7;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_B )
    {
        arg165.field_0 = 5;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_M )
    {
        arg165.frame = 10;
        arg165.field_0 = 7;
    }
    else if ( arg->field_8->KbdLastHit == Input::KC_SPACE || arg->field_8->KbdLastHit == Input::KC_ESCAPE )
    {
        cont_play = 0;
    }

    if ( arg165.field_0 )
        ypaworld->ypaworld_func165(&arg165);

    return cont_play;
}

int ProcessReplayFrame()
{
    if ( !sb_0x411324__sub2__sub0(&world_update_arg) )
    {
        ypaworld->ypaworld_func164();

        if ( dword_513638 )
        {
            if ( !ypaworld->LoadSettings("settings.tmp",
                                         userdata.UserName,
                                         (World::SDF_BUDDY | World::SDF_PROTO | World::SDF_USER),
                                         false) )
                return 0;

            dword_513638 = 0;
        }

        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
        world_update_arg.TimeStamp = 0;
        userdata.lastInputEvent = 0;

        if ( !ypaworld->OpenGameShell() )
        {
            ypa_log_out("GameShell-Error!!!\n");
            ypaworld->DeinitGameShell();

            return 0;
        }

        userdata.p_YW->_levelInfo.State = TLevelInfo::STATE_MENU;

        GameScreenMode = GAME_SCREEN_MODE_MENU;

        input_states = TInputState();

        Input::Engine.QueryInput(&input_states);
    }
    return 1;
}

int ProcessMenuFrame()
{
    userdata.GlobalTime = world_update_arg.TimeStamp;
    userdata.DTime = world_update_arg.DTime;
    userdata.Input = &input_states;

    ypaworld->ProcessGameShell();

    if ( userdata.envAction.action == EnvAction::ACTION_QUIT )
        return 0;
    else if ( userdata.envAction.action == EnvAction::ACTION_PLAY )
    {
        CrashDiag::Breadcrumb("LEVEL", "start requested level=%d", userdata.envAction.params[0]);
        CrashDiag::SetPhase("LevelStart");
        userdata.SaveSettings();
        ypaworld->CloseGameShell();

        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;

        if ( !userdata.SaveBuildProtoState() )
            return 0;

        yw_arg161 v22;
        v22.lvlID = userdata.envAction.params[0];
        v22.field_4 = 0;

        if ( !ypaworld->ypaworld_func183(&v22) )
        {
            ypa_log_out("Sorry, unable to init this level!\n");

            ypaworld->DeinitGameShell();
            return 0;
        }
        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    else if ( userdata.envAction.action == EnvAction::ACTION_LOAD )
    {
        CrashDiag::Breadcrumb("LEVEL", "load save requested");
        CrashDiag::SetPhase("LevelLoad");
        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;

        const TLevelInfo &a4 = ypaworld->GetLevelInfo();

        userdata.SaveSettings();
        ypaworld->CloseGameShell();

        if ( !userdata.SaveBuildProtoState() )
            return 0;

        if ( !ypaworld->LoadGame( fmt::sprintf("save:%s/%d.sgm", userdata.UserName, 0) ) )
        {
            ypa_log_out("Error while loading level (level %d, User %s\n", a4.LevelID, userdata.UserName.c_str());

            ypaworld->DeinitGameShell();
            return 0;
        }
        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    else if ( userdata.envAction.action == EnvAction::ACTION_NETPLAY )
    {
        CrashDiag::Breadcrumb("LEVEL", "netplay start requested level=%d", userdata.envAction.params[0]);
        CrashDiag::SetPhase("NetLevelStart");
        userdata.SaveSettings();

        if ( !userdata.SaveBuildProtoState() )
            return 0;

        dword_513638 = 1;

        ypaworld->CloseGameShell();

        yw_arg161 v22;
        v22.lvlID = userdata.envAction.params[0];
        v22.field_4 = 0;

        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;

        if ( !ypaworld->ypaworld_func179(&v22) )
        {
            ypa_log_out("Sorry, unable to init this level for network!\n");
            ypaworld->DeinitGameShell();

            return 0;
        }

        GameScreenMode = GAME_SCREEN_MODE_GAME;
        Input::Engine.QueryInput(&input_states);
    }
    else if ( userdata.envAction.action == EnvAction::ACTION_REPLAY )
    {
        std::string repname = sub_4107A0(world_update_arg.TimeStamp);
        if ( repname.empty() )
        {
            userdata.lastInputEvent = world_update_arg.TimeStamp;
            return 1;
        }

        if ( !userdata.SaveBuildProtoState() )
            return 0;

        dword_513638 = 1;

        ypaworld->CloseGameShell();

        GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;

        if ( ypaworld->ypaworld_func162(repname) )
        {
            dword_513630 = 1;
            GameScreenMode = GAME_SCREEN_MODE_REPLAY;
        }
        else
        {
            ypa_log_out("Sorry, unable to init player!\n");
            world_update_arg.TimeStamp = 0;
            userdata.lastInputEvent = 0;

            if ( !ypaworld->OpenGameShell() )
            {
                ypa_log_out("GameShell-Error!!!\n");
                ypaworld->DeinitGameShell();
                return 0;
            }

            GameScreenMode = GAME_SCREEN_MODE_MENU;
        }

        Input::Engine.QueryInput(&input_states);
    }

    return 1;
}


// OpenNeoUA frame-rate independent simulation timing is always active in gameplay.
//
// The game clock runs at 1024 units per second and the engine does exactly one
// simulation step per rendered frame with DTime = measured frame delta + 1
// (the historical Period++ bias). That couples gameplay speed to gfx.maxfps:
// every rendered frame adds one extra clock unit, so 120/240 fps plays visibly
// faster than 60 fps (~+17% at 240).
//
// Since almost all gameplay already scales by frameTime, feeding the TRUE
// measured delta (no bias) makes the simulation advance in real time at any
// frame cap, with native per-frame fluidity. Menu, replay and netplay keep the
// legacy biased timing untouched.
static bool FrameRateIndependentActive()
{
    if ( GameScreenMode != GAME_SCREEN_MODE_GAME || !ypaworld )
        return false;

    // Netplay keeps its own flush/sync timing assumptions.
    if ( ypaworld->_isNetGame )
        return false;

    return true;
}

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

    if ( FrameRateIndependentActive() )
    {
        // True measured delta, no +1 bias. Floor to 1 (itimer can round to 0
        // above ~1024 fps and _FPS divides by DTime), clamp to ~250ms so an
        // alt-tab or loading stall cannot become one giant physics step.
        if ( input_states.Period < 1 )
            input_states.Period = 1;
        else if ( input_states.Period > 256 )
            input_states.Period = 256;
    }
    else
    {
        input_states.Period++;
    }

    world_update_arg.DTime = input_states.Period;
    world_update_arg.field_8 = &input_states;
    world_update_arg.TimeStamp += input_states.Period;

    if (ypaworld->_mouseGrabbed)
        System::SetReleativeMouse(true);
    else
        System::SetReleativeMouse(false);

    CrashDiag::SetPhase("GuiTimers");
    Gui::Root::Instance.TimersUpdate(input_states.Period);

    int result = 1;
    if ( GameScreenMode == GAME_SCREEN_MODE_MENU )
    {
        CrashDiag::SetPhase("MenuFrame");
        result = ProcessMenuFrame();
    }
    else if ( GameScreenMode == GAME_SCREEN_MODE_GAME )
    {
        CrashDiag::SetPhase("GameplayFrame");
        result = ProcessGameplayFrame();
    }
    else if ( GameScreenMode == GAME_SCREEN_MODE_REPLAY )
    {
        CrashDiag::SetPhase("ReplayFrame");
        result = ProcessReplayFrame();
    }

    CrashDiag::SetPhase("FrameComplete");
    CrashDiag::FrameEnd(world_update_arg.TimeStamp, GameScreenMode, DiagnosticLevelId());
    return result;
}

int init_classesLists_and_variables()
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
    //Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_input>() );
    Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_itimer>() );
    //Nucleus::ClassList.push_back( Nucleus::MakeClassDescr<NC_STACK_iwimp>() );
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

void deinit_globl_engines()
{
    Steam::ApiLoader::Instance.Shutdown();

    if ( tform_inited )
        TF::Engine.Deinit();
    if ( input_inited )
        Input::Engine.Deinit();
    if ( audio_inited )
        SFXEngine::SFXe.deinit();

    ypa_log_out("Nucleus shutdown:\n");
}

int WinMain__sub0__sub0()
{
    ypaworld = 0;
    GameScreenMode = GAME_SCREEN_MODE_UNKNOWN;
    userdata.clear();
    input_states = TInputState();
    world_update_arg = base_64arg();

    if ( !init_classesLists_and_variables() )
    {
        sub_412038("Couldn't open Nucleus!");
        deinit_globl_engines();
        return 0;
    }
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

    audio_inited = SFXEngine::SFXe.init();
    input_inited = Input::Engine.Init();
    tform_inited = TF::Engine.Init();

    // OpenNeoUA: optional and non-fatal. The log line it emits is the primary
    // on-device diagnostic for Steam Input, including the app-id mismatch that
    // a non-Steam shortcut causes.
    Steam::ApiLoader::Instance.Initialize();
    Input::Actions.AddBackend(&Input::SteamBackend());

    if ( !audio_inited )
    {
        sub_412038("Couldn't open audio engine!");
        deinit_globl_engines();
        return 0;
    }

    if ( !tform_inited )
    {
        sub_412038("Couldn't open tform engine!");
        deinit_globl_engines();
        return 0;
    }
    if ( !input_inited )
    {
        sub_412038("Couldn't open input engine!");
        deinit_globl_engines();
        return 0;
    }

    return 1;
}

int yw_initGameWithSettings()
{
    FSMgr::FileHandle *user_def = uaOpenFileAlloc("env:user.def", "r");

    std::string settingsFileName;

    if ( user_def )
    {
        std::string line;
        user_def->ReadLine(&line);

        settingsFileName = fmt::sprintf("save:%s/user.txt", line);

        FSMgr::FileHandle *user_txt = uaOpenFileAlloc(settingsFileName, "r");

        if ( user_txt )
        {
            delete user_txt;

            userdata.UserName = line;
            settingsFileName = fmt::sprintf("%s/user.txt", line);
        }
        else
        {
            ypa_log_out("Warning: default user file doesn't exist (%s)\n", settingsFileName.c_str());
            settingsFileName = fmt::sprintf("sdu7/user.txt");
            userdata.UserName = "SDU7";
        }

        delete user_def;
    }
    else
    {
        settingsFileName = fmt::sprintf("sdu7/user.txt");
        userdata.UserName = "SDU7";
        ypa_log_out("Warning: No default user set\n");
    }

    userdata.diskListActiveElement = -1;

    int v8 = 1;
    for ( ProfileList::iterator it = userdata.profiles.begin(); it != userdata.profiles.end(); it++ )
    {
        if ( !StriCmp(it->name, userdata.UserName) )
        {
            userdata.diskListActiveElement = v8;
            break;
        }

        v8++;
    }

    return ypaworld->LoadSettings(settingsFileName,
                                  userdata.UserName,
                                  World::SDF_ALL,
                                  true, !MenuSmokeEnabled()) != 0;
}

void ReadSnapsDir()
{
    FSMgr::DirIter dir = uaOpenDir("env:snaps/");

    if ( dir )
    {
        FSMgr::iNode *entr;
        while ( dir.getNext(&entr) )
        {
            if ( entr->getType() == FSMgr::iNode::NTYPE_FILE && !StriCmp(entr->getName().substr(0, 4), "demo") )
                userdata.snaps.push_back( fmt::sprintf("env:snaps/%s", entr->getName()) );
        }
    }
}

void sub_4113E8()
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

    deinit_globl_engines();
}

int WinMain__sub0__sub1()
{
    buildDate = "Jul 09 1998  23:52:47";
//    strcpy(buildDate, __DATE__);
//    strcat(buildDate, " ");
//    strcat(buildDate, __TIME__);

    ypaworld = Nucleus::CInit<NC_STACK_ypaworld>( { {NC_STACK_ypaworld::YW_ATT_BUILD_DATE, std::string(buildDate)} } );

    Gui::UA::yw = ypaworld;

    if ( !ypaworld )
    {
        ypa_log_out("Unable to init ypaworld.class\n");
        return 0;
    }
    if ( !ypaworld->InitGameShell(&userdata) )
    {
        ypa_log_out("Unable to init shell structure\n");
        return 0;
    }

    if ( !yw_initGameWithSettings() )
    {
        ypa_log_out("Unable to init game with default settings\n");
        return 0;
    }

    if (MenuSmokeEnabled())
    {
        ypaworld->PrepareMenuSmokeResolution();
        if (!ypaworld->SetGameShellVideoMode(true))
        {
            ypa_log_out("Unable to force 1280x800 menu smoke mode\n");
            return 0;
        }
    }

    const bool mustOpenGameShell = !userdata.HasInited;
    if ( mustOpenGameShell && !ypaworld->OpenGameShell())
    {
        ypa_log_out("Error: Unable to open Gameshell\n");
        return 0;
    }

    GameScreenMode = GAME_SCREEN_MODE_MENU;
    ReadSnapsDir();

    return 1;
}


int WinMain__sub0()
{
    if ( WinMain__sub0__sub0() )
    {
        std::vector<std::string> &cmdl = System::GetCmdLineArray();
        int32_t i = System::FindCmdLineArg("-env");
        if (i >= 0 && i + 1 < (int32_t)cmdl.size())
            Common::Env.SetPrefix("env", cmdl[i + 1]);

        if ( WinMain__sub0__sub1() )
            return 1;
        deinit_globl_engines();
    }

    return 0;
}

uint32_t maxTicks = 1000/60; // init on 60FPS

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

    System::IniConf::ReadFromNucleusIni();
    bool gfxVbo = System::IniConf::GfxVBO.Get<bool>();

    System::Init(!gfxVbo);

    GFX::Engine.Init();
    System::Movie.Init();

    Gui::UA::Init();

    if ( !WinMain__sub0() )
    {
        return MenuSmokeEnabled() ? 2 : 0;
    }

    System::IniConf::ReadFromNucleusIni();

    CrashDiag::Init(System::IniConf::GameCrashDiagnostics.Get<bool>(),
                    std::string("OpenNeoUA ") + __DATE__ + " " + __TIME__);
    CrashDiag::Breadcrumb("STARTUP", "runtime initialized");

    // OpenNeoUA: cache global runtime configuration after Nucleus.ini is parsed.
    World::BlackSectTint::Init();
    World::EnergyFX::Init();

    uint32_t ticks = 0;

    Gui::Root::Instance.SetHwCompose(true);
    ypaworld->LoadGuiFonts();
    ypaworld->CreateNewGuiElements();

    if (MenuSmokeEnabled())
    {
        bool smokePassed = RunMenuSmoke();
        CrashDiag::DisarmWatchdog();
        CrashDiag::SetPhase("Shutdown");
        ypaworld->DeleteNewGuiElements();
        sub_4113E8();
        Gui::UA::Deinit();
        CrashDiag::Shutdown();
        System::Deinit();
        if (smokePassed && !MenuSmokeWriteReportAfterShutdown())
            smokePassed = false;
        return smokePassed ? 0 : 2;
    }


    //Gui::Root::Instance.AddPortal( Common::Point(640, 480), Common::Rect(0, 0, 300, 300));

    // New gui test windows
    /*Gui::UAWindow *smpl = new Gui::UAWindow("Test1", Common::PointRect(100, 100, 200, 300),
        Gui::UAWindow::FLAG_WND_RESIZEABLE |
        Gui::UAWindow::FLAG_WND_VSCROLL |
        Gui::UAWindow::FLAG_WND_CLOSE );
    smpl->SetEnable(true);
    smpl->SetAlpha(190);

    Gui::Root::Instance.AddWidget(smpl);

    Gui::UAWindow *smpl2 = new Gui::UAWindow("Test2", Common::PointRect(0, 0, 50, 60),
        Gui::UAWindow::FLAG_WND_RESIZEABLE |
        Gui::UAWindow::FLAG_WND_VSCROLL |
        Gui::UAWindow::FLAG_WND_CLOSE |
        Gui::UAWindow::FLAG_WND_HELP |
        Gui::UAWindow::FLAG_WND_MAXM |
        Gui::UAWindow::FLAG_WND_HSCROLL);
    smpl2->SetEnable(true);*/
    //smpl2->SetAlpha(190);

    //scl->MoveTo(100, 100);
    //scl->ResizeWH(300, 360);

    //Gui::Root::Instance.AddWidgetPortal(0, smpl2);
    //Gui::Root::Instance.AddWidget(smpl2);
    //smpl->AddChild(smpl2);




//    int fps = 0;
//    uint32_t fpstick = SDL_GetTicks() + 1000;

    while ( true )
    {

        if (GFX::Engine.FpsMaxTicks == 0)
        {
            if ( !ProcessNextFrame() )
                break;

            if ( System::ProcessEvents() )
                break;
        }
        else
        {
            uint32_t curTick = SDL_GetTicks();

            if (curTick >= ticks)
            {
                if ( !ProcessNextFrame() )
                    break;

                if ( System::ProcessEvents() )
                    break;

                ticks = curTick;

                uint32_t diffTick = SDL_GetTicks() - curTick;

                if (diffTick < GFX::Engine.FpsMaxTicks)
                {
                    uint16_t delay = GFX::Engine.FpsMaxTicks - diffTick;
                    ticks += delay;
                    SDL_Delay(delay);
                }
            }
            else
                SDL_Delay(1);
        }

//        fps++;
//        if (SDL_GetTicks() > fpstick)
//        {
//            printf("fps %d\n", fps);
//            fpstick = SDL_GetTicks() + 1000;
//            fps = 0;
//        }

    }

    CrashDiag::DisarmWatchdog();
    CrashDiag::SetPhase("Shutdown");
    ypaworld->DeleteNewGuiElements();

    sub_4113E8();
    Gui::UA::Deinit();

    CrashDiag::Shutdown();
    System::Deinit();

    return 0;
}
