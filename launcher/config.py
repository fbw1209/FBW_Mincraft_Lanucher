from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Any

from .paths import CONFIG_FILE, default_game_dir, ensure_app_dirs


def _physical_memory_mb() -> int:
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys // (1024 * 1024))
    except Exception:
        pass
    return 8192


PHYSICAL_MEMORY_MB = _physical_memory_mb()
MAX_MEMORY_LIMIT = max(2048, min(16384, (PHYSICAL_MEMORY_MB - 1024) // 1024 * 1024))
DEFAULT_MAX_MEMORY = max(2048, min(8192, (PHYSICAL_MEMORY_MB // 2) // 1024 * 1024))


def _clamp_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


@dataclass
class Config:
    username: str = "Player"
    game_dir: str = str(default_game_dir())
    java_path: str = ""
    auto_java: bool = True
    min_memory: int = 512
    max_memory: int = DEFAULT_MAX_MEMORY
    selected_version: str = ""
    download_source: str = "auto"
    close_after_launch: bool = False
    show_log: bool = True
    fullscreen: bool = False
    last_version: str = ""
    last_played: str = ""
    hidden_versions: list[str] = field(default_factory=list)

    def normalized(self) -> "Config":
        data = asdict(self)
        data["username"] = validate_username(self.username) or "Player"
        game_dir = str(data.get("game_dir") or "").strip()
        data["game_dir"] = game_dir or str(default_game_dir())
        data["java_path"] = str(data.get("java_path") or "").strip()
        data["min_memory"] = _clamp_int(data.get("min_memory"), 512, 256, MAX_MEMORY_LIMIT)
        data["max_memory"] = _clamp_int(
            data.get("max_memory"), DEFAULT_MAX_MEMORY, max(1024, data["min_memory"]), MAX_MEMORY_LIMIT
        )
        data["max_memory"] = max(1024, min(MAX_MEMORY_LIMIT, int(round(data["max_memory"] / 1024) * 1024)))
        if data["min_memory"] > data["max_memory"]:
            data["min_memory"] = data["max_memory"]
        if data.get("download_source") not in ("auto", "official", "mirror"):
            data["download_source"] = "auto"
        hidden = data.get("hidden_versions")
        data["hidden_versions"] = (
            [str(item) for item in hidden if isinstance(item, str)]
            if isinstance(hidden, list)
            else []
        )
        return Config(**{k: v for k, v in data.items() if k in {f.name for f in fields(Config)}})


def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 16:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if any(ch not in allowed for ch in name):
        return ""
    return name


class ConfigStore:
    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.config = self.load()

    def load(self) -> Config:
        ensure_app_dirs()
        raw: dict[str, Any] = {}
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    raw = loaded
        except Exception:
            raw = {}
        known = {f.name for f in fields(Config)}
        values = {k: v for k, v in raw.items() if k in known}
        return Config(**values).normalized()

    def save(self, config: Config | None = None) -> Config:
        with self._lock:
            if config is not None:
                self.config = config.normalized()
            ensure_app_dirs()
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(asdict(self.config), handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return self.config


_store: ConfigStore | None = None


def get_config_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store
