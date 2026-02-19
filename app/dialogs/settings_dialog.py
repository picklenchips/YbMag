"""
Settings dialog for UI configuration
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGroupBox,
    QCheckBox,
    QComboBox,
    QLabel,
    QHBoxLayout,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from typing import Optional, Any, Callable


class SettingsDialog(QDialog):
    """Dialog for UI settings including theme selection"""

    def __init__(
        self,
        resource_selector: Any,
        parent=None,
        on_theme_changed: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(parent)

        self.setWindowTitle("UI Settings")
        self.resource_selector = resource_selector
        self.on_theme_changed = on_theme_changed

        self._create_ui()

    def _create_ui(self):
        """Create the settings UI"""
        self.setMinimumSize(400, 250)

        main_layout = QVBoxLayout()

        # Theme settings group
        theme_group = QGroupBox("Theme", self)
        theme_layout = QVBoxLayout()

        theme_row = QHBoxLayout()
        theme_label = QLabel("Theme:", self)
        self.theme_combo = QComboBox(self)
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Auto", "auto")

        # Set the combo box to the current theme mode
        current_theme = self.resource_selector.get_theme()
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        theme_layout.addLayout(theme_row)

        theme_group.setLayout(theme_layout)
        main_layout.addWidget(theme_group)

        # Add some spacing
        main_layout.addStretch()

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.setLayout(main_layout)

    def _on_theme_changed(self):
        """Handle theme change"""
        theme = self.theme_combo.currentData()
        # Update the resource selector
        self.resource_selector.set_theme(theme)
        # Call the callback if provided
        if self.on_theme_changed:
            self.on_theme_changed(theme)
