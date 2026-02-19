"""
String property control
Translated from C++ PropStringControl.h
"""

from PyQt6.QtWidgets import QLineEdit, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropString
from .prop_control_base import PropControlBase


class PropStringControl(PropControlBase):
    """Control widget for string properties"""

    prop: PropString

    def __init__(
        self, prop: PropString, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        self.edit = QLineEdit(self)
        self.edit.setReadOnly(self.prop.is_readonly)
        self.edit.editingFinished.connect(self._on_editing_finished)

        self.update_all()

        if layout := self.layout():
            layout.addWidget(self.edit)

    def _on_editing_finished(self):
        """Handle text editing finished"""
        new_value = self.edit.text()

        def set_func(value):
            self.prop.value = value

        if not self.prop_set_value(new_value, set_func):
            QMessageBox.critical(self, "Error", "Failed to set property value")
            self.update_all()

    def update_all(self):
        """Update line edit from property value"""
        try:
            self.edit.setEnabled(
                not self.should_display_as_locked() and not self.prop.is_readonly
            )
            self.edit.blockSignals(True)

            value = self.prop.value
            self.edit.setText(value)

            self.edit.blockSignals(False)
        except Exception:
            self.edit.blockSignals(False)
