from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .installer import install_version, merge_loader_version
from .net import DownloadError, download_file, fetch_json, read_text
from .version import list_local_versions, required_java_major, resolve_version

Progress = Callable[[int, str], None]
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class LoaderInstallError(RuntimeError):
    pass


def _emit(progress: Progress | None, percent: int, text: str) -> None:
    if progress is not None:
        try:
            progress(max(0, min(100, int(percent))), text)
        except Exception:
            pass


def _download_installer(url: str, destination: Path, progress: Progress | None, cancel: Any) -> None:
    mirror = ""
    if "maven.minecraftforge.net" in url:
        mirror = url.replace("https://maven.minecraftforge.net", "https://bmclapi2.bangbang93.com/maven")
    elif "maven.neoforged.net/releases" in url:
        mirror = url.replace("https://maven.neoforged.net/releases", "https://bmclapi2.bangbang93.com/maven")
    destination.parent.mkdir(parents=True, exist_ok=True)
    urls = [url] + ([mirror] if mirror else [])

    def reporter(done: int, total: int, text: str, speed: float) -> None:
        percent = 20 if total <= 0 else min(55, 20 + int(done * 35 / total))
        _emit(progress, percent, f"下载安装器 · {done / 1048576:.1f}/{total / 1048576:.1f} MB")

    from .net import DownloadItem, download_many

    download_many(
        [DownloadItem(urls=urls, destination=destination, kind="raw", label=destination.name)],
        reporter,
        max_workers=1,
        cancel=cancel,
    )


def _ensure_launcher_profiles(game_dir: Path) -> None:
    path = game_dir / "launcher_profiles.json"
    if path.is_file():
        return
    data = {
        "profiles": {},
        "settings": {},
        "version": 3,
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _run_installer(
    java_path: Path,
    args: list[str],
    game_dir: Path,
    progress: Progress | None,
    label: str,
) -> None:
    _emit(progress, 60, f"{label} · 正在安装（可能需要几分钟）")
    env = os.environ.copy()
    env["appdata"] = str(game_dir)
    try:
        completed = subprocess.run(
            [str(java_path)] + args,
            cwd=str(game_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            creationflags=CREATE_NO_WINDOW,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        raise LoaderInstallError(f"{label} 安装超时") from error
    output = (completed.stdout or "").strip()
    if completed.returncode != 0:
        tail = "\n".join(output.splitlines()[-12:])
        raise LoaderInstallError(f"{label} 安装失败（退出代码 {completed.returncode}）\n{tail}")
    _emit(progress, 90, f"{label} · 正在检查安装结果")


def _find_installed_version(
    game_dir: Path,
    needle: str,
    mc_version: str,
    started_at: float,
) -> str:
    candidates = []
    for item in list_local_versions(game_dir):
        lowered = item.id.lower()
        if needle.lower() not in lowered:
            continue
        if mc_version and mc_version not in item.id and not str(item.raw.get("inheritsFrom", "")).startswith(mc_version):
            continue
        if item.modified + 2 < started_at:
            continue
        candidates.append(item)
    if not candidates:
        for item in list_local_versions(game_dir):
            if needle.lower() in item.id.lower() and mc_version in item.id:
                candidates.append(item)
    if not candidates:
        raise LoaderInstallError(f"安装完成，但没有找到 {needle} 的版本配置")
    candidates.sort(key=lambda item: item.modified, reverse=True)
    return candidates[0].id


def _forge_installer_url(mc_version: str, forge_version: str) -> str:
    name = f"forge-{mc_version}-{forge_version}-installer.jar"
    return (
        "https://maven.minecraftforge.net/net/minecraftforge/forge/"
        f"{mc_version}-{forge_version}/{name}"
    )


def install_forge(
    game_dir: Path,
    mc_version: str,
    java_path: Path,
    progress: Progress | None = None,
    cancel: Any = None,
    source: str = "auto",
) -> str:
    _emit(progress, 5, "获取 Forge 版本信息")
    try:
        promotions = fetch_json(
            "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json",
            timeout=25,
        )
    except Exception as error:
        raise LoaderInstallError(f"无法获取 Forge 版本列表：{error}") from error
    promos = promotions.get("promos") if isinstance(promotions, dict) else {}
    if not isinstance(promos, dict):
        promos = {}
    forge_version = promos.get(f"{mc_version}-recommended") or promos.get(f"{mc_version}-latest")
    if not forge_version:
        raise LoaderInstallError(f"Forge 没有支持 Minecraft {mc_version} 的版本")

    installer = game_dir / "launcher" / f"forge-{mc_version}-{forge_version}-installer.jar"
    url = _forge_installer_url(mc_version, str(forge_version))
    _emit(progress, 15, f"下载 Forge {forge_version}")
    _download_installer(url, installer, progress, cancel)
    _ensure_launcher_profiles(game_dir)
    started = time.time()
    _run_installer(java_path, ["-jar", str(installer), "--installClient", str(game_dir)], game_dir, progress, "Forge")
    _emit(progress, 96, "查找 Forge 版本")
    version_id = _find_installed_version(game_dir, "forge", mc_version, started)
    merged = merge_loader_version(game_dir, version_id, f"{mc_version}-Forge_{forge_version}")
    _emit(progress, 100, f"Forge {forge_version} 安装完成")
    return merged


def _neoforge_mc_prefix(mc_version: str) -> str:
    parts = mc_version.split(".")
    if len(parts) >= 3 and parts[0] == "1":
        return f"{int(parts[1])}.{int(parts[2])}"
    if len(parts) >= 2 and parts[0] == "1":
        return f"{int(parts[1])}.0"
    return mc_version


def _pick_neoforge_version(mc_version: str) -> str:
    details = fetch_json(
        "https://bmclapi2.bangbang93.com/neoforge/meta/api/maven/details/releases/net/neoforged/neoforge",
        timeout=30,
    )
    files = details.get("files") if isinstance(details, dict) else []
    prefix = _neoforge_mc_prefix(mc_version)
    versions = []
    for entry in files if isinstance(files, list) else []:
        if not isinstance(entry, dict) or entry.get("type") != "DIRECTORY":
            continue
        name = str(entry.get("name") or "")
        if not name.startswith(prefix + "."):
            continue
        versions.append(name)
    if not versions:
        raise LoaderInstallError(f"NeoForge 没有支持 Minecraft {mc_version} 的版本")
    stable = [item for item in versions if "beta" not in item.lower()]
    pool = stable or versions

    def sort_key(value: str) -> tuple:
        parts = value.split(".")
        numbers = []
        for part in parts:
            try:
                numbers.append(int(part))
            except ValueError:
                numbers.append(0)
        return tuple(numbers)

    return sorted(pool, key=sort_key)[-1]


def install_neoforge(
    game_dir: Path,
    mc_version: str,
    java_path: Path,
    progress: Progress | None = None,
    cancel: Any = None,
    source: str = "auto",
) -> str:
    _emit(progress, 5, "获取 NeoForge 版本信息")
    neoforge_version = _pick_neoforge_version(mc_version)
    installer = game_dir / "launcher" / f"neoforge-{neoforge_version}-installer.jar"
    url = (
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
        f"{neoforge_version}/neoforge-{neoforge_version}-installer.jar"
    )
    _emit(progress, 15, f"下载 NeoForge {neoforge_version}")
    try:
        _download_installer(url, installer, progress, cancel)
    except Exception as error:
        raise LoaderInstallError(
            "NeoForge 安装器下载失败。当前网络可能无法访问 maven.neoforged.net，"
            "请尝试开启代理或使用其他网络。\n" + str(error)
        ) from error
    _ensure_launcher_profiles(game_dir)
    started = time.time()
    _run_installer(java_path, ["-jar", str(installer), "--installClient", str(game_dir)], game_dir, progress, "NeoForge")
    _emit(progress, 96, "查找 NeoForge 版本")
    version_id = _find_installed_version(game_dir, "neoforge", mc_version, started)
    merged = merge_loader_version(
        game_dir, version_id, f"{mc_version}-NeoForge_{neoforge_version.split('+')[0]}"
    )
    _emit(progress, 100, f"NeoForge {neoforge_version} 安装完成")
    return merged


def _optifine_entries() -> list[dict[str, Any]]:
    data = fetch_json("https://bmclapi2.bangbang93.com/optifine/versionList", timeout=30)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def pick_optifine(mc_version: str) -> dict[str, Any]:
    entries = [item for item in _optifine_entries() if str(item.get("mcversion")) == mc_version]
    if not entries:
        raise LoaderInstallError(f"OptiFine 没有支持 Minecraft {mc_version} 的版本")
    stable = [item for item in entries if "pre" not in str(item.get("patch", "")).lower()]
    pool = stable or entries

    def sort_key(item: dict[str, Any]) -> tuple:
        patch = str(item.get("patch") or "")
        return (str(item.get("type") or ""), patch)

    return sorted(pool, key=sort_key)[-1]


def install_optifine(
    game_dir: Path,
    mc_version: str,
    java_path: Path,
    progress: Progress | None = None,
    cancel: Any = None,
    source: str = "auto",
) -> str:
    _emit(progress, 5, "获取 OptiFine 版本信息")
    entry = pick_optifine(mc_version)
    mc = str(entry.get("mcversion") or mc_version)
    kind = str(entry.get("type") or "HD_U")
    patch = str(entry.get("patch") or "")
    filename = str(entry.get("filename") or f"OptiFine_{mc}_{kind}_{patch}.jar")
    url = f"https://bmclapi2.bangbang93.com/optifine/{mc}/{kind}/{patch}"
    installer = game_dir / "launcher" / filename
    _emit(progress, 15, f"下载 OptiFine {kind}_{patch}")
    _download_installer(url, installer, progress, cancel)
    started = time.time()
    temp_home = Path(tempfile.mkdtemp(prefix="fml-optifine-"))
    nested = temp_home / ".minecraft"
    (nested / "versions").mkdir(parents=True, exist_ok=True)
    (nested / "libraries").mkdir(parents=True, exist_ok=True)
    base_src = game_dir / "versions" / mc
    if base_src.is_dir():
        shutil.copytree(base_src, nested / "versions" / mc, dirs_exist_ok=True)
    (nested / "launcher_profiles.json").write_text(
        '{"profiles":{},"settings":{},"version":3}', encoding="utf-8"
    )
    args = [f"-Duser.home={temp_home}", "-cp", str(installer), "optifine.Installer"]
    try:
        major = int(subprocess.run(
            [str(java_path), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        ).stdout.split('"')[1].split(".")[0])
    except Exception:
        major = 0
    if major >= 9:
        args = ["--add-exports", "cpw.mods.bootstraplauncher/cpw.mods.bootstraplauncher=ALL-UNNAMED"] + args
    try:
        _run_installer(java_path, args, temp_home, progress, "OptiFine")
        _emit(progress, 93, "整理 OptiFine 安装文件")
        for child in (nested / "versions").iterdir():
            if child.is_dir() and child.name != mc:
                shutil.copytree(child, game_dir / "versions" / child.name, dirs_exist_ok=True)
        nested_libs = nested / "libraries"
        if nested_libs.is_dir():
            shutil.copytree(nested_libs, game_dir / "libraries", dirs_exist_ok=True)
    finally:
        shutil.rmtree(temp_home, ignore_errors=True)
    _emit(progress, 96, "查找 OptiFine 版本")
    version_id = _find_installed_version(game_dir, "optifine", mc_version, started)
    merged = merge_loader_version(game_dir, version_id, f"{mc_version}-OptiFine_{kind}_{patch}")
    _emit(progress, 100, f"OptiFine {kind}_{patch} 安装完成")
    return merged
