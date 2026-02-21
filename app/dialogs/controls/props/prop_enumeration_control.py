"""
Enumeration property control
Translated from C++ PropEnumerationControl.h
"""

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QComboBox, QLineEdit, QMessageBox, QWidget
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropEnumeration, PropertyVisibility
from .prop_control_base import PropControlBase


class PropEnumerationControl(PropControlBase):
    """Control widget for enumeration properties"""

    prop: PropEnumeration

    def __init__(
        self,
        prop: PropEnumeration,
        parent: Optional[QWidget],
        grabber: Optional[Grabber],
    ):
        super().__init__(prop, parent, grabber)

        is_readonly = self.prop.is_readonly

        self.combo = None
        self.edit = None

        if is_readonly:
            self.edit = QLineEdit(self)
            self.edit.setReadOnly(True)
        else:
            self.combo = QComboBox(self)

        self.update_all()

        if self.combo:
            self.combo.currentIndexChanged.connect(self._on_combo_changed)

        if layout := self.layout():
            if self.combo:
                layout.addWidget(self.combo)
            if self.edit:
                layout.addWidget(self.edit)

        if self.combo:
            self.combo.installEventFilter(self)
        if self.edit:
            self.edit.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            if watched in (self.combo, self.edit):
                self.on_prop_selected()
        return super().eventFilter(watched, event)

    def _on_combo_changed(self, index: int):
        """Handle combo box selection change"""
        if index < 0 or not self.combo:
            return

        value = self.combo.currentData()

        def set_func(val):
            self.prop.int_value = val

        if not self.prop_set_value(value, set_func):
            QMessageBox.warning(self, "Set property", "Failed to set property value")
            self.update_all()

    def update_all(self):
        """Update combo box or line edit from property"""
        if self.combo:
            self.combo.blockSignals(True)
            try:
                self.combo.setEnabled(
                    not self.prop.is_readonly and not self.should_display_as_locked()
                )
                self.combo.clear()

                selected_found = False

                try:
                    selected_entry = self.prop.selected_entry
                except Exception:
                    selected_entry = None

                try:
                    entries = list(self.prop.entries)
                except Exception:
                    entries = []

                for entry in entries:
                    try:
                        if not entry.is_available:
                            continue
                        if entry.visibility == PropertyVisibility.INVISIBLE:
                            continue

                        name = entry.display_name
                        val = entry.value

                        self.combo.addItem(name, val)

                        if selected_entry is not None and entry == selected_entry:
                            self.combo.setCurrentIndex(self.combo.count() - 1)
                            selected_found = True
                    except Exception:
                        pass

                if not selected_found:
                    self.combo.setCurrentIndex(-1)

            except Exception:
                pass
            finally:
                self.combo.blockSignals(False)

        if self.edit:
            self.edit.blockSignals(True)
            try:
                selected_entry = self.prop.selected_entry
                self.edit.setText(selected_entry.display_name)
            except Exception:
                self.edit.setText("<Error>")
            finally:
                self.edit.blockSignals(False)
