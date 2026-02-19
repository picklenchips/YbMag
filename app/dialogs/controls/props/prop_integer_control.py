"""
Integer property control
Translated from C++ PropIntControl.h
"""

from PyQt6.QtWidgets import QSpinBox, QLineEdit, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropInteger, PropIntRepresentation
from .prop_control_base import PropControlBase


class PropIntegerControl(PropControlBase):
    """Control widget for integer properties"""

    prop: PropInteger

    def __init__(
        self, prop: PropInteger, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        self.spin = None
        self.edit = None

        try:
            representation = self.prop.representation
            is_readonly = self.prop.is_readonly

            # For special representations, use line edit
            if representation in [
                PropIntRepresentation.MACADDRESS,
                PropIntRepresentation.IPV4ADDRESS,
            ]:
                self.edit = QLineEdit(self)
                self.edit.setReadOnly(True)
            elif is_readonly:
                self.edit = QLineEdit(self)
                self.edit.setReadOnly(True)
            else:
                # Use spinbox for normal integers
                self.spin = QSpinBox(self)
                try:
                    min_val = max(-2147483648, self.prop.minimum)
                    max_val = min(2147483647, self.prop.maximum)
                    self.spin.setRange(int(min_val), int(max_val))

                    try:
                        inc = self.prop.increment
                        self.spin.setSingleStep(int(inc))
                    except Exception:
                        self.spin.setSingleStep(1)
                except Exception:
                    pass

                self.spin.valueChanged.connect(self._on_value_changed)
        except Exception as e:
            print(f"Error initializing PropIntegerControl: {e}")
            self.edit = QLineEdit(self)
            self.edit.setReadOnly(True)

        self.update_all()

        if layout := self.layout():
            if self.spin:
                layout.addWidget(self.spin)
            if self.edit:
                layout.addWidget(self.edit)

    def _on_value_changed(self, value: int):
        """Handle spinbox value change"""

        def set_func(val):
            self.prop.value = val

        if not self.prop_set_value(value, set_func):
            QMessageBox.critical(self, "Error", "Failed to set property value")
            self.update_all()

    @staticmethod
    def _format_ip(ip: int) -> str:
        """Format integer as IP address"""
        return f"{(ip >> 24) & 0xFF}.{(ip >> 16) & 0xFF}.{(ip >> 8) & 0xFF}.{(ip >> 0) & 0xFF}"

    @staticmethod
    def _format_mac(mac: int) -> str:
        """Format integer as MAC address"""
        return ":".join([f"{(mac >> (40 - i*8)) & 0xFF:02x}" for i in range(6)])

    def _value_to_string(self, val: int, rep: PropIntRepresentation) -> str:
        """Convert value to string based on representation"""
        if rep == PropIntRepresentation.BOOLEAN:
            return "True" if val else "False"
        elif rep == PropIntRepresentation.HEXNUMBER:
            return f"0x{val:x}"
        elif rep == PropIntRepresentation.MACADDRESS:
            return self._format_mac(val)
        elif rep == PropIntRepresentation.IPV4ADDRESS:
            return self._format_ip(val)
        else:
            return str(val)

    def update_all(self):
        """Update control from property value"""
        try:
            if self.spin:
                self.spin.setEnabled(
                    not self.should_display_as_locked() and not self.prop.is_readonly
                )
                self.spin.blockSignals(True)

                value = self.prop.value
                self.spin.setValue(int(value))

                self.spin.blockSignals(False)

            if self.edit:
                self.edit.blockSignals(True)

                value = self.prop.value
                rep = self.prop.representation
                text = self._value_to_string(value, rep)
                self.edit.setText(text)

                self.edit.blockSignals(False)

        except Exception:
            if self.spin:
                self.spin.blockSignals(False)
            if self.edit:
                self.edit.blockSignals(False)
