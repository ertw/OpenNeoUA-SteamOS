#!/bin/sh

# Resolve the physical script location so invoking this launcher through a
# symlink still uses the directory containing the actual game overlay.
script_path=$0
case "$script_path" in
    /*) ;;
    *) script_path=$(pwd -P)/$script_path || exit 1 ;;
esac

while [ -L "$script_path" ]; do
    script_dir=$(CDPATH= cd -P -- "$(dirname -- "$script_path")" 2>/dev/null && pwd -P) || exit 1
    link_target=$(readlink "$script_path") || exit 1
    case "$link_target" in
        /*) script_path=$link_target ;;
        *) script_path=$script_dir/$link_target ;;
    esac
done

game_root=$(CDPATH= cd -P -- "$(dirname -- "$script_path")" 2>/dev/null && pwd -P) || exit 1
cd "$game_root" || exit 1

if [ -n "${LD_LIBRARY_PATH-}" ]; then
    LD_LIBRARY_PATH="$game_root/lib:$LD_LIBRARY_PATH"
else
    LD_LIBRARY_PATH="$game_root/lib"
fi
export LD_LIBRARY_PATH

exec "$game_root/bin/OpenNeoUA" "$@"
