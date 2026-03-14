"""
Dialog for configuring image and video save defaults (directory, filename, extension).
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
    QCheckBox,
)

from resources.style_manager import get_style_manager

SETTINGS_PATH = Path(__file__).parents[1] / "settings" / "settings.json"

IMAGE_EXTENSIONS = [
    ("PNG", ".png"),
    ("JPEG", ".jpg"),
    ("Bitmap", ".bmp"),
    ("TIFF", ".tif"),
]

VIDEO_EXTENSIONS = [
    ("MP4 (H.264)", ".mp4"),
]


def _load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: dict):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


class SaveSettingsDialog(QDialog):
    """Dialog for configuring default save locations, filenames and extensions
    for image and video capture."""

    def __init__(self, parent=None, mode: str = "image"):
        """
        Args:
            parent: Parent widget.
            mode: ``"image"`` or ``"video"`` – which settings page to show.
        """
        super().__init__(parent)
        self._mode = mode
        self.setWindowTitle(
            "Image Save Settings" if mode == "image" else "Video Save Settings"
        )
        self.setMinimumWidth(480)

        settings = _load_settings()
        self._settings = settings

        layout = QVBoxLayout()

        # --- Directory ---
        dir_group = QGroupBox("Default Folder")
        dir_layout = QHBoxLayout()

        if mode == "image":
            current_dir = settings.get("default_image_directory", "")
        else:
            current_dir = settings.get("default_video_directory", "")

        self._dir_edit = QLineEdit(current_dir)
        self._dir_edit.setPlaceholderText("System default")
        self._dir_edit.setReadOnly(True)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_directory)

        dir_layout.addWidget(self._dir_edit, 1)
        dir_layout.addWidget(browse_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # --- Filename ---
        name_group = QGroupBox("Default Filename")
        name_layout = QHBoxLayout()

        if mode == "image":
            current_name = settings.get("default_image_filename", "")
        else:
            current_name = settings.get("default_video_filename", "")

        self._name_edit = QLineEdit(current_name)
        self._name_edit.setPlaceholderText(
            "capture" if mode == "image" else "recording"
        )
        name_layout.addWidget(self._name_edit)
        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # --- Extension ---
        ext_group = QGroupBox("Default Extension")
        ext_layout = QHBoxLayout()

        self._ext_combo = QComboBox()
        extensions = IMAGE_EXTENSIONS if mode == "image" else VIDEO_EXTENSIONS
        if mode == "image":
            current_ext = settings.get("default_image_extension", ".png")
        else:
            current_ext = settings.get("default_video_extension", ".mp4")

        for label, ext in extensions:
            self._ext_combo.addItem(f"{label} ({ext})", ext)

        idx = self._ext_combo.findData(current_ext)
        if idx >= 0:
            self._ext_combo.setCurrentIndex(idx)

        ext_layout.addWidget(self._ext_combo)
        ext_layout.addStretch()
        ext_group.setLayout(ext_layout)
        layout.addWidget(ext_group)

        # --- Use default filename toggle ---
        if mode == "image":
            use_default = settings.get("use_default_image_filename", False)
            label_text = "Use default filename (skip file dialog when saving images)"
        else:
            use_default = settings.get("use_default_video_filename", False)
            label_text = "Use default filename (skip file dialog when recording)"

        self._use_default_check = QCheckBox(label_text)
        self._use_default_check.setChecked(use_default)
        self._use_default_check.setToolTip(
            "When enabled, files are saved automatically with a timestamped\n"
            "name in the default folder. The file dialog will not appear."
        )
        layout.addWidget(self._use_default_check)

        layout.addStretch()

        # --- Buttons ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _browse_directory(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder", self._dir_edit.text()
        )
        if folder:
            self._dir_edit.setText(folder)

    def _on_accept(self):
        """Save all values to settings.json and pass them back to the caller."""
        settings = _load_settings()

        directory = self._dir_edit.text()
        filename = self._name_edit.text().strip()
        extension = self._ext_combo.currentData()

        if self._mode == "image":
            if directory:
                settings["default_image_directory"] = directory
            settings["default_image_filename"] = filename
            settings["default_image_extension"] = extension
            settings["use_default_image_filename"] = self._use_default_check.isChecked()
        else:
            if directory:
                settings["default_video_directory"] = directory
            settings["default_video_filename"] = filename
            settings["default_video_extension"] = extension
            settings["use_default_video_filename"] = self._use_default_check.isChecked()

        _save_settings(settings)
        self.accept()

    # --- Public accessors (valid after accept) ---
    @property
    def directory(self) -> str:
        return self._dir_edit.text()

    @property
    def filename(self) -> str:
        return self._name_edit.text().strip()

    @property
    def extension(self) -> str:
        return self._ext_combo.currentData()

    @property
    def use_default(self) -> bool:
        return self._use_default_check.isChecked()

    def apply_theme(self) -> None:
        style_manager = get_style_manager()
        style_manager.apply_theme()
        self.update()
