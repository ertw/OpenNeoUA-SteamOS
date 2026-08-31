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

# Native Linux / Steam Deck

The Linux build is a native `x86_64` overlay. It does not include Urban Assault
data. Requires Docker. Do not use Proton.

## Build the overlay

```sh
./packaging/steamrt4/local_ci.py
```

Extract the archive into a writable Urban Assault installation:

```sh
tar -xJf build/local-ci/artifacts/OpenNeoUA-steamrt4-x86_64-*.tar.xz \
  -C "/path/to/Urban Assault"
```

## Add it to Steam (Spacewar / Steam Input IGA)

OpenNeoUA's native Steam Input layout is authored for **Spacewar appid 480**.
A Non-Steam shortcut gets a synthetic app id, so the official layout
**Official Layout for Spacewar - OpenNeoUA Deck IGA** appears with every
binding unset. Launch the game **as Spacewar** so Steam, the overlay, and
Steam Input stay on 480.

1. Quit Steam completely (Desktop Mode).
2. From the Urban Assault folder:

```sh
python3 install_steamdeck_spacewar.py ./OpenNeoUA.sh
```

3. Start Steam. Ensure **Spacewar** is in your library (Steamworks accounts
   have app 480).
4. In Game Mode, launch **Spacewar** — not a Non-Steam shortcut. Leave
   Compatibility off.
5. In-game **Input Settings**, enable **Joystick**. Leave **Alt Joystick** off.

Do not overwrite Steam's `controller_config/game_actions_480.vdf`; OpenNeoUA
installs its IGA at runtime.

### Legacy Non-Steam fallback (keyboard/mouse layout only)

If you cannot use Spacewar, Non-Steam still works with the older Deck layout:

1. Steam → Add a Game → Add a Non-Steam Game → browse to `OpenNeoUA.sh`.
2. Leave Compatibility off.
3. Enable Steam Input. Import `SteamInput/openneoua_deck_default.vdf`, or select
   **OpenNeoUA Deck Default** if it is already listed.
4. In-game **Input Settings**, enable **Joystick**. Leave **Alt Joystick** off.

If Game Mode will not start `OpenNeoUA.sh`, point the shortcut at
`bin/OpenNeoUA` and set **Start In** to the Urban Assault directory.

This path does **not** load the IGA official bindings for appid 480.

## Private Steam Deck AppImage (local only)

Builds an AppImage from a locally owned base-game ISO at `vendor/ua.iso`. Game
data never enters CI or public artifacts — keep the ISO gitignored.

```sh
cp "/path/to/Urban Assault.iso" vendor/ua.iso
./packaging/steamrt4/build_steamdeck.py \
  --output-dir build/steamdeck-private/artifacts
```

Use `--iso` to override the default path. Steam Input support is bundled from
the vendored Steamworks SDK at `vendor/steamworks-sdk/` when you build the
overlay with `./packaging/steamrt4/local_ci.py`.

`chmod +x` the AppImage and copy it to the Deck. Saves live in
`~/.local/share/OpenNeoUA`.

For repeatable developer installs, the repository includes an SSH deployer.
It uses the `steamdeck` host from `~/.ssh/config`, verifies the uploaded
SHA-256 on the Deck, and atomically replaces the stable executable at
`~/.local/bin/OpenNeoUA-dev.AppImage`:

```sh
./packaging/steamrt4/deploy_steamdeck.py
```

The newest AppImage under `build/steamdeck-private/artifacts` is selected by
default. Deployment refuses before copying any data while Steam is running on
the Deck and refreshes Spacewar's launch option after every successful update.
Development deployment also adds `--input-debug`, which displays the expected
and actual Steam Input base mode/layer plus live action state in-game.
Pass an explicit AppImage when needed. `--rsync` seeds a temporary
copy from the installed build and transfers changed blocks; ordinary SCP is
the simpler default. `--skip-spacewar-config` is available when only the file
should be replaced.

The developer TUI collects build, deployment, generator, test, and CI tasks:

```sh
./packaging/steamrt4/dev_menu.py
```

### Register the AppImage as Spacewar

Quit Steam, then from Desktop Mode:

```sh
./OpenNeoUA-SteamDeck-private-x86_64-….AppImage --install-steam-spacewar
```

Start Steam and launch **Spacewar** in Game Mode. Steam Input should show
**OpenNeoUA Deck IGA** with bindings set. Adding the AppImage as a Non-Steam
game will show the official Spacewar layout title with empty bindings — that
is the synthetic-appid mismatch, not a packaging bug.

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
