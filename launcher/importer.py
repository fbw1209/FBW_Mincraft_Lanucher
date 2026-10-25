from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from .installer import install_version
from .net import DownloadError
from .version import VersionManifest, list_local_versions, read_version_json

Progress = Callable[[int, str], None]


def _emit(progress: Progress | None, percent: int, text: str) -> None:
    if progress is not None:
        try:
            progress(max(0, min(100, int(percent))), text)
        except Exception:
            pass


def _looks_like_version_json(path: Path) -> bool:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return False
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return isinstance(data, dict) and bool(data.get("id")) and (
            "mainClass" in data or "inheritsFrom" in data or "libraries" in data
        )
    except Exception:
        return False


def _scan_versions(root: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    if not root.is_dir():
        return result
    if (root / f"{root.name}.json").is_file() and _looks_like_version_json(root / f"{root.name}.json"):
        return [(root.name, root)]
    versions_dir = root / "versions" if (root / "versions").is_dir() else root
    try:
        children = list(versions_dir.iterdir())
    except OSError:
        return result
    for child in children:
        try:
            if child.is_dir():
                json_path = child / f"{child.name}.json"
                if json_path.is_file() and _looks_like_version_json(json_path):
                    result.append((child.name, child))
        except OSError:
            continue
    if result:
        return result
    for json_path in root.rglob("*.json"):
        try:
            if not _looks_like_version_json(json_path):
                continue
            if json_path.stem != json_path.parent.name:
                continue
            result.append((json_path.parent.name, json_path.parent))
        except OSError:
            continue
    return result


def import_versions(
    game_dir: Path,
    source_path: Path,
    source: str = "auto",
    manifest: VersionManifest | None = None,
    progress: Progress | None = None,
    cancel: Any = None,
) -> list[str]:
    game_dir.mkdir(parents=True, exist_ok=True)
    temp_dir: Path | None = None
    try:
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            _emit(progress, 2, "解压版本压缩包")
            temp_dir = Path(tempfile.mkdtemp(prefix="fml-import-"))
            with zipfile.ZipFile(source_path) as archive:
                for member in archive.infolist():
                    target = temp_dir / member.filename
                    try:
                        target.resolve().relative_to(temp_dir.resolve())
                    except Exception:
                        continue
                    archive.extract(member, temp_dir)
            scan_root = temp_dir
        else:
            scan_root = source_path

        candidates = _scan_versions(scan_root)
        if not candidates:
            raise DownloadError("没有在所选位置找到可导入的版本")

        imported: list[str] = []
        _emit(progress, 10, f"发现 {len(candidates)} 个版本")
        for index, (folder_name, folder) in enumerate(candidates):
            if cancel is not None and cancel.is_set():
                raise DownloadError("导入已取消")
            try:
                json_path = folder / f"{folder_name}.json"
                if not json_path.is_file():
                    continue
                with json_path.open("r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                version_id = str(raw.get("id") or folder_name)
                destination = game_dir / "versions" / version_id
                destination.mkdir(parents=True, exist_ok=True)
                if destination.resolve() != folder.resolve():
                    shutil.copytree(folder, destination, dirs_exist_ok=True)
                if json_path.name != f"{version_id}.json":
                    shutil.copy2(json_path, destination / f"{version_id}.json")
                imported.append(version_id)
            except Exception:
                continue
            percent = 10 + int(30 * (index + 1) / max(1, len(candidates)))
            _emit(progress, percent, f"导入版本 {folder_name}")

        imported = list(dict.fromkeys(imported))
        if not imported:
            raise DownloadError("版本文件复制失败")

        _emit(progress, 42, "补充运行库与资源文件")
        errors: list[str] = []
        for index, version_id in enumerate(imported):
            if cancel is not None and cancel.is_set():
                raise DownloadError("导入已取消")
            try:
                version = read_version_json(game_dir, version_id)
                parent_id = str(version.get("inheritsFrom") or "")
                if parent_id:
                    installed = {item.id for item in list_local_versions(game_dir)}
                    if parent_id not in installed:
                        entry_url = ""
                        if manifest is not None:
                            entry = manifest.find(parent_id)
                            if entry:
                                entry_url = str(entry.get("url") or "")
                        install_version(
                            game_dir,
                            parent_id,
                            entry_url=entry_url,
                            source=source,
                            progress=lambda percent, text: _emit(progress, 42 + int(percent * 20 / 100), text),
                            cancel=cancel,
                        )
                install_version(
                    game_dir,
                    version_id,
                    source=source,
                    progress=lambda percent, text, idx=index: _emit(
                        progress,
                        62 + int((idx + percent / 100) * 38 / max(1, len(imported))),
                        text,
                    ),
                    cancel=cancel,
                )
            except Exception as error:
                errors.append(f"{version_id}: {error}")
        _emit(progress, 100, f"导入完成，共 {len(imported)} 个版本")
        if errors and len(errors) == len(imported):
            raise DownloadError("导入后无法补齐文件：\n" + "\n".join(errors[:3]))
        return imported
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
