"""
Enumeration property control
Translated from C++ PropEnumerationControl.h
"""

from PyQt6.QtCore import Qt
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
            self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.update_all()

        if layout := self.layout():
            if self.combo:
                layout.addWidget(self.combo)
            if self.edit:
                layout.addWidget(self.edit)

    def _on_combo_changed(self, index: int):
        """Handle combo box selection change"""
        if index < 0:
            return

        value = self.combo.currentText() if self.combo else None

        def set_func(val):
            self.prop.value = val

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

                for entry in self.prop.entries:
                    try:
                        if not entry.is_available:
                            continue
                        if entry.visibility == PropertyVisibility.INVISIBLE:
                            continue

                        name = entry.display_name
                        val = entry.value

                        self.combo.addItem(name, val)

                        if selected_entry and entry == selected_entry:
                            self.combo.setCurrentIndex(self.combo.count() - 1)
                            selected_found = True
                    except Exception:
                        pass

                if not selected_found:
                    self.combo.setCurrentIndex(-1)

            except Exception as e:
                print(f"Error updating enumeration control: {e}")
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
