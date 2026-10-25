from __future__ import annotations

import copy
import json
import platform
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .net import DownloadError, fetch_json, read_text
from .paths import CACHE_DIR, MIRROR_MANIFEST_URL, OFFICIAL_MANIFEST_URL

OS_NAME = "windows"
ARCH = "x86_64" if sys.maxsize > 2**32 else "x86"
OS_VERSION = platform.version() or "10.0"


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(part) for part in parts) if parts else (0,)


def _version_in_range(value: str, minimum: str = "", maximum: str = "") -> bool:
    current = _version_tuple(value)
    if minimum and current < _version_tuple(minimum):
        return False
    if maximum and current > _version_tuple(maximum):
        return False
    return True


def _rule_matches(rule: dict[str, Any], features: dict[str, bool]) -> bool:
    os_rule = rule.get("os")
    if isinstance(os_rule, dict):
        if os_rule.get("name") and os_rule["name"] != OS_NAME:
            return False
        arch = os_rule.get("arch")
        if arch:
            arch = str(arch)
            if arch == "x86":
                if ARCH != "x86":
                    return False
            elif arch in ("x86_64", "amd64"):
                if ARCH != "x86_64":
                    return False
            elif arch == "arm64":
                if ARCH != "arm64":
                    return False
        if os_rule.get("version"):
            try:
                if not re.search(str(os_rule["version"]), OS_VERSION):
                    return False
            except re.error:
                pass
        range_rule = os_rule.get("versionRange")
        if isinstance(range_rule, dict):
            if not _version_in_range(OS_VERSION, str(range_rule.get("min", "")), str(range_rule.get("max", ""))):
                return False
    feature_rule = rule.get("features")
    if isinstance(feature_rule, dict):
        for key, expected in feature_rule.items():
            if bool(features.get(key, False)) != bool(expected):
                return False
    return True


def rules_allow(rules: Any, features: dict[str, bool] | None = None) -> bool:
    if not isinstance(rules, list) or not rules:
        return True
    features = features or {}
    allowed = False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if _rule_matches(rule, features):
            allowed = rule.get("action", "allow") == "allow"
    return allowed


def maven_to_path(name: str) -> str:
    base, _, extension = name.partition("@")
    extension = extension or "jar"
    parts = base.split(":")
    if len(parts) < 3:
        return ""
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else ""
    file_name = f"{artifact}-{version}"
    if classifier:
        file_name += f"-{classifier}"
    file_name += f".{extension}"
    return "/".join(group.split(".") + [artifact, version, file_name])


def library_artifact(library: dict[str, Any]) -> dict[str, Any]:
    downloads = library.get("downloads") or {}
    artifact = downloads.get("artifact")
    if isinstance(artifact, dict):
        return artifact
    path = maven_to_path(str(library.get("name", "")))
    if not path:
        return {}
    base = str(library.get("url", "")).rstrip("/")
    url = f"{base}/{path}" if base else ""
    return {"path": path, "url": url}


def library_native(library: dict[str, Any]) -> dict[str, Any]:
    natives = library.get("natives")
    if not isinstance(natives, dict):
        return {}
    classifier = natives.get(OS_NAME)
    if not classifier:
        return {}
    classifier = str(classifier).replace("${arch}", "64" if ARCH == "x86_64" else "32")
    downloads = library.get("downloads") or {}
    classifiers = downloads.get("classifiers") or {}
    artifact = classifiers.get(classifier)
    if isinstance(artifact, dict):
        return artifact
    path = maven_to_path(str(library.get("name", "")) + ":" + classifier)
    if not path:
        return {}
    base = str(library.get("url", "")).rstrip("/")
    url = f"{base}/{path}" if base else ""
    return {"path": path, "url": url}


def _merge_libraries(parent: list[Any], child: list[Any]) -> list[Any]:
    result: list[Any] = []
    index: dict[str, int] = {}
    for library in list(parent) + list(child):
        if not isinstance(library, dict):
            continue
        name = str(library.get("name", ""))
        if name and name in index:
            result[index[name]] = copy.deepcopy(library)
        else:
            if name:
                index[name] = len(result)
            result.append(copy.deepcopy(library))
    return result


def _merge_arguments(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in set(parent) | set(child):
        pvalue = parent.get(key)
        cvalue = child.get(key)
        if key in ("game", "jvm") and isinstance(pvalue, list) and isinstance(cvalue, list):
            merged[key] = copy.deepcopy(pvalue) + copy.deepcopy(cvalue)
        elif isinstance(pvalue, dict) and isinstance(cvalue, dict):
            merged[key] = {**copy.deepcopy(pvalue), **copy.deepcopy(cvalue)}
        elif cvalue is not None:
            merged[key] = copy.deepcopy(cvalue)
        elif pvalue is not None:
            merged[key] = copy.deepcopy(pvalue)
    return merged


def merge_version(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(parent)
    for key, value in child.items():
        if key in ("libraries", "arguments", "minecraftArguments", "inheritsFrom", "downloads", "id"):
            continue
        merged[key] = copy.deepcopy(value)
    merged["id"] = child.get("id") or parent.get("id")
    downloads = copy.deepcopy(parent.get("downloads") or {})
    if isinstance(child.get("downloads"), dict):
        downloads.update(copy.deepcopy(child["downloads"]))
    if downloads:
        merged["downloads"] = downloads

    merged["libraries"] = _merge_libraries(parent.get("libraries") or [], child.get("libraries") or [])
    if isinstance(parent.get("arguments"), dict) and isinstance(child.get("arguments"), dict):
        merged["arguments"] = _merge_arguments(parent["arguments"], child["arguments"])
    elif isinstance(child.get("arguments"), dict):
        merged["arguments"] = copy.deepcopy(child["arguments"])
    if child.get("minecraftArguments"):
        merged["minecraftArguments"] = child["minecraftArguments"]

    base_jar = parent.get("_client_jar_id") or parent.get("id")
    if isinstance(child.get("downloads"), dict) and child["downloads"].get("client"):
        base_jar = child.get("id") or base_jar
    merged["_client_jar_id"] = base_jar
    chain = list(parent.get("_version_chain") or [parent.get("id")])
    child_id = child.get("id") or ""
    if child_id and child_id not in chain:
        chain.append(child_id)
    merged["_version_chain"] = chain
    return merged


def read_version_json(game_dir: Path, version_id: str) -> dict[str, Any]:
    candidates = [
        game_dir / "versions" / version_id / f"{version_id}.json",
        game_dir / "versions" / f"{version_id}.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
            except Exception as error:
                raise DownloadError(f"版本文件解析失败：{path}\n{error}") from error
    raise FileNotFoundError(f"未找到版本 {version_id} 的 JSON，请先安装该版本")


def resolve_version(game_dir: Path, version_id: str, _stack: tuple[str, ...] = ()) -> dict[str, Any]:
    if version_id in _stack:
        raise DownloadError(f"版本继承出现循环：{' -> '.join(_stack + (version_id,))}")
    if len(_stack) > 8:
        raise DownloadError("版本继承层数过多")
    raw = read_version_json(game_dir, version_id)
    parent_id = raw.get("inheritsFrom")
    if parent_id:
        parent = resolve_version(game_dir, str(parent_id), _stack + (version_id,))
        return merge_version(parent, raw)
    result = copy.deepcopy(raw)
    result.setdefault("id", version_id)
    result["_client_jar_id"] = raw.get("jar") or result["id"]
    result["_version_chain"] = [result["id"]]
    return result


def required_java_major(version: dict[str, Any]) -> int:
    java_version = version.get("javaVersion")
    if isinstance(java_version, dict):
        try:
            major = int(java_version.get("majorVersion"))
            if major > 0:
                return major
        except (TypeError, ValueError):
            pass
    version_id = str(version.get("id", ""))
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_id)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3) or 0)
        if major == 1:
            if minor >= 21 or (minor == 20 and patch >= 5):
                return 21
            if minor >= 18:
                return 17
            if minor >= 17:
                return 16
        elif major >= 2:
            return 21
        return 8
    return 8


def version_type(version: dict[str, Any]) -> str:
    return str(version.get("type") or "release")


def type_label(value: str) -> str:
    return {
        "release": "正式版",
        "snapshot": "快照",
        "old_beta": "远古 Beta",
        "old_alpha": "远古 Alpha",
        "fabric": "Fabric",
        "forge": "Forge",
        "neoforge": "NeoForge",
        "quilt": "Quilt",
    }.get(value, value or "未知")


def loader_name(version_id: str) -> str:
    lowered = version_id.lower()
    if "neoforge" in lowered:
        return "NeoForge"
    if "fabric" in lowered:
        return "Fabric"
    if "quilt" in lowered:
        return "Quilt"
    if "forge" in lowered:
        return "Forge"
    if "optifine" in lowered:
        return "OptiFine"
    return "原版"


def client_jar_path(game_dir: Path, version: dict[str, Any]) -> Path:
    jar_id = version.get("_client_jar_id") or version.get("jar") or version.get("id")
    return game_dir / "versions" / str(jar_id) / f"{jar_id}.jar"


def base_version_id(game_dir: Path, version_id: str) -> str:
    try:
        resolved = resolve_version(game_dir, version_id)
        chain = resolved.get("_version_chain") or []
        if isinstance(chain, list) and chain:
            return str(chain[0])
    except Exception:
        pass
    return version_id


def ensure_instance_layout(game_dir: Path, version_id: str) -> Path:
    folder = game_dir / "versions" / version_id
    if not folder.is_dir() or loader_name(version_id) == "原版":
        return folder
    try:
        raw = read_version_json(game_dir, version_id)
    except Exception:
        return folder
    if raw.get("inheritsFrom"):
        return folder
    for name in ("mods", "config", "saves", "resourcepacks", "shaderpacks", "crash-reports", "logs"):
        try:
            (folder / name).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return folder


def minecraft_version_from_id(value: str) -> str:
    text = str(value or "")
    if text.lower().startswith("fabric-loader-"):
        match = re.search(r"-(\d+\.\d+(?:\.\d+)?)$", text)
        if match:
            return match.group(1)
    match = re.match(r"(\d+\.\d+(?:\.\d+)?)", text)
    if match:
        return match.group(1)
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
    return match.group(1) if match else ""


def instance_dir_for_version(game_dir: Path, version_id: str) -> Path:
    folder = game_dir / "versions" / version_id
    try:
        if folder.is_dir():
            for name in ("mods", "saves", "config", "options.txt", "resourcepacks", "shaderpacks"):
                if (folder / name).exists():
                    return folder
    except OSError:
        pass
    return game_dir


def logging_file(version: dict[str, Any]) -> dict[str, Any]:
    logging = version.get("logging")
    if not isinstance(logging, dict):
        return {}
    client = logging.get("client")
    if not isinstance(client, dict):
        return {}
    file_info = client.get("file")
    if not isinstance(file_info, dict):
        return {}
    return {"argument": client.get("argument", ""), "file": file_info}


def allowed_libraries(version: dict[str, Any], features: dict[str, bool] | None = None) -> list[dict[str, Any]]:
    result = []
    for library in version.get("libraries") or []:
        if isinstance(library, dict) and rules_allow(library.get("rules"), features):
            result.append(library)
    return result


def collect_classpath(game_dir: Path, version: dict[str, Any]) -> list[Path]:
    entries: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            entries.append(path)

    for library in allowed_libraries(version):
        downloads = library.get("downloads") or {}
        if library.get("natives") and not downloads.get("artifact") and not library.get("url"):
            continue
        artifact = library_artifact(library)
        path = artifact.get("path")
        if path:
            add(game_dir / "libraries" / str(path).replace("/", "\\"))
    add(client_jar_path(game_dir, version))
    return entries


def native_artifacts(version: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for library in allowed_libraries(version):
        native = library_native(library)
        if native and native.get("path"):
            result.append(
                {
                    "artifact": native,
                    "exclude": (library.get("extract") or {}).get("exclude") or [],
                }
            )
    return result


@dataclass
class LocalVersion:
    id: str
    directory: Path
    json_path: Path
    raw: dict[str, Any]
    modified: float
    version_type: str = "release"
    loader: str = "原版"
    base_id: str = ""
    complete: bool = True

    @property
    def display_type(self) -> str:
        return type_label(self.version_type)

    @property
    def size_hint(self) -> str:
        return ""


def _best_effort_raw(game_dir: Path, version_id: str, depth: int = 0) -> dict[str, Any]:
    try:
        return read_version_json(game_dir, version_id)
    except Exception:
        return {}


def list_local_versions(game_dir: Path) -> list[LocalVersion]:
    versions_dir = game_dir / "versions"
    if not versions_dir.is_dir():
        return []
    result: list[LocalVersion] = []
    seen: set[str] = set()
    candidates: list[tuple[Path, Path]] = []
    for child in versions_dir.iterdir():
        try:
            if child.is_dir():
                json_path = child / f"{child.name}.json"
                if json_path.is_file():
                    candidates.append((child, json_path))
            elif child.suffix.lower() == ".json":
                candidates.append((versions_dir, child))
        except OSError:
            continue
    for directory, json_path in candidates:
        try:
            with json_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                continue
            version_id = str(raw.get("id") or json_path.stem)
            if version_id in seen:
                continue
            seen.add(version_id)
            raw_type = str(raw.get("type") or "")
            base_id = str(raw.get("inheritsFrom") or version_id)
            if not raw_type and raw.get("inheritsFrom"):
                parent = _best_effort_raw(game_dir, str(raw["inheritsFrom"]))
                raw_type = str(parent.get("type") or "release")
            loader = loader_name(version_id)
            jar = directory / f"{base_id}.jar" if directory.name == base_id else versions_dir / base_id / f"{base_id}.jar"
            if raw.get("jar"):
                jar = versions_dir / str(raw["jar"]) / f"{raw['jar']}.jar"
            complete = json_path.is_file()
            if base_id == version_id:
                complete = jar.is_file()
            result.append(
                LocalVersion(
                    id=version_id,
                    directory=directory,
                    json_path=json_path,
                    raw=raw,
                    modified=json_path.stat().st_mtime,
                    version_type=raw_type or "release",
                    loader=loader,
                    base_id=base_id,
                    complete=complete,
                )
            )
        except Exception:
            continue
    result.sort(key=lambda item: item.modified, reverse=True)
    return result


class VersionManifest:
    def __init__(self, source: str = "auto") -> None:
        self.source = source
        self.data: dict[str, Any] = {}
        self.versions: list[dict[str, Any]] = []
        self.latest: dict[str, str] = {}
        self.cache_file = CACHE_DIR / "version_manifest.json"
        self.used_mirror = False
        self.stale = False

    def load(self, force: bool = False, max_age: float = 600.0) -> "VersionManifest":
        if not force and self.data:
            return self
        raw: Any = None
        if not force:
            raw = self._read_cache()
        if raw is None or force:
            urls = []
            if self.source == "mirror":
                urls = [MIRROR_MANIFEST_URL, OFFICIAL_MANIFEST_URL]
            elif self.source == "official":
                urls = [OFFICIAL_MANIFEST_URL]
            else:
                urls = [OFFICIAL_MANIFEST_URL, MIRROR_MANIFEST_URL]
            errors = []
            for index, url in enumerate(urls):
                try:
                    raw = json.loads(read_text(url, timeout=25))
                    self.used_mirror = "bmclapi" in url
                    break
                except Exception as error:
                    errors.append(error)
            if raw is None:
                cached = self._read_cache(ignore_age=True)
                if cached is not None:
                    raw = cached
                    self.stale = True
                else:
                    detail = "\n".join(str(item) for item in errors)
                    raise DownloadError(f"获取 Minecraft 版本列表失败：\n{detail}")
            else:
                self._write_cache(raw)
        self._apply(raw)
        return self

    def _read_cache(self, ignore_age: bool = False) -> Any:
        try:
            if not self.cache_file.is_file():
                return None
            with self.cache_file.open("r", encoding="utf-8") as handle:
                cached = json.load(handle)
            fetched = float(cached.get("_fetched_at", 0))
            if not ignore_age and time.time() - fetched > 600:
                return None
            data = cached.get("data")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write_cache(self, data: dict[str, Any]) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump({"_fetched_at": time.time(), "data": data}, handle, ensure_ascii=False)
            tmp.replace(self.cache_file)
        except Exception:
            pass

    def _apply(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise DownloadError("版本列表格式错误")
        versions = data.get("versions")
        if not isinstance(versions, list):
            raise DownloadError("版本列表缺少 versions 字段")
        self.data = data
        self.versions = [item for item in versions if isinstance(item, dict) and item.get("id")]
        latest = data.get("latest")
        self.latest = latest if isinstance(latest, dict) else {}

    def find(self, version_id: str) -> dict[str, Any] | None:
        for version in self.versions:
            if version.get("id") == version_id:
                return version
        return None

    def release_versions(self) -> list[dict[str, Any]]:
        return [version for version in self.versions if version.get("type") == "release"]


def fetch_remote_version(version_id: str, entry_url: str, source: str = "auto") -> dict[str, Any]:
    cache_file = CACHE_DIR / "versions" / f"{version_id}.json"
    try:
        if cache_file.is_file():
            with cache_file.open("r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if isinstance(cached, dict) and cached.get("id") == version_id:
                return cached
    except Exception:
        pass
    urls = []
    if entry_url:
        urls.append(entry_url)
    mirror = f"{MIRROR_MANIFEST_URL.split('/mc/')[0]}/version/{version_id}/json"
    if source == "mirror":
        urls = [mirror, entry_url] if entry_url else [mirror]
    elif source == "auto":
        urls = ([entry_url] if entry_url else []) + [mirror]
    data = fetch_json([url for url in urls if url], timeout=30)
    if not isinstance(data, dict):
        raise DownloadError(f"版本 {version_id} 的 JSON 格式错误")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        tmp.replace(cache_file)
    except Exception:
        pass
    return data


def asset_index_id(version: dict[str, Any]) -> str:
    index = version.get("assetIndex")
    if isinstance(index, dict) and index.get("id"):
        return str(index["id"])
    return str(version.get("assets") or "")


def game_assets_dir(game_dir: Path, version: dict[str, Any]) -> Path:
    index_id = asset_index_id(version)
    if index_id in ("legacy", "pre-1.6"):
        index_id = "legacy"
    return game_dir / "assets" / "virtual" / index_id
