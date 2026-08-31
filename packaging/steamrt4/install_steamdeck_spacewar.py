#!/usr/bin/env python3
"""Register OpenNeoUA as Spacewar (appid 480) Launch Options for Steam Input.

Steam Input configs are keyed to the Steam app identity of the running window.
A Non-Steam shortcut gets a synthetic app id, so the official Spacewar layout
"OpenNeoUA Deck IGA" appears with every binding unset. Launching through
Spacewar itself keeps the client, overlay, and IGA on appid 480.

This tool patches userdata/*/config/localconfig.vdf:

    apps/480/LaunchOptions = "<quoted payload> # %command%"

Steam must be quit before writing; otherwise the client overwrites the file
on exit. Do not replace Steam's controller_config/game_actions_480.vdf —
OpenNeoUA overrides the IGA at runtime via SetInputActionManifestFilePath.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union


SPACEWAR_APPID = "480"
LAUNCH_OPTIONS_SUFFIX = " # %command%"
VdfNode = Union[str, "VdfDict"]
VdfDict = Dict[str, VdfNode]


class InstallError(RuntimeError):
    """Fatal installer failure with a user-facing message."""


def fail(message: str) -> None:
    raise InstallError(message)


def quote_shell_path(path: Path) -> str:
    text = str(path)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_launch_options(payload: Path, *, input_debug: bool = False) -> str:
    debug_option = " --input-debug" if input_debug else ""
    return quote_shell_path(payload.resolve()) + debug_option + LAUNCH_OPTIONS_SUFFIX


def resolve_payload(argument: Optional[str]) -> Path:
    candidates: List[Path] = []
    if argument:
        candidates.append(Path(argument))
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        candidates.append(Path(appimage))
    script_dir = Path(__file__).resolve().parent
    # Overlay layout: installer next to OpenNeoUA.sh, or under bin/.
    for relative in ("OpenNeoUA.sh", Path("..") / "OpenNeoUA.sh"):
        candidates.append(script_dir / relative)

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved

    fail(
        "cannot resolve an executable payload; pass the AppImage or OpenNeoUA.sh path"
    )


def find_steam_roots(home: Path) -> List[Path]:
    roots: List[Path] = []
    for relative in (
        Path(".steam") / "steam",
        Path(".local") / "share" / "Steam",
        Path(".steam") / "root",
    ):
        candidate = home / relative
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir() and (resolved / "userdata").is_dir():
            if resolved not in roots:
                roots.append(resolved)
    return roots


def list_localconfig_paths(steam_root: Path) -> List[Path]:
    userdata = steam_root / "userdata"
    if not userdata.is_dir():
        return []
    found: List[Tuple[float, Path]] = []
    for child in userdata.iterdir():
        if not child.is_dir() or not child.name.isdigit():
            continue
        config = child / "config" / "localconfig.vdf"
        if config.is_file() and not config.is_symlink():
            found.append((config.stat().st_mtime, config))
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _mtime, path in found]


def steam_is_running() -> bool:
    """Return True if a Steam client process looks active.

    Checks /proc for a process whose basename is steam (the client), not
    steamwebhelper alone. Also honours ~/.steam/steam.pid when present.
    """

    home = Path.home()
    for pid_path in (home / ".steam" / "steam.pid", home / ".steam" / "steam" / "steam.pid"):
        if not pid_path.is_file():
            continue
        try:
            text = pid_path.read_text(encoding="utf-8").strip().splitlines()
            if not text:
                continue
            pid = int(text[0].strip())
        except (OSError, ValueError):
            continue
        if pid > 0 and Path("/proc/{}".format(pid)).is_dir():
            return True

    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        cmdline = entry / "cmdline"
        try:
            raw = cmdline.read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        argv0 = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        base = Path(argv0).name.lower()
        if base == "steam" or base.startswith("steam."):
            return True
    return False


_TOKEN_RE = re.compile(
    r'"((?:\\.|[^"\\])*)"'  # quoted string
    r"|(\{)"
    r"|(\})"
    r"|([^\s{}\"]+)"  # bare token (rare in localconfig)
    r"|(\s+)"
    r"|(.)",
    re.DOTALL,
)


def _unescape_vdf(value: str) -> str:
    out: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            out.append(value[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _escape_vdf(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def tokenize_vdf(text: str) -> List[str]:
    tokens: List[str] = []
    for match in _TOKEN_RE.finditer(text):
        quoted, open_brace, close_brace, bare, whitespace, other = match.groups()
        if whitespace is not None:
            continue
        if quoted is not None:
            tokens.append(_unescape_vdf(quoted))
        elif open_brace is not None:
            tokens.append("{")
        elif close_brace is not None:
            tokens.append("}")
        elif bare is not None:
            tokens.append(bare)
        else:
            fail("invalid VDF token near {!r}".format(text[match.start() : match.start() + 20]))
    return tokens


def parse_vdf(text: str) -> VdfDict:
    tokens = tokenize_vdf(text)
    index = 0

    def parse_object() -> VdfDict:
        nonlocal index
        result: VdfDict = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                index += 1
                return result
            key = token
            index += 1
            if index >= len(tokens):
                fail("VDF key {!r} is missing a value".format(key))
            value_token = tokens[index]
            index += 1
            if value_token == "{":
                value: VdfNode = parse_object()
            elif value_token == "}":
                fail("VDF key {!r} has a closing brace as its value".format(key))
            else:
                value = value_token
            # localconfig occasionally repeats keys; last write wins for scalars,
            # but nested objects with the same key should merge shallowly only
            # when both are dicts so we do not drop sibling sections.
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                existing = result[key]
                assert isinstance(existing, dict)
                existing.update(value)
            else:
                result[key] = value
        return result

    root = parse_object()
    if index != len(tokens):
        fail("VDF has trailing tokens after the root object")
    return root


def serialize_vdf(data: Mapping[str, VdfNode], indent: int = 0) -> str:
    lines: List[str] = []
    prefix = "\t" * indent
    for key, value in data.items():
        lines.append('{}"{}"'.format(prefix, _escape_vdf(str(key))))
        if isinstance(value, dict):
            lines.append("{}{{".format(prefix))
            lines.append(serialize_vdf(value, indent + 1).rstrip("\n"))
            lines.append("{}}}".format(prefix))
        else:
            lines.append('{}"{}"'.format(prefix, _escape_vdf(str(value))))
    return "\n".join(lines) + ("\n" if lines else "")


def ensure_path(root: MutableMapping[str, VdfNode], keys: Sequence[str]) -> MutableMapping[str, VdfNode]:
    current: MutableMapping[str, VdfNode] = root
    for key in keys:
        existing = current.get(key)
        if existing is None:
            nested: VdfDict = {}
            current[key] = nested
            current = nested
            continue
        if not isinstance(existing, dict):
            fail("VDF path {!r} collides with a scalar value".format("/".join(keys)))
        current = existing
    return current


def set_spacewar_launch_options(root: MutableMapping[str, VdfNode], launch_options: str) -> None:
    # Prefer the canonical Valve path; create it when absent.
    store_keys = (
        "UserLocalConfigStore",
        "Software",
        "Valve",
        "Steam",
        "apps",
        SPACEWAR_APPID,
    )
    # Some clients lowercase the Software/Valve path.
    candidates = [
        store_keys,
        (
            "UserLocalConfigStore",
            "software",
            "valve",
            "Steam",
            "apps",
            SPACEWAR_APPID,
        ),
    ]

    target: Optional[MutableMapping[str, VdfNode]] = None
    for keys in candidates:
        cursor: Mapping[str, VdfNode] = root
        found = True
        for key in keys[:-1]:
            node = cursor.get(key)
            if not isinstance(node, dict):
                found = False
                break
            cursor = node
        if found:
            target = ensure_path(root, keys)
            break
    if target is None:
        target = ensure_path(root, store_keys)
    target["LaunchOptions"] = launch_options


def patch_localconfig(path: Path, launch_options: str) -> str:
    original = path.read_text(encoding="utf-8")
    data = parse_vdf(original)
    set_spacewar_launch_options(data, launch_options)
    # Preserve a leading BOM-less UTF-8 dump. Steam accepts LF.
    updated = serialize_vdf(data)
    if not updated.endswith("\n"):
        updated += "\n"
    path.write_text(updated, encoding="utf-8")
    return updated


def format_next_steps(payload: Path, account_id: str, steam_root: Path) -> str:
    return "\n".join(
        [
            "Patched Spacewar (480) Launch Options for Steam userdata {}.".format(account_id),
            "  Steam root : {}".format(steam_root),
            "  Payload    : {}".format(payload),
            "",
            "Next steps:",
            "  1. Start Steam (Desktop Mode or Game Mode).",
            "  2. Ensure Spacewar is in your library (Steamworks accounts have app 480).",
            "  3. In Game Mode, launch Spacewar — not a Non-Steam AppImage shortcut.",
            "  4. Leave Compatibility off. Steam Input should show",
            '     "Official Layout for Spacewar - OpenNeoUA Deck IGA" with bindings set.',
            "",
            "Do not overwrite Steam's controller_config/game_actions_480.vdf;",
            "OpenNeoUA installs its IGA at runtime.",
        ]
    )


def install(
    payload: Path,
    *,
    home: Optional[Path] = None,
    force_steam_running: Optional[bool] = None,
    input_debug: bool = False,
) -> Tuple[Path, Path, str]:
    home_path = home if home is not None else Path.home()
    if not payload.is_file() or not os.access(payload, os.X_OK):
        fail("payload is not an executable file: {}".format(payload))

    running = steam_is_running() if force_steam_running is None else force_steam_running
    if running:
        fail(
            "Steam appears to be running; quit Steam completely before installing "
            "(otherwise localconfig.vdf is overwritten on exit)"
        )

    roots = find_steam_roots(home_path)
    if not roots:
        fail(
            "cannot find a Steam userdata directory under {} "
            "(.steam/steam or .local/share/Steam)".format(home_path)
        )

    configs: List[Tuple[Path, Path]] = []
    for root in roots:
        for config in list_localconfig_paths(root):
            configs.append((root, config))
    if not configs:
        fail("Steam userdata exists but no localconfig.vdf was found")

    # Most recently modified localconfig wins when several accounts are present.
    configs.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    steam_root, config_path = configs[0]
    account_id = config_path.parent.parent.name
    launch_options = build_launch_options(payload, input_debug=input_debug)
    patch_localconfig(config_path, launch_options)
    return steam_root, config_path, account_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Set Spacewar (480) Launch Options to an OpenNeoUA AppImage or "
            "OpenNeoUA.sh so Steam Input uses appid 480."
        )
    )
    parser.add_argument(
        "payload",
        nargs="?",
        help="path to the AppImage or OpenNeoUA.sh (default: $APPIMAGE or sibling launcher)",
    )
    parser.add_argument(
        "--print-launch-options",
        action="store_true",
        help="print the Launch Options string and exit without writing",
    )
    parser.add_argument(
        "--input-debug",
        action="store_true",
        help="add the compact Steam Input mode overlay to the game launch",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = resolve_payload(args.payload)
        if args.print_launch_options:
            sys.stdout.write(build_launch_options(payload, input_debug=args.input_debug) + "\n")
            return 0
        steam_root, _config_path, account_id = install(payload, input_debug=args.input_debug)
        sys.stdout.write(format_next_steps(payload, account_id, steam_root) + "\n")
        return 0
    except InstallError as exc:
        sys.stderr.write("install_steamdeck_spacewar: {}\n".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
