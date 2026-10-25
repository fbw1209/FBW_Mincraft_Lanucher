from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .paths import APP_DISPLAY_NAME, APP_VERSION, LOGS_DIR
from .version import (
    allowed_libraries,
    asset_index_id,
    client_jar_path,
    collect_classpath,
    game_assets_dir,
    instance_dir_for_version,
    library_native,
    logging_file,
    native_artifacts,
    required_java_major,
    resolve_version,
    version_type,
)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PLACEHOLDER = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class LaunchError(RuntimeError):
    pass


@dataclass
class LaunchPlan:
    command: list[str]
    cwd: Path
    version_id: str
    java_major: int
    log_path: Path
    assets_dir: Path
    game_dir: Path
    created_at: float = field(default_factory=time.time)

    @property
    def command_line(self) -> str:
        return subprocess.list2cmdline(self.command)


def offline_uuid(username: str) -> str:
    digest = bytearray(hashlib.md5(("OfflinePlayer:" + username).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest))).replace("-", "")


def _extract_natives(game_dir: Path, version: dict[str, Any]) -> Path:
    version_id = str(version.get("id"))
    natives_dir = game_dir / "versions" / version_id / "natives"
    natives_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("java", "jna", "lwjgl", "netty"):
        (natives_dir / sub).mkdir(exist_ok=True)
    try:
        for child in list(natives_dir.iterdir()):
            if child.is_file() and child.suffix.lower() in (".dll", ".so", ".dylib", ".jnilib"):
                child.unlink(missing_ok=True)
    except OSError:
        pass
    for entry in native_artifacts(version):
        artifact = entry.get("artifact") or {}
        path = game_dir / "libraries" / str(artifact.get("path", "")).replace("/", os.sep)
        if not path.is_file():
            continue
        excludes = [str(item) for item in entry.get("exclude") or []]
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    name = member.filename.replace("\\", "/")
                    if member.is_dir():
                        continue
                    if any(name.startswith(prefix) for prefix in excludes):
                        continue
                    target = natives_dir / name
                    try:
                        target.resolve().relative_to(natives_dir.resolve())
                    except Exception:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("wb") as destination:
                        destination.write(source.read())
        except (OSError, zipfile.BadZipFile):
            continue
    return natives_dir


def _ensure_virtual_assets(game_dir: Path, version: dict[str, Any]) -> None:
    index_id = asset_index_id(version)
    if not index_id:
        return
    index_path = game_dir / "assets" / "indexes" / f"{index_id}.json"
    if not index_path.is_file():
        return
    try:
        with index_path.open("r", encoding="utf-8") as handle:
            index = json.load(handle)
    except Exception:
        return
    virtual = bool(index.get("virtual"))
    map_to_resources = bool(index.get("map_to_resources"))
    if not virtual and not map_to_resources:
        return
    objects = index.get("objects") or {}
    if not isinstance(objects, dict):
        return
    for name, info in objects.items():
        if not isinstance(info, dict) or not info.get("hash"):
            continue
        hash_value = str(info["hash"])
        source = game_dir / "assets" / "objects" / hash_value[:2] / hash_value
        if not source.is_file():
            continue
        targets = []
        if map_to_resources:
            targets.append(game_dir / "resources" / str(name))
        if virtual:
            targets.append(game_dir / "assets" / "virtual" / index_id / str(name))
        if map_to_resources and index_id in ("legacy", "pre-1.6"):
            targets.append(game_dir / "assets" / "virtual" / "legacy" / str(name))
        for target in targets:
            if target.is_file() and target.stat().st_size == source.stat().st_size:
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    os.link(source, target)
            except OSError:
                try:
                    target.write_bytes(source.read_bytes())
                except OSError:
                    pass


def _argument_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and isinstance(item.get("value"), (str, list)):
                result.extend(_argument_value(item["value"]))
        return result
    return []


def _evaluate_arguments(entries: list[Any], features: dict[str, bool]) -> list[str]:
    from .version import rules_allow

    result: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            result.append(entry)
        elif isinstance(entry, dict):
            if rules_allow(entry.get("rules"), features):
                result.extend(_argument_value(entry.get("value")))
    return result


def _replace_placeholders(value: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))

    return PLACEHOLDER.sub(replace, value)


def _has_option(args: list[str], option: str) -> bool:
    return option in args


def _remove_memory_args(args: list[str]) -> list[str]:
    return [arg for arg in args if not re.match(r"^-Xm[sx]", arg)]


def _pick_assets_index(version: dict[str, Any], game_dir: Path) -> tuple[str, Path]:
    index_id = asset_index_id(version)
    if index_id and (game_dir / "assets" / "indexes" / f"{index_id}.json").is_file():
        return index_id, game_dir / "assets"
    assets_name = str(version.get("assets") or "")
    if assets_name and (game_dir / "assets" / "indexes" / f"{assets_name}.json").is_file():
        return assets_name, game_dir / "assets"
    return index_id, game_dir / "assets"


def build_launch_plan(
    game_dir: Path,
    version_id: str,
    cfg: Config,
    java_path: Path,
    java_major: int,
) -> LaunchPlan:
    version = resolve_version(game_dir, version_id)
    version["id"] = str(version.get("id") or version_id)
    instance_dir = instance_dir_for_version(game_dir, version_id)
    try:
        instance_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        instance_dir = game_dir
    required = required_java_major(version)
    if java_major and required and java_major < required:
        raise LaunchError(f"Java 版本过低：需要 Java {required}，当前为 Java {java_major}")

    classpath = collect_classpath(game_dir, version)
    missing = [path for path in classpath if not path.is_file()]
    if missing:
        preview = "\n".join(str(path) for path in missing[:5])
        raise LaunchError(
            "游戏文件不完整，缺少以下文件，请在“下载”页面重新安装该版本：\n" + preview
        )
    main_class = str(version.get("mainClass") or "")
    if not main_class:
        raise LaunchError("版本配置缺少主类，无法启动")

    natives_dir = _extract_natives(game_dir, version)
    _ensure_virtual_assets(game_dir, version)
    index_name, assets_root = _pick_assets_index(version, game_dir)
    username = cfg.username or "Player"
    user_uuid = offline_uuid(username)
    game_directory = str(instance_dir)
    jar_id = version.get("_client_jar_id") or version.get("id")

    variables = {
        "auth_player_name": username,
        "version_name": str(version.get("id")),
        "game_directory": game_directory,
        "assets_root": str(assets_root),
        "game_assets": str(game_assets_dir(game_dir, version)),
        "assets_index_name": index_name,
        "auth_uuid": user_uuid,
        "auth_access_token": "0",
        "auth_session": "token:0:0",
        "user_type": "legacy",
        "version_type": version_type(version),
        "natives_directory": str(natives_dir),
        "launcher_name": APP_DISPLAY_NAME,
        "launcher_version": APP_VERSION,
        "classpath": os.pathsep.join(str(path) for path in classpath),
        "classpath_separator": os.pathsep,
        "library_directory": str(game_dir / "libraries"),
        "resolution_width": "854",
        "resolution_height": "480",
        "user_properties": "{}",
        "clientid": "0",
        "auth_xuid": "0",
        "quickPlayPath": "",
        "quickPlaySingleplayer": "",
        "quickPlayMultiplayer": "",
        "quickPlayRealms": "",
    }

    features: dict[str, bool] = {
        "is_demo_user": False,
        "has_custom_resolution": False,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }

    arguments = version.get("arguments") if isinstance(version.get("arguments"), dict) else {}
    jvm_args = _evaluate_arguments(arguments.get("jvm") or [], features)
    jvm_args = [_replace_placeholders(arg, variables) for arg in jvm_args]
    jvm_args = _remove_memory_args(jvm_args)

    if not _has_option(jvm_args, "-Xmx"):
        memory_args = [f"-Xms{cfg.min_memory}M", f"-Xmx{cfg.max_memory}M"]
        jvm_args = memory_args + jvm_args

    if not any("-Djava.library.path=" in arg for arg in jvm_args):
        jvm_args.append(f"-Djava.library.path={natives_dir}")
    if not any("minecraft.launcher.brand" in arg for arg in jvm_args):
        jvm_args.append(f"-Dminecraft.launcher.brand={APP_DISPLAY_NAME}")
        jvm_args.append(f"-Dminecraft.launcher.version={APP_VERSION}")
    jvm_args.append("-Dlog4j2.formatMsgNoLookups=true")

    if not any(arg.startswith("-XX:+Use") for arg in jvm_args) and cfg.max_memory >= 2048:
        jvm_args.extend(["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=50"])

    log_info = logging_file(version)
    if log_info:
        log_file = log_info.get("file") or {}
        file_id = str(log_file.get("id") or "")
        log_path = game_dir / "assets" / "log_configs" / file_id
        if file_id and log_path.is_file():
            argument = str(log_info.get("argument") or "-Dlog4j.configurationFile=${path}")
            argument = argument.replace("${path}", str(log_path))
            if "log4j.configurationFile" not in " ".join(jvm_args):
                jvm_args.append(argument)

    classpath_value = os.pathsep.join(str(path) for path in classpath)
    if not _has_option(jvm_args, "-cp") and not _has_option(jvm_args, "-classpath"):
        jvm_args.extend(["-cp", classpath_value])

    game_args_raw = _evaluate_arguments(arguments.get("game") or [], features)
    if not game_args_raw and version.get("minecraftArguments"):
        try:
            game_args_raw = shlex.split(str(version["minecraftArguments"]))
        except Exception:
            game_args_raw = str(version["minecraftArguments"]).split()
    game_args = [_replace_placeholders(arg, variables) for arg in game_args_raw]

    def ensure_pair(flag: str, value: str) -> None:
        if not _has_option(game_args, flag):
            game_args.extend([flag, value])

    modern_arguments = "--username" in " ".join(game_args_raw)
    if modern_arguments:
        ensure_pair("--username", username)
        ensure_pair("--version", str(version.get("id")))
        ensure_pair("--uuid", user_uuid)
        ensure_pair("--accessToken", "0")
        ensure_pair("--userType", "legacy")
        ensure_pair("--versionType", version_type(version))
        if index_name:
            ensure_pair("--assetIndex", index_name)
    ensure_pair("--gameDir", game_directory)
    ensure_pair("--assetsDir", str(assets_root))
    if cfg.fullscreen and "--fullscreen" not in game_args:
        game_args.append("--fullscreen")

    command = [str(java_path)] + jvm_args + [main_class] + game_args
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_name = f"{time.strftime('%Y%m%d-%H%M%S')}-{version.get('id')}.log"
    log_path = LOGS_DIR / re.sub(r'[<>:"/\\|?*]', "_", log_name)
    return LaunchPlan(
        command=command,
        cwd=instance_dir,
        version_id=str(version.get("id")),
        java_major=java_major,
        log_path=log_path,
        assets_dir=assets_root,
        game_dir=instance_dir,
    )


def launch_process(
    plan: LaunchPlan,
    on_line: Callable[[str], None] | None = None,
    on_exit: Callable[[int], None] | None = None,
) -> subprocess.Popen[str]:
    plan.log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = plan.log_path.open("a", encoding="utf-8", errors="replace")
    log_handle.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 {plan.version_id} =====\n")
    log_handle.write(plan.command_line + "\n\n")
    log_handle.flush()
    try:
        process = subprocess.Popen(
            plan.command,
            cwd=str(plan.cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        log_handle.close()
        raise

    def reader() -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    line = line.rstrip("\r\n")
                    try:
                        log_handle.write(line + "\n")
                        log_handle.flush()
                    except Exception:
                        pass
                    if on_line is not None:
                        try:
                            on_line(line)
                        except Exception:
                            pass
        finally:
            try:
                process.wait()
            except Exception:
                pass
            code = process.returncode if process.returncode is not None else -1
            try:
                log_handle.write(f"\n===== 游戏退出，代码 {code} =====\n")
                log_handle.close()
            except Exception:
                pass
            if on_exit is not None:
                try:
                    on_exit(code)
                except Exception:
                    pass

    threading.Thread(target=reader, name="minecraft-output", daemon=True).start()
    return process
