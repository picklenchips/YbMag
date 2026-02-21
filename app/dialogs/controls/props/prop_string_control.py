"""
String property control
Translated from C++ PropStringControl.h
"""

from PyQt6.QtWidgets import QLineEdit, QMessageBox, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropString
from .prop_control_base import PropControlBase


class StringLineEdit(QLineEdit):
    """Line edit with Enter/Escape key handling (matches C++ StringLineEdit)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._escape_callback = None

    def set_escape_callback(self, cb):
        self._escape_callback = cb

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.editingFinished.emit()
            return
        if e.key() == Qt.Key.Key_Escape:
            if self._escape_callback:
                self._escape_callback()
            return
        super().keyPressEvent(e)


class PropStringControl(PropControlBase):
    """Control widget for string properties (matches C++ PropStringControl)"""

    prop: PropString

    def __init__(
        self, prop: PropString, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        # Get max length
        max_length = None
        try:
            max_length = prop.max_length
        except Exception:
            pass

        self.edit = StringLineEdit(self)
        self.edit.setReadOnly(prop.is_readonly)
        self.edit.editingFinished.connect(self._set_value)
        self.edit.set_escape_callback(self._update_value)

        if max_length is not None:
            self.edit.setMaxLength(int(max_length))

        self.update_all()

        if layout := self.layout():
            layout.addWidget(self.edit)

    def _set_value(self):
        """Handle editing finished (matches C++ set_value)"""
        if self.edit.isReadOnly():
            return

        new_val = self.edit.text()

        def set_func(val):
            self.prop.value = val

        if not self.prop_set_value(new_val, set_func):
            QMessageBox.critical(self, "", "Failed to set property value")
            self.update_all()

    def _update_value(self):
        """Restore value display from property (matches C++ update_value)"""
        self.edit.blockSignals(True)
        try:
            val = self.prop.value
            self.edit.setText(val)
        except Exception:
            self.edit.setText("<Error>")
        self.edit.blockSignals(False)

    def update_all(self):
        """Update all UI elements (matches C++ update_all)"""
        self._update_value()

        self.edit.blockSignals(True)

        try:
            is_readonly = self.prop.is_readonly
        except Exception:
            is_readonly = True
        is_locked = self.should_display_as_locked()

        self.edit.setSelection(0, 0)
        self.edit.setReadOnly(is_readonly or is_locked)

        self.edit.blockSignals(False)
        self.edit.update()
