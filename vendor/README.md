# Local vendor files

This directory holds dependencies and assets that are **not redistributed**
with public CI artifacts.

## Tracked in git

- `steamworks-sdk/` — Valve Steamworks SDK (headers and redistributable
  `libsteam_api.so`). Used to build and bundle Steam Input support.

## Local only (never commit)

Place these files on your machine for private Deck/AppImage builds and menu
smoke tests. They are gitignored and excluded from Docker CI snapshots.

| Path | Purpose |
| --- | --- |
| `ua.iso` | Owned copy of the Urban Assault base-game ISO |

Example:

```sh
cp "/path/to/Urban Assault.iso" vendor/ua.iso
```

The Steam Deck AppImage builder reads `vendor/ua.iso` by default:

```sh
./packaging/steamrt4/build_steamdeck.py
```

Override with `--iso /other/path.iso` if needed.
