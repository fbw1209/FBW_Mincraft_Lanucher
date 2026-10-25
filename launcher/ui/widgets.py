from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable

import customtkinter as ctk

from . import theme


def card(parent: tk.Misc, **kwargs) -> ctk.CTkFrame:
    options = {
        "fg_color": theme.CARD,
        "corner_radius": 14,
        "border_width": 1,
        "border_color": theme.BORDER,
    }
    options.update(kwargs)
    return ctk.CTkFrame(parent, **options)


def primary_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    width: int = 100,
    height: int = 36,
    **kwargs,
) -> ctk.CTkButton:
    options = {
        "text": text,
        "command": command,
        "width": width,
        "height": height,
        "corner_radius": 9,
        "fg_color": theme.ACCENT,
        "hover_color": theme.ACCENT_HOVER,
        "text_color": theme.WHITE,
        "font": theme.font(13, "bold"),
    }
    options.update(kwargs)
    return ctk.CTkButton(parent, **options)


def secondary_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    width: int = 88,
    height: int = 34,
    **kwargs,
) -> ctk.CTkButton:
    options = {
        "text": text,
        "command": command,
        "width": width,
        "height": height,
        "corner_radius": 9,
        "fg_color": theme.WHITE,
        "hover_color": theme.CARD_HOVER,
        "text_color": theme.ACCENT,
        "border_width": 1,
        "border_color": theme.BORDER_STRONG,
        "font": theme.font(13),
    }
    options.update(kwargs)
    return ctk.CTkButton(parent, **options)


def text_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None] | None = None,
    **kwargs,
) -> ctk.CTkButton:
    options = {
        "text": text,
        "command": command,
        "width": 1,
        "height": 28,
        "corner_radius": 7,
        "fg_color": "transparent",
        "hover_color": theme.CARD_ACTIVE,
        "text_color": theme.ACCENT,
        "font": theme.font(13),
    }
    options.update(kwargs)
    return ctk.CTkButton(parent, **options)


class Badge(ctk.CTkLabel):
    COLORS = {
        "blue": (theme.ACCENT_SOFT, theme.ACCENT_TEXT),
        "green": (theme.GREEN_SOFT, theme.GREEN),
        "gray": ("#F1F3F4", theme.MUTED),
        "yellow": (theme.WARNING_SOFT, theme.WARNING),
        "red": (theme.DANGER_SOFT, theme.DANGER),
    }

    def __init__(self, parent: tk.Misc, text: str, color: str = "blue", **kwargs) -> None:
        fill, foreground = self.COLORS.get(color, self.COLORS["gray"])
        super().__init__(
            parent,
            text=text,
            fg_color=fill,
            text_color=foreground,
            corner_radius=6,
            height=22,
            padx=8,
            font=theme.font(11),
            **kwargs,
        )


def _bind_hover(widget: tk.Misc, on_enter: Callable[[], None], on_leave: Callable[[], None]) -> None:
    def enter(_event: tk.Event) -> None:
        on_enter()

    def leave(_event: tk.Event) -> None:
        on_leave()

    def walk(item: tk.Misc) -> None:
        try:
            item.bind("<Enter>", enter, add="+")
            item.bind("<Leave>", leave, add="+")
        except Exception:
            pass
        for child in item.winfo_children():
            walk(child)

    walk(widget)


class NavItem(ctk.CTkButton):
    def __init__(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> None:
        super().__init__(
            parent,
            text=text,
            command=command,
            anchor="w",
            height=42,
            corner_radius=10,
            fg_color="transparent",
            hover_color=theme.CARD_HOVER,
            text_color=theme.TEXT_SOFT,
            font=theme.font(14),
            border_spacing=12,
        )
        self.active = False

    def set_active(self, active: bool) -> None:
        self.active = active
        if active:
            self.configure(fg_color=theme.CARD_ACTIVE, text_color=theme.ACCENT_TEXT)
        else:
            self.configure(fg_color="transparent", text_color=theme.TEXT_SOFT)


class StatCard(ctk.CTkFrame):
    def __init__(self, parent: tk.Misc, title: str, accent: str = theme.ACCENT) -> None:
        super().__init__(
            parent,
            fg_color=theme.CARD,
            corner_radius=14,
            border_width=1,
            border_color=theme.BORDER,
            height=94,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.icon = ctk.CTkLabel(
            self,
            text="",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=theme.ACCENT_SOFT,
            font=theme.font(14, "bold"),
        )
        self.icon.configure(text_color=accent)
        self.icon.grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)
        self.title_label = ctk.CTkLabel(
            self,
            text=title,
            text_color=theme.MUTED,
            font=theme.font(12),
            anchor="w",
        )
        self.title_label.grid(row=0, column=1, sticky="sw", pady=(18, 0))
        self.value_label = ctk.CTkLabel(
            self,
            text="-",
            text_color=theme.TEXT,
            font=theme.font(17, "bold"),
            anchor="w",
        )
        self.value_label.grid(row=1, column=1, sticky="nw", pady=(0, 16))

    def set_value(self, value: str, symbol: str = "") -> None:
        if symbol:
            self.icon.configure(text=symbol)
        self.value_label.configure(text=value)


class VersionRow(ctk.CTkFrame):
    def __init__(
        self,
        parent: tk.Misc,
        version_id: str,
        subtitle: str,
        badges: Iterable[tuple[str, str]] = (),
        primary_text: str = "启动",
        primary_command: Callable[[], None] | None = None,
        secondary_text: str = "",
        secondary_command: Callable[[], None] | None = None,
        symbol: str = "M",
        disabled: bool = False,
    ) -> None:
        super().__init__(
            parent,
            fg_color=theme.CARD,
            corner_radius=14,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.grid_columnconfigure(1, weight=1)
        self._normal_color = theme.CARD
        self._hover_color = theme.CARD_HOVER

        icon = ctk.CTkLabel(
            self,
            text=symbol,
            width=42,
            height=42,
            corner_radius=11,
            fg_color=theme.ACCENT_SOFT,
            text_color=theme.ACCENT_TEXT,
            font=theme.font(15, "bold"),
        )
        icon.grid(row=0, column=0, padx=(16, 13), pady=15)

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="ew", pady=12)
        content.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(content, fg_color="transparent")
        top.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top,
            text=version_id,
            text_color=theme.TEXT,
            font=theme.font(15, "bold"),
            anchor="w",
        ).pack(side="left")
        for badge_text, color in badges:
            Badge(top, badge_text, color).pack(side="left", padx=(7, 0))
        ctk.CTkLabel(
            content,
            text=subtitle,
            text_color=theme.MUTED,
            font=theme.font(11),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.grid(row=0, column=2, padx=16, pady=15, sticky="e")
        if secondary_text and secondary_command is not None:
            secondary_button(action_frame, secondary_text, secondary_command, width=86).pack(
                side="left", padx=(0, 8)
            )
        self.primary = primary_button(
            action_frame,
            primary_text,
            primary_command,
            width=86,
            height=34,
            state="disabled" if disabled else "normal",
            fg_color=theme.INPUT if disabled else theme.ACCENT,
            text_color=theme.MUTED if disabled else theme.WHITE,
        )
        self.primary.pack(side="left")

        if primary_command is not None:
            _bind_hover(
                self,
                lambda: self.configure(fg_color=self._hover_color),
                lambda: self.configure(fg_color=self._normal_color),
            )


class EmptyState(ctk.CTkFrame):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        description: str,
        action_text: str = "",
        action_command: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        icon = ctk.CTkLabel(
            self,
            text="",
            width=44,
            height=44,
            corner_radius=14,
            fg_color=theme.ACCENT_SOFT,
        )
        icon.grid(row=0, column=0, pady=(16, 10))
        ctk.CTkLabel(
            self,
            text=title,
            text_color=theme.TEXT,
            font=theme.font(15, "bold"),
        ).grid(row=1, column=0)
        ctk.CTkLabel(
            self,
            text=description,
            text_color=theme.MUTED,
            font=theme.font(12),
            justify="center",
        ).grid(row=2, column=0, pady=(4, 12))
        if action_text and action_command is not None:
            primary_button(self, action_text, action_command, width=116).grid(row=3, column=0, pady=(0, 16))


def clear_children(widget: tk.Misc) -> None:
    for child in widget.winfo_children():
        child.destroy()
