"""
Float property control
Translated from C++ PropFloatControl.h
"""

from PyQt6.QtWidgets import QDoubleSpinBox, QLineEdit, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropFloat
from .prop_control_base import PropControlBase


class PropFloatControl(PropControlBase):
    """Control widget for float properties"""

    prop: PropFloat

    def __init__(
        self, prop: PropFloat, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        is_readonly = self.prop.is_readonly

        self.spin = None
        self.edit = None

        if is_readonly:
            self.edit = QLineEdit(self)
            self.edit.setReadOnly(True)
        else:
            self.spin = QDoubleSpinBox(self)
            try:
                min_val = self.prop.minimum
                max_val = self.prop.maximum
                self.spin.setRange(min_val, max_val)

                # Set reasonable decimals
                self.spin.setDecimals(6)

                try:
                    inc = self.prop.increment
                    self.spin.setSingleStep(inc)
                except Exception:
                    self.spin.setSingleStep(0.1)
            except Exception:
                pass

            self.spin.valueChanged.connect(self._on_value_changed)

        self.update_all()

        if layout := self.layout():
            if self.spin:
                layout.addWidget(self.spin)
            if self.edit:
                layout.addWidget(self.edit)

    def _on_value_changed(self, value: float):
        """Handle spinbox value change"""

        def set_func(val):
            self.prop.value = val

        if not self.prop_set_value(value, set_func):
            QMessageBox.critical(self, "Error", "Failed to set property value")
            self.update_all()

    def update_all(self):
        """Update control from property value"""
        try:
            if self.spin:
                self.spin.setEnabled(
                    not self.should_display_as_locked() and not self.prop.is_readonly
                )
                self.spin.blockSignals(True)

                value = self.prop.value
                self.spin.setValue(value)

                self.spin.blockSignals(False)

            if self.edit:
                self.edit.blockSignals(True)

                value = self.prop.value
                self.edit.setText(str(value))

                self.edit.blockSignals(False)

        except Exception:
            if self.spin:
                self.spin.blockSignals(False)
            if self.edit:
                self.edit.blockSignals(False)
