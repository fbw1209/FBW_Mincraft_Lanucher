from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FML"
APP_DISPLAY_NAME = "FBW Minecraft Launcher"
APP_VERSION = "1.1.0"

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
DATA_DIR = APP_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
LOGS_DIR = DATA_DIR / "logs"
RUNTIME_DIR = DATA_DIR / "runtime"
ASSETS_DIR = RESOURCE_DIR / "assets"
CONFIG_FILE = DATA_DIR / "config.json"
ICON_FILE = ASSETS_DIR / "icon.ico"
ICON_PNG = ASSETS_DIR / "icon.png"

OFFICIAL_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
MIRROR_MANIFEST_URL = "https://bmclapi2.bangbang93.com/mc/game/version_manifest.json"
JAVA_RUNTIME_MANIFEST_URL = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)
FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader"


def ensure_app_dirs() -> None:
    for path in (DATA_DIR, CACHE_DIR, LOGS_DIR, RUNTIME_DIR, ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def default_game_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / ".minecraft"
    return Path.home() / ".minecraft"
