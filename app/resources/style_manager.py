"""UI stylesheet manager for light/dark themes."""

from datetime import datetime
from pathlib import Path
from typing import Dict, Literal, Optional

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

ThemeMode = Literal["auto", "light", "dark"]

# Global instance
_style_manager_instance = None


def get_style_manager() -> "StyleManager":
    """Get the global StyleManager instance"""
    global _style_manager_instance
    if _style_manager_instance is None:
        _style_manager_instance = StyleManager()
    return _style_manager_instance


def _is_dark_mode() -> bool:
    """Determine if the system is in dark mode based on palette lightness."""
    cur_time = datetime.now().astimezone()
    if cur_time.hour < 7 or cur_time.hour >= 19:
        return True
    default_palette = QPalette()
    return (
        default_palette.color(QPalette.ColorRole.WindowText).lightness()
        > default_palette.color(QPalette.ColorRole.Window).lightness()
    )


class StyleManager:
    """Load and apply QSS for the current theme."""

    def __init__(self):
        self.base_dir = Path(__file__).parent
        self._theme_mode: ThemeMode = "auto"
        self._current_theme: Optional[str] = None
        self._base_qss: Optional[str] = None
        self._last_applied_qss: Optional[str] = None

    def set_theme(self, mode: ThemeMode):
        if mode not in ("auto", "light", "dark"):
            raise ValueError(
                f"Invalid theme mode: {mode}. Must be 'auto', 'light', or 'dark'"
            )
        self._theme_mode = mode

    def get_theme(self) -> ThemeMode:
        return self._theme_mode

    def _resolve_theme(self, mode: Optional[ThemeMode] = None) -> str:
        if mode is None:
            mode = self._theme_mode
        if mode == "auto":
            return "dark" if _is_dark_mode() else "light"
        return mode

    def _theme_colors(self, theme: str) -> Dict[str, str]:
        if theme == "dark":
            return {
                "BG_MAIN": "#0f1115",
                "BG_SURFACE": "#151821",
                "BG_ALT": "#1a1f2a",
                "TEXT": "#e6e6e6",
                "BORDER": "#222633",
                "BORDER_STRONG": "#2a2f3a",
                "ACCENT": "#4ea1ff",
                "ACCENT_SOFT": "#1b2030",
                "SELECTION_BG": "#1f2a3d",
                "SELECTION_TEXT": "#e6e6e6",
            }
        return {
            "BG_MAIN": "#f6f7fb",
            "BG_SURFACE": "#ffffff",
            "BG_ALT": "#f3f5f9",
            "TEXT": "#1f2328",
            "BORDER": "#e6e8ee",
            "BORDER_STRONG": "#d9dbe3",
            "ACCENT": "#93c5fd",
            "ACCENT_SOFT": "#f1f5ff",
            "SELECTION_BG": "#e8f0ff",
            "SELECTION_TEXT": "#1f2328",
        }

    def get_theme_background_color(self, mode: Optional[ThemeMode] = None) -> QColor:
        theme = self._resolve_theme(mode)
        colors = self._theme_colors(theme)
        return QColor(colors["BG_MAIN"])

    def _load_base_qss(self) -> str:
        if self._base_qss is None:
            qss_path = self.base_dir / "styles" / "base.qss"
            try:
                self._base_qss = qss_path.read_text(encoding="utf-8")
            except Exception:
                self._base_qss = ""
        return self._base_qss

    def _build_qss(self, theme: str) -> str:
        qss = self._load_base_qss()
        for key, value in self._theme_colors(theme).items():
            qss = qss.replace(f"{{{{{key}}}}}", value)
        return qss

    def apply_theme(self, mode: Optional[ThemeMode] = None) -> None:
        theme = self._resolve_theme(mode)
        qss_text = self._build_qss(theme)
        if self._current_theme == theme and self._last_applied_qss == qss_text:
            return

        app = QApplication.instance()
        if app:
            assert isinstance(app, QApplication), "Expected QApplication instance"
            app.setStyleSheet(qss_text)
            self._current_theme = theme
            self._last_applied_qss = qss_text
