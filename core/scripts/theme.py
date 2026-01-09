# core/theme.py
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Callable, Optional
import logging


@dataclass
class ColorScheme:
    """Color scheme for the application"""
    # Background colors
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_button_normal: str
    bg_button_active: str

    # Text colors
    fg_primary: str
    fg_secondary: str
    fg_disabled: str

    # Accent colors
    accent_record: str
    accent_record_active: str
    accent_action: str
    accent_action_active: str
    accent_utility: str
    accent_utility_active: str

    # UI elements
    progress_bg: str
    progress_fg: str
    text_select_bg: str
    text_select_fg: str
    scrollbar_bg: str
    scrollbar_fg: str
    menubar_bg: str
    menubar_fg: str


class Theme:
    """Manages application themes"""

    DARK = ColorScheme(
        bg_primary="#1e1e1e",
        bg_secondary="#2b2b2b",
        bg_tertiary="#383838",
        bg_button_normal="#383838",
        bg_button_active="#4a4a4a",

        fg_primary="#e0e0e0",
        fg_secondary="#a0a0a0",
        fg_disabled="#606060",

        accent_record="#8b4545",
        accent_record_active="#b33c3c",
        accent_action="#4a7ba7",
        accent_action_active="#5a8fc4",
        accent_utility="#4a8b57",
        accent_utility_active="#5ba368",

        progress_bg="#2b2b2b",
        progress_fg="#5ba368",  # Green for progress
        text_select_bg="#4a7ba7",
        text_select_fg="#ffffff",
        scrollbar_bg="#2b2b2b",
        scrollbar_fg="#555555",
        menubar_bg="#333333",
        menubar_fg="#e0e0e0"
    )

    LIGHT = ColorScheme(
        bg_primary="#f0f0f0",
        bg_secondary="#ffffff",
        bg_tertiary="#e8e8e8",
        bg_button_normal="#e8e8e8",
        bg_button_active="#d0d0d0",

        fg_primary="#000000",
        fg_secondary="#666666",
        fg_disabled="#a0a0a0",

        accent_record="#ffcccb",
        accent_record_active="#ff0000",
        accent_action="#add8e6",
        accent_action_active="#87ceeb",
        accent_utility="#90ee90",
        accent_utility_active="#00ff00",

        progress_bg="#ffffff",
        progress_fg="#6fbf73",  # Lighter green for progress
        text_select_bg="#0078d7",
        text_select_fg="#ffffff",
        scrollbar_bg="#f0f0f0",
        scrollbar_fg="#c0c0c0",
        menubar_bg="#e0e0e0",
        menubar_fg="#000000"
    )

    def __init__(self, initial_theme: str = "dark"):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._current_theme = initial_theme
        self._callbacks: list[Callable] = []

    @property
    def current(self) -> ColorScheme:
        """Get current color scheme"""
        if self._current_theme == "dark":
            return self.DARK
        return self.LIGHT

    @property
    def current_name(self) -> str:
        """Get current theme name"""
        return self._current_theme

    def set_theme(self, theme_name: str):
        """Set active theme and notify callbacks"""
        if theme_name not in ["dark", "light"]:
            self.logger.warning(f"Invalid theme: {theme_name}")
            return

        self._current_theme = theme_name
        self.logger.info(f"Theme changed to: {theme_name}")

        # Notify all registered callbacks
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                self.logger.error(f"Error in theme callback: {e}")

    def register_callback(self, callback: Callable):
        """Register callback to be called when theme changes"""
        self._callbacks.append(callback)

    def configure_ttk_styles(self, root: tk.Tk):
        """Configure ttk widget styles for current theme"""
        style = ttk.Style(root)
        colors = self.current

        # Configure Progressbar
        style.theme_use('default')
        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor=colors.progress_bg,
            background=colors.progress_fg,
            bordercolor=colors.bg_secondary,
            lightcolor=colors.progress_fg,
            darkcolor=colors.progress_fg
        )

        # Configure frame backgrounds
        style.configure("TFrame", background=colors.bg_primary)
        style.configure("TLabel", background=colors.bg_primary, foreground=colors.fg_primary)