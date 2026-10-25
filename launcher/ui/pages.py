from __future__ import annotations

import io
import os
import queue
import threading
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk

from ..config import MAX_MEMORY_LIMIT, validate_username
from ..net import read_bytes
from ..paths import APP_VERSION, ICON_PNG
from ..version import LocalVersion, type_label
from . import theme
from .dialogs import AlertDialog
from .widgets import (
    Badge,
    EmptyState,
    StatCard,
    VersionRow,
    card,
    clear_children,
    primary_button,
    secondary_button,
    text_button,
)


def _format_mtime(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def _format_date(value: str) -> str:
    if not value:
        return "未知时间"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return value[:10]


def _short_path(path: Path, limit: int = 52) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return text[: limit // 2 - 2] + "..." + text[-(limit // 2 - 1):]


def _scale(widget: tk.Misc) -> float:
    try:
        return max(1.0, widget.winfo_fpixels("1i") / 96.0)
    except Exception:
        return 1.0


def _on_wheel(event: tk.Event) -> str:
    try:
        event.widget.yview_scroll(-int(event.delta / 120) * 3, "units")
    except Exception:
        pass
    return "break"


def _matches(query: str, text: str) -> bool:
    tokens = [token for token in query.lower().split() if token]
    if not tokens:
        return True
    haystack = text.lower()
    return all(token in haystack for token in tokens)


def _format_downloads(value: int) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f} 亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f} 万"
    return str(value)


class Page(ctk.CTkFrame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, fg_color="transparent")
        self.app = app

    def on_show(self) -> None:
        pass


class HomePage(Page):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=2, pady=(0, 18))
        header.grid_columnconfigure(0, weight=1)
        self.hello_label = ctk.CTkLabel(
            header,
            text="你好",
            text_color=theme.TEXT,
            font=theme.font(25, "bold"),
            anchor="w",
        )
        self.hello_label.grid(row=0, column=0, sticky="w")
        self.sub_label = ctk.CTkLabel(
            header,
            text="准备好开始新的冒险了吗？",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        )
        self.sub_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.account_button = ctk.CTkButton(
            header,
            text="离线账户 · Player",
            command=lambda: self.app.show_page("settings"),
            width=150,
            height=36,
            corner_radius=10,
            fg_color=theme.WHITE,
            hover_color=theme.CARD_HOVER,
            border_width=1,
            border_color=theme.BORDER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        )
        self.account_button.grid(row=0, column=1, rowspan=2, sticky="e")

        self.hero = ctk.CTkFrame(self, fg_color="#EEF4FF", corner_radius=20, height=232)
        self.hero.grid(row=1, column=0, sticky="ew")
        self.hero.grid_propagate(False)
        self.hero_canvas = tk.Canvas(self.hero, bg="#EEF4FF", highlightthickness=0)
        self.hero_canvas.place(x=520, y=10, width=350, height=212)
        self.hero.bind("<Configure>", self._draw_hero)

        self.hero_title = ctk.CTkLabel(
            self.hero,
            text="Minecraft",
            fg_color="transparent",
            text_color="#003FB8",
            font=theme.font(31, "bold"),
            anchor="w",
        )
        self.hero_title.place(x=36, y=32)
        self.hero_sub = ctk.CTkLabel(
            self.hero,
            text="选择一个版本，开始你的方块世界",
            fg_color="transparent",
            text_color=theme.TEXT_SOFT,
            font=theme.font(13),
            anchor="w",
        )
        self.hero_sub.place(x=38, y=80)
        self.hero_version = ctk.CTkLabel(
            self.hero,
            text="当前版本 · 未选择",
            fg_color="transparent",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        )
        self.hero_version.place(x=38, y=107)

        self.play_button = primary_button(self.hero, "开始游戏", self.app.start_game, width=148, height=44)
        self.play_button.place(x=36, y=148)
        self.version_menu = ctk.CTkOptionMenu(
            self.hero,
            values=["暂无版本"],
            command=self.app.select_version,
            width=182,
            height=36,
            corner_radius=9,
            fg_color=theme.WHITE,
            button_color=theme.WHITE,
            button_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            dropdown_fg_color=theme.WHITE,
            dropdown_hover_color=theme.CARD_ACTIVE,
            dropdown_text_color=theme.TEXT_SOFT,
            font=theme.font(12),
            dropdown_font=theme.font(12),
        )
        self.version_menu.place(x=194, y=152)

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="ew", pady=(16, 24))
        for index in range(3):
            stats.grid_columnconfigure(index, weight=1, uniform="stat")
        self.stat_versions = StatCard(stats, "已安装版本", theme.ACCENT)
        self.stat_versions.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.stat_java = StatCard(stats, "Java 环境", theme.GREEN)
        self.stat_java.grid(row=0, column=1, sticky="ew", padx=8)
        self.stat_last = StatCard(stats, "上次启动", theme.WARNING)
        self.stat_last.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        recent_header = ctk.CTkFrame(self, fg_color="transparent")
        recent_header.grid(row=3, column=0, sticky="new")
        recent_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            recent_header,
            text="最近游玩",
            text_color=theme.TEXT,
            font=theme.font(16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        text_button(recent_header, "查看全部", lambda: self.app.show_page("versions")).grid(
            row=0, column=1, sticky="e"
        )
        self.recent_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.recent_frame.grid(row=4, column=0, sticky="new", pady=(10, 0))
        self.recent_frame.grid_columnconfigure(0, weight=1)

    def _draw_hero(self, _event: tk.Event | None = None) -> None:
        try:
            width = max(2, self.hero.winfo_width())
            scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        except Exception:
            return
        canvas = self.hero_canvas
        canvas_w = int(350 * scale)
        canvas_h = int(212 * scale)
        margin = int(10 * scale)
        if width < canvas_w + int(430 * scale):
            canvas_w = max(int(220 * scale), width - int(430 * scale))
            canvas_h = min(canvas_h, max(80, self.hero.winfo_height() - margin * 2))
        canvas.place_configure(
            x=max(int(420 * scale), width - canvas_w - margin),
            y=margin,
            width=canvas_w,
            height=canvas_h,
        )
        canvas.delete("all")

        def point(x: float, y: float) -> tuple[int, int]:
            return int(x * scale), int(y * scale)

        x1, y1 = point(238, -66)
        x2, y2 = point(404, 92)
        canvas.create_oval(x1, y1, x2, y2, fill="#DDE9FF", outline="")
        x1, y1 = point(28, 144)
        x2, y2 = point(108, 224)
        canvas.create_oval(x1, y1, x2, y2, fill="#E8F0FF", outline="")
        theme.draw_logo(canvas, canvas_w * 0.70, canvas_h * 0.53, 165 * scale)
        for x, y, size in ((48, 48, 8), (88, 156, 5), (150, 30, 6), (286, 168, 7)):
            px, py = point(x, y)
            ps = int(size * scale)
            canvas.create_rectangle(px, py, px + ps, py + ps, fill="#C9DDFF", outline="")

    def update_view(self) -> None:
        cfg = self.app.cfg
        hour = datetime.now().hour
        greeting = "早上好" if hour < 12 else ("下午好" if hour < 18 else "晚上好")
        self.hello_label.configure(text=f"{greeting}，{cfg.username}")
        self.account_button.configure(text=f"离线账户 · {cfg.username}")
        versions = self.app.local_versions
        ids = [item.id for item in versions]
        if ids:
            selected = cfg.selected_version if cfg.selected_version in ids else ids[0]
            self.version_menu.configure(values=ids, state="normal")
            self.version_menu.set(selected)
            self.hero_version.configure(text=f"当前版本 · {selected}")
            if self.app.game_running:
                self.play_button.configure(
                    text="游戏运行中",
                    state="disabled",
                    fg_color=theme.INPUT,
                    text_color=theme.MUTED,
                )
            else:
                self.play_button.configure(
                    text="开始游戏",
                    state="normal",
                    fg_color=theme.ACCENT,
                    text_color=theme.WHITE,
                )
        else:
            self.version_menu.configure(values=["暂无版本"], state="disabled")
            self.version_menu.set("暂无版本")
            self.hero_version.configure(text="还没有安装任何版本")
            self.play_button.configure(
                text="下载游戏",
                state="normal",
                fg_color=theme.ACCENT,
                text_color=theme.WHITE,
            )
        self.stat_versions.set_value(f"{len(versions)} 个", "版")
        self.stat_java.set_value(self.app.java_summary(), "J")
        self.stat_last.set_value(cfg.last_played or "暂无", "时")

        clear_children(self.recent_frame)
        if not versions:
            EmptyState(
                self.recent_frame,
                "还没有安装游戏",
                "前往下载页面安装一个 Minecraft 版本即可开始。",
                "去下载",
                lambda: self.app.show_page("downloads"),
            ).pack(fill="x")
            return
        for version in versions[:2]:
            self._add_recent(version)

    def _add_recent(self, version: LocalVersion) -> None:
        badges: list[tuple[str, str]] = []
        if version.version_type in ("release", "snapshot", "old_beta", "old_alpha"):
            badges.append((version.display_type, "blue" if version.version_type == "release" else "gray"))
        if version.loader != "原版":
            badges.append((version.loader, "green"))
        row = VersionRow(
            self.recent_frame,
            version.id,
            f"最后修改 {_format_mtime(version.modified)}",
            badges,
            primary_text="启动",
            primary_command=lambda vid=version.id: self.app.start_version(vid),
            secondary_text="详情",
            secondary_command=lambda vid=version.id: self.app.show_page("versions"),
            symbol=version.loader[:1] if version.loader != "原版" else "M",
        )
        row.pack(fill="x", pady=(0, 8))


class VersionsPage(Page):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._search_job: str | None = None
        self._versions: dict[str, LocalVersion] = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=2)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="版本",
            text_color=theme.TEXT,
            font=theme.font(25, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="管理已经安装的 Minecraft 版本，也可以导入其他启动器的版本",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        primary_button(header, "导入版本", self.app.show_import_dialog, width=92, height=34).grid(
            row=0, column=3, rowspan=2, sticky="e"
        )
        self.hidden_button = secondary_button(header, "已隐藏", self.app.show_hidden_dialog, width=78, height=34)
        self.hidden_button.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 8))
        secondary_button(header, "刷新", self.refresh, width=72, height=34).grid(
            row=0, column=1, rowspan=2, sticky="e", padx=(0, 8)
        )

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=2, pady=(16, 8))
        toolbar.grid_columnconfigure(1, weight=1)
        self.search_entry = ctk.CTkEntry(
            toolbar,
            placeholder_text="搜索版本、类型或加载器",
            width=300,
            height=36,
            corner_radius=9,
            border_width=0,
            fg_color=theme.WHITE,
            text_color=theme.TEXT,
            placeholder_text_color=theme.MUTED,
            font=theme.font(12),
        )
        self.search_entry.grid(row=0, column=0, sticky="w")
        self.search_entry.bind("<KeyRelease>", self._schedule_refresh)
        self.count_label = ctk.CTkLabel(
            toolbar,
            text="",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="e",
        )
        self.count_label.grid(row=0, column=1, sticky="e")

        table = card(self)
        table.grid(row=2, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        scale = _scale(self)
        self.tree = ttk.Treeview(
            table,
            columns=("version", "type", "loader", "modified", "state"),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        for column, title, width in (
            ("version", "版本", 380),
            ("type", "类型", 120),
            ("loader", "加载器", 120),
            ("modified", "最后修改", 180),
            ("state", "状态", 100),
        ):
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=int(width * scale), anchor="w", stretch=(column == "version"))
        self.tree.tag_configure("incomplete", foreground=theme.WARNING)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="FML.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda event: self._launch())
        self.tree.bind("<MouseWheel>", _on_wheel)
        self.tree.bind("<Return>", lambda event: self._launch())

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=3, column=0, sticky="ew", pady=(12, 2))
        action.grid_columnconfigure(0, weight=1)
        self.selection_label = ctk.CTkLabel(
            action,
            text="选择一个版本",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.selection_label.grid(row=0, column=0, sticky="w")
        self.open_button = secondary_button(action, "打开文件夹", self._open_folder, width=100, height=36)
        self.open_button.configure(state="disabled")
        self.open_button.grid(row=0, column=1, padx=(0, 8))
        self.manage_button = secondary_button(action, "管理", self._manage, width=82, height=36)
        self.manage_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
        self.manage_button.grid(row=0, column=2, padx=(0, 8))
        self.launch_button = primary_button(action, "启动", self._launch, width=100, height=36)
        self.launch_button.configure(state="disabled")
        self.launch_button.grid(row=0, column=3)

    def on_show(self) -> None:
        self.refresh()

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
        self._search_job = self.after(180, self.refresh)

    def refresh(self) -> None:
        self._search_job = None
        query = self.search_entry.get().strip().lower()
        versions = []
        for item in self.app.local_versions:
            text = f"{item.id} {type_label(item.version_type)} {item.loader} {item.directory}"
            if _matches(query, text):
                versions.append(item)
        self.tree.delete(*self.tree.get_children())
        self._versions = {}
        self.count_label.configure(text=f"共 {len(versions)} 个版本")
        hidden_count = len(self.app.cfg.hidden_versions)
        self.hidden_button.configure(text=f"已隐藏 {hidden_count}" if hidden_count else "已隐藏")
        for item in versions:
            self._versions[item.id] = item
            state = "可用" if item.complete else "文件不完整"
            tags = ("incomplete",) if not item.complete else ()
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                values=(item.id, type_label(item.version_type), item.loader, _format_mtime(item.modified), state),
                tags=tags,
            )
        selected = self.app.cfg.selected_version
        if selected in self._versions:
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.tree.see(selected)
        self._update_selection()

    def _selected(self) -> LocalVersion | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._versions.get(selection[0])

    def _on_select(self, _event: tk.Event | None = None) -> None:
        self._update_selection()

    def _update_selection(self) -> None:
        item = self._selected()
        if item is None:
            self.selection_label.configure(text="选择一个版本")
            self.launch_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
            self.open_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
            self.manage_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
            return
        self.selection_label.configure(text=f"{item.id} · {type_label(item.version_type)} · {item.loader}")
        self.launch_button.configure(state="normal", fg_color=theme.ACCENT, text_color=theme.WHITE)
        self.open_button.configure(state="normal", text_color=theme.ACCENT)
        self.manage_button.configure(state="normal", text_color=theme.ACCENT)

    def _launch(self) -> None:
        item = self._selected()
        if item is not None:
            self.app.start_version(item.id)

    def _open_folder(self) -> None:
        item = self._selected()
        if item is not None:
            self.app.open_version_folder(item.id)

    def _manage(self) -> None:
        item = self._selected()
        if item is not None:
            self.app.show_version_manage_dialog(item.id)


class DownloadsPage(Page):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.filter_value = "release"
        self._search_job: str | None = None
        self._versions: dict[str, dict[str, Any]] = {}

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=2)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="下载游戏",
            text_color=theme.TEXT,
            font=theme.font(25, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="先选择 Minecraft 版本，再选择原版、Fabric、Forge、NeoForge 或 OptiFine",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        secondary_button(header, "刷新列表", self.app.reload_manifest, width=88, height=34).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=2, pady=(16, 8))
        toolbar.grid_columnconfigure(2, weight=1)
        self.filter = ctk.CTkSegmentedButton(
            toolbar,
            values=["正式版", "快照", "全部"],
            command=self._change_filter,
            height=34,
            corner_radius=8,
            fg_color=theme.INPUT,
            selected_color=theme.ACCENT_SOFT,
            selected_hover_color="#DDE8FF",
            unselected_color=theme.INPUT,
            unselected_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        )
        self.filter.set("正式版")
        self.filter.grid(row=0, column=0, sticky="w")
        self.search_entry = ctk.CTkEntry(
            toolbar,
            placeholder_text="搜索版本号",
            width=230,
            height=36,
            corner_radius=9,
            border_width=0,
            fg_color=theme.WHITE,
            text_color=theme.TEXT,
            placeholder_text_color=theme.MUTED,
            font=theme.font(12),
        )
        self.search_entry.grid(row=0, column=1, padx=(12, 0), sticky="w")
        self.search_entry.bind("<KeyRelease>", self._schedule_refresh)
        self.count_label = ctk.CTkLabel(
            toolbar,
            text="",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="e",
        )
        self.count_label.grid(row=0, column=2, sticky="e")

        table = card(self)
        table.grid(row=3, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        scale = _scale(self)
        self.tree = ttk.Treeview(
            table,
            columns=("version", "type", "date", "state"),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        for column, title, width in (
            ("version", "版本", 460),
            ("type", "类型", 140),
            ("date", "发布时间", 200),
            ("state", "状态", 120),
        ):
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=int(width * scale), anchor="w", stretch=(column == "version"))
        self.tree.tag_configure("installed", foreground=theme.GREEN)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="FML.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda event: self._install())
        self.tree.bind("<Return>", lambda event: self._install())
        self.tree.bind("<MouseWheel>", _on_wheel)

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=4, column=0, sticky="ew", pady=(12, 2))
        action.grid_columnconfigure(0, weight=1)
        self.selection_label = ctk.CTkLabel(
            action,
            text="选择一个版本后点击安装",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.selection_label.grid(row=0, column=0, sticky="w")
        self.install_button = primary_button(action, "安装 / 选择加载器", self._install, width=158, height=36)
        self.install_button.configure(state="disabled")
        self.install_button.grid(row=0, column=1)

    def on_show(self) -> None:
        self.refresh()
        self.app.ensure_manifest()

    def _change_filter(self, value: str) -> None:
        self.filter_value = {"正式版": "release", "快照": "snapshot", "全部": "all"}.get(value, "release")
        self.refresh()

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
        self._search_job = self.after(180, self.refresh)

    def refresh(self) -> None:
        self._search_job = None
        manifest = self.app.manifest
        self.tree.delete(*self.tree.get_children())
        self._versions = {}
        if not manifest or not manifest.versions:
            if getattr(self.app, "manifest_error", ""):
                self.count_label.configure(text="版本列表获取失败，请检查网络后点击刷新列表", text_color=theme.DANGER)
            else:
                self.count_label.configure(text="正在获取版本列表…", text_color=theme.MUTED)
            self._update_selection()
            return
        query = self.search_entry.get().strip().lower()
        installed = {item.id for item in self.app.local_versions}
        count = 0
        for version in manifest.versions:
            version_id = str(version.get("id", ""))
            version_type = str(version.get("type", ""))
            if self.filter_value == "release" and version_type != "release":
                continue
            if self.filter_value == "snapshot" and version_type != "snapshot":
                continue
            if not _matches(query, f"{version_id} {type_label(version_type)}"):
                continue
            count += 1
            self._versions[version_id] = version
            state = "已安装" if version_id in installed else "可安装"
            tags = ("installed",) if version_id in installed else ()
            self.tree.insert(
                "",
                "end",
                iid=version_id,
                values=(version_id, type_label(version_type), _format_date(str(version.get("releaseTime", ""))), state),
                tags=tags,
            )
        self.count_label.configure(text=f"共 {count} 个版本", text_color=theme.MUTED)
        selected = self.app.cfg.selected_version
        if selected in self._versions:
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.tree.see(selected)
        self._update_selection()

    def _selected(self) -> dict[str, Any] | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._versions.get(selection[0])

    def _on_select(self, _event: tk.Event | None = None) -> None:
        self._update_selection()

    def _update_selection(self) -> None:
        version = self._selected()
        if version is None:
            self.selection_label.configure(text="选择一个版本后点击安装")
            self.install_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
            return
        version_id = str(version.get("id", ""))
        self.selection_label.configure(text=f"{version_id} · 选择安装方式")
        self.install_button.configure(state="normal", fg_color=theme.ACCENT, text_color=theme.WHITE)

    def _install(self) -> None:
        version = self._selected()
        if version is None:
            return
        version_id = str(version.get("id", ""))
        entry_url = str(version.get("url", ""))
        self.app.show_loader_dialog(version_id, entry_url)


class ResourcesPage(Page):
    TYPES = {"模组": "mod", "光影": "shader", "资源包": "resourcepack", "整合包": "modpack"}
    SOURCES = {"Modrinth": "modrinth", "CurseForge": "curseforge"}

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._search_job: str | None = None
        self._token = 0
        self._items: dict[str, Any] = {}
        self._last_context: tuple[str, str, str, str, str] | None = None

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=2)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="资源",
            text_color=theme.TEXT,
            font=theme.font(25, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="从 Modrinth 与 CurseForge 下载模组、光影、资源包和整合包",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=2, pady=(16, 6))
        toolbar.grid_columnconfigure(3, weight=1)
        self.source = ctk.CTkSegmentedButton(
            toolbar,
            values=["Modrinth", "CurseForge"],
            command=lambda value: self._start_search(),
            height=34,
            corner_radius=8,
            fg_color=theme.INPUT,
            selected_color=theme.ACCENT_SOFT,
            selected_hover_color="#DDE8FF",
            unselected_color=theme.INPUT,
            unselected_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        )
        self.source.set("Modrinth")
        self.source.grid(row=0, column=0, sticky="w")
        self.type_filter = ctk.CTkSegmentedButton(
            toolbar,
            values=["模组", "光影", "资源包", "整合包"],
            command=lambda value: self._start_search(),
            height=34,
            corner_radius=8,
            fg_color=theme.INPUT,
            selected_color=theme.ACCENT_SOFT,
            selected_hover_color="#DDE8FF",
            unselected_color=theme.INPUT,
            unselected_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        )
        self.type_filter.set("模组")
        self.type_filter.grid(row=0, column=1, padx=(10, 0), sticky="w")
        self.search_entry = ctk.CTkEntry(
            toolbar,
            placeholder_text="搜索资源名称",
            width=240,
            height=36,
            corner_radius=9,
            border_width=0,
            fg_color=theme.WHITE,
            text_color=theme.TEXT,
            placeholder_text_color=theme.MUTED,
            font=theme.font(12),
        )
        self.search_entry.grid(row=0, column=2, padx=(10, 8), sticky="w")
        self.search_entry.bind("<KeyRelease>", self._schedule_search)
        self.search_entry.bind("<Return>", lambda event: self._start_search())
        primary_button(toolbar, "搜索", self._start_search, width=72, height=36).grid(row=0, column=3, sticky="e")

        self.compat_label = ctk.CTkLabel(
            self,
            text="",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.compat_label.grid(row=2, column=0, sticky="w", padx=4, pady=(0, 8))

        table = card(self)
        table.grid(row=3, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        scale = _scale(self)
        self._photos: dict[str, Any] = {}
        self._icon_bytes: dict[str, bytes] = {}
        self._icon_size = max(18, int(28 * scale))
        try:
            default_image = ImageOps.fit(
                Image.open(ICON_PNG).convert("RGBA"),
                (self._icon_size, self._icon_size),
                Image.LANCZOS,
            )
            self._default_photo = ImageTk.PhotoImage(default_image)
        except Exception:
            self._default_photo = None
        self.tree = ttk.Treeview(
            table,
            columns=("name", "author", "downloads", "summary"),
            show="tree headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        self.tree.heading("#0", text="", anchor="center")
        self.tree.column("#0", width=int(44 * scale), stretch=False, anchor="center")
        for column, title, width in (
            ("name", "名称", 320),
            ("author", "作者", 140),
            ("downloads", "下载量", 110),
            ("summary", "简介", 520),
        ):
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=int(width * scale), anchor="w", stretch=(column == "summary"))
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="FML.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda event: self._open_selected())
        self.tree.bind("<Return>", lambda event: self._open_selected())
        self.tree.bind("<MouseWheel>", _on_wheel)

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=4, column=0, sticky="ew", pady=(12, 2))
        action.grid_columnconfigure(0, weight=1)
        self.selection_label = ctk.CTkLabel(
            action,
            text="选择一个资源查看可用文件",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.selection_label.grid(row=0, column=0, sticky="w")
        self.open_button = primary_button(action, "查看文件", self._open_selected, width=112, height=36)
        self.open_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
        self.open_button.grid(row=0, column=1)

    def _context(self) -> tuple[str, str]:
        return self.app.selected_game_context()

    def on_show(self) -> None:
        mc, loader = self._context()
        source = self.SOURCES.get(self.source.get(), "modrinth")
        type_key = self.TYPES.get(self.type_filter.get(), "mod")
        context_key = (source, type_key, self.search_entry.get().strip(), mc, loader)
        if context_key != self._last_context:
            self._start_search()

    def _schedule_search(self, _event: tk.Event | None = None) -> None:
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except Exception:
                pass
        self._search_job = self.after(400, self._start_search)

    def _start_search(self) -> None:
        self._search_job = None
        self._token += 1
        token = self._token
        source = self.SOURCES.get(self.source.get(), "modrinth")
        type_key = self.TYPES.get(self.type_filter.get(), "mod")
        mc, loader = self._context()
        self._last_context = (source, type_key, self.search_entry.get().strip(), mc, loader)
        if mc:
            loader_text = f" · {loader}" if loader else ""
            self.compat_label.configure(text=f"兼容 Minecraft {mc}{loader_text}", text_color=theme.MUTED)
        else:
            self.compat_label.configure(text="未选择游戏版本 · 显示全部资源", text_color=theme.MUTED)
        self.tree.delete(*self.tree.get_children())
        self._items = {}
        self.selection_label.configure(text="正在搜索资源…")
        self.open_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
        self.app.search_resources(
            source,
            type_key,
            self.search_entry.get().strip(),
            mc,
            loader,
            lambda items, error: self._show_results(items, error, token),
        )

    def _show_results(self, items: list[Any], error: Exception | None, token: int) -> None:
        if token != self._token:
            return
        if error is not None:
            message = str(error).splitlines()[0] if str(error) else "网络错误"
            self.compat_label.configure(text=f"搜索失败：{message}", text_color=theme.DANGER)
            self.selection_label.configure(text="搜索失败，请检查网络")
            return
        self._items = {}
        self._photos = {}
        for index, item in enumerate(items):
            key = str(index)
            self._items[key] = item
            summary = item.summary or ""
            if len(summary) > 90:
                summary = summary[:88] + "…"
            self.tree.insert(
                "",
                "end",
                iid=key,
                image=self._default_photo,
                values=(item.name, item.author or "-", _format_downloads(item.downloads), summary),
            )
        self._load_icons(items, token)
        if items:
            self.selection_label.configure(text=f"找到 {len(items)} 个资源")
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._on_select()
        else:
            self.selection_label.configure(text="没有找到资源，试试更换关键词或游戏版本")
            self.open_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)

    def _load_icons(self, items: list[Any], token: int) -> None:
        cached: list[tuple[str, str, bytes]] = []
        pending: list[tuple[str, str]] = []
        for index, item in enumerate(items):
            url = str(getattr(item, "icon_url", "") or "")
            if not url:
                continue
            key = str(index)
            if url in self._icon_bytes:
                cached.append((key, url, self._icon_bytes[url]))
            else:
                pending.append((key, url))
        if cached:
            self._apply_icons(cached, token)
        if not pending:
            return

        work_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        for entry in pending:
            work_queue.put(entry)

        def worker() -> None:
            while True:
                try:
                    key, url = work_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    raw = read_bytes(url, 8, 1)
                except Exception:
                    continue
                if token != self._token:
                    return
                self.app._post(
                    "bg_done",
                    (
                        lambda _result, k=key, u=url, r=raw: self._apply_icons([(k, u, r)], token),
                        None,
                    ),
                )

        for _ in range(min(8, len(pending))):
            threading.Thread(target=worker, name="fml-icons", daemon=True).start()

    def _apply_icons(self, data: list[tuple[str, str, bytes]], token: int) -> None:
        if token != self._token:
            return
        for key, url, raw in data:
            try:
                image = Image.open(io.BytesIO(raw)).convert("RGBA")
                image = ImageOps.fit(image, (self._icon_size, self._icon_size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self._photos[key] = photo
                self._icon_bytes[url] = raw
                if self.tree.exists(key):
                    self.tree.item(key, image=photo)
            except Exception:
                continue

    def _on_select(self, _event: tk.Event | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            self.selection_label.configure(text="选择一个资源查看可用文件")
            self.open_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
            return
        item = self._items.get(selection[0])
        if item is None:
            return
        self.selection_label.configure(text=f"{item.name} · {item.author or '未知作者'}")
        self.open_button.configure(state="normal", fg_color=theme.ACCENT, text_color=theme.WHITE)

    def _open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item = self._items.get(selection[0])
        if item is not None:
            self.app.show_resource_dialog(item)


class SettingsPage(Page):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=2)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="设置",
            text_color=theme.TEXT,
            font=theme.font(25, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="调整账户、游戏目录、Java 与启动器行为",
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        primary_button(header, "保存设置", self.save, width=100, height=36).grid(
            row=0, column=1, rowspan=2, sticky="e"
        )

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0, scrollbar_button_color=theme.BORDER_STRONG
        )
        self.scroll.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        self.scroll.grid_columnconfigure(0, weight=1)

        self._build_account()
        self._build_game()
        self._build_java()
        self._build_launcher()
        self._build_about()

    def _section(self, title: str, description: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        wrapper = card(self.scroll)
        wrapper.pack(fill="x", pady=(0, 12), padx=(0, 6))
        wrapper.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            wrapper,
            text=title,
            text_color=theme.TEXT,
            font=theme.font(15, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(
            wrapper,
            text=description,
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=20)
        content = ctk.CTkFrame(wrapper, fg_color="transparent")
        content.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 20))
        content.grid_columnconfigure(1, weight=1)
        return wrapper, content

    def _label(self, parent: tk.Misc, text: str, row: int, pady: tuple[int, int] = (0, 8)) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
            anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=pady)

    def _entry(self, parent: tk.Misc, width: int = 340) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            width=width,
            height=38,
            corner_radius=9,
            border_width=0,
            fg_color=theme.INPUT,
            text_color=theme.TEXT,
            placeholder_text_color=theme.MUTED,
            font=theme.font(12),
        )

    def _build_account(self) -> None:
        _, content = self._section("账户", "当前仅支持离线账户。玩家名称会用于游戏内显示，并生成本地 UUID。")
        self._label(content, "玩家名称", 0)
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=2, sticky="w")
        self.avatar_label = ctk.CTkLabel(
            row,
            text="P",
            width=42,
            height=42,
            corner_radius=21,
            fg_color=theme.ACCENT_SOFT,
            text_color=theme.ACCENT_TEXT,
            font=theme.font(17, "bold"),
        )
        self.avatar_label.pack(side="left", padx=(0, 12))
        self.username_entry = self._entry(row, width=260)
        self.username_entry.pack(side="left")
        self.username_entry.bind("<KeyRelease>", self._update_avatar)
        ctk.CTkLabel(
            content,
            text="1-16 位字母、数字或下划线。",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(11),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_game(self) -> None:
        _, content = self._section("游戏", "设置游戏目录与内存分配。修改目录不会移动已有的游戏文件。")
        self._label(content, "游戏目录", 0)
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=2, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        self.game_dir_entry = self._entry(row)
        self.game_dir_entry.grid(row=0, column=0, sticky="ew")
        secondary_button(row, "浏览", self._browse_game_dir, width=70, height=38).grid(
            row=0, column=1, padx=(8, 0)
        )
        secondary_button(row, "打开", self.app.open_game_dir, width=70, height=38).grid(
            row=0, column=2, padx=(8, 0)
        )

        self._label(content, "最大内存", 2, pady=(16, 0))
        memory_row = ctk.CTkFrame(content, fg_color="transparent")
        memory_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        memory_row.grid_columnconfigure(1, weight=1)
        self.memory_slider = ctk.CTkSlider(
            memory_row,
            from_=1024,
            to=MAX_MEMORY_LIMIT,
            number_of_steps=max(1, (MAX_MEMORY_LIMIT - 1024) // 1024),
            command=self._update_memory_label,
            height=20,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            fg_color=theme.INPUT,
        )
        self.memory_slider.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.memory_label = ctk.CTkLabel(
            memory_row,
            text="4 GB",
            text_color=theme.TEXT,
            font=theme.font(12, "bold"),
            width=60,
            anchor="e",
        )
        self.memory_label.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            content,
            text=f"可用上限根据本机内存设置为 {MAX_MEMORY_LIMIT // 1024} GB，推荐 4 GB。",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(11),
            anchor="w",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.fullscreen_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            content,
            text="全屏启动游戏",
            variable=self.fullscreen_var,
            onvalue=True,
            offvalue=False,
            switch_width=36,
            switch_height=18,
            progress_color=theme.ACCENT,
            button_color=theme.WHITE,
            button_hover_color=theme.WHITE,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _build_java(self) -> None:
        _, content = self._section("Java", "启动器会优先自动选择匹配版本的 Java。留空则自动检测。")
        self._label(content, "Java 路径", 0)
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.grid(row=1, column=0, columnspan=2, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        self.java_entry = self._entry(row)
        self.java_entry.grid(row=0, column=0, sticky="ew")
        secondary_button(row, "浏览", self._browse_java, width=70, height=38).grid(
            row=0, column=1, padx=(8, 0)
        )
        self.java_status_label = ctk.CTkLabel(
            content,
            text="正在检测…",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
            wraplength=580,
        )
        self.java_status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.auto_java_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            content,
            text="缺少 Java 时自动下载 Mojang 运行时",
            variable=self.auto_java_var,
            onvalue=True,
            offvalue=False,
            switch_width=36,
            switch_height=18,
            progress_color=theme.ACCENT,
            button_color=theme.WHITE,
            button_hover_color=theme.WHITE,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(14, 0))
        text_button(content, "重新检测 Java", self._redetect_java).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

    def _build_launcher(self) -> None:
        _, content = self._section("启动器", "下载源与启动后的行为。")
        self._label(content, "下载源", 0)
        self.source_seg = ctk.CTkSegmentedButton(
            content,
            values=["自动", "官方", "镜像"],
            height=34,
            corner_radius=8,
            fg_color=theme.INPUT,
            selected_color=theme.ACCENT_SOFT,
            selected_hover_color="#DDE8FF",
            unselected_color=theme.INPUT,
            unselected_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        )
        self.source_seg.grid(row=1, column=0, columnspan=2, sticky="w")
        self.source_seg.set("自动")
        ctk.CTkLabel(
            content,
            text="自动模式会优先使用官方源，失败时切换 BMCLAPI 镜像。",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(11),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.close_after_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            content,
            text="启动游戏后最小化启动器",
            variable=self.close_after_var,
            onvalue=True,
            offvalue=False,
            switch_width=36,
            switch_height=18,
            progress_color=theme.ACCENT,
            button_color=theme.WHITE,
            button_hover_color=theme.WHITE,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(16, 0))
        self.show_log_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            content,
            text="启动游戏后打开日志窗口",
            variable=self.show_log_var,
            onvalue=True,
            offvalue=False,
            switch_width=36,
            switch_height=18,
            progress_color=theme.ACCENT,
            button_color=theme.WHITE,
            button_hover_color=theme.WHITE,
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_about(self) -> None:
        wrapper, content = self._section("关于", "轻量、简洁的 Minecraft 启动器。")
        ctk.CTkLabel(
            content,
            text=f"FBW Minecraft Launcher · 版本 {APP_VERSION}",
            text_color=theme.TEXT_SOFT,
            font=theme.font(12),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(
            content,
            text="基于 Python 与 CustomTkinter 构建。仅支持离线账户，游戏文件来自 Mojang 官方。",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
            justify="left",
            wraplength=590,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _update_avatar(self, _event: tk.Event | None = None) -> None:
        value = self.username_entry.get().strip()
        self.avatar_label.configure(text=(value[:1].upper() or "P"))

    def _update_memory_label(self, value: float) -> None:
        memory = int(round(value / 1024) * 1024)
        self.memory_label.configure(text=f"{memory // 1024} GB")

    def _browse_game_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self, initialdir=self.game_dir_entry.get() or str(Path.home())
        )
        if selected:
            self.game_dir_entry.delete(0, "end")
            self.game_dir_entry.insert(0, selected)

    def _browse_java(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择 java.exe",
            filetypes=[("Java", "java.exe"), ("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if selected:
            self.java_entry.delete(0, "end")
            self.java_entry.insert(0, selected)

    def _redetect_java(self) -> None:
        self.app.detect_java_async(force=True)
        self.java_status_label.configure(text="正在重新检测…", text_color=theme.MUTED)

    def on_show(self) -> None:
        cfg = self.app.cfg
        self.username_entry.delete(0, "end")
        self.username_entry.insert(0, cfg.username)
        self.game_dir_entry.delete(0, "end")
        self.game_dir_entry.insert(0, cfg.game_dir)
        self.java_entry.delete(0, "end")
        self.java_entry.insert(0, cfg.java_path)
        self.memory_slider.set(cfg.max_memory)
        self._update_memory_label(cfg.max_memory)
        self.fullscreen_var.set(cfg.fullscreen)
        self.auto_java_var.set(cfg.auto_java)
        self.close_after_var.set(cfg.close_after_launch)
        self.show_log_var.set(cfg.show_log)
        source = {"auto": "自动", "official": "官方", "mirror": "镜像"}.get(cfg.download_source, "自动")
        self.source_seg.set(source)
        self._update_avatar()
        self.update_java_status()

    def update_java_status(self) -> None:
        if not hasattr(self, "java_status_label"):
            return
        info = self.app.java_info
        if self.app.java_scanning:
            text = "正在检测本机 Java…"
            color = theme.MUTED
        elif info is not None:
            text = f"已检测到 {info.label} · {info.path}"
            color = theme.GREEN
        else:
            text = "未检测到可用的 Java，请指定路径或开启自动下载。"
            color = theme.WARNING
        self.java_status_label.configure(text=text, text_color=color)

    def save(self) -> None:
        username = validate_username(self.username_entry.get())
        if not username:
            AlertDialog(
                self,
                "玩家名称无效",
                "请输入 1-16 位字母、数字或下划线。",
                kind="error",
            )
            return
        game_dir_text = self.game_dir_entry.get().strip()
        if not game_dir_text:
            AlertDialog(self, "游戏目录无效", "请选择一个游戏目录。", kind="error")
            return
        game_dir = Path(game_dir_text)
        try:
            game_dir.mkdir(parents=True, exist_ok=True)
        except Exception as error:
            AlertDialog(self, "无法创建游戏目录", str(error), kind="error")
            return
        memory = int(round(self.memory_slider.get() / 1024) * 1024)
        memory = max(1024, min(MAX_MEMORY_LIMIT, memory))
        source = {"自动": "auto", "官方": "official", "镜像": "mirror"}.get(self.source_seg.get(), "auto")
        updated = self.app.cfg
        old_source = updated.download_source
        updated.username = username
        updated.game_dir = str(game_dir)
        updated.java_path = self.java_entry.get().strip()
        updated.max_memory = memory
        updated.min_memory = min(updated.min_memory, memory)
        updated.auto_java = bool(self.auto_java_var.get())
        updated.fullscreen = bool(self.fullscreen_var.get())
        updated.close_after_launch = bool(self.close_after_var.get())
        updated.show_log = bool(self.show_log_var.get())
        updated.download_source = source
        self.app.save_config(updated, reload_manifest=(source != old_source))
        self.app.notify("设置已保存")
