# OpenNeoUA

OpenNeoUA is an independent, open-source and non-commercial evolution of the
`UA_source`/OpenUA engine for **Urban Assault**. It modernizes real engine
limitations while preserving vanilla data, levels, scripts, saves and the
original game feeling. A legitimate copy of the original game data is still
required to play.

The project is derived from the upstream `Marisa-Chan/UA_source` lineage and
keeps that provenance visible. Microsoft, TerraTools and the other rights
holders are not affiliated with or endorsing this project. Existing credits and
notices remain applicable.

**License** GPLv2

# Building OpenNeoUA on Modern Windows (64-bit MSYS2):

1. Download and install MSYS2:
https://www.msys2.org/

2. Open MSYS2 MSYS

3. Run:
pacman -Syu for updating.
If MSYS2 asks you to close the terminal, close it and reopen it before continuing.

4. Install all required dependencies:
pacman -S --needed mingw-w64-x86_64-toolchain mingw-w64-x86_64-cmake mingw-w64-x86_64-SDL2 mingw-w64-x86_64-SDL2_image mingw-w64-x86_64-SDL2_ttf mingw-w64-x86_64-SDL2_net mingw-w64-x86_64-openal mingw-w64-x86_64-libvorbis mingw-w64-x86_64-ffmpeg mingw-w64-x86_64-lua

5. Download the source code ZIP from:
https://github.com/TeuZzZ-17/OpenNeoUA


6. Extract the project folder to your Desktop.
Example:
C:\Users\YourName\Desktop\OpenNeoUA

7. Open the MinGW64 environment with MSYS2 MinGW 64-bit
or directly:
C:\msys64\mingw64.exe

8. In MinGW64 go to the project folder
Example:
cd /c/Users/YourName/Desktop/OpenNeoUA

9. Configure the project:
cmake -B build -S src

10. Compile the project:
cmake --build build -j12

11. If compilation succeeds, you will find:
build/OpenNeoUA.exe

12. Obtain an original copy of Urban Assault:
Use a clean, unmodified installation of the original game.

13. Copy the following into your Urban Assault installation folder:
    
OpenNeoUA.exe,
res,
fonts,
locale/language.lng

15. If OpenNeoUA.exe reports missing DLL files at startup:
Copy the required DLLs from:
C:\msys64\mingw64\bin
into the same folder as:
OpenNeoUA.exe

16. After this step, build/OpenNeoUA.exe should be portable and runnable outside the MSYS2 environment.

# Native Linux / SteamOS / Steam Deck / Bazzite

The Linux build is an `x86_64` overlay. It contains OpenNeoUA and its private
non-runtime libraries, but it does not contain any original Urban Assault data.
Use it only with a lawfully obtained, clean Urban Assault installation.

Run the same pinned SteamRT4 pipeline used by GitHub Actions with Docker:

```sh
./packaging/steamrt4/local_ci.py
```

Artifacts are written to `build/local-ci/artifacts/`. Use `--output-dir PATH`
to choose another destination, `--refresh-image` to pull the pinned base and
rebuild every image layer, or `--keep-work` to retain the sanitized snapshot
and per-run work directory for debugging. Dirty working trees are supported;
only tracked changes and explicitly allowed, non-ignored development files are
included in a deterministic synthetic Git snapshot. New game-data payloads
must be staged before running local CI.

The CI artifact is named
`OpenNeoUA-steamrt4-x86_64-<short-sha>.tar.xz` for a clean tree, or
`OpenNeoUA-steamrt4-x86_64-<base7>-dirty-<snapshot7>.tar.xz` for a dirty tree.
Verify the external checksum before extracting it:

```sh
sha256sum -c OpenNeoUA-steamrt4-x86_64-<short-sha>.tar.xz.sha256
tar -xJf OpenNeoUA-steamrt4-x86_64-<short-sha>.tar.xz -C "/path/to/Urban Assault"
cd "/path/to/Urban Assault"
sha256sum -c MANIFEST.sha256
(cd Fonts && sha256sum -c SHA256SUMS)
```

The Urban Assault directory must remain writable because the engine writes its
configuration, logs, screenshots, and save files there. Keep the extracted
overlay in that directory; `OpenNeoUA.sh` changes to its own game root before
starting `bin/OpenNeoUA`, so it can be launched from another working directory
and from a path containing spaces.

## Add it to Steam

1. In Steam, choose **Add a Game → Add a Non-Steam Game** and browse to
   `OpenNeoUA.sh` in the Urban Assault directory.
2. Open the shortcut’s **Properties → Compatibility** and enable the forced
   compatibility tool. Install Steam Linux Runtime 4.0 if necessary; Steam
   exposes it as app ID `4183110`.
3. Select **Steam Linux Runtime 4.0**, not Proton. The initial build is native
   Linux only and targets `x86_64`.
4. Start the shortcut. Keyboard and mouse are supported, and the existing SDL2
   joystick path is retained. On a Steam Deck, a **Legacy Steam Input** profile
   can map controller buttons to keyboard and mouse controls.

The same procedure works in SteamOS Desktop Mode and Game Mode. On Bazzite,
use the Steam-managed runtime and do not install game dependencies into the
immutable host system. The game directory itself must still be writable.

This initial package does not claim “Deck Verified”. Steamworks integration,
native Steam Input action manifests, dynamic glyphs, the on-screen keyboard,
and improved controller hot-plugging are deferred to a later phase.

## Private Steam Deck AppImage (local only)

For a locally owned `UA-Complete/Urban Assault.iso`, build a private AppImage
that includes only the validated base-game payload. Proprietary files are
mounted read-only during assembly and never enter GitHub Actions or the Docker
build context:

```sh
./packaging/steamrt4/build_steamdeck.py \
  --assets-dir UA-Complete \
  --output-dir build/steamdeck-private/artifacts
```

The output pair is named
`OpenNeoUA-SteamDeck-private-x86_64-<source-id>-assets-<iso12>.AppImage` and
`.sha256`. Use the AppImage directly on a Steam Deck after marking it
executable. Persistent state is stored in
`${XDG_DATA_HOME:-$HOME/.local/share}/OpenNeoUA`; replacing the AppImage does
not remove saves or settings.

To exercise the actual rendered title and Options menus under software Mesa:

```sh
./packaging/steamrt4/test_game_menu.py \
  --appimage build/steamdeck-private/artifacts/OpenNeoUA-SteamDeck-private-*.AppImage \
  --output-dir build/steamdeck-private/test-results
```

The harness extracts with `--appimage-extract` (no FUSE), uses Xvfb when
available or the pinned `linux/amd64` assembly image otherwise, and validates
three 1280×800 PPM framebuffer captures plus an atomic JSON transition report.
These commands are intentionally local-only and do not upload or publish
owned game assets.

For runtime development, `bin/OpenNeoUA` also accepts `--asset-root PATH` and
`--user-dir PATH`. Existing launches without these options retain the legacy
single-directory behavior.

The CI job checks the build, ELF dependencies, package allowlist, licenses,
checksums, archive layout, and launcher behavior. Actual startup, rendering,
audio/video playback, localization, level loading, save creation/reload,
fullscreen `1280×800`, 30-fps performance, suspend/resume, and Deck/Bazzite
controller behavior still require manual testing on a clean game installation.

# Third-Party Derived Interface Assets Notice

Certain PNG files located under `Data/fonts/` are unofficial, fan-made interface variants created for OpenNeoUA.

These files are based on, converted from, or visually derived from original user-interface artwork distributed with Microsoft Urban Assault (1998). The original assets were provided in legacy ILBM/ILB formats; the versions included here have been converted to PNG and modified with new faction-specific colours and related visual adjustments.

Urban Assault, its original artwork, interface elements, names, trademarks, and all associated intellectual-property rights remain the property of their respective copyright and trademark holders.

OpenNeoUA is an independent, free, non-commercial fan project. It is not affiliated with, endorsed by, sponsored by, or officially approved by Microsoft, TerraTools, or any other current or former rights holder.

No ownership is claimed over the underlying original Urban Assault artwork. No claim is made beyond any original modifications or contributions that may be protectable under applicable law.

These interface assets are provided solely to support and demonstrate OpenNeoUA's optional faction-specific user-interface functionality. They do not represent a complete redistribution of the original game's asset library.

The third-party-derived assets contained in `Data/fonts/` are not covered by the GNU General Public License that applies to the OpenNeoUA source code. No licence or permission concerning the underlying third-party artwork is granted by this repository.

Users remain responsible for complying with applicable copyright law and should use OpenNeoUA together with a lawfully obtained copy of Urban Assault.

If you are an authorised rights holder and believe that any material in this repository should be removed, replaced, or otherwise modified, please contact me.

Any legitimate request will be reviewed promptly and in good faith.

The GPL licence applies to the OpenNeoUA source code only.
