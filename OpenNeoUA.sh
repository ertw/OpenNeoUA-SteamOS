#!/bin/sh

# Resolve the physical script location so invoking this launcher through a
# symlink still uses the directory containing the actual game overlay.
# Steam's compatibility-tool wrapper can also rewrite argv0 or insert Proton
# verbs (waitforexitandrun) before the real arguments.

fail() {
    printf '%s\n' "OpenNeoUA.sh: $*" >&2
    if [ -n "${game_root-}" ] && [ -d "$game_root" ]; then
        printf '%s\n' "$*" >> "$game_root/openneoua-launch.log" 2>/dev/null || true
    fi
    exit 127
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        waitforexitandrun|run|getcompatpath|getnativepath)
            shift
            ;;
        *)
            break
            ;;
    esac
done

script_path=$0
case "$script_path" in
    /*) ;;
    *) script_path=$(pwd -P)/$script_path || fail "cannot resolve working directory" ;;
esac

while [ -L "$script_path" ]; do
    script_dir=$(CDPATH= cd -P -- "$(dirname -- "$script_path")" 2>/dev/null && pwd -P) || fail "cannot resolve symlink directory"
    link_target=$(readlink "$script_path") || fail "cannot read symlink $script_path"
    case "$link_target" in
        /*) script_path=$link_target ;;
        *) script_path=$script_dir/$link_target ;;
    esac
done

game_root=$(CDPATH= cd -P -- "$(dirname -- "$script_path")" 2>/dev/null && pwd -P) || true

# Non-Steam shortcuts wrapped by Steam Linux Runtime sometimes pass a rewritten
# argv0.  STEAM_COMPAT_INSTALL_PATH is the Start In / install directory Steam
# already knows about.
if { [ -z "${game_root-}" ] || [ ! -x "$game_root/bin/OpenNeoUA" ]; } && [ -n "${STEAM_COMPAT_INSTALL_PATH-}" ]; then
    compat_root=$(CDPATH= cd -P -- "$STEAM_COMPAT_INSTALL_PATH" 2>/dev/null && pwd -P) || true
    if [ -x "${compat_root-}/bin/OpenNeoUA" ]; then
        game_root=$compat_root
    fi
fi

if [ -z "${game_root-}" ] || [ ! -x "$game_root/bin/OpenNeoUA" ]; then
    fail "cannot find bin/OpenNeoUA (argv0=$0 cwd=$(pwd -P 2>/dev/null || pwd))"
fi

if [ "$#" -gt 0 ]; then
    case "$1" in
        "$script_path"|"$game_root/OpenNeoUA.sh"|OpenNeoUA.sh|./OpenNeoUA.sh)
            shift
            ;;
    esac
fi

cd "$game_root" || fail "cannot change directory to $game_root"

if [ -n "${LD_LIBRARY_PATH-}" ]; then
    LD_LIBRARY_PATH="$game_root/lib:$LD_LIBRARY_PATH"
else
    LD_LIBRARY_PATH="$game_root/lib"
fi
export LD_LIBRARY_PATH

exec "$game_root/bin/OpenNeoUA" "$@"
fail "failed to exec $game_root/bin/OpenNeoUA"
