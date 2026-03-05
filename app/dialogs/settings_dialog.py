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
    QSpinBox,
)
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
        self.setMinimumSize(420, 300)

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

        # Property dialog layout group
        layout_group = QGroupBox("Property Dialog", self)
        layout_layout = QVBoxLayout()

        self.tabbed_checkbox = QCheckBox("Use tabbed layout", self)
        self.tabbed_checkbox.setToolTip(
            "Organize properties into category tabs with a global search bar.\n"
            "Takes effect the next time you open the property dialog."
        )
        self.tabbed_checkbox.setChecked(self.resource_selector.get_tabbed_properties())
        self.tabbed_checkbox.toggled.connect(self._on_tabbed_changed)
        layout_layout.addWidget(self.tabbed_checkbox)

        layout_group.setLayout(layout_layout)
        main_layout.addWidget(layout_group)

        # Power-supply polling settings group
        polling_group = QGroupBox("Power Supply", self)
        polling_layout = QVBoxLayout()

        polling_row = QHBoxLayout()
        polling_label = QLabel("Poll interval:", self)
        self.poll_interval_spin = QSpinBox(self)
        self.poll_interval_spin.setRange(50, 10000)
        self.poll_interval_spin.setSingleStep(50)
        self.poll_interval_spin.setSuffix(" ms")
        self.poll_interval_spin.setValue(
            self.resource_selector.get_power_supply_poll_interval_ms()
        )
        self.poll_interval_spin.setToolTip(
            "Polling period for power-supply readback updates.\n"
            "Lower = more responsive, higher = less USB traffic."
        )
        self.poll_interval_spin.valueChanged.connect(
            self._on_power_supply_poll_interval_changed
        )

        polling_row.addWidget(polling_label)
        polling_row.addWidget(self.poll_interval_spin)
        polling_row.addStretch()
        polling_layout.addLayout(polling_row)

        polling_group.setLayout(polling_layout)
        main_layout.addWidget(polling_group)

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

    def _on_tabbed_changed(self, checked: bool):
        """Handle tabbed-layout toggle"""
        self.resource_selector.set_tabbed_properties(checked)

    def _on_power_supply_poll_interval_changed(self, interval_ms: int):
        """Handle power-supply poll-interval changes."""
        self.resource_selector.set_power_supply_poll_interval_ms(interval_ms)
