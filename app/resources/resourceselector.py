from PyQt6.QtGui import QPalette, QIcon
from pathlib import Path
from typing import Literal
from datetime import datetime

# Global instance
_resource_selector_instance = None


def get_resource_selector():
    """Get the global ResourceSelector instance"""
    global _resource_selector_instance
    if _resource_selector_instance is None:
        _resource_selector_instance = ResourceSelector()
    return _resource_selector_instance


def _is_dark_mode() -> bool:
    """Determine if the system is in dark mode based on palette lightness and device time"""
    # Simple heuristic: assume dark mode is more likely in the evening/night
    cur_time = datetime.now().astimezone()
    if cur_time.hour < 7 or cur_time.hour >= 19:
        return True
    default_palette = QPalette()
    return (
        default_palette.color(QPalette.ColorRole.WindowText).lightness()
        > default_palette.color(QPalette.ColorRole.Window).lightness()
    )


class ResourceSelector:

    def __init__(self):
        # Get the directory of this script (resourceselector.py)
        self.base_dir = Path(__file__).parent
        # Theme mode: 'auto', 'light', or 'dark'
        self._theme_mode: Literal["auto", "light", "dark"] = "auto"
        self._update_theme()

    def _update_theme(self):
        """Update the current theme based on theme_mode"""
        if self._theme_mode == "auto":
            self.theme = "theme_dark" if _is_dark_mode() else "theme_light"
        else:
            self.theme = f"theme_{self._theme_mode}"

    def set_theme(self, mode: Literal["auto", "light", "dark"]):
        """Set the theme mode"""
        if mode not in ("auto", "light", "dark"):
            raise ValueError(
                f"Invalid theme mode: {mode}. Must be 'auto', 'light', or 'dark'"
            )
        self._theme_mode = mode
        self._update_theme()

    def get_theme(self) -> Literal["auto", "light", "dark"]:
        """Get the current theme mode"""
        return self._theme_mode

    def select(self, item: str) -> str:
        # Construct path relative to this script's location with theme directory
        # Insert theme directory into the path
        # e.g., "images/camera.png" -> "images/+theme_dark/camera.png"
        path_obj = Path(item)
        parts = path_obj.parts

        if len(parts) > 1 and parts[0] == "images":
            # Replace "images" with "images/+theme_xxx"
            resource_path = (
                self.base_dir / parts[0] / f"+{self.theme}" / Path(*parts[1:])
            )
        else:
            # No images directory, just use as-is
            resource_path = self.base_dir / item

        return str(resource_path)

    def loadIcon(self, item: str) -> QIcon:
        icon_path = self.select(item)
        # Check if the icon file exists, if not try without theme fallback
        if not Path(icon_path).exists():
            # Fallback: try the path as-is without theme directory
            fallback_path = self.base_dir / item
            if Path(fallback_path).exists():
                icon_path = str(fallback_path)
        return QIcon(icon_path)
