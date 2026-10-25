from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import traceback
from collections import deque
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from .. import resources as resource_api
from ..resources import ensure_fabric_api, fabric_api_installed
from ..config import Config, get_config_store, validate_username
from ..importer import import_versions as import_versions_from_path
from ..installer import install_fabric, install_version, merge_loader_version
from ..loaders import install_forge, install_neoforge, install_optifine
from ..java import JavaInfo, JavaManager, component_from_version
from ..launch import LaunchError, build_launch_plan, launch_process
from ..paths import APP_DISPLAY_NAME, APP_VERSION, ICON_FILE, ICON_PNG, LOGS_DIR
from ..version import (
    LocalVersion,
    VersionManifest,
    base_version_id,
    ensure_instance_layout,
    instance_dir_for_version,
    list_local_versions,
    loader_name,
    minecraft_version_from_id,
    read_version_json,
    required_java_major,
    resolve_version,
)
from . import theme
from .dialogs import AlertDialog, ConfirmDialog, ImportDialog, LoaderDialog, LogWindow, ResourceDialog
from .pages import DownloadsPage, HomePage, ResourcesPage, SettingsPage, VersionsPage
from .widgets import NavItem, clear_children

LOGGER = logging.getLogger("fml")


class LimeLauncherApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=theme.BG)
        self.store = get_config_store()
        self.cfg: Config = self.store.config
        self.manifest = VersionManifest(self.cfg.download_source)
        self.manifest_error = ""
        self.java_manager = JavaManager()
        self.java_info: JavaInfo | None = None
        self.java_scanning = False
        self.local_versions: list[LocalVersion] = []
        self.busy = False
        self.game_running = False
        self.current_process: Any = None
        self.cancel_event: threading.Event | None = None
        self.log_window: LogWindow | None = None
        self._pending_log: deque[str] = deque(maxlen=3000)
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._manifest_loading = False
        self._status_reset_job: str | None = None
        self._progress_hide_job: str | None = None
        self._current_page = "home"

        self._setup_window()
        self._build_layout()
        self.show_page("home")
        LOGGER.info("界面初始化完成")
        self.after(60, self._poll_events)
        self.after(120, self._startup)

    def _setup_window(self) -> None:
        self.title("FML")
        self.geometry("1180x760")
        self.minsize(1000, 640)
        try:
            self.iconbitmap(str(ICON_FILE))
        except Exception:
            pass
        self._icon_handles = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.withdraw()
        self.after(700, self._show_window)

    def _show_window(self) -> None:
        LOGGER.info("准备显示主窗口")
        self._center_window()
        self.deiconify()
        self.lift()
        self.after(120, lambda: theme.apply_light_titlebar(self))
        self.after(140, lambda: setattr(self, "_icon_handles", theme.apply_windows_icon(self, ICON_FILE)))

    def _center_window(self) -> None:
        try:
            self.update_idletasks()
            scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
            left, top, work_w, work_h = self._work_area()
            if not work_w or not work_h:
                work_w = self.winfo_screenwidth()
                work_h = self.winfo_screenheight()
            width = min(1180, max(1000, int((work_w - 80) / scale)))
            height = min(760, max(640, int((work_h - 80) / scale)))
            actual_w = int(width * scale)
            actual_h = int(height * scale)
            x = left + max(0, (work_w - actual_w) // 2)
            y = top + max(0, (work_h - actual_h) // 2)
            x = min(max(left, x), max(left, left + work_w - actual_w))
            y = min(max(top, y), max(top, top + work_h - actual_h))
            self.wm_geometry(f"{actual_w}x{actual_h}+{x}+{y}")
        except Exception:
            LOGGER.exception("窗口居中失败")

    def _work_area(self) -> tuple[int, int, int, int]:
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
        return 0, 0, 0, 0

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=224)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self.sidebar = ctk.CTkFrame(self, fg_color=theme.SIDEBAR, corner_radius=0, width=224)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(24, 26))
        brand.grid_columnconfigure(1, weight=1)
        dpi_scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        logo_px = int(40 * dpi_scale)
        logo = ctk.CTkCanvas(brand, width=logo_px, height=logo_px, bg=theme.SIDEBAR, highlightthickness=0)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        theme.draw_logo(logo, logo_px / 2, logo_px / 2, logo_px)
        ctk.CTkLabel(
            brand,
            text="FBW Minecraft",
            text_color=theme.TEXT,
            font=theme.font(16, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(
            brand,
            text="LAUNCHER · FML",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(8),
            anchor="w",
        ).grid(row=1, column=1, sticky="nw")

        nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="new", padx=12)
        self.nav_items: dict[str, NavItem] = {}
        for name, label in (("home", "主页"), ("versions", "版本"), ("downloads", "下载"), ("resources", "资源"), ("settings", "设置")):
            item = NavItem(nav, label, lambda page=name: self.show_page(page))
            item.pack(fill="x", pady=2)
            self.nav_items[name] = item

        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.grid(row=2, column=0, sticky="nsew")

        self.account_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=theme.CARD,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER,
            height=66,
        )
        self.account_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.account_card.grid_propagate(False)
        self.account_card.grid_columnconfigure(1, weight=1)
        self.avatar = ctk.CTkLabel(
            self.account_card,
            text="P",
            width=38,
            height=38,
            corner_radius=19,
            fg_color=theme.ACCENT_SOFT,
            text_color=theme.ACCENT_TEXT,
            font=theme.font(15, "bold"),
        )
        self.avatar.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=14)
        self.sidebar_name = ctk.CTkLabel(
            self.account_card,
            text="Player",
            text_color=theme.TEXT,
            font=theme.font(13, "bold"),
            anchor="w",
        )
        self.sidebar_name.grid(row=0, column=1, sticky="sw", pady=(15, 0))
        self.sidebar_account_type = ctk.CTkLabel(
            self.account_card,
            text="离线账户",
            text_color=theme.MUTED,
            font=theme.font(10),
            anchor="w",
        )
        self.sidebar_account_type.grid(row=1, column=1, sticky="nw", pady=(0, 15))
        self._make_clickable(self.account_card, lambda: self.show_page("settings"))

        ctk.CTkLabel(
            self.sidebar,
            text=f"v{APP_VERSION}",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(10),
        ).grid(row=4, column=0, pady=(0, 16))

        self.page_container = ctk.CTkFrame(self, fg_color="transparent")
        self.page_container.grid(row=0, column=1, sticky="nsew", padx=(26, 26), pady=(24, 6))
        self.page_container.grid_rowconfigure(0, weight=1)
        self.page_container.grid_columnconfigure(0, weight=1)
        theme.configure_ttk(self)

        self.pages = {
            "home": HomePage(self.page_container, self),
            "versions": VersionsPage(self.page_container, self),
            "downloads": DownloadsPage(self.page_container, self),
            "resources": ResourcesPage(self.page_container, self),
            "settings": SettingsPage(self.page_container, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.status_bar = ctk.CTkFrame(self, fg_color=theme.WHITE, corner_radius=0, height=42)
        self.status_bar.grid(row=1, column=1, sticky="ew")
        self.status_bar.grid_propagate(False)
        self.status_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkFrame(self.status_bar, fg_color=theme.BORDER, height=1, corner_radius=0).grid(
            row=0, column=0, columnspan=5, sticky="ew"
        )
        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="就绪",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.status_label.grid(row=1, column=0, sticky="w", padx=(28, 12), pady=(0, 1))
        self.progress_bar = ctk.CTkProgressBar(
            self.status_bar,
            width=170,
            height=5,
            corner_radius=3,
            fg_color=theme.BORDER,
            progress_color=theme.ACCENT,
            mode="determinate",
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=2, sticky="e", padx=(0, 12), pady=(1, 0))
        self.progress_bar.grid_remove()
        self.log_button = ctk.CTkButton(
            self.status_bar,
            text="查看日志",
            command=self.open_log_window,
            width=70,
            height=26,
            corner_radius=7,
            fg_color="transparent",
            hover_color=theme.CARD_HOVER,
            text_color=theme.MUTED,
            font=theme.font(11),
        )
        self.log_button.grid(row=1, column=3, sticky="e", padx=(0, 18), pady=(0, 1))

        self._update_sidebar()

    def _make_clickable(self, widget: Any, command: Callable[[], None]) -> None:
        widget.configure(cursor="hand2")

        def click(_event: Any) -> None:
            command()

        def walk(item: Any) -> None:
            try:
                item.bind("<Button-1>", click)
                item.configure(cursor="hand2")
            except Exception:
                pass
            for child in item.winfo_children():
                walk(child)

        walk(widget)

    def _update_sidebar(self) -> None:
        name = self.cfg.username or "Player"
        self.sidebar_name.configure(text=name)
        self.avatar.configure(text=(name[:1].upper() or "P"))
        self.account_card.configure(fg_color=theme.CARD)

    def show_page(self, name: str) -> None:
        page = self.pages.get(name)
        if page is None:
            return
        self._current_page = name
        for key, item in self.nav_items.items():
            item.set_active(key == name)
        try:
            page.tkraise()
        except Exception:
            return
        try:
            page.on_show()
        except Exception:
            LOGGER.exception("页面加载失败：%s", name)

    def _startup(self) -> None:
        LOGGER.info("开始启动刷新")
        self.refresh_local_versions()
        LOGGER.info("启动刷新完成")
        self.detect_java_async()
        self.fetch_manifest_async()

    def refresh_local_versions(self) -> None:
        game_dir = Path(self.cfg.game_dir)
        try:
            game_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._migrate_legacy_versions(game_dir)
        self._normalize_versions(game_dir)
        hidden = set(self.cfg.hidden_versions)
        self.local_versions = [
            item for item in list_local_versions(game_dir) if item.id not in hidden
        ]
        ids = [item.id for item in self.local_versions]
        if self.cfg.selected_version not in ids:
            if self.cfg.last_version in ids:
                self.cfg.selected_version = self.cfg.last_version
            elif ids:
                self.cfg.selected_version = ids[0]
            else:
                self.cfg.selected_version = ""
            self.store.save(self.cfg)
        self._update_sidebar()
        try:
            self.pages["home"].update_view()
        except Exception:
            LOGGER.exception("刷新主页失败")
        if self._current_page == "versions":
            try:
                self.pages["versions"].refresh()
            except Exception:
                LOGGER.exception("刷新版本页失败")
        if self._current_page == "downloads":
            try:
                self.pages["downloads"].refresh()
            except Exception:
                LOGGER.exception("刷新下载页失败")

    def _migrate_legacy_versions(self, game_dir: Path) -> None:
        if getattr(self, "_migrating_versions", False):
            return
        self._migrating_versions = True
        try:
            versions_dir = game_dir / "versions"
            for item in list_local_versions(game_dir):
                base = str(item.raw.get("inheritsFrom") or "")
                if not base:
                    continue
                target = ""
                lowered = item.id.lower()
                if lowered.startswith("fabric-loader-"):
                    rest = item.id[len("fabric-loader-"):]
                    suffix = "-" + base
                    if rest.endswith(suffix):
                        loader = rest[: -len(suffix)].split("+")[0]
                        target = f"{base}-Fabric {loader}"
                elif "-forge-" in item.id:
                    base_id, _, forge = item.id.partition("-forge-")
                    if base_id == base:
                        target = f"{base}-Forge_{forge.split('+')[0]}"
                elif lowered.startswith("neoforge-"):
                    forge = item.id[len("neoforge-"):].split("+")[0]
                    target = f"{base}-NeoForge_{forge}"
                if not target or (versions_dir / target).exists():
                    continue
                try:
                    merged = merge_loader_version(game_dir, item.id, target)
                    if item.id in self.cfg.hidden_versions:
                        self.cfg.hidden_versions = list(
                            dict.fromkeys(
                                merged if value == item.id else value
                                for value in self.cfg.hidden_versions
                            )
                        )
                        self.store.save(self.cfg)
                    LOGGER.info("已整理旧版本 %s -> %s", item.id, merged)
                except Exception:
                    LOGGER.exception("整理旧版本失败：%s", item.id)
        finally:
            self._migrating_versions = False

    def _merged_base_id(self, game_dir: Path, version_id: str) -> str:
        for marker in ("-Fabric ", "-Forge_", "-NeoForge_", "-OptiFine_"):
            if marker in version_id:
                base = version_id.split(marker, 1)[0]
                if base and (game_dir / "versions" / base).is_dir():
                    return base
        return ""

    def _has_instance_data(self, folder: Path) -> bool:
        for name in ("mods", "saves", "config", "resourcepacks", "shaderpacks"):
            child = folder / name
            try:
                if child.is_dir() and any(child.iterdir()):
                    return True
            except OSError:
                return True
        return False

    def _cleanup_redundant_base(self, game_dir: Path, base_id: str, keep_id: str) -> None:
        if not base_id or base_id == keep_id:
            return
        if base_id in self.cfg.hidden_versions or self.cfg.selected_version == base_id:
            return
        base_dir = game_dir / "versions" / base_id
        if not base_dir.is_dir():
            return
        try:
            raw = read_version_json(game_dir, base_id)
        except Exception:
            return
        if raw.get("inheritsFrom"):
            return
        for item in list_local_versions(game_dir):
            if str(item.raw.get("inheritsFrom") or "") == base_id:
                return
        if self._has_instance_data(base_dir):
            return
        shutil.rmtree(base_dir, ignore_errors=True)
        if self.cfg.last_version == base_id:
            self.cfg.last_version = ""
            self.store.save(self.cfg)
        LOGGER.info("已清理加载器安装产生的重复原版：%s", base_id)

    def _normalize_versions(self, game_dir: Path) -> None:
        if getattr(self, "_normalizing_versions", False):
            return
        self._normalizing_versions = True
        try:
            versions = list_local_versions(game_dir)
            for item in versions:
                if not item.raw.get("inheritsFrom"):
                    ensure_instance_layout(game_dir, item.id)
            for item in versions:
                base = self._merged_base_id(game_dir, item.id)
                if base:
                    self._cleanup_redundant_base(game_dir, base, item.id)
        finally:
            self._normalizing_versions = False

    def java_summary(self) -> str:
        if self.java_scanning:
            return "检测中"
        if self.java_info is None:
            return "未检测"
        return self.java_info.label

    def detect_java_async(self, force: bool = False) -> None:
        if self.java_scanning:
            return
        self.java_scanning = True
        try:
            self.pages["home"].update_view()
            self.pages["settings"].update_java_status()
        except Exception:
            pass

        def worker() -> None:
            try:
                infos = self.java_manager.detect(force=force)
                self._post("java_ok", infos)
            except Exception as error:
                self._post("java_error", error)

        threading.Thread(target=worker, name="java-detect", daemon=True).start()

    def _select_java_from(self, infos: list[JavaInfo]) -> None:
        best = infos[0] if infos else None
        if best is not None:
            self.java_info = best
        else:
            self.java_info = None
        self.java_scanning = False
        try:
            self.pages["home"].update_view()
            self.pages["settings"].update_java_status()
        except Exception:
            pass

    def fetch_manifest_async(self, force: bool = False) -> None:
        if self._manifest_loading:
            return
        self._manifest_loading = True
        self.manifest_error = ""

        def worker() -> None:
            try:
                manifest = VersionManifest(self.cfg.download_source)
                manifest.load(force=force)
                self._post("manifest_ok", manifest)
            except Exception as error:
                self._post("manifest_error", error)

        threading.Thread(target=worker, name="version-manifest", daemon=True).start()

    def ensure_manifest(self) -> None:
        if self.manifest.versions or self._manifest_loading:
            return
        self.fetch_manifest_async()

    def reload_manifest(self) -> None:
        if self.busy:
            self.notify("当前任务完成后才能刷新版本列表", "warn")
            return
        self.manifest_error = ""
        self.notify("正在刷新版本列表…", "info")
        self.fetch_manifest_async(force=True)

    def save_config(self, cfg: Config | None = None, reload_manifest: bool = False) -> None:
        old_game_dir = self.cfg.game_dir
        old_source = self.cfg.download_source
        self.cfg = self.store.save(cfg or self.cfg)
        self._update_sidebar()
        try:
            self.pages["home"].update_view()
        except Exception:
            pass
        if reload_manifest or self.cfg.download_source != old_source:
            self.manifest = VersionManifest(self.cfg.download_source)
            self.fetch_manifest_async(force=True)
        if self.cfg.game_dir != old_game_dir:
            self.refresh_local_versions()

    def select_version(self, version_id: str) -> None:
        if not version_id:
            return
        if version_id != self.cfg.selected_version:
            self.cfg.selected_version = version_id
            self.store.save(self.cfg)
        try:
            self.pages["home"].update_view()
        except Exception:
            pass

    def _valid_username(self) -> bool:
        return bool(validate_username(self.cfg.username))

    def start_version(self, version_id: str) -> None:
        self.select_version(version_id)
        self.start_game()

    def start_game(self) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        if self.game_running:
            self.notify("游戏正在运行中", "warn")
            return
        version_id = self.cfg.selected_version
        local_ids = {item.id for item in self.local_versions}
        if not version_id or version_id not in local_ids:
            self.notify("请先安装一个 Minecraft 版本", "warn")
            self.show_page("downloads")
            return
        if not self._valid_username():
            self.show_page("settings")
            AlertDialog(
                self,
                "玩家名称无效",
                "请先在设置中填写 1-16 位字母、数字或下划线的玩家名称。",
                kind="error",
            )
            return
        game_dir = Path(self.cfg.game_dir)
        try:
            game_dir.mkdir(parents=True, exist_ok=True)
        except Exception as error:
            AlertDialog(self, "无法创建游戏目录", str(error), kind="error")
            return
        cfg = self.cfg

        def task(progress: Callable[[int, str], None]) -> Any:
            version = resolve_version(game_dir, version_id)
            required = required_java_major(version)
            progress(2, "正在检查 Java")
            java = self.java_manager.ensure(
                required,
                component_from_version(version),
                cfg.java_path,
                cfg.auto_java,
                progress,
                self.cancel_event,
            )
            if loader_name(version_id) == "Fabric":
                instance_dir = instance_dir_for_version(game_dir, version_id)
                if not fabric_api_installed(instance_dir):
                    progress(76, "正在安装 Fabric API")
                    try:
                        ensure_fabric_api(
                            instance_dir,
                            minecraft_version_from_id(version_id)
                            or base_version_id(game_dir, version_id),
                            progress=lambda percent, text: progress(76 + int(percent * 0.1), text),
                            cancel=self.cancel_event,
                        )
                    except Exception:
                        LOGGER.exception("自动安装 Fabric API 失败")
            progress(88, "正在准备启动文件")
            plan = build_launch_plan(game_dir, version_id, cfg, java.path, java.major)
            progress(92, "正在启动游戏")
            process = launch_process(plan, on_line=self._on_game_line, on_exit=self._on_game_exit)
            return plan, process, java

        def done(result: Any) -> None:
            plan, process, java = result
            self.java_info = java
            self.current_process = process
            self.game_running = True
            self.cfg.last_version = plan.version_id
            self.cfg.last_played = time.strftime("%Y-%m-%d %H:%M")
            self.store.save(self.cfg)
            self._set_status(f"游戏已启动 · {plan.version_id} · Java {java.major}", "success")
            self.notify("游戏已启动", "success")
            try:
                self.pages["home"].update_view()
                self.pages["settings"].update_java_status()
            except Exception:
                pass
            if self.cfg.show_log:
                self.open_log_window()
            if self.cfg.close_after_launch:
                self.after(1400, self.iconify)

        def error(exc: Exception, detail: str) -> None:
            LOGGER.error("启动失败：%s\n%s", exc, detail)
            AlertDialog(
                self,
                "启动失败",
                str(exc) or "发生未知错误，请查看日志。",
                detail=detail,
                kind="error",
            )

        self.run_task(task, f"正在启动 {version_id}", done, error)

    def install_version(self, version_id: str, entry_url: str = "", fabric: bool = False) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        game_dir = Path(self.cfg.game_dir)
        source = self.cfg.download_source
        label = f"正在安装 {version_id}" + (" + Fabric" if fabric else "")

        def task(progress: Callable[[int, str], None]) -> str:
            cancel = self.cancel_event
            if fabric:
                return install_fabric(
                    game_dir,
                    version_id,
                    entry_url=entry_url,
                    source=source,
                    progress=progress,
                    cancel=cancel,
                )
            return install_version(
                game_dir,
                version_id,
                entry_url=entry_url,
                source=source,
                progress=progress,
                cancel=cancel,
            )

        def done(installed_id: str) -> None:
            self.refresh_local_versions()
            self.cfg.selected_version = installed_id
            self.store.save(self.cfg)
            try:
                self.pages["home"].update_view()
            except Exception:
                pass
            self.notify(f"{installed_id} 安装完成", "success")

        def error(exc: Exception, detail: str) -> None:
            LOGGER.error("安装失败：%s\n%s", exc, detail)
            AlertDialog(
                self,
                "安装失败",
                str(exc) or "下载或安装过程中发生错误。",
                detail=detail,
                kind="error",
            )

        self.run_task(task, label, done, error)

    def show_loader_dialog(self, version_id: str, entry_url: str = "") -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        LoaderDialog(self, version_id, lambda loader: self.install_with_loader(version_id, loader, entry_url))

    def install_with_loader(self, version_id: str, loader: str, entry_url: str = "") -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        game_dir = Path(self.cfg.game_dir)
        source = self.cfg.download_source
        loader_names = {
            "vanilla": "原版",
            "fabric": "Fabric",
            "forge": "Forge",
            "neoforge": "NeoForge",
            "optifine": "OptiFine",
        }
        title = f"正在安装 {version_id} · {loader_names.get(loader, loader)}"
        base_existed = (game_dir / "versions" / version_id).is_dir()

        def task(progress: Callable[[int, str], None]) -> str:
            cancel = self.cancel_event
            if loader == "fabric":
                installed = install_fabric(
                    game_dir,
                    version_id,
                    entry_url=entry_url,
                    source=source,
                    progress=lambda percent, text: progress(int(percent * 0.9), text),
                    cancel=cancel,
                )
                progress(93, "正在安装 Fabric API")
                try:
                    ensure_fabric_api(
                        instance_dir_for_version(game_dir, installed),
                        version_id,
                        progress=lambda percent, text: progress(93 + int(percent * 0.07), text),
                        cancel=cancel,
                    )
                except Exception:
                    LOGGER.exception("自动安装 Fabric API 失败")
                progress(100, "安装完成")
                return installed
            install_version(
                game_dir,
                version_id,
                entry_url=entry_url,
                source=source,
                progress=lambda percent, text: progress(int(percent * 0.35), text),
                cancel=cancel,
            )
            if loader == "vanilla":
                return version_id
            version = resolve_version(game_dir, version_id)
            required = required_java_major(version)
            progress(36, "正在准备 Java")
            java = self.java_manager.ensure(
                required,
                component_from_version(version),
                self.cfg.java_path,
                self.cfg.auto_java,
                progress=lambda percent, text: progress(36 + int(percent * 0.09), text),
                cancel=cancel,
            )
            mapped = lambda percent, text: progress(45 + int(percent * 0.55), text)
            if loader == "forge":
                return install_forge(game_dir, version_id, java.path, mapped, cancel, source)
            if loader == "neoforge":
                return install_neoforge(game_dir, version_id, java.path, mapped, cancel, source)
            if loader == "optifine":
                return install_optifine(game_dir, version_id, java.path, mapped, cancel, source)
            raise ValueError(f"未知加载器：{loader}")

        def done(installed_id: str) -> None:
            if loader != "vanilla" and installed_id != version_id:
                self._cleanup_redundant_base(game_dir, version_id, installed_id)
                ensure_instance_layout(game_dir, installed_id)
            self.refresh_local_versions()
            self.cfg.selected_version = installed_id
            self.store.save(self.cfg)
            try:
                self.pages["home"].update_view()
            except Exception:
                pass
            self.notify(f"{installed_id} 安装完成", "success")

        def error(exc: Exception, detail: str) -> None:
            LOGGER.error("加载器安装失败：%s\n%s", exc, detail)
            AlertDialog(
                self,
                "安装失败",
                str(exc) or "安装过程中发生错误。",
                detail=detail,
                kind="error",
            )

        self.run_task(task, title, done, error)

    def show_import_dialog(self) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        ImportDialog(self, self._import_mode)

    def _import_mode(self, mode: str) -> None:
        if mode == "zip":
            selected = filedialog.askopenfilename(
                parent=self,
                title="选择版本压缩包",
                filetypes=[("版本压缩包", "*.zip"), ("所有文件", "*.*")],
            )
        else:
            title = "选择版本文件夹" if mode == "folder" else "选择其他 .minecraft 游戏目录"
            selected = filedialog.askdirectory(parent=self, title=title)
        if selected:
            self.import_versions_async(Path(selected))

    def import_versions_async(self, source_path: Path) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        game_dir = Path(self.cfg.game_dir)
        source = self.cfg.download_source
        manifest = self.manifest

        def task(progress: Callable[[int, str], None]) -> list[str]:
            return import_versions_from_path(
                game_dir,
                source_path,
                source=source,
                manifest=manifest,
                progress=progress,
                cancel=self.cancel_event,
            )

        def done(imported: list[str]) -> None:
            if imported:
                restored = set(imported)
                self.cfg.hidden_versions = [
                    item for item in self.cfg.hidden_versions if item not in restored
                ]
                self.cfg.selected_version = imported[-1]
                self.store.save(self.cfg)
            self.refresh_local_versions()
            self.show_page("versions")
            self.notify(f"已导入 {len(imported)} 个版本", "success")

        def error(exc: Exception, detail: str) -> None:
            LOGGER.error("导入版本失败：%s\n%s", exc, detail)
            AlertDialog(self, "导入失败", str(exc), detail=detail, kind="error")

        self.run_task(task, f"正在导入 {source_path.name}", done, error)

    def selected_game_context(self) -> tuple[str, str]:
        version_id = self.cfg.selected_version
        if not version_id:
            return "", ""
        base = version_id
        local = next((item for item in self.local_versions if item.id == version_id), None)
        if local is not None:
            inherited = str(local.raw.get("inheritsFrom") or "")
            try:
                base = inherited or base_version_id(Path(self.cfg.game_dir), version_id)
            except Exception:
                base = inherited or version_id
        if not re.fullmatch(r"(?:1\.\d+(?:\.\d+)?|\d{2,}\.\d+(?:\.\d+)?)", base):
            base = minecraft_version_from_id(version_id)
        loader = loader_name(version_id)
        mapped = {
            "Fabric": "fabric",
            "Forge": "forge",
            "NeoForge": "neoforge",
            "Quilt": "quilt",
            "OptiFine": "",
        }.get(loader, "")
        return base, mapped

    def run_background(
        self,
        func: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
    ) -> None:
        def worker() -> None:
            try:
                result = func()
            except Exception as error:
                self._post("bg_error", (on_error, error, traceback.format_exc()))
            else:
                self._post("bg_done", (on_done, result))

        threading.Thread(target=worker, name="fml-background", daemon=True).start()

    def search_resources(
        self,
        source: str,
        type_key: str,
        query: str,
        mc_version: str,
        loader: str,
        callback: Callable[[list[Any], Exception | None], None],
    ) -> None:
        self.run_background(
            lambda: resource_api.search(source, query, type_key, mc_version, loader, 50),
            lambda items: callback(items, None),
            lambda error, detail: callback([], error),
        )

    def show_resource_dialog(self, item: Any) -> None:
        mc_version, loader = self.selected_game_context()
        type_labels = {"mod": "模组", "shader": "光影", "resourcepack": "资源包", "modpack": "整合包"}
        source_label = "Modrinth" if item.source == "modrinth" else "CurseForge"
        meta = f"{source_label} · {type_labels.get(item.type_key, item.type_key)} · {item.downloads:,} 次下载"
        if mc_version:
            meta += f" · 当前版本 {mc_version}" + (f" / {loader}" if loader else "")
        dialog = ResourceDialog(self, item, meta, lambda file: self.download_resource(item, file))

        def safe_files(files: list[Any]) -> None:
            try:
                if dialog.winfo_exists():
                    dialog.set_files(files)
            except Exception:
                pass

        def safe_error(error: Exception, detail: str) -> None:
            try:
                if dialog.winfo_exists():
                    dialog.set_error(f"获取文件失败：{error}")
            except Exception:
                pass

        self.run_background(
            lambda: resource_api.get_files(item, mc_version, loader),
            safe_files,
            safe_error,
        )

    def download_resource(self, item: Any, file: Any) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        game_dir = Path(self.cfg.game_dir)
        target_dir = game_dir
        if item.type_key != "modpack" and self.cfg.selected_version:
            target_dir = self.version_instance_dir(self.cfg.selected_version)

        def task(progress: Callable[[int, str], None]) -> Path:
            return resource_api.download_resource(item, file, target_dir, progress, self.cancel_event)

        def done(path: Path) -> None:
            if item.type_key == "modpack":
                self.notify(f"整合包已保存到 {path.parent}", "success")
            else:
                self.notify(f"已保存到 {path.parent}", "success")

        def error(exc: Exception, detail: str) -> None:
            LOGGER.error("资源下载失败：%s\n%s", exc, detail)
            AlertDialog(self, "下载失败", str(exc), detail=detail, kind="error")

        self.run_task(task, f"正在下载 {item.name}", done, error)

    def run_task(
        self,
        func: Callable[[Callable[[int, str], None]], Any],
        label: str,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
    ) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        self.busy = True
        self.cancel_event = threading.Event()
        self._set_status(label, "info")
        self._show_progress(0)

        def progress(percent: int, text: str) -> None:
            self._post("progress", (percent, text))

        def worker() -> None:
            try:
                result = func(progress)
            except Exception as error:
                self._post("task_error", (on_error, error, traceback.format_exc()))
            else:
                self._post("task_done", (on_done, result))
            finally:
                self._post("task_idle", None)

        threading.Thread(target=worker, name="launcher-task", daemon=True).start()

    def _on_game_line(self, line: str) -> None:
        self._post("log_line", line)

    def _on_game_exit(self, code: int) -> None:
        self._post("game_exit", code)

    def open_log_window(self) -> None:
        if self.log_window is not None:
            try:
                self.log_window.deiconify()
                self.log_window.lift()
                return
            except Exception:
                self.log_window = None
        self.log_window = LogWindow(self)
        while self._pending_log:
            self.log_window.append(self._pending_log.popleft())

    def _open_version_folder(self, version_id: str) -> None:
        path = Path(self.cfg.game_dir) / "versions" / version_id
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except Exception as error:
            AlertDialog(self, "无法打开文件夹", str(error), kind="error")

    def open_version_folder(self, version_id: str) -> None:
        self._open_version_folder(version_id)

    def open_game_dir(self) -> None:
        try:
            path = Path(self.cfg.game_dir)
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(str(path))
        except Exception as error:
            AlertDialog(self, "无法打开游戏目录", str(error), kind="error")

    def version_instance_dir(self, version_id: str) -> Path:
        return instance_dir_for_version(Path(self.cfg.game_dir), version_id)

    def show_version_manage_dialog(self, version_id: str) -> None:
        from .dialogs import VersionManageDialog

        VersionManageDialog(self, version_id)

    def show_hidden_dialog(self) -> None:
        from .dialogs import HiddenVersionsDialog

        HiddenVersionsDialog(self)

    def hide_version(self, version_id: str) -> None:
        hidden = list(dict.fromkeys(list(self.cfg.hidden_versions) + [version_id]))
        self.cfg.hidden_versions = hidden
        if self.cfg.selected_version == version_id:
            self.cfg.selected_version = ""
        if self.cfg.last_version == version_id:
            self.cfg.last_version = ""
        self.store.save(self.cfg)
        self.refresh_local_versions()
        self.notify(f"已将 {version_id} 从列表移除（文件仍保留）", "success")

    def restore_hidden_versions(self, version_ids: list[str]) -> None:
        hidden = set(self.cfg.hidden_versions)
        for version_id in version_ids:
            hidden.discard(version_id)
        self.cfg.hidden_versions = sorted(hidden)
        self.store.save(self.cfg)
        self.refresh_local_versions()
        self.notify(f"已恢复 {len(version_ids)} 个隐藏版本", "success")

    def delete_version_files(self, version_id: str) -> None:
        game_dir = Path(self.cfg.game_dir)
        version_dir = game_dir / "versions" / version_id
        try:
            version_dir.resolve().relative_to((game_dir / "versions").resolve())
        except Exception:
            raise RuntimeError("版本路径不在游戏目录中，已取消删除")
        if not version_dir.is_dir():
            raise FileNotFoundError(f"版本文件夹不存在：{version_dir}")
        shutil.rmtree(version_dir)
        if version_id in self.cfg.hidden_versions:
            self.cfg.hidden_versions = [
                item for item in self.cfg.hidden_versions if item != version_id
            ]
        if self.cfg.selected_version == version_id:
            self.cfg.selected_version = ""
        if self.cfg.last_version == version_id:
            self.cfg.last_version = ""
        self.store.save(self.cfg)
        self.refresh_local_versions()
        self.notify(f"已删除版本 {version_id}", "success")

    def export_launch_script(self, version_id: str) -> None:
        if self.busy:
            self.notify("请等待当前任务完成", "warn")
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="导出启动脚本",
            defaultextension=".bat",
            initialfile=f"启动-{re.sub(r'[<>:"/\\|?*]', '_', version_id)}.bat",
            filetypes=[("启动脚本", "*.bat")],
        )
        if not target:
            return
        game_dir = Path(self.cfg.game_dir)
        target_path = Path(target)
        cfg = self.cfg

        def task(progress: Callable[[int, str], None]) -> Any:
            version = resolve_version(game_dir, version_id)
            required = required_java_major(version)
            java = self.java_manager.ensure(
                required,
                component_from_version(version),
                cfg.java_path,
                cfg.auto_java,
                progress,
                self.cancel_event,
            )
            plan = build_launch_plan(game_dir, version_id, cfg, java.path, java.major)
            return plan

        def done(plan: Any) -> None:
            try:
                self._write_launch_script(plan, target_path)
            except Exception as error:
                AlertDialog(self, "导出失败", str(error), kind="error")
                return
            self.notify(f"启动脚本已导出：{target_path}", "success")

        def error(exc: Exception, detail: str) -> None:
            AlertDialog(self, "导出失败", str(exc), detail=detail, kind="error")

        self.run_task(task, f"正在准备 {version_id} 的启动脚本", done, error)

    def _write_launch_script(self, plan: Any, target: Path) -> None:
        command_line = subprocess.list2cmdline(plan.command)
        if len(command_line) < 7400:
            content = (
                "@echo off\n"
                "chcp 65001 >nul\n"
                f'cd /d "{plan.cwd}"\n'
                f"{command_line}\n"
                "pause\n"
            )
            target.write_text(content, encoding="utf-8")
            return

        ps1_path = target.with_suffix(".ps1")

        def quote(value: str) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        arguments = "\n".join(f"  {quote(argument)}," for argument in plan.command[1:])
        ps1 = (
            f"Set-Location -LiteralPath {quote(str(plan.cwd))}\n"
            "$arguments = @(\n"
            f"{arguments}\n"
            ")\n"
            f"& {quote(plan.command[0])} @arguments\n"
            "Read-Host '按 Enter 关闭'\n"
        )
        ps1_path.write_text(ps1, encoding="utf-8-sig")
        content = (
            "@echo off\n"
            "chcp 65001 >nul\n"
            f'powershell -NoProfile -ExecutionPolicy Bypass -File "{ps1_path.name}"\n'
            "pause\n"
        )
        target.write_text(content, encoding="utf-8")

    def notify(self, text: str, kind: str = "info") -> None:
        color = {
            "success": theme.GREEN,
            "warn": theme.WARNING,
            "error": theme.DANGER,
            "info": theme.MUTED,
        }.get(kind, theme.MUTED)
        self.status_label.configure(text=text, text_color=color)
        if self._status_reset_job is not None:
            try:
                self.after_cancel(self._status_reset_job)
            except Exception:
                pass
        self._status_reset_job = self.after(5000, self._reset_status)

    def _set_status(self, text: str, kind: str = "info") -> None:
        color = {
            "success": theme.GREEN,
            "warn": theme.WARNING,
            "error": theme.DANGER,
            "info": theme.MUTED,
        }.get(kind, theme.MUTED)
        self.status_label.configure(text=text, text_color=color)

    def _reset_status(self) -> None:
        self._status_reset_job = None
        if self.busy:
            return
        if self.game_running:
            self._set_status("游戏运行中", "success")
        else:
            self._set_status("就绪", "info")

    def _show_progress(self, value: float) -> None:
        if self._progress_hide_job is not None:
            try:
                self.after_cancel(self._progress_hide_job)
            except Exception:
                pass
            self._progress_hide_job = None
        try:
            self.progress_bar.grid()
            self.progress_bar.set(max(0.0, min(1.0, value)))
        except Exception:
            pass

    def _hide_progress_later(self) -> None:
        if self._progress_hide_job is not None:
            try:
                self.after_cancel(self._progress_hide_job)
            except Exception:
                pass
        self._progress_hide_job = self.after(1200, self._hide_progress)

    def _hide_progress(self) -> None:
        self._progress_hide_job = None
        try:
            self.progress_bar.grid_remove()
        except Exception:
            pass

    def _post(self, event_type: str, payload: Any) -> None:
        self._events.put((event_type, payload))

    def _poll_events(self) -> None:
        try:
            while True:
                try:
                    event_type, payload = self._events.get_nowait()
                except queue.Empty:
                    break
                self._handle_event(event_type, payload)
        finally:
            self.after(60, self._poll_events)

    def _handle_event(self, event_type: str, payload: Any) -> None:
        if event_type == "progress":
            percent, text = payload
            self._set_status(text, "info")
            self._show_progress(percent / 100 if percent <= 100 else 1.0)
        elif event_type == "task_done":
            callback, result = payload
            self.busy = False
            self.cancel_event = None
            self._hide_progress_later()
            if callback is not None:
                try:
                    callback(result)
                except Exception:
                    LOGGER.exception("任务完成回调失败")
        elif event_type == "task_error":
            callback, error, detail = payload
            self.busy = False
            self.cancel_event = None
            self._hide_progress_later()
            self._set_status("任务失败", "error")
            if callback is not None:
                try:
                    callback(error, detail)
                except Exception:
                    LOGGER.exception("任务错误回调失败")
            else:
                AlertDialog(self, "操作失败", str(error), detail=detail, kind="error")
        elif event_type == "task_idle":
            self.busy = False
            self._hide_progress_later()
        elif event_type == "bg_done":
            callback, result = payload
            if callback is not None:
                try:
                    callback(result)
                except Exception:
                    LOGGER.exception("后台任务回调失败")
        elif event_type == "bg_error":
            callback, error, detail = payload
            LOGGER.error("后台任务失败：%s\n%s", error, detail)
            if callback is not None:
                try:
                    callback(error, detail)
                except Exception:
                    LOGGER.exception("后台任务错误回调失败")
            else:
                AlertDialog(self, "操作失败", str(error), detail=detail, kind="error")
        elif event_type == "manifest_ok":
            self.manifest = payload
            self.manifest_error = ""
            self._manifest_loading = False
            if self._current_page == "downloads":
                try:
                    self.pages["downloads"].refresh()
                except Exception:
                    LOGGER.exception("刷新下载页面失败")
            if self.manifest.stale:
                self.notify("网络较慢，已使用缓存的版本列表", "warn")
        elif event_type == "manifest_error":
            self._manifest_loading = False
            self.manifest_error = str(payload)
            self.notify("获取版本列表失败，请检查网络", "error")
            if self._current_page == "downloads":
                try:
                    self.pages["downloads"].refresh()
                except Exception:
                    pass
        elif event_type == "java_ok":
            self._select_java_from(payload)
        elif event_type == "java_error":
            self.java_scanning = False
            LOGGER.error("Java 检测失败：%s", payload)
            try:
                self.pages["home"].update_view()
                self.pages["settings"].update_java_status()
            except Exception:
                pass
        elif event_type == "log_line":
            if self.log_window is None:
                self._pending_log.append(str(payload))
                if self.cfg.show_log and self.game_running:
                    self.open_log_window()
            else:
                self.log_window.append(str(payload))
        elif event_type == "game_exit":
            self.game_running = False
            self.current_process = None
            code = int(payload)
            if code == 0:
                self._set_status("游戏已退出", "success")
            else:
                self._set_status(f"游戏异常退出（代码 {code}）", "error")
                self.notify(f"游戏异常退出（代码 {code}），请查看日志", "error")
            try:
                self.pages["home"].update_view()
            except Exception:
                pass

    def _exit_app(self) -> None:
        try:
            self.after(10, self.tk.quit)
        except Exception:
            pass

    def _on_close(self) -> None:
        if self.busy:
            def close_anyway() -> None:
                if self.cancel_event is not None:
                    self.cancel_event.set()
                self._exit_app()

            ConfirmDialog(
                self,
                "正在执行任务",
                "下载或启动任务仍在进行，退出可能会留下未完成的文件。确定要退出吗？",
                close_anyway,
                confirm_text="退出",
            )
            return
        if self.game_running:
            ConfirmDialog(
                self,
                "游戏正在运行",
                "退出启动器不会关闭已经启动的游戏。确定要退出吗？",
                self._exit_app,
                confirm_text="退出",
            )
            return
        self._exit_app()

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:  # type: ignore[override]
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        LOGGER.error("界面异常：\n%s", detail)
        try:
            AlertDialog(self, "界面出现异常", str(exc_value), detail=detail, kind="error")
        except Exception:
            pass


def setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "launcher.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def run() -> None:
    from ..paths import ensure_app_dirs

    ensure_app_dirs()
    setup_logging()
    LOGGER.info("启动 %s v%s", APP_DISPLAY_NAME, APP_VERSION)
    app = LimeLauncherApp()
    app.mainloop()
