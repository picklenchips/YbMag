"""
Boolean property control
Translated from C++ PropBooleanControl.h
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropBoolean, Property
from .prop_control_base import PropControlBase


class PropBooleanControl(PropControlBase):
    """Control widget for boolean properties"""

    prop: PropBoolean

    def __init__(
        self, prop: PropBoolean, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        self.check = QCheckBox(self)
        self.check.setText("")
        self.check.stateChanged.connect(self._on_check_changed)

        self.update_all()
        if layout := self.layout():
            layout.addWidget(self.check)
            layout.setContentsMargins(8, 8, 0, 8)

    def _on_check_changed(self, state: int):
        """Handle checkbox state change"""
        new_value = state == Qt.CheckState.Checked.value

        def set_func(value):
            self.prop.value = value

        if not self.prop_set_value(new_value, set_func):
            QMessageBox.critical(self, "Error", "Failed to set property value")
            self.update_all()

    def update_all(self):
        """Update checkbox from property value"""
        try:
            self.check.setEnabled(
                not self.should_display_as_locked() and not self.prop.is_readonly
            )
            self.check.blockSignals(True)

            value = self.prop.value
            self.check.setChecked(value)

            self.check.blockSignals(False)
        except Exception:
            self.check.blockSignals(False)
