"""
Enumeration property control
Translated from C++ PropEnumerationControl.h
"""

from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QMessageBox,
    QWidget,
    QSizePolicy,
    QBoxLayout,
)
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
            # Configure combo box for visibility
            self.combo.setMinimumHeight(28)
            self.combo.setMinimumWidth(150)  # Wider to show full enum values
            self.combo.setMaxVisibleItems(10)  # Allow scrolling if many items
            # Set combo to expand horizontally

            self.combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )

        self.update_all()

        if self.combo:
            self.combo.currentIndexChanged.connect(self._on_combo_changed)

        if self.edit:
            self.edit.setMinimumHeight(28)

        if layout := self.layout():

            if self.combo:
                layout.addWidget(self.combo)
                if isinstance(layout, QBoxLayout):
                    layout.setStretchFactor(self.combo, 1)
            if self.edit:
                layout.addWidget(self.edit)
                if isinstance(layout, QBoxLayout):
                    layout.setStretchFactor(self.edit, 1)

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

                current_value = None
                try:
                    # Get the current int_value (safer than comparing objects)
                    current_value = self.prop.int_value
                except Exception:
                    pass

                entries = []
                # Try multiple ways to access entries - they might be stored differently
                try:
                    # Method 1: Direct .entries attribute
                    if hasattr(self.prop, "entries"):
                        entries = list(self.prop.entries)
                except Exception:
                    pass

                # If still no entries, try accessing via selected_entry
                if not entries:
                    try:
                        selected = self.prop.selected_entry
                        if selected:
                            # At least we have one entry
                            entries = [selected]
                    except Exception:
                        pass

                # Track if we found and set the selected item
                current_index_set = False
                added_count = 0

                for entry in entries:
                    try:
                        # Check availability safely
                        try:
                            is_available = entry.is_available
                        except Exception:
                            is_available = True  # Default to available if can't check

                        if not is_available:
                            continue

                        # Check visibility safely
                        try:
                            visibility = entry.visibility
                            if visibility == PropertyVisibility.INVISIBLE:
                                continue
                        except Exception:
                            pass  # If can't check visibility, skip the check

                        # Get display name safely
                        try:
                            name = entry.display_name
                        except Exception:
                            try:
                                name = entry.name
                            except Exception:
                                name = ""

                        if not name or name.strip() == "":
                            # Skip entries with empty display names
                            continue

                        # Get value safely
                        try:
                            val = entry.value
                        except Exception:
                            continue

                        self.combo.addItem(name, val)
                        added_count += 1

                        # Match by value, not by object equality
                        if (
                            not current_index_set
                            and current_value is not None
                            and val == current_value
                        ):
                            self.combo.setCurrentIndex(self.combo.count() - 1)
                            current_index_set = True
                    except Exception:
                        pass

                # If no entry was selected by value, select the first available entry
                if not current_index_set and self.combo.count() > 0:
                    self.combo.setCurrentIndex(0)

                # If combo is empty, disable it and show indicator
                if self.combo.count() == 0:
                    self.combo.addItem("<No Entries>", None)
                    self.combo.setEnabled(False)

            except Exception as e:
                self.combo.setEnabled(False)
                self.combo.addItem(f"<Error: {type(e).__name__}>", None)
            finally:
                self.combo.blockSignals(False)

        if self.edit:
            self.edit.blockSignals(True)
            try:
                selected_entry = self.prop.selected_entry
                if selected_entry:
                    try:
                        name = selected_entry.display_name
                    except Exception:
                        try:
                            name = selected_entry.name
                        except Exception:
                            name = "<Unknown>"
                    self.edit.setText(name)
                else:
                    self.edit.setText("<No Selection>")
            except Exception:
                self.edit.setText("<Error>")
            finally:
                self.edit.blockSignals(False)
