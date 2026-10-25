from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .net import DownloadError, DownloadItem, download_many, read_text

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_MIRROR = "https://mod.mcimirror.top/modrinth/v2"
CURSEFORGE_API = "https://mod.mcimirror.top/curseforge/v1"

MODRINTH_TYPES = {
    "mod": "mod",
    "shader": "shader",
    "resourcepack": "resourcepack",
    "modpack": "modpack",
}
CURSEFORGE_CLASSES = {
    "mod": 6,
    "resourcepack": 12,
    "shader": 6552,
    "modpack": 4471,
}
CURSEFORGE_LOADERS = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}
TARGET_FOLDERS = {
    "mod": "mods",
    "shader": "shaderpacks",
    "resourcepack": "resourcepacks",
    "modpack": "modpacks",
}


@dataclass
class ResourceItem:
    source: str
    id: str
    name: str
    summary: str
    author: str
    downloads: int
    type_key: str
    slug: str = ""
    icon_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceFile:
    name: str
    filename: str
    url: str
    size: int = 0
    sha1: str = ""
    published: str = ""
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)
    version_id: str = ""


def _get_json(urls: list[str]) -> Any:
    errors = []
    for url in urls:
        try:
            return json.loads(read_text(url, timeout=18, attempts=1))
        except Exception as error:
            errors.append(str(error))
    raise DownloadError("资源接口请求失败：\n" + "\n".join(errors[-2:]))


def _modrinth_facets(type_key: str, mc_version: str, loader: str) -> str:
    facets: list[list[str]] = [[f"project_type:{MODRINTH_TYPES.get(type_key, type_key)}"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if type_key == "mod" and loader in ("fabric", "forge", "neoforge", "quilt"):
        facets.append([f"categories:{loader}"])
    return json.dumps(facets, separators=(",", ":"))


def search_modrinth(
    query: str,
    type_key: str,
    mc_version: str = "",
    loader: str = "",
    limit: int = 40,
) -> list[ResourceItem]:
    params = {
        "query": query,
        "limit": str(limit),
        "index": "relevance" if query else "downloads",
        "facets": _modrinth_facets(type_key, mc_version, loader),
    }
    url = MODRINTH_API + "/search?" + urllib.parse.urlencode(params)
    mirror = MODRINTH_MIRROR + "/search?" + urllib.parse.urlencode(params)
    data = _get_json([url, mirror])
    result: list[ResourceItem] = []
    for hit in data.get("hits", []) if isinstance(data, dict) else []:
        if not isinstance(hit, dict):
            continue
        result.append(
            ResourceItem(
                source="modrinth",
                id=str(hit.get("project_id") or ""),
                name=str(hit.get("title") or "未知项目"),
                summary=str(hit.get("description") or ""),
                author=str(hit.get("author") or ""),
                downloads=int(hit.get("downloads") or 0),
                type_key=type_key,
                slug=str(hit.get("slug") or ""),
                icon_url=str(hit.get("icon_url") or ""),
                raw=hit,
            )
        )
    return result


def search_curseforge(
    query: str,
    type_key: str,
    mc_version: str = "",
    loader: str = "",
    limit: int = 40,
) -> list[ResourceItem]:
    class_id = CURSEFORGE_CLASSES.get(type_key, 6)
    params: dict[str, str] = {
        "gameId": "432",
        "classId": str(class_id),
        "searchFilter": query,
        "pageSize": str(limit),
        "index": "0",
        "sortField": "2",
        "sortOrder": "desc",
    }
    if mc_version:
        params["gameVersion"] = mc_version
    if type_key == "mod" and loader in CURSEFORGE_LOADERS:
        params["modLoaderType"] = str(CURSEFORGE_LOADERS[loader])
    url = CURSEFORGE_API + "/mods/search?" + urllib.parse.urlencode(params)
    data = _get_json([url])
    result: list[ResourceItem] = []
    for item in data.get("data", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        authors = item.get("authors") or []
        author = ""
        if isinstance(authors, list) and authors and isinstance(authors[0], dict):
            author = str(authors[0].get("name") or "")
        logo = item.get("logo") or {}
        icon = ""
        if isinstance(logo, dict):
            icon = str(logo.get("thumbnailUrl") or logo.get("url") or "")
        result.append(
            ResourceItem(
                source="curseforge",
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "未知项目"),
                summary=str(item.get("summary") or ""),
                author=author,
                downloads=int(item.get("downloadCount") or 0),
                type_key=type_key,
                slug=str(item.get("slug") or ""),
                icon_url=icon,
                raw=item,
            )
        )
    return result


def search(
    source: str,
    query: str,
    type_key: str,
    mc_version: str = "",
    loader: str = "",
    limit: int = 40,
) -> list[ResourceItem]:
    if source == "curseforge":
        return search_curseforge(query, type_key, mc_version, loader, limit)
    return search_modrinth(query, type_key, mc_version, loader, limit)


def _cf_edge_url(file_id: int, filename: str) -> str:
    return f"https://edge.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{filename}"


def _file_sha1(hashes: Any) -> str:
    if isinstance(hashes, list):
        for item in hashes:
            if isinstance(item, dict) and int(item.get("algo") or 0) == 1:
                return str(item.get("value") or "")
    if isinstance(hashes, dict):
        return str(hashes.get("sha1") or "")
    return ""


def get_modrinth_files(item: ResourceItem, mc_version: str, loader: str) -> list[ResourceFile]:
    url = f"{MODRINTH_API}/project/{item.id}/version?include_changelog=false"
    mirror = f"{MODRINTH_MIRROR}/project/{item.id}/version?include_changelog=false"
    data = _get_json([url, mirror])
    result: list[ResourceFile] = []
    for version in data if isinstance(data, list) else []:
        if not isinstance(version, dict):
            continue
        game_versions = [str(v) for v in version.get("game_versions") or []]
        loaders = [str(v) for v in version.get("loaders") or []]
        if mc_version and game_versions and mc_version not in game_versions:
            continue
        if item.type_key == "mod" and loader in ("fabric", "forge", "neoforge", "quilt") and loaders:
            if loader not in loaders:
                continue
        files = version.get("files") or []
        if not isinstance(files, list) or not files:
            continue
        primary = next((f for f in files if isinstance(f, dict) and f.get("primary")), None)
        file_info = primary or files[0]
        if not isinstance(file_info, dict):
            continue
        result.append(
            ResourceFile(
                name=str(version.get("name") or version.get("version_number") or file_info.get("filename") or ""),
                filename=str(file_info.get("filename") or "download.bin"),
                url=str(file_info.get("url") or ""),
                size=int(file_info.get("size") or 0),
                sha1=str((file_info.get("hashes") or {}).get("sha1") or ""),
                published=str(version.get("date_published") or ""),
                game_versions=game_versions,
                loaders=loaders,
                version_id=str(version.get("id") or ""),
            )
        )
    result.sort(key=lambda file: file.published, reverse=True)
    return result


def get_curseforge_files(item: ResourceItem, mc_version: str, loader: str) -> list[ResourceFile]:
    params: dict[str, str] = {"pageSize": "50", "index": "0"}
    if mc_version:
        params["gameVersion"] = mc_version
    if item.type_key == "mod" and loader in CURSEFORGE_LOADERS:
        params["modLoaderType"] = str(CURSEFORGE_LOADERS[loader])
    url = f"{CURSEFORGE_API}/mods/{item.id}/files?" + urllib.parse.urlencode(params)
    data = _get_json([url])
    result: list[ResourceFile] = []
    for file_info in data.get("data", []) if isinstance(data, dict) else []:
        if not isinstance(file_info, dict):
            continue
        game_versions = [str(v) for v in file_info.get("gameVersions") or []]
        if mc_version and game_versions and mc_version not in game_versions:
            continue
        filename = str(file_info.get("fileName") or "download.bin")
        file_id = int(file_info.get("id") or 0)
        download_url = str(file_info.get("downloadUrl") or "")
        if not download_url and file_id:
            download_url = _cf_edge_url(file_id, filename)
        result.append(
            ResourceFile(
                name=str(file_info.get("displayName") or filename),
                filename=filename,
                url=download_url,
                size=int(file_info.get("fileLength") or 0),
                sha1=_file_sha1(file_info.get("hashes")),
                published=str(file_info.get("fileDate") or ""),
                game_versions=game_versions,
                loaders=game_versions,
                version_id=str(file_id),
            )
        )
    result.sort(key=lambda file: file.published, reverse=True)
    return result


def get_files(item: ResourceItem, mc_version: str, loader: str) -> list[ResourceFile]:
    if item.source == "curseforge":
        return get_curseforge_files(item, mc_version, loader)
    return get_modrinth_files(item, mc_version, loader)


def _download_candidates(url: str) -> list[str]:
    result = [url]
    if "cdn.modrinth.com" in url:
        result.append(url.replace("https://cdn.modrinth.com", "https://mod.mcimirror.top"))
    for host in ("https://edge.forgecdn.net", "https://mediafilez.forgecdn.net", "https://media.forgecdn.net"):
        if url.startswith(host):
            result.append("https://mod.mcimirror.top" + url[len(host):])
    return list(dict.fromkeys(item for item in result if item))


def safe_filename(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")
    return value or "download.bin"


def download_resource(
    item: ResourceItem,
    file: ResourceFile,
    game_dir: Path,
    progress: Callable[[int, str], None] | None = None,
    cancel: Any = None,
) -> Path:
    folder = game_dir / TARGET_FOLDERS.get(item.type_key, "mods")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / safe_filename(file.filename)
    urls = _download_candidates(file.url)
    if not urls:
        raise DownloadError("该文件没有可用的下载地址")

    def reporter(done: int, total: int, text: str, speed: float) -> None:
        if progress is None:
            return
        percent = 0 if total <= 0 else min(100, int(done * 100 / total))
        progress(percent, f"下载 {item.name} · {done / 1048576:.1f}/{total / 1048576:.1f} MB")

    download_many(
        [
            DownloadItem(
                urls=urls,
                destination=destination,
                size=file.size,
                sha1=file.sha1,
                label=file.filename,
                kind="mod",
            )
        ],
        reporter,
        max_workers=1,
        cancel=cancel,
    )
    if progress:
        progress(100, f"已保存到 {destination}")
    return destination


FABRIC_API_PROJECT_ID = "P7dR8mSH"


def fabric_api_installed(instance_dir: Path) -> bool:
    mods = instance_dir / "mods"
    try:
        if not mods.is_dir():
            return False
        for child in mods.iterdir():
            name = child.name.lower()
            if not child.is_file():
                continue
            if not (name.endswith(".jar") or name.endswith(".jar.disabled")):
                continue
            if "fabric-api" in name or "fabric_api" in name or name.startswith("fabricapi"):
                return True
    except OSError:
        return False
    return False


def ensure_fabric_api(
    instance_dir: Path,
    mc_version: str,
    progress: Callable[[int, str], None] | None = None,
    cancel: Any = None,
) -> Path | None:
    if not mc_version or fabric_api_installed(instance_dir):
        return None
    item = ResourceItem(
        source="modrinth",
        id=FABRIC_API_PROJECT_ID,
        name="Fabric API",
        summary="Fabric 模组开发与运行所需的基础 API",
        author="FabricMC",
        downloads=0,
        type_key="mod",
        slug="fabric-api",
    )
    files = get_modrinth_files(item, mc_version, "fabric")
    if not files:
        raise DownloadError(f"没有找到兼容 Minecraft {mc_version} 的 Fabric API")
    return download_resource(item, files[0], instance_dir, progress, cancel)
