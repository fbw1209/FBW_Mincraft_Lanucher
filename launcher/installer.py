from __future__ import annotations

import copy
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Callable

from .net import (
    DownloadError,
    DownloadItem,
    fetch_json,
    download_many,
    url_candidates,
)
from .paths import FABRIC_META
from .version import (
    allowed_libraries,
    ensure_instance_layout,
    asset_index_id,
    client_jar_path,
    fetch_remote_version,
    library_artifact,
    library_native,
    logging_file,
    resolve_version,
)

Progress = Callable[[int, str], None]


def _emit(progress: Progress | None, percent: int, text: str) -> None:
    if progress is not None:
        try:
            progress(max(0, min(100, int(percent))), text)
        except Exception:
            pass


class _Stage:
    def __init__(self, progress: Progress | None, base: int, span: int) -> None:
        self.progress = progress
        self.base = base
        self.span = span

    def __call__(self, percent: int, text: str) -> None:
        _emit(self.progress, self.base + self.span * max(0, min(100, percent)) / 100, text)

    def download_reporter(self, prefix: str) -> Callable[[int, int, str, float], None]:
        def reporter(done: int, total: int, text: str, speed: float) -> None:
            percent = 0 if total <= 0 else min(100, int(done * 100 / total))
            speed_text = f" · {speed / 1048576:.1f} MB/s" if speed > 0 else ""
            self(percent, f"{prefix} · {done / 1048576:.1f}/{total / 1048576:.1f} MB{speed_text}")

        return reporter


def _write_version_json(game_dir: Path, version_id: str, data: dict[str, Any]) -> Path:
    directory = game_dir / "versions" / version_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version_id}.json"
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def _client_item(game_dir: Path, version: dict[str, Any], source: str) -> DownloadItem:
    jar_id = version.get("_client_jar_id") or version.get("id")
    downloads = version.get("downloads") or {}
    info = downloads.get("client") or {}
    url = info.get("url") or ""
    urls = url_candidates(url, "client", source, str(jar_id))
    if not urls:
        mirror = f"https://bmclapi2.bangbang93.com/version/{jar_id}/client"
        urls = [mirror]
    return DownloadItem(
        urls=urls,
        destination=client_jar_path(game_dir, version),
        size=int(info.get("size") or 0),
        sha1=str(info.get("sha1") or ""),
        label=f"{jar_id}.jar",
        kind="client",
    )


def _library_items(game_dir: Path, version: dict[str, Any], source: str) -> list[DownloadItem]:
    items: dict[str, DownloadItem] = {}
    for library in allowed_libraries(version):
        artifact = library_artifact(library)
        path = artifact.get("path")
        if path:
            destination = game_dir / "libraries" / str(path).replace("/", os.sep)
            url = artifact.get("url") or ""
            urls = url_candidates(url, "library", source)
            if not urls and url:
                urls = [url]
            if urls:
                item = DownloadItem(
                    urls=urls,
                    destination=destination,
                    size=int(artifact.get("size") or library.get("size") or 0),
                    sha1=str(artifact.get("sha1") or library.get("sha1") or ""),
                    label=str(path).rsplit("/", 1)[-1],
                    kind="library",
                )
                items[str(destination).lower()] = item
        native = library_native(library)
        native_path = native.get("path")
        if native_path:
            destination = game_dir / "libraries" / str(native_path).replace("/", os.sep)
            url = native.get("url") or ""
            urls = url_candidates(url, "library", source)
            if urls:
                items[str(destination).lower()] = DownloadItem(
                    urls=urls,
                    destination=destination,
                    size=int(native.get("size") or 0),
                    sha1=str(native.get("sha1") or ""),
                    label=str(native_path).rsplit("/", 1)[-1],
                    kind="library",
                )
    return list(items.values())


def _logging_item(game_dir: Path, version: dict[str, Any], source: str) -> DownloadItem | None:
    info = logging_file(version)
    if not info:
        return None
    file_info = info.get("file") or {}
    url = str(file_info.get("url") or "")
    file_id = str(file_info.get("id") or "client-log.xml")
    if not url:
        return None
    destination = game_dir / "assets" / "log_configs" / file_id
    return DownloadItem(
        urls=url_candidates(url, "raw", source),
        destination=destination,
        size=int(file_info.get("size") or 0),
        sha1=str(file_info.get("sha1") or ""),
        label=file_id,
        kind="raw",
    )


def _ensure_asset_index(
    game_dir: Path,
    version: dict[str, Any],
    source: str,
    stage: _Stage,
    cancel: threading.Event | None,
) -> tuple[dict[str, Any] | None, Path | None]:
    index_info = version.get("assetIndex")
    if not isinstance(index_info, dict):
        return None, None
    index_id = asset_index_id(version)
    if not index_id:
        return None, None
    path = game_dir / "assets" / "indexes" / f"{index_id}.json"
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and isinstance(data.get("objects"), dict):
                return data, path
        except Exception:
            pass
    url = str(index_info.get("url") or "")
    if not url:
        raise DownloadError("该版本缺少资源索引下载地址")
    stage(2, "下载资源索引")
    download_many(
        [
            DownloadItem(
                urls=url_candidates(url, "asset_index", "auto"),
                destination=path,
                size=int(index_info.get("size") or 0),
                sha1=str(index_info.get("sha1") or ""),
                label=f"{index_id}.json",
                kind="asset_index",
            )
        ],
        None,
        max_workers=1,
        cancel=cancel,
    )
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise DownloadError("资源索引格式错误")
    return data, path


def _copy_asset(source: Path, destination: Path) -> None:
    try:
        if destination.is_file() and destination.stat().st_size == source.stat().st_size:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    except OSError:
        pass


def _prepare_virtual_assets(
    game_dir: Path,
    index: dict[str, Any],
    index_id: str,
    stage: _Stage | None,
) -> None:
    virtual = bool(index.get("virtual"))
    map_to_resources = bool(index.get("map_to_resources"))
    if not virtual and not map_to_resources:
        return
    objects = index.get("objects") or {}
    targets: list[tuple[Path, Path]] = []
    for name, info in objects.items():
        if not isinstance(info, dict) or not info.get("hash"):
            continue
        hash_value = str(info["hash"])
        source = game_dir / "assets" / "objects" / hash_value[:2] / hash_value
        if map_to_resources:
            targets.append((source, game_dir / "resources" / str(name)))
        if virtual:
            targets.append((source, game_dir / "assets" / "virtual" / index_id / str(name)))
        if map_to_resources and index_id in ("legacy", "pre-1.6"):
            targets.append((source, game_dir / "assets" / "virtual" / "legacy" / str(name)))
    total = len(targets)
    for index_number, (source, destination) in enumerate(targets):
        if stage is not None and total and index_number % 200 == 0:
            stage(int(index_number * 100 / total), "整理旧版资源文件")
        _copy_asset(source, destination)


def _download_assets(
    game_dir: Path,
    index: dict[str, Any],
    index_id: str,
    source: str,
    stage: _Stage,
    cancel: threading.Event | None,
) -> None:
    objects = index.get("objects") or {}
    if not isinstance(objects, dict):
        return
    items: dict[str, DownloadItem] = {}
    for name, info in objects.items():
        if not isinstance(info, dict):
            continue
        hash_value = str(info.get("hash") or "")
        if not hash_value:
            continue
        destination = game_dir / "assets" / "objects" / hash_value[:2] / hash_value
        url = f"https://resources.download.minecraft.net/{hash_value[:2]}/{hash_value}"
        if str(destination).lower() in items:
            continue
        items[str(destination).lower()] = DownloadItem(
            urls=url_candidates(url, "asset", source),
            destination=destination,
            size=int(info.get("size") or 0),
            sha1=hash_value,
            label=str(name),
            kind="asset",
        )
    if not items:
        return
    stage(0, "下载游戏资源")
    download_many(
        list(items.values()),
        stage.download_reporter("下载游戏资源"),
        max_workers=12,
        cancel=cancel,
        text="下载游戏资源",
    )
    _prepare_virtual_assets(game_dir, index, index_id, stage)



def merge_loader_version(game_dir: Path, loader_id: str, target_name: str) -> str:
    version = resolve_version(game_dir, loader_id)
    loader_dir = game_dir / "versions" / loader_id
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", target_name).strip().rstrip(".")
    if not safe_name:
        safe_name = target_name
    target_dir = game_dir / "versions" / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)
    base_jar = client_jar_path(game_dir, version)
    if not base_jar.is_file():
        raise DownloadError(f"合并版本失败，缺少客户端 jar：{base_jar}")
    if loader_dir.is_dir() and loader_dir.resolve() != target_dir.resolve():
        for child in loader_dir.iterdir():
            if child.name in (f"{loader_id}.json", f"{loader_id}.jar"):
                continue
            destination = target_dir / child.name
            try:
                if child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
            except OSError:
                pass
    data = {key: copy.deepcopy(value) for key, value in version.items() if not key.startswith("_")}
    data["id"] = safe_name
    data.pop("inheritsFrom", None)
    data.pop("jar", None)
    json_path = target_dir / f"{safe_name}.json"
    tmp = json_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, json_path)
    target_jar = target_dir / f"{safe_name}.jar"
    try:
        if base_jar.resolve() != target_jar.resolve():
            shutil.copy2(base_jar, target_jar)
    except OSError as error:
        raise DownloadError(f"复制客户端 jar 失败：{error}") from error
    if loader_dir.is_dir() and loader_dir.resolve() != target_dir.resolve():
        shutil.rmtree(loader_dir, ignore_errors=True)
    ensure_instance_layout(game_dir, safe_name)
    return safe_name


def install_version(
    game_dir: Path,
    version_id: str,
    entry_url: str = "",
    source: str = "auto",
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    force_json: bool = False,
) -> str:
    game_dir.mkdir(parents=True, exist_ok=True)
    stage = _Stage(progress, 0, 100)
    _emit(progress, 0, f"准备安装 {version_id}")
    json_path = game_dir / "versions" / version_id / f"{version_id}.json"
    if force_json or not json_path.is_file():
        _emit(progress, 1, "获取版本信息")
        data = fetch_remote_version(version_id, entry_url, source)
        data["id"] = version_id
        _write_version_json(game_dir, version_id, data)
    version = resolve_version(game_dir, version_id)

    _emit(progress, 2, "检查客户端文件")
    client_stage = _Stage(progress, 2, 12)
    client_item = _client_item(game_dir, version, source)
    download_many([client_item], client_stage.download_reporter("下载客户端"), max_workers=1, cancel=cancel)

    _emit(progress, 15, "检查运行库")
    library_stage = _Stage(progress, 15, 22)
    logging_item = _logging_item(game_dir, version, source)
    library_items = _library_items(game_dir, version, source)
    if logging_item is not None:
        library_items.append(logging_item)
    download_many(
        library_items,
        library_stage.download_reporter("下载运行库"),
        max_workers=8,
        cancel=cancel,
    )

    asset_stage = _Stage(progress, 38, 8)
    index, _ = _ensure_asset_index(game_dir, version, source, asset_stage, cancel)
    if index is not None:
        asset_stage = _Stage(progress, 46, 52)
        _download_assets(game_dir, index, asset_index_id(version), source, asset_stage, cancel)
    else:
        _emit(progress, 98, "该版本无需额外资源文件")

    _emit(progress, 99, "安装完成")
    _emit(progress, 100, f"{version_id} 安装完成")
    return version_id


def install_fabric(
    game_dir: Path,
    game_version: str,
    entry_url: str = "",
    source: str = "auto",
    loader_version: str = "",
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> str:
    game_dir.mkdir(parents=True, exist_ok=True)
    _emit(progress, 0, f"准备安装 Fabric（{game_version}）")

    install_version(
        game_dir,
        game_version,
        entry_url=entry_url,
        source=source,
        progress=lambda percent, text: _emit(progress, percent * 45 / 100, text),
        cancel=cancel,
    )

    _emit(progress, 46, "获取 Fabric Loader 版本")
    try:
        loader_list = fetch_json(f"{FABRIC_META}/{game_version}", timeout=25)
    except Exception as error:
        raise DownloadError(f"无法获取 Fabric 版本列表，可能该游戏版本不受支持。\n{error}") from error
    if not isinstance(loader_list, list) or not loader_list:
        raise DownloadError("Fabric 没有适配该版本的游戏")
    if not loader_version:
        stable = []
        for item in loader_list:
            loader = item.get("loader") if isinstance(item, dict) else None
            if isinstance(loader, dict) and loader.get("stable") and loader.get("version"):
                stable.append(str(loader["version"]))
        if stable:
            loader_version = stable[0]
        else:
            try:
                loader_version = str(loader_list[0]["loader"]["version"])
            except Exception as error:
                raise DownloadError("无法解析 Fabric Loader 版本") from error

    _emit(progress, 52, f"下载 Fabric Loader {loader_version}")
    profile_url = f"{FABRIC_META}/{game_version}/{loader_version}/profile/json"
    profile = fetch_json(profile_url, timeout=25)
    if not isinstance(profile, dict):
        raise DownloadError("Fabric 配置格式错误")
    fabric_id = str(profile.get("id") or f"fabric-loader-{loader_version}-{game_version}")
    profile["id"] = fabric_id
    profile.setdefault("inheritsFrom", game_version)
    profile["type"] = "fabric"
    _write_version_json(game_dir, fabric_id, profile)
    version = resolve_version(game_dir, fabric_id)

    _emit(progress, 60, "下载 Fabric 运行库")
    library_stage = _Stage(progress, 60, 38)
    items = _library_items(game_dir, version, source)
    logging_item = _logging_item(game_dir, version, source)
    if logging_item is not None:
        items.append(logging_item)
    download_many(items, library_stage.download_reporter("下载 Fabric 组件"), max_workers=8, cancel=cancel)

    target_name = f"{game_version}-Fabric {loader_version.split('+')[0]}"
    merged = merge_loader_version(game_dir, fabric_id, target_name)
    _emit(progress, 100, f"Fabric {loader_version} 安装完成")
    return merged
