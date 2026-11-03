// Asset-backed menu smoke driver; invoked only with --menu-smoke-dir.
#include "menu_smoke.h"
#include "common/includes.h"
#include "common/utils.h"
#include "system/system.h"
#include "gui/button.h"
#include "gui/uawidgets.h"
#include "platform/winp.h"

#include <cerrno>
#include <fstream>
#include <sstream>
#include <sys/stat.h>


namespace MenuSmoke
{
bool Enabled()
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

static bool MenuSmokeRenderFrames(int count, int *frameCount, int (*processNextFrame)())
{
    for (int i = 0; i < count; ++i)
    {
        if (!processNextFrame())
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

bool WriteReportAfterShutdown()
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

bool Run(UserData &userdata, int (*processNextFrame)())
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

    const int optionsIndex = userdata.titel_button->GetIndexByID(UIWidgets::MAIN_MENU_WIDGET_IDS::BTN_OPTIONS);
    if (optionsIndex < 0 || optionsIndex >= (int)userdata.titel_button->field_d8.size() ||
        optionsIndex >= (int)userdata.titel_button->buttons.size())
    {
        ypa_log_out("menu smoke: Options widget was not created\n");
        return false;
    }
    const NC_STACK_button::button_str2 &options = userdata.titel_button->field_d8[optionsIndex];
    const ButtonBox &bounds = userdata.titel_button->buttons[optionsIndex];
    if (bounds.w <= 0 || bounds.h <= 0 || options.width <= 0)
    {
        ypa_log_out("menu smoke: Options widget has empty bounds\n");
        return false;
    }

    int frameCount = 0;
    if (!MenuSmokeRenderFrames(3, &frameCount, processNextFrame))
        return false;
    GFX::Engine.SaveScreenshot("env:snaps/menu-title-before");

    const Common::Point physical = GFX::Engine.GetScreenSize();
    const Common::Point logical = GFX::Engine.GetVirtualUIResolution();
    if (physical.x != 1280 || physical.y != 800 || logical.x <= 0 || logical.y <= 0)
    {
        ypa_log_out("menu smoke: renderer did not select 1280x800\n");
        return false;
    }
    const int clickX = (bounds.x + bounds.w / 2) * physical.x / logical.x;
    const int clickY = (bounds.y + bounds.h / 2) * physical.y / logical.y;
    if (!MenuSmokePushMouse(SDL_MOUSEMOTION, clickX, clickY) || System::ProcessEvents())
        return false;
    if (!MenuSmokePushMouse(SDL_MOUSEBUTTONDOWN, clickX, clickY, SDL_BUTTON_LEFT) || System::ProcessEvents())
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount, processNextFrame))
        return false;
    if (!MenuSmokePushMouse(SDL_MOUSEBUTTONUP, clickX, clickY, SDL_BUTTON_LEFT) || System::ProcessEvents())
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount, processNextFrame) || userdata.EnvMode != ENVMODE_SETTINGS)
    {
        ypa_log_out("menu smoke: normal Options click did not enter settings\n");
        return false;
    }
    if (!MenuSmokeRenderFrames(2, &frameCount, processNextFrame))
        return false;
    GFX::Engine.SaveScreenshot("env:snaps/menu-options");

    if (!MenuSmokePushEscape() || System::ProcessEvents())
        return false;
    if (!MenuSmokeRenderFrames(1, &frameCount, processNextFrame) || userdata.EnvMode != ENVMODE_TITLE)
    {
        ypa_log_out("menu smoke: normal Escape did not return to title\n");
        return false;
    }
    if (!MenuSmokeRenderFrames(2, &frameCount, processNextFrame))
        return false;
    GFX::Engine.SaveScreenshot("env:snaps/menu-title-after");

    const char *renderer = (const char *)glGetString(GL_RENDERER);
    const char *version = (const char *)glGetString(GL_VERSION);
    const char *vendor = (const char *)glGetString(GL_VENDOR);
    const std::string provenance = MenuSmokeProvenance();
    const std::string isoSha = MenuSmokeProvenanceValue(provenance, "iso_sha256");
    const std::string sourceId = MenuSmokeProvenanceValue(provenance, "source_id");

    std::string report;
    report += "{\n  \"version\": 1,\n";
    report += "  \"milestones\": [\n";
    report += "    {\"event\": \"title-before\", \"mode\": \"ENVMODE_TITLE\", \"frames\": 3},\n";
    report += "    {\"event\": \"options\", \"mode\": \"ENVMODE_SETTINGS\", \"frames\": 2},\n";
    report += "    {\"event\": \"title-after\", \"mode\": \"ENVMODE_TITLE\", \"frames\": 2}\n  ],\n";
    report += fmt::sprintf("  \"frame_count\": %d,\n  \"title_frames\": 5,\n  \"options_frames\": 2,\n", frameCount);
    report += fmt::sprintf("  \"resolution\": [%d, %d],\n", physical.x, physical.y);
    report += "  \"renderer\": {\"gl_renderer\": \"" + MenuSmokeJsonEscape(renderer ? renderer : "") +
             "\", \"gl_version\": \"" + MenuSmokeJsonEscape(version ? version : "") +
             "\", \"gl_vendor\": \"" + MenuSmokeJsonEscape(vendor ? vendor : "") + "\"},\n";
    report += "  \"final_mode\": \"ENVMODE_TITLE\",\n";
    report += "  \"asset_provenance\": {\"asset_root\": \"" + MenuSmokeJsonEscape(FSMgr::iDir::getAssetRoot()) +
             "\", \"source_id\": \"" + MenuSmokeJsonEscape(sourceId) +
             "\", \"iso_sha256\": \"" + MenuSmokeJsonEscape(isoSha) + "\"}\n}\n";
    g_menuSmokeReport = report;
    g_menuSmokeReportPath = smokeDir + "/menu-smoke.json";
    return true;
}
}
