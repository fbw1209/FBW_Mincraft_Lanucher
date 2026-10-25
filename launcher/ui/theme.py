from __future__ import annotations

import ctypes
import os
import tkinter as tk
import tkinter.ttk as ttk
from typing import Any

BG = "#F8F9FA"
SIDEBAR = "#FFFFFF"
CARD = "#FFFFFF"
CARD_HOVER = "#F6F8FB"
CARD_ACTIVE = "#E8F0FE"
BORDER = "#E4E7EC"
BORDER_STRONG = "#D7DBE0"
ACCENT = "#005DFF"
ACCENT_HOVER = "#0047CC"
ACCENT_SOFT = "#E9F0FF"
ACCENT_TEXT = "#003FB8"
GREEN = "#188038"
GREEN_SOFT = "#E6F4EA"
TEXT = "#202124"
TEXT_SOFT = "#3C4043"
MUTED = "#5F6368"
MUTED_LIGHT = "#80868B"
WARNING = "#B06000"
WARNING_SOFT = "#FEF7E0"
DANGER = "#D93025"
DANGER_SOFT = "#FCE8E6"
INFO = "#005DFF"
INFO_SOFT = "#E9F0FF"
INPUT = "#F1F3F4"
WHITE = "#FFFFFF"

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"

_font_cache: dict[tuple[int, str], Any] = {}


def font(size: int, weight: str = "normal") -> Any:
    import customtkinter as ctk

    key = (size, weight)
    cached = _font_cache.get(key)
    if cached is None:
        cached = ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
        _font_cache[key] = cached
    return cached


def ui_font(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return (FONT_FAMILY, size, weight)


def mono_font(size: int) -> tuple[str, int]:
    return (MONO_FAMILY, size)


def set_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def apply_light_titlebar(window: Any) -> None:
    if os.name != "nt":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        pass


_LOGO_OUTER = [
    (249.999, 416.565),
    (105.749, 333.284),
    (105.749, 166.717),
    (249.999, 83.435),
    (394.251, 166.717),
    (394.251, 333.282),
]
_LOGO_INNER = [
    (250.001, 378.263),
    (138.922, 314.131),
    (138.922, 185.869),
    (250.001, 121.737),
    (361.078, 185.869),
    (361.078, 314.131),
]
_LOGO_LETTER = [
    (217.809, 195.554),
    (217.809, 237.679),
    (326.701, 237.679),
    (326.701, 259.142),
    (217.809, 259.142),
    (217.809, 325.908),
    (172.503, 325.908),
    (172.503, 174.092),
    (327.498, 174.092),
    (327.498, 195.554),
]


def draw_logo(canvas: tk.Canvas, cx: float, cy: float, size: float = 40.0) -> None:
    factor = size / 500.0

    def transform(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [((x - 250) * factor + cx, (y - 250) * factor + cy) for x, y in points]

    canvas.create_polygon(transform(_LOGO_OUTER), fill=ACCENT, outline="")
    canvas.create_polygon(transform(_LOGO_INNER), fill="#FFFFFF", outline="")
    canvas.create_polygon(transform(_LOGO_LETTER), fill=ACCENT, outline="")


def configure_ttk(root: Any) -> None:
    style = ttk.Style(root)
    try:
        available = style.theme_names()
        style.theme_use("vista" if "vista" in available else ("winnative" if "winnative" in available else "clam"))
    except Exception:
        pass
    try:
        scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        scale = 1.0
    body_font = (FONT_FAMILY, -int(12 * scale))
    head_font = (FONT_FAMILY, -int(11 * scale), "bold")
    style.configure(".", font=body_font)
    style.configure(
        "FML.Treeview",
        background=WHITE,
        fieldbackground=WHITE,
        foreground=TEXT,
        rowheight=int(34 * scale),
        borderwidth=0,
        relief="flat",
        font=body_font,
    )
    style.map(
        "FML.Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", TEXT)],
    )
    style.configure(
        "FML.Treeview.Heading",
        background="#F8F9FA",
        foreground=MUTED,
        relief="flat",
        font=head_font,
        padding=(int(8 * scale), int(7 * scale)),
    )
    style.map("FML.Treeview.Heading", background=[("active", "#F1F3F4")])
    style.configure(
        "FML.Vertical.TScrollbar",
        background=BORDER_STRONG,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        width=int(10 * scale),
    )
    style.configure(
        "FML.Horizontal.TScrollbar",
        background=BORDER_STRONG,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
    )


def apply_windows_icon(window: Any, icon_path: Any) -> Any:
    if os.name != "nt":
        return None
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        dpi = 96
        try:
            dpi = user32.GetDpiForWindow(hwnd) or 96
        except Exception:
            pass

        def metric(index: int, fallback: int) -> int:
            try:
                return user32.GetSystemMetricsForDpi(index, dpi) or fallback
            except Exception:
                return user32.GetSystemMetrics(index) or fallback

        big_size = metric(11, 32)
        small_size = metric(49, 16)
        user32.LoadImageW.restype = ctypes.c_void_p
        big = user32.LoadImageW(
            None, ctypes.c_wchar_p(str(icon_path)), 1, big_size, big_size, 0x10
        )
        small = user32.LoadImageW(
            None, ctypes.c_wchar_p(str(icon_path)), 1, small_size, small_size, 0x10
        )
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        user32.SendMessageW.restype = ctypes.c_void_p
        if big:
            user32.SendMessageW(hwnd, 0x80, 1, big)
        if small:
            user32.SendMessageW(hwnd, 0x80, 0, small)
        return big, small
    except Exception:
        return None
