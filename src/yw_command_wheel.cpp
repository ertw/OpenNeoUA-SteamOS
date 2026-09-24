#include "yw_command_wheel.h"

#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "includes.h"
#include "font.h"
#include "locale/locale.h"
#include "lstvw.h"
#include "system/gfx.h"
#include "system/gamepad_util.h"
#include "system/inpt.h"
#include "ypabact.h"
#include "yw.h"
#include "yw_internal.h"

extern bzd bzda;
extern GuiList exit_menu;

namespace CommandWheel
{
namespace
{

enum SliceId
{
    SLICE_TO_HOST = 0,       // N
    SLICE_TO_COMM = 1,       // NE
    SLICE_NEXT_UNIT = 2,     // E
    SLICE_LAST_SEAT = 3,     // SE
    SLICE_TAKE_CONTROL = 4,  // S
    SLICE_AUTOPILOT = 5,     // SW
    SLICE_ANALYZER = 6,      // W
    SLICE_SET_COMM = 7,      // NW
};

struct Slot
{
    int Binding = 0;
    uint8_t Glyph = 0;
    int TooltipId = 0;
    bool Enabled = false;
};

constexpr float kSelectMag = 0.50f;
constexpr float kCancelMag = 0.35f;
constexpr float kStickyHalfWidth = 1.35f;
constexpr uint8_t kDiscOpacity = 180;
constexpr uint8_t kSelectedOpacity = 220;
constexpr uint8_t kDisabledOpacity = 110;

void BuildSlots(const NC_STACK_ypaworld *yw, Slot slots[kSliceCount])
{
    for ( int i = 0; i < kSliceCount; ++i )
        slots[i] = Slot();

    if ( !yw || !yw->_userUnit || !yw->_userRobo )
        return;

    const int commandMask = yw_GetCommandPanelMask(yw);
    const int nav = yw_ComputePlayerNavMask(yw);
    const bool unitAlive = yw->_userUnit->_status != BACT_STATUS_DEAD;
    const bool spectator = yw->IsSpectatorControlled();

    slots[SLICE_TO_HOST] = {
        World::INPUT_BIND_TO_HOST, 81,
        Locale::TIP_GUI_GOTOHS, !spectator && (nav & 0x10) != 0
    };

    slots[SLICE_TO_COMM] = {
        World::INPUT_BIND_TO_COMM, 82,
        Locale::TIP_GUI_GOTOCMDR, !spectator && (nav & 0x20) != 0
    };

    const bool showTurrets = !spectator && (nav & 0x40) != 0 &&
        bzda.field_8DC != 0 &&
        (yw->_userRobo == yw->_userUnit || yw->_playerInHSGun);
    slots[SLICE_NEXT_UNIT] = {
        World::INPUT_BIND_NEXT_UNIT,
        (uint8_t)(showTurrets ? 66 : 83),
        showTurrets ? Locale::TIP_GUI_GOINTOGUNS : Locale::TIP_GUI_NEXTUNIT,
        !spectator && (nav & 0x40) != 0
    };

    NC_STACK_ypabact *lastSeat = yw_GetLastSeatTarget(yw);
    slots[SLICE_LAST_SEAT] = {
        World::INPUT_BIND_LAST_SEAT, 84,
        0, !spectator && lastSeat != NULL && lastSeat != yw->_userUnit
    };

    slots[SLICE_TAKE_CONTROL] = {
        World::INPUT_BIND_CONTROL, 69,
        Locale::TIP_GUI_TAKECONTROL,
        !spectator && (commandMask & 8) != 0
    };

    slots[SLICE_AUTOPILOT] = {
        World::INPUT_BIND_AUTOPILOT, 70,
        0, !spectator && (commandMask & 0x20) != 0
    };

    slots[SLICE_ANALYZER] = {
        World::INPUT_BIND_ANALYZER, 63,
        Locale::TIP_ANALYZER, !spectator && unitAlive
    };

    slots[SLICE_SET_COMM] = {
        World::INPUT_BIND_SET_COMM, 82,
        0, !spectator && yw_CanSetCommander(yw)
    };
}

std::string SlotLabel(const NC_STACK_ypaworld *yw, const Slot &slot)
{
    if ( yw && yw->_GameShell && slot.Binding > 0 &&
         slot.Binding < World::INPUT_BIND_MAX &&
         !yw->_GameShell->InputConfigTitle[slot.Binding].empty() )
    {
        return yw->_GameShell->InputConfigTitle[slot.Binding];
    }

    if ( slot.TooltipId > 0 )
        return Locale::Text::Tooltip(slot.TooltipId);

    return std::string();
}

std::string SlotKeyHint(const NC_STACK_ypaworld *yw, const Slot &slot)
{
    if ( !yw || !yw->_GameShell || slot.Binding <= 0 ||
         slot.Binding >= World::INPUT_BIND_MAX )
        return std::string();

    const UserData::TInputConf &binding = yw->_GameShell->InputConfig[slot.Binding];
    if ( binding.Type != World::INPUT_BIND_TYPE_HOTKEY )
        return std::string();

    const int16_t keycode = Input::Engine.GetHotKey(binding.KeyID);
    if ( keycode == Input::KC_NONE )
        return std::string();
    if ( keycode < 0 || (size_t)keycode >= Input::Engine.KeyTitle.size() )
        return std::string();
    if ( Input::Engine.KeyTitle.at(keycode).empty() )
        return std::string();

    return std::string("[") + Input::Engine.KeyTitle.at(keycode) + "]";
}

bool ShouldForceClose(NC_STACK_ypaworld *yw, TInputState *inpt)
{
    if ( !yw || !inpt || !yw->_guiLoaded || yw->_hideHudForScreenshots ||
         !yw->_userUnit || !yw->_userRobo )
        return true;
    if ( yw->_userUnit->_bact_type == BACT_TYPES_MISSLE ||
         yw->_userUnit->_status == BACT_STATUS_DEAD ||
         yw->_userUnit->_status == BACT_STATUS_CREATE ||
         yw->_userUnit->_status == BACT_STATUS_BEAM ||
         yw->_userRobo->_status == BACT_STATUS_DEAD )
        return true;
    if ( yw->IsSpectatorControlled() )
        return true;
    if ( yw->HasActiveNewGemNotification() )
        return true;
    if ( exit_menu.IsOpen() )
        return true;
    if ( yw->_gamePaused || yw->_gameplayPauseRequested )
        return true;
    if ( !Input::Actions.Controller().Connected )
        return true;
    if ( Input::Actions.Pressed(World::INPUT_BIND_QUIT) ||
         Input::Actions.Pressed(World::INPUT_BIND_PAUSE) ||
         inpt->KbdLastHit == Input::KC_ESCAPE ||
         inpt->KbdLastHit == Input::KC_F11 )
    {
        return true;
    }
    return false;
}

int MeasureTextWidth(TileMap *tiles, const std::string &text)
{
    if ( !tiles )
        return (int)text.size() * 6;

    int width = 0;
    for ( unsigned char ch : text )
        width += tiles->map[ch].w;
    return width;
}

std::vector<std::string> WrapHubText(TileMap *tiles, const std::string &text, int maxWidth)
{
    std::vector<std::string> lines;
    if ( text.empty() || maxWidth <= 0 )
        return lines;

    std::string word;
    std::string line;
    auto flushWord = [&]()
    {
        if ( word.empty() )
            return;
        const std::string candidate = line.empty() ? word : (line + " " + word);
        if ( MeasureTextWidth(tiles, candidate) <= maxWidth )
        {
            line = candidate;
        }
        else
        {
            if ( !line.empty() )
                lines.push_back(line);
            if ( MeasureTextWidth(tiles, word) <= maxWidth )
            {
                line = word;
            }
            else
            {
                std::string chunk;
                for ( unsigned char ch : word )
                {
                    const std::string next = chunk + (char)ch;
                    if ( !chunk.empty() && MeasureTextWidth(tiles, next) > maxWidth )
                    {
                        lines.push_back(chunk);
                        chunk.assign(1, (char)ch);
                    }
                    else
                    {
                        chunk = next;
                    }
                }
                line = chunk;
            }
        }
        word.clear();
    };

    for ( unsigned char ch : text )
    {
        if ( ch == ' ' || ch == '\n' )
        {
            flushWord();
            if ( ch == '\n' && !line.empty() )
            {
                lines.push_back(line);
                line.clear();
            }
        }
        else
        {
            word.push_back((char)ch);
        }
    }
    flushWord();
    if ( !line.empty() )
        lines.push_back(line);
    return lines;
}

void EmitCenteredHubLine(NC_STACK_ypaworld *yw, CmdStream *glyphs,
                         const std::string &text, int boxWidth,
                         uint8_t r, uint8_t g, uint8_t b)
{
    if ( !yw || !glyphs || text.empty() || !yw->_guiTiles[15] )
        return;

    FontUA::set_center_xpos(glyphs, (int16_t)(-boxWidth / 2));
    FontUA::set_txtColor(glyphs, r, g, b);
    FontUA::FormateCenteredSkipableItem(yw->_guiTiles[15], glyphs, text, boxWidth);
}

SDL_Color AccentOrFallback(NC_STACK_ypaworld *yw)
{
    if ( yw && yw->_userRobo &&
         yw->_userRobo->_owner >= 1 && yw->_userRobo->_owner <= 6 &&
         yw->_userRobo->_owner != World::OWNER_RESIST )
    {
        return yw->GetColor(yw->_userRobo->_owner);
    }
    return GFX::Engine.Color(0, 200, 220);
}

} // namespace

void State::Reset()
{
    _commandWheelHeld = false;
    Close();
}

void State::CloseOverlay(bool clearPending)
{
    _open = false;
    _highlight = -1;
    if ( clearPending )
        _pendingSlice = -1;
}

void State::Close()
{
    CloseOverlay(true);
}

bool State::UpdateInput(NC_STACK_ypaworld *yw, TInputState *inpt)
{
    const bool captureLeftStick = _open;
    const Input::ControllerState &pad = Input::Actions.Controller();
    const bool commandWheelHeld = pad.Connected && pad.CommandWheelHeld;
    const bool pressed = commandWheelHeld && !_commandWheelHeld;
    _commandWheelHeld = commandWheelHeld;

    if ( ShouldForceClose(yw, inpt) )
    {
        Close();
        return captureLeftStick;
    }

    if ( !_open )
    {
        if ( !pressed )
            return false;

        _open = true;
        _highlight = -1;
        _pendingSlice = -1;
        yw->_stickyDrive.Reset();
    }
    else if ( pressed )
    {
        const float mag = std::sqrt(pad.LeftX * pad.LeftX + pad.LeftY * pad.LeftY);

        int fire = _highlight;
        if ( mag < kCancelMag )
            fire = -1;

        _pendingSlice = fire;
        CloseOverlay(false);
        return true;
    }

    Input::GamepadUtil::Stick stick = {pad.LeftX, pad.LeftY};
    const Input::GamepadUtil::RadialSelectResult sel =
        Input::GamepadUtil::RadialSelect(stick, kSliceCount, kSelectMag,
                                         kCancelMag, _highlight, kStickyHalfWidth);
    _highlight = sel.Slice;

    return true;
}

void State::ApplyPending(NC_STACK_ypaworld *yw, TInputState *inpt)
{
    if ( ShouldForceClose(yw, inpt) )
    {
        Close();
        return;
    }

    if ( _pendingSlice < 0 )
        return;

    const int slice = _pendingSlice;
    _pendingSlice = -1;

    if ( slice < 0 || slice >= kSliceCount )
        return;
    Slot slots[kSliceCount];
    BuildSlots(yw, slots);
    const Slot &slot = slots[slice];
    if ( !slot.Enabled )
        return;

    Input::Actions.SubmitHotkeyForBinding(inpt, slot.Binding);
}

void State::Draw(NC_STACK_ypaworld *yw) const
{
    if ( !_open || !yw || !GFX::Engine.IsVirtualUIPass() )
        return;
    if ( !yw->_userUnit || yw->_userUnit->_bact_type == BACT_TYPES_MISSLE )
        return;

    Slot slots[kSliceCount];
    BuildSlots(yw, slots);

    const float cx = yw->_screenSize.x * 0.5f;
    const float cy = yw->_screenSize.y * 0.5f;
    const float outer = std::min(yw->_screenSize.x, yw->_screenSize.y) * 0.28f;
    const float inner = outer * 0.38f;
    const float iconR = (inner + outer) * 0.5f;
    const float sliceAngle = 2.0f * (float)M_PI / (float)kSliceCount;

    const SDL_Color accent = AccentOrFallback(yw);
    GFX::TGLColor baseCol;
    baseCol.r = 0.05f;
    baseCol.g = 0.08f;
    baseCol.b = 0.10f;
    baseCol.a = kDiscOpacity / 255.0f;

    GFX::TGLColor selCol;
    selCol.r = accent.r / 255.0f;
    selCol.g = accent.g / 255.0f;
    selCol.b = accent.b / 255.0f;
    selCol.a = kSelectedOpacity / 255.0f;

    GFX::TGLColor disCol = baseCol;
    disCol.a = kDisabledOpacity / 255.0f;

    GFX::TGLColor sliceCols[kSliceCount];
    for ( int i = 0; i < kSliceCount; ++i )
    {
        sliceCols[i] = slots[i].Enabled ? baseCol : disCol;
        if ( i == _highlight && slots[i].Enabled )
            sliceCols[i] = selCol;
    }

    GFX::Engine.DrawVirtualUIAnnularSectors(cx, cy, inner, outer, kSliceCount, sliceCols);

    GFX::TGLColor hub = baseCol;
    hub.a = 0.85f;
    GFX::Engine.DrawVirtualUIFilledDisc(cx, cy, inner, hub);

    GFX::TGLColor border;
    border.r = 0.78f;
    border.g = 0.82f;
    border.b = 0.86f;
    border.a = 0.95f;

    GFX::TGLColor selBorder;
    selBorder.r = selCol.r;
    selBorder.g = selCol.g;
    selBorder.b = selCol.b;
    selBorder.a = 1.0f;

    const float tau = 2.0f * (float)M_PI;
    GFX::Engine.DrawVirtualUIArc(cx, cy, outer, 0.0f, tau, border, 48);
    GFX::Engine.DrawVirtualUIArc(cx, cy, inner, 0.0f, tau, border, 32);

    for ( int i = 0; i < kSliceCount; ++i )
    {
        const float a0 = sliceAngle * ((float)i - 0.5f);
        const float ix = cx + inner * std::sin(a0);
        const float iy = cy - inner * std::cos(a0);
        const float ox = cx + outer * std::sin(a0);
        const float oy = cy - outer * std::cos(a0);
        GFX::Engine.DrawVirtualUILine(ix, iy, ox, oy, border);
    }

    if ( _highlight >= 0 && _highlight < kSliceCount && slots[_highlight].Enabled )
    {
        const float a0 = sliceAngle * ((float)_highlight - 0.5f);
        const float a1 = sliceAngle * ((float)_highlight + 0.5f);
        GFX::Engine.DrawVirtualUIArc(cx, cy, outer, a0, a1, selBorder, 8);
        GFX::Engine.DrawVirtualUIArc(cx, cy, inner, a0, a1, selBorder, 6);
        const float edges[2] = {a0, a1};
        for ( int e = 0; e < 2; ++e )
        {
            const float a = edges[e];
            const float ix = cx + inner * std::sin(a);
            const float iy = cy - inner * std::cos(a);
            const float ox = cx + outer * std::sin(a);
            const float oy = cy - outer * std::cos(a);
            GFX::Engine.DrawVirtualUILine(ix, iy, ox, oy, selBorder);
        }
    }

    const int iconSize = yw->_iconOrderW > 0 ? yw->_iconOrderW
                                            : std::max(16, yw->_fontH);
    CmdStream glyphs;
    glyphs.reserve(768);

    for ( int i = 0; i < kSliceCount; ++i )
    {
        const float ang = sliceAngle * (float)i;
        const float ix = cx + iconR * std::sin(ang) - iconSize * 0.5f;
        const float iy = cy - iconR * std::cos(ang) - iconSize * 0.5f;

        const int tileset = !slots[i].Enabled ? 23
                            : (i == _highlight ? 22 : 21);
        FontUA::select_tileset(&glyphs, tileset);
        FontUA::set_xpos(&glyphs, (int16_t)std::lround(ix));
        FontUA::set_ypos(&glyphs, (int16_t)std::lround(iy));
        FontUA::store_u8(&glyphs, slots[i].Glyph);
    }

    std::string hubText;
    std::string hubKey;
    if ( _highlight >= 0 && _highlight < kSliceCount )
    {
        hubText = SlotLabel(yw, slots[_highlight]);
        hubKey = SlotKeyHint(yw, slots[_highlight]);
    }

    if ( (!hubText.empty() || !hubKey.empty()) && yw->_guiTiles[15] )
    {
        const int hubBox = std::max(24, (int)std::lround(inner * 1.55f));
        std::vector<std::string> lines;
        if ( !hubKey.empty() )
            lines.push_back(hubKey);
        const auto wrapped = WrapHubText(yw->_guiTiles[15], hubText, hubBox);
        lines.insert(lines.end(), wrapped.begin(), wrapped.end());
        if ( lines.size() > 4 )
            lines.resize(4);

        const int lineH = yw->_fontH > 0 ? yw->_fontH : yw->_guiTiles[15]->h;
        const int blockH = (int)lines.size() * lineH;
        FontUA::select_tileset(&glyphs, 15);
        FontUA::set_center_ypos(&glyphs, (int16_t)(-blockH / 2));

        for ( size_t i = 0; i < lines.size(); ++i )
        {
            const bool isKey = !hubKey.empty() && i == 0;
            const SDL_Color &col = isKey ? yw->_iniColors[61] : yw->_iniColors[63];
            EmitCenteredHubLine(yw, &glyphs, lines[i], hubBox,
                                col.r, col.g, col.b);
            if ( i + 1 < lines.size() )
                FontUA::next_line(&glyphs);
        }
    }

    FontUA::set_end(&glyphs);

    SDL_Color accentColor = accent;
    const SDL_Color *uiAccent =
        (yw->_userRobo && yw->_userRobo->_owner != World::OWNER_RESIST)
        ? &accentColor : NULL;
    GFX::Engine.ProcessDrawSeq(glyphs, NULL, uiAccent);
}

} // namespace CommandWheel
