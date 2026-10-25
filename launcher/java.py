from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .net import DownloadError, DownloadItem, download_many, fetch_json
from .paths import CACHE_DIR, JAVA_RUNTIME_MANIFEST_URL, RUNTIME_DIR

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass(frozen=True)
class JavaInfo:
    path: Path
    version: str
    major: int
    vendor: str = ""
    raw: str = ""

    @property
    def label(self) -> str:
        vendor = f" · {self.vendor}" if self.vendor else ""
        return f"Java {self.major}{vendor}"

    @property
    def detail(self) -> str:
        return f"Java {self.version} · {self.path}"


def _parse_java_output(text: str) -> tuple[str, int, str]:
    match = re.search(r'version "([^"]+)"', text)
    version = match.group(1) if match else ""
    major = 0
    if version:
        parts = version.split(".")
        try:
            if parts[0] == "1" and len(parts) > 1:
                major = int(parts[1])
            else:
                major = int(re.match(r"\d+", parts[0]).group(0)) if re.match(r"\d+", parts[0]) else 0
        except Exception:
            major = 0
    vendor = ""
    for name in ("Oracle", "Temurin", "Adoptium", "OpenJDK", "Microsoft", "Zulu", "GraalVM", "Corretto", "Liberica"):
        if name.lower() in text.lower():
            vendor = name
            break
    return version, major, vendor


def normalize_java_path(path: Path) -> Path:
    if path.name.lower() == "javaw.exe":
        java = path.with_name("java.exe")
        if java.is_file():
            return java
    return path


def probe_java(path: Path) -> JavaInfo | None:
    try:
        path = normalize_java_path(path)
        if not path.is_file():
            return None
        completed = subprocess.run(
            [str(path), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        text = completed.stdout or ""
        version, major, vendor = _parse_java_output(text)
        if major <= 0:
            return None
        return JavaInfo(path=path, version=version, major=major, vendor=vendor, raw=text)
    except Exception:
        return None


def _candidate_roots() -> list[Path]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    localappdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roots = [
        RUNTIME_DIR,
        Path("C:/Program Files/Java"),
        Path("C:/Program Files/Eclipse Adoptium"),
        Path("C:/Program Files/Microsoft"),
        Path("C:/Program Files/Zulu"),
        Path("C:/Program Files/Amazon Corretto"),
        Path("C:/Program Files/BellSoft"),
        Path("C:/Program Files/Common Files/Oracle/Java"),
        Path("D:/Java"),
        Path("D:/Program Files/Java"),
        localappdata / "Programs" / "Eclipse Adoptium",
        localappdata / "Programs" / "Microsoft",
    ]
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        roots.insert(0, Path(java_home))
    return roots


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _collect_candidates(extra: Iterable[str] = ()) -> list[Path]:
    candidates: list[Path] = []
    for item in extra:
        if not item:
            continue
        path = Path(item)
        if path.is_dir():
            candidates.extend([path / "bin" / "java.exe", path / "java.exe"])
        else:
            candidates.append(path)
    for root in _candidate_roots():
        if not root.exists():
            continue
        direct = [
            root / "bin" / "java.exe",
            root / "jre" / "bin" / "java.exe",
        ]
        candidates.extend(direct)
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                candidates.extend(
                    [
                        child / "bin" / "java.exe",
                        child / "jre" / "bin" / "java.exe",
                        child / "Contents" / "Home" / "bin" / "java.exe",
                    ]
                )
        except OSError:
            continue
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / "java.exe")
    which = shutil.which("java")
    if which:
        candidates.append(Path(which))
    return _unique_paths([path for path in candidates if path.is_file()])


def _pcl_java_hints() -> list[str]:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    config = appdata / "PCL" / "config.json"
    try:
        with config.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        result = []
        for item in data.get("JavaList", []):
            folder = item.get("Folder")
            if folder:
                result.append(str(Path(folder) / "java.exe"))
        return result
    except Exception:
        return []


class JavaManager:
    def __init__(self) -> None:
        self._cache: list[JavaInfo] = []
        self._cache_time = 0.0
        self._runtime_manifest: dict[str, Any] | None = None
        self.runtime_manifest_file = CACHE_DIR / "java_runtime_manifest.json"

    def detect(self, force: bool = False) -> list[JavaInfo]:
        if not force and self._cache and time.time() - self._cache_time < 120:
            return list(self._cache)
        hints = _pcl_java_hints()
        found: list[JavaInfo] = []
        for candidate in _collect_candidates(hints):
            info = probe_java(candidate)
            if info is not None:
                found.append(info)
        found.sort(key=lambda item: (item.major, item.version), reverse=True)
        self._cache = found
        self._cache_time = time.time()
        return list(found)

    def select(self, required_major: int, override: str = "") -> JavaInfo | None:
        if override:
            path = Path(override)
            info = probe_java(path / "java.exe" if path.is_dir() else path)
            if info is not None:
                return info
            return None
        candidates = self.detect()
        if not candidates:
            return None
        if required_major == 8:
            for info in sorted(candidates, key=lambda item: (item.major != 8, item.major)):
                if info.major == 8:
                    return info
            return None
        exact = [info for info in candidates if info.major == required_major]
        if exact:
            return exact[0]
        newer = sorted([info for info in candidates if info.major > required_major], key=lambda item: item.major)
        if newer:
            return newer[0]
        return None

    def best_available(self) -> JavaInfo | None:
        candidates = self.detect()
        return candidates[0] if candidates else None

    def download_runtime(
        self,
        component: str,
        progress: Callable[[int, str], None] | None = None,
        cancel: Any = None,
    ) -> JavaInfo:
        manifest = self._get_runtime_manifest()
        platform_data = manifest.get("windows-x64") or {}
        entry = platform_data.get(component)
        if not entry:
            raise DownloadError(f"当前系统没有可用的 Java 运行时组件：{component}")
        entries = entry if isinstance(entry, list) else [entry]
        entries = [item for item in entries if isinstance(item, dict)]
        if not entries:
            raise DownloadError(f"Java 运行时组件 {component} 的清单无效")
        items = entries[0].get("manifest") or {}
        if isinstance(items, list):
            items = items[0] if items else {}
        manifest_url = items.get("url", "") if isinstance(items, dict) else ""
        if not manifest_url:
            raise DownloadError("Java 运行时清单地址无效")
        runtime_manifest = fetch_json(manifest_url, timeout=30)
        files = runtime_manifest.get("files") or {}
        if not isinstance(files, dict):
            raise DownloadError("Java 运行时文件清单无效")
        destination = RUNTIME_DIR / component
        destination.mkdir(parents=True, exist_ok=True)
        java_exe = destination / "bin" / "java.exe"
        if java_exe.is_file():
            info = probe_java(java_exe)
            if info:
                return info

        download_items: list[DownloadItem] = []
        for relative, info in files.items():
            if not isinstance(info, dict) or info.get("type") != "file":
                continue
            downloads = info.get("downloads") or {}
            raw = downloads.get("raw") or {}
            url = raw.get("url")
            if not url:
                continue
            target = destination / Path(str(relative).replace("/", os.sep))
            download_items.append(
                DownloadItem(
                    urls=[url],
                    destination=target,
                    size=int(raw.get("size") or 0),
                    sha1=str(raw.get("sha1") or ""),
                    label=str(relative),
                    kind="raw",
                )
            )

        def reporter(done: int, total: int, text: str, speed: float) -> None:
            if progress is None:
                return
            percent = 0 if total <= 0 else min(99, int(done * 100 / total))
            progress(percent, f"下载 Java 运行时 · {done / 1048576:.1f}/{total / 1048576:.1f} MB")

        download_many(download_items, reporter, max_workers=8, cancel=cancel, text="下载 Java 运行时")
        info = probe_java(java_exe)
        if info is None:
            raise DownloadError("Java 运行时下载完成，但无法启动 java.exe")
        if progress:
            progress(100, f"Java 运行时已就绪（Java {info.major}）")
        return info

    def ensure(
        self,
        required_major: int,
        component: str = "",
        override: str = "",
        auto_download: bool = True,
        progress: Callable[[int, str], None] | None = None,
        cancel: Any = None,
    ) -> JavaInfo:
        info = self.select(required_major, override)
        if info is not None:
            return info
        if not auto_download:
            raise DownloadError(
                f"未找到 Java {required_major}，请在设置中指定 Java 路径，或开启自动下载 Java"
            )
        component = component or component_for_major(required_major)
        info = self.download_runtime(component, progress=progress, cancel=cancel)
        self.detect(force=True)
        if required_major != 8 and info.major < required_major:
            raise DownloadError(f"下载的 Java 版本过低（{info.major}），需要 Java {required_major}")
        return info

    def _get_runtime_manifest(self) -> dict[str, Any]:
        if self._runtime_manifest is not None:
            return self._runtime_manifest
        try:
            if self.runtime_manifest_file.is_file() and time.time() - self.runtime_manifest_file.stat().st_mtime < 86400:
                with self.runtime_manifest_file.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    self._runtime_manifest = data
                    return data
        except Exception:
            pass
        data = fetch_json(JAVA_RUNTIME_MANIFEST_URL, timeout=30)
        if not isinstance(data, dict):
            raise DownloadError("Java 运行时清单格式无效")
        self._runtime_manifest = data
        try:
            self.runtime_manifest_file.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_manifest_file.open("w", encoding="utf-8") as handle:
                json.dump(data, handle)
        except Exception:
            pass
        return data


COMPONENT_BY_MAJOR = {
    8: "jre-legacy",
    16: "java-runtime-alpha",
    17: "java-runtime-gamma",
    21: "java-runtime-delta",
    25: "java-runtime-epsilon",
}


def component_for_major(major: int) -> str:
    if major in COMPONENT_BY_MAJOR:
        return COMPONENT_BY_MAJOR[major]
    lower = [key for key in COMPONENT_BY_MAJOR if key <= major]
    if lower:
        return COMPONENT_BY_MAJOR[max(lower)]
    return "java-runtime-gamma"


def component_from_version(version: dict[str, Any]) -> str:
    java_version = version.get("javaVersion")
    if isinstance(java_version, dict):
        component = java_version.get("component")
        if component:
            return str(component)
    from .version import required_java_major

    return component_for_major(required_java_major(version))
