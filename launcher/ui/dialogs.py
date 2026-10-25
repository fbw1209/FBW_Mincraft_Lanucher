from __future__ import annotations

import os
import shutil
import time
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk

from ..paths import ICON_FILE, LOGS_DIR
from . import theme
from .widgets import card, primary_button, secondary_button, text_button


def _center(window: ctk.CTkToplevel, parent: tk.Misc, width: int, height: int) -> None:
    try:
        parent.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    except Exception:
        x = y = 200
    window.geometry(f"{width}x{height}+{x}+{y}")


def _setup_toplevel(window: ctk.CTkToplevel, title: str, parent: tk.Misc) -> None:
    window.title(title)
    window.configure(fg_color=theme.BG)
    window.transient(parent)
    try:
        window.iconbitmap(str(ICON_FILE))
    except Exception:
        pass
    window.after(120, lambda: theme.apply_windows_icon(window, ICON_FILE))


class AlertDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        detail: str = "",
        kind: str = "info",
    ) -> None:
        super().__init__(parent)
        _setup_toplevel(self, title, parent)
        self.resizable(False, False)
        width, height = 470, 250 if not detail else 360
        _center(self, parent, width, height)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        color = theme.DANGER if kind == "error" else theme.ACCENT
        soft = theme.DANGER_SOFT if kind == "error" else theme.ACCENT_SOFT
        symbol = "!" if kind == "error" else "i"
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 8))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text=symbol,
            width=34,
            height=34,
            corner_radius=17,
            fg_color=soft,
            text_color=color,
            font=theme.font(17, "bold"),
        ).grid(row=0, column=0, rowspan=2, padx=(0, 14))
        ctk.CTkLabel(
            header,
            text=title,
            text_color=theme.TEXT,
            font=theme.font(17, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            header,
            text=message,
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
            justify="left",
            wraplength=360,
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))

        if detail:
            box = ctk.CTkTextbox(
                self,
                fg_color=theme.INPUT,
                text_color=theme.TEXT_SOFT,
                border_width=0,
                corner_radius=10,
                font=ctk.CTkFont(family=theme.MONO_FAMILY, size=11),
            )
            box.grid(row=1, column=0, sticky="nsew", padx=24, pady=(8, 10))
            box.insert("1.0", detail)
            box.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="e", padx=24, pady=(4, 20))
        primary_button(footer, "知道了", self.destroy, width=92).pack()
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass


class ConfirmDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        confirm_text: str = "确定",
    ) -> None:
        super().__init__(parent)
        _setup_toplevel(self, title, parent)
        self.resizable(False, False)
        _center(self, parent, 430, 220)
        self.grid_columnconfigure(0, weight=1)
        self._on_confirm = on_confirm

        ctk.CTkLabel(
            self,
            text=title,
            text_color=theme.TEXT,
            font=theme.font(17, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=26, pady=(24, 8))
        ctk.CTkLabel(
            self,
            text=message,
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
            justify="left",
            wraplength=370,
        ).grid(row=1, column=0, sticky="w", padx=26)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="e", padx=26, pady=22)
        secondary_button(footer, "取消", self.destroy, width=82).pack(side="left", padx=(0, 8))
        primary_button(footer, confirm_text, self._confirm, width=96, fg_color=theme.DANGER).pack(side="left")
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_set()
        except Exception:
            pass

    def _confirm(self) -> None:
        self.destroy()
        try:
            self._on_confirm()
        except Exception:
            pass


class LogWindow(ctk.CTkToplevel):
    def __init__(self, app) -> None:
        super().__init__(app)
        _setup_toplevel(self, "游戏日志", app)
        self.app = app
        self.geometry("900x600")
        self.minsize(680, 420)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._closed = False

        header = ctk.CTkFrame(self, fg_color=theme.WHITE, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="游戏日志",
            text_color=theme.TEXT,
            font=theme.font(16, "bold"),
        ).grid(row=0, column=0, padx=20, pady=14, sticky="w")
        ctk.CTkLabel(
            header,
            text="实时输出，可用于排查启动问题",
            text_color=theme.MUTED,
            font=theme.font(11),
        ).grid(row=0, column=1, padx=10, sticky="w")
        text_button(header, "打开文件夹", self._open_folder).grid(row=0, column=2, padx=(0, 6))
        text_button(header, "清空", self._clear).grid(row=0, column=3, padx=(0, 8))
        secondary_button(header, "关闭", self._close, width=74, height=30).grid(row=0, column=4, padx=(0, 16), pady=10)

        self.text = ctk.CTkTextbox(
            self,
            fg_color=theme.BG,
            text_color=theme.TEXT_SOFT,
            border_width=0,
            corner_radius=0,
            font=ctk.CTkFont(family=theme.MONO_FAMILY, size=11),
            wrap="word",
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        self.text.configure(state="disabled")
        self._line_count = 0
        self.after(80, lambda: theme.apply_light_titlebar(self))

    def append(self, line: str) -> None:
        if self._closed:
            return
        try:
            self.text.configure(state="normal")
            self.text.insert("end", line + "\n")
            self._line_count += 1
            if self._line_count > 4000:
                self.text.delete("1.0", f"{max(1, self._line_count - 3000)}.0")
                self._line_count = 3000
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def _clear(self) -> None:
        try:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")
            self._line_count = 0
        except Exception:
            pass

    def _open_folder(self) -> None:
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(LOGS_DIR))
        except Exception:
            pass

    def _close(self) -> None:
        self._closed = True
        try:
            self.app.log_window = None
        except Exception:
            pass
        self.destroy()


class LoaderDialog(ctk.CTkToplevel):
    OPTIONS = [
        ("vanilla", "原版", "仅安装 Minecraft 本体，不添加模组加载器"),
        ("fabric", "Fabric", "轻量、更新快的现代模组加载器"),
        ("forge", "Forge", "兼容大量传统模组与整合包"),
        ("neoforge", "NeoForge", "Forge 的现代分支，主要支持 1.20.2 及以上"),
        ("optifine", "OptiFine", "高清修复与光影支持，可单独安装"),
    ]

    def __init__(self, parent: tk.Misc, version_id: str, on_choose: Callable[[str], None]) -> None:
        super().__init__(parent)
        _setup_toplevel(self, "选择安装方式", parent)
        self.resizable(False, False)
        _center(self, parent, 570, 590)
        self.grid_columnconfigure(0, weight=1)
        self._on_choose = on_choose

        ctk.CTkLabel(
            self,
            text="选择安装方式",
            text_color=theme.TEXT,
            font=theme.font(20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=26, pady=(22, 2))
        ctk.CTkLabel(
            self,
            text=f"Minecraft {version_id} · 安装前会自动补齐游戏本体文件",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 14))

        for index, (key, title, description) in enumerate(self.OPTIONS):
            row = ctk.CTkFrame(
                self,
                fg_color=theme.WHITE,
                corner_radius=12,
                border_width=1,
                border_color=theme.BORDER,
            )
            row.grid(row=2 + index, column=0, sticky="ew", padx=24, pady=4)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row,
                text=title,
                text_color=theme.TEXT,
                font=theme.font(14, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 0))
            ctk.CTkLabel(
                row,
                text=description,
                text_color=theme.MUTED,
                font=theme.font(11),
                anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=16, pady=(2, 10))
            primary_button(
                row,
                "安装",
                lambda value=key: self._choose(value),
                width=72,
                height=32,
            ).grid(row=0, column=1, rowspan=2, padx=16, pady=10)

        ctk.CTkLabel(
            self,
            text="Forge / NeoForge / OptiFine 需要运行官方安装器，可能会下载较多文件。",
            text_color=theme.MUTED_LIGHT,
            font=theme.font(10),
            anchor="w",
            wraplength=500,
        ).grid(row=8, column=0, sticky="w", padx=28, pady=(12, 4))
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            theme.apply_light_titlebar(self)
        except Exception:
            pass

    def _choose(self, loader: str) -> None:
        self.destroy()
        try:
            self._on_choose(loader)
        except Exception:
            pass


class ImportDialog(ctk.CTkToplevel):
    OPTIONS = [
        ("folder", "导入版本文件夹", "选择包含 <版本名>.json 的版本目录"),
        ("zip", "导入版本压缩包", "支持 PCL 等启动器导出的版本 zip"),
        ("scan", "扫描其他游戏目录", "读取另一个 .minecraft/versions 中的全部版本"),
    ]

    def __init__(self, parent: tk.Misc, on_mode: Callable[[str], None]) -> None:
        super().__init__(parent)
        _setup_toplevel(self, "导入版本", parent)
        self.resizable(False, False)
        _center(self, parent, 540, 390)
        self.grid_columnconfigure(0, weight=1)
        self._on_mode = on_mode

        ctk.CTkLabel(
            self,
            text="导入已有版本",
            text_color=theme.TEXT,
            font=theme.font(20, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=26, pady=(22, 2))
        ctk.CTkLabel(
            self,
            text="复制完成后会自动补齐缺失的运行库和资源文件。",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=26, pady=(0, 14))

        for index, (key, title, description) in enumerate(self.OPTIONS):
            card = ctk.CTkFrame(
                self,
                fg_color=theme.WHITE,
                corner_radius=12,
                border_width=1,
                border_color=theme.BORDER,
            )
            card.grid(row=2 + index, column=0, sticky="ew", padx=24, pady=4)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=title,
                text_color=theme.TEXT,
                font=theme.font(13, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=16, pady=(9, 0))
            ctk.CTkLabel(
                card,
                text=description,
                text_color=theme.MUTED,
                font=theme.font(10),
                anchor="w",
            ).grid(row=1, column=0, sticky="w", padx=16, pady=(1, 9))
            primary_button(
                card,
                "选择",
                lambda value=key: self._choose(value),
                width=70,
                height=30,
            ).grid(row=0, column=1, rowspan=2, padx=16, pady=9)
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            theme.apply_light_titlebar(self)
        except Exception:
            pass

    def _choose(self, mode: str) -> None:
        self.destroy()
        try:
            self._on_mode(mode)
        except Exception:
            pass


class ResourceDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: tk.Misc,
        item: Any,
        meta_text: str,
        on_download: Callable[[Any], None],
    ) -> None:
        super().__init__(parent)
        _setup_toplevel(self, item.name, parent)
        self.geometry("900x620")
        self.minsize(760, 520)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.item = item
        self.on_download = on_download
        self.files: list[Any] = []
        self.selected_file: Any = None

        header = ctk.CTkFrame(self, fg_color=theme.WHITE, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=item.name,
            text_color=theme.TEXT,
            font=theme.font(19, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=22, pady=(16, 2))
        ctk.CTkLabel(
            header,
            text=item.summary,
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=22)
        ctk.CTkLabel(
            header,
            text=meta_text,
            text_color=theme.MUTED_LIGHT,
            font=theme.font(10),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", padx=22, pady=(4, 14))

        table = ctk.CTkFrame(self, fg_color=theme.WHITE, corner_radius=12, border_width=1, border_color=theme.BORDER)
        table.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 10))
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            columns=("name", "game", "date", "size"),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        for column, title, width in (
            ("name", "文件", 350),
            ("game", "兼容版本", 210),
            ("date", "发布时间", 150),
            ("size", "大小", 100),
        ):
            self.tree.heading(column, text=title, anchor="w")
            self.tree.column(column, width=width, anchor="w", stretch=(column == "name"))
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        for column, width in (("name", 390), ("game", 230), ("date", 160), ("size", 110)):
            self.tree.column(column, width=int(width * scale))
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="FML.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda event: self._download())
        self.tree.bind("<MouseWheel>", self._on_wheel)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=22, pady=(0, 18))
        footer.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(
            footer,
            text="正在获取可用文件…",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.status.grid(row=0, column=0, sticky="w")
        self.download_button = primary_button(footer, "下载所选文件", self._download, width=132, height=36)
        self.download_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)
        self.download_button.grid(row=0, column=1, sticky="e")
        self.after(80, lambda: theme.apply_light_titlebar(self))

    def _on_wheel(self, event: tk.Event) -> str:
        self.tree.yview_scroll(-int(event.delta / 120) * 3, "units")
        return "break"

    def set_files(self, files: list[Any]) -> None:
        self.files = files
        self.tree.delete(*self.tree.get_children())
        for index, file in enumerate(files):
            games = ", ".join(file.game_versions[:4])
            date = file.published[:10]
            size = f"{file.size / 1048576:.1f} MB" if file.size else "-"
            self.tree.insert("", "end", iid=str(index), values=(file.name, games, date, size))
        if files:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self.status.configure(text=f"共 {len(files)} 个可用文件", text_color=theme.MUTED)
        else:
            self.status.configure(text="没有找到与该版本兼容的文件", text_color=theme.WARNING)

    def set_error(self, message: str) -> None:
        self.status.configure(text=message, text_color=theme.DANGER)

    def _on_select(self, _event: tk.Event | None = None) -> None:
        selection = self.tree.selection()
        if selection:
            try:
                self.selected_file = self.files[int(selection[0])]
                self.status.configure(text=f"已选择：{self.selected_file.filename}", text_color=theme.MUTED)
                self.download_button.configure(state="normal", fg_color=theme.ACCENT, text_color=theme.WHITE)
            except Exception:
                self.selected_file = None
                self.download_button.configure(state="disabled", fg_color=theme.INPUT, text_color=theme.MUTED)

    def _download(self) -> None:
        if self.selected_file is None:
            return
        file = self.selected_file
        self.destroy()
        try:
            self.on_download(file)
        except Exception:
            pass


class VersionManageDialog(ctk.CTkToplevel):
    def __init__(self, app, version_id: str) -> None:
        super().__init__(app)
        _setup_toplevel(self, f"版本管理 - {version_id}", app)
        self.geometry("900x680")
        self.minsize(780, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.app = app
        self.version_id = version_id
        self.game_dir = Path(app.cfg.game_dir)
        self.instance_dir = app.version_instance_dir(version_id)
        self._saves: dict[str, Path] = {}
        self._mods: dict[str, Path] = {}
        self._save_size_token = 0

        header = ctk.CTkFrame(self, fg_color=theme.WHITE, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=version_id,
            text_color=theme.TEXT,
            font=theme.font(19, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=22, pady=(16, 2))
        ctk.CTkLabel(
            header,
            text=f"管理目录：{self.instance_dir}",
            text_color=theme.MUTED,
            font=theme.font(10),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 14))
        secondary_button(header, "关闭", self.destroy, width=72, height=30).grid(
            row=0, column=1, rowspan=2, padx=20
        )

        self.tabs = ctk.CTkTabview(
            self,
            fg_color=theme.BG,
            segmented_button_selected_color=theme.ACCENT_SOFT,
            segmented_button_selected_hover_color="#DDE8FF",
            segmented_button_unselected_color=theme.INPUT,
            segmented_button_unselected_hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=16, pady=(8, 16))
        save_tab = self.tabs.add("存档")
        mod_tab = self.tabs.add("模组")
        version_tab = self.tabs.add("版本")
        self._build_saves(save_tab)
        self._build_mods(mod_tab)
        self._build_version(version_tab)
        self._refresh_saves()
        self._refresh_mods()
        self.after(80, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            theme.apply_light_titlebar(self)
        except Exception:
            pass

    def _folder(self, name: str) -> Path:
        return self.instance_dir / name

    def _open_folder(self, name: str) -> None:
        folder = self._folder(name)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception:
            pass

    def _build_saves(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 8))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bar,
            text="管理当前版本的存档世界",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        secondary_button(bar, "打开文件夹", lambda: self._open_folder("saves"), width=92, height=30).grid(
            row=0, column=1, padx=(0, 6)
        )
        self.delete_save_button = secondary_button(
            bar, "删除所选", self._delete_save, width=84, height=30
        )
        self.delete_save_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
        self.delete_save_button.grid(row=0, column=2, padx=(0, 6))
        secondary_button(bar, "刷新", self._refresh_saves, width=64, height=30).grid(row=0, column=3)

        table = card(parent)
        table.grid(row=1, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.save_tree = ttk.Treeview(
            table,
            columns=("name", "modified", "size"),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        for column, title, width in (("name", "存档名称", 440), ("modified", "最后修改", 220), ("size", "大小", 120)):
            self.save_tree.heading(column, text=title, anchor="w")
            self.save_tree.column(column, width=int(width * scale), anchor="w", stretch=(column == "name"))
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.save_tree.yview, style="FML.Vertical.TScrollbar")
        self.save_tree.configure(yscrollcommand=scrollbar.set)
        self.save_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.save_tree.bind("<<TreeviewSelect>>", lambda event: self._update_save_buttons())

    def _directory_size(self, folder: Path) -> int:
        total = 0
        try:
            for path in folder.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        except OSError:
            pass
        return total

    def _refresh_saves(self) -> None:
        self.save_tree.delete(*self.save_tree.get_children())
        self._saves = {}
        folder = self._folder("saves")
        rows = []
        try:
            if folder.is_dir():
                for child in folder.iterdir():
                    if child.is_dir():
                        rows.append(child)
        except OSError:
            pass
        rows.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
        pending_sizes: list[tuple[str, Path]] = []
        for index, child in enumerate(rows):
            key = str(index)
            self._saves[key] = child
            level = child / "level.dat"
            mtime = level.stat().st_mtime if level.is_file() else child.stat().st_mtime
            self.save_tree.insert(
                "",
                "end",
                iid=key,
                values=(child.name, time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)), "计算中…"),
            )
            pending_sizes.append((key, child))
        self._update_save_buttons()
        if pending_sizes:
            self._save_size_token += 1
            token = self._save_size_token

            def work() -> list[tuple[str, int]]:
                return [(key, self._directory_size(folder)) for key, folder in pending_sizes]

            def apply(sizes: list[tuple[str, int]]) -> None:
                if token != self._save_size_token:
                    return
                try:
                    if not self.winfo_exists():
                        return
                    for key, size in sizes:
                        if self.save_tree.exists(key):
                            values = list(self.save_tree.item(key, "values"))
                            values[2] = f"{size / 1048576:.1f} MB"
                            self.save_tree.item(key, values=values)
                except Exception:
                    pass

            self.app.run_background(work, apply, lambda error, detail: None)

    def _update_save_buttons(self) -> None:
        enabled = bool(self.save_tree.selection())
        self.delete_save_button.configure(
            state="normal" if enabled else "disabled",
            text_color=theme.ACCENT if enabled else theme.MUTED_LIGHT,
        )

    def _delete_save(self) -> None:
        selection = self.save_tree.selection()
        if not selection:
            return
        folder = self._saves.get(selection[0])
        if folder is None:
            return

        def confirm() -> None:
            shutil.rmtree(folder, ignore_errors=True)
            self._refresh_saves()

        ConfirmDialog(self, "删除存档", f"确定删除存档“{folder.name}”吗？此操作不可恢复。", confirm)

    def _build_mods(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 8))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bar,
            text="启用、禁用或删除当前版本的模组",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        secondary_button(bar, "打开文件夹", lambda: self._open_folder("mods"), width=92, height=30).grid(
            row=0, column=1, padx=(0, 6)
        )
        self.toggle_mod_button = secondary_button(bar, "启用/禁用", self._toggle_mod, width=88, height=30)
        self.toggle_mod_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
        self.toggle_mod_button.grid(row=0, column=2, padx=(0, 6))
        self.delete_mod_button = secondary_button(bar, "删除所选", self._delete_mod, width=84, height=30)
        self.delete_mod_button.configure(state="disabled", text_color=theme.MUTED_LIGHT)
        self.delete_mod_button.grid(row=0, column=3, padx=(0, 6))
        secondary_button(bar, "刷新", self._refresh_mods, width=64, height=30).grid(row=0, column=4)

        table = card(parent)
        table.grid(row=1, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.mod_tree = ttk.Treeview(
            table,
            columns=("name", "state", "size"),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        for column, title, width in (("name", "模组文件", 500), ("state", "状态", 140), ("size", "大小", 120)):
            self.mod_tree.heading(column, text=title, anchor="w")
            self.mod_tree.column(column, width=int(width * scale), anchor="w", stretch=(column == "name"))
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.mod_tree.yview, style="FML.Vertical.TScrollbar")
        self.mod_tree.configure(yscrollcommand=scrollbar.set)
        self.mod_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.mod_tree.bind("<<TreeviewSelect>>", lambda event: self._update_mod_buttons())

    def _refresh_mods(self) -> None:
        self.mod_tree.delete(*self.mod_tree.get_children())
        self._mods = {}
        folder = self._folder("mods")
        files = []
        try:
            if folder.is_dir():
                for child in folder.iterdir():
                    if child.is_file() and (child.name.lower().endswith(".jar") or child.name.lower().endswith(".jar.disabled")):
                        files.append(child)
        except OSError:
            pass
        files.sort(key=lambda item: item.name.lower())
        for index, child in enumerate(files):
            key = str(index)
            self._mods[key] = child
            disabled = child.name.lower().endswith(".disabled")
            name = child.name[:-9] if disabled else child.name
            self.mod_tree.insert(
                "",
                "end",
                iid=key,
                values=(name, "已禁用" if disabled else "已启用", f"{child.stat().st_size / 1024:.0f} KB"),
            )
        self._update_mod_buttons()

    def _update_mod_buttons(self) -> None:
        enabled = bool(self.mod_tree.selection())
        for button in (self.toggle_mod_button, self.delete_mod_button):
            button.configure(
                state="normal" if enabled else "disabled",
                text_color=theme.ACCENT if enabled else theme.MUTED_LIGHT,
            )

    def _selected_mod(self) -> Path | None:
        selection = self.mod_tree.selection()
        if not selection:
            return None
        return self._mods.get(selection[0])

    def _toggle_mod(self) -> None:
        path = self._selected_mod()
        if path is None:
            return
        try:
            if path.name.lower().endswith(".disabled"):
                path.rename(path.with_name(path.name[:-9]))
            else:
                path.rename(path.with_name(path.name + ".disabled"))
        except OSError as error:
            AlertDialog(self, "操作失败", str(error), kind="error")
        self._refresh_mods()

    def _delete_mod(self) -> None:
        path = self._selected_mod()
        if path is None:
            return

        def confirm() -> None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            self._refresh_mods()

        ConfirmDialog(self, "删除模组", f"确定删除模组文件“{path.name}”吗？", confirm)

    def _build_version(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        isolated = self.instance_dir.resolve() != self.game_dir.resolve()
        intro = ctk.CTkFrame(parent, fg_color=theme.WHITE, corner_radius=12, border_width=1, border_color=theme.BORDER)
        intro.grid(row=0, column=0, sticky="ew", pady=(8, 12))
        intro.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            intro,
            text="版本目录",
            text_color=theme.TEXT,
            font=theme.font(13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            intro,
            text=f"{self.instance_dir}\n" + ("当前版本使用独立游戏目录（版本隔离）" if isolated else "当前版本使用公共游戏目录"),
            text_color=theme.MUTED,
            font=theme.font(10),
            anchor="w",
            justify="left",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        primary_button(actions, "导出启动脚本", lambda: self.app.export_launch_script(self.version_id), width=126).grid(
            row=0, column=0, sticky="w", pady=4
        )
        secondary_button(actions, "从列表移除（保留文件）", self._hide_version, width=180).grid(
            row=1, column=0, sticky="w", pady=4
        )
        primary_button(actions, "删除版本文件", self._delete_version, width=126, fg_color=theme.DANGER).grid(
            row=2, column=0, sticky="w", pady=(4, 0)
        )

    def _hide_version(self) -> None:
        def confirm() -> None:
            self.app.hide_version(self.version_id)
            self.destroy()

        ConfirmDialog(
            self,
            "从列表移除版本",
            "版本会从启动器列表中隐藏，但版本文件、模组和存档都会保留。确定继续吗？",
            confirm,
        )

    def _delete_version(self) -> None:
        def confirm() -> None:
            try:
                self.app.delete_version_files(self.version_id)
            except Exception as error:
                AlertDialog(self, "删除失败", str(error), kind="error")
                return
            self.destroy()

        ConfirmDialog(
            self,
            "删除版本文件",
            "这会删除整个版本文件夹，包括该版本隔离的模组和存档，且无法恢复。确定删除吗？",
            confirm,
            confirm_text="删除",
        )


class HiddenVersionsDialog(ctk.CTkToplevel):
    def __init__(self, app) -> None:
        super().__init__(app)
        _setup_toplevel(self, "已隐藏的版本", app)
        self.geometry("560x480")
        self.minsize(480, 380)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.app = app

        ctk.CTkLabel(
            self,
            text="已隐藏的版本",
            text_color=theme.TEXT,
            font=theme.font(18, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            self,
            text="这些版本仍在磁盘上，只是不会显示在版本列表中。",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 10))

        table = card(self)
        table.grid(row=2, column=0, sticky="nsew", padx=20)
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            columns=("version",),
            show="headings",
            style="FML.Treeview",
            selectmode="browse",
        )
        self.tree.heading("version", text="版本", anchor="w")
        self.tree.column("version", width=460, anchor="w", stretch=True)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview, style="FML.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
        self.tree.bind("<Double-1>", lambda event: self._restore())

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=20, pady=16)
        footer.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(
            footer,
            text="",
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        )
        self.status.grid(row=0, column=0, sticky="w")
        secondary_button(footer, "关闭", self.destroy, width=72).grid(row=0, column=1, padx=(0, 8))
        self.restore_button = primary_button(footer, "恢复所选", self._restore, width=100)
        self.restore_button.grid(row=0, column=2)
        self._refresh()
        self.after(80, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            theme.apply_light_titlebar(self)
        except Exception:
            pass

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        hidden = list(self.app.cfg.hidden_versions)
        for index, version_id in enumerate(hidden):
            self.tree.insert("", "end", iid=str(index), values=(version_id,))
        self.status.configure(text=f"共 {len(hidden)} 个隐藏版本")
        if hidden:
            self.tree.selection_set("0")
            self.tree.focus("0")

    def _restore(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        hidden = list(self.app.cfg.hidden_versions)
        ids = []
        for index in selection:
            try:
                ids.append(hidden[int(index)])
            except Exception:
                continue
        if not ids:
            return
        self.app.restore_hidden_versions(ids)
        self._refresh()
        if not self.app.cfg.hidden_versions:
            self.destroy()
