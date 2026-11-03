"""Shared paths and pinned container versions for the SteamRT4 tools.

The same base image is pinned in Dockerfile.*, run-ci.sh, and linux-steamrt4.yml; update
those together when deliberately upgrading the runtime.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STEAMRT4_VERSION = "4.0.20260805.254769"
STEAMRT4_IMAGE = "registry.gitlab.steamos.cloud/steamrt/steamrt4/sdk:" + STEAMRT4_VERSION
LOCAL_IMAGE = "openneoua-steamrt4-local-ci:" + STEAMRT4_VERSION
STEAMDECK_IMAGE = "openneoua-steamdeck-appimage:" + STEAMRT4_VERSION
SMOKETEST_IMAGE = "openneoua-smoketest:" + STEAMRT4_VERSION

# Repository resources shipped with the engine (never original game data).
ASSET_DIRECTORIES = (
    "Collision",
    "Env",
    "Filters",
    "Fonts",
    "Interface",
    "Levels",
    "Locale",
    "Models",
    "Res",
    "Scripts",
    "Sounds",
    "Wireless",
)
ASSET_FILES = ("OpenNeoUA.ini", "OpenNeoUA.sh")
