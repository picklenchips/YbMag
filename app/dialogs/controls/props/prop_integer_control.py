"""
Integer property control
Translated from C++ PropIntControl.h, PropIntSpinBox.h, PropIntSlider.h
"""

from PyQt6.QtWidgets import (
    QSpinBox,
    QLineEdit,
    QMessageBox,
    QWidget,
    QSlider,
    QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from typing import Optional

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropInteger, PropIntRepresentation
from .prop_control_base import PropControlBase


class IntSlider(QSlider):
    """Slider widget for integer properties with smooth value mapping
    Translated from C++ PropIntSlider.h
    """

    SLIDER_MAX = 10000
    value_changed = pyqtSignal(int)
    value_step = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(Qt.Orientation.Horizontal, parent)

        self.val_ = 0
        self.min_ = 0
        self.max_ = 99

        super().setMinimum(0)
        super().setMaximum(self.SLIDER_MAX)
        super().setSingleStep(1)

        self.valueChanged.connect(self._on_slider_changed)

    def setRange(self, min_val: int, max_val: int):
        """Set the actual min/max values for the property"""
        self.min_ = min_val
        self.max_ = max_val
        self._update_position()

    def setValue(self, val: int):
        """Set the actual property value"""
        self.val_ = val
        self._update_position()

    def _slider_to_value(self, slider_pos: int) -> int:
        """Convert slider position to actual property value"""
        rel = slider_pos / float(self.SLIDER_MAX)
        range_len = self.max_ - self.min_
        val = self.min_ + range_len * rel

        if val >= float(self.max_):
            return self.max_
        if val <= float(self.min_):
            return self.min_
        return int(val)

    def _value_to_slider(self, value: int) -> int:
        """Convert actual property value to slider position"""
        offset = value - self.min_
        range_len = self.max_ - self.min_
        if range_len == 0:
            return 0
        rel = offset / float(range_len)
        return int(self.SLIDER_MAX * rel)

    def _on_slider_changed(self, slider_pos: int):
        """Handle slider position change"""
        self.val_ = self._slider_to_value(slider_pos)
        self.value_changed.emit(self.val_)

    def _update_position(self):
        """Update slider position to match current value"""
        slider_pos = self._value_to_slider(self.val_)
        self.blockSignals(True)
        super().setValue(slider_pos)
        self.blockSignals(False)

    def keyPressEvent(self, event):
        """Handle keyboard input for value stepping"""
        mag = 1
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            mag = 10

        if event.key() in [Qt.Key.Key_Left, Qt.Key.Key_Down]:
            self.value_step.emit(-mag)
            event.accept()
        elif event.key() in [Qt.Key.Key_Right, Qt.Key.Key_Up]:
            self.value_step.emit(mag)
            event.accept()
        elif event.key() == Qt.Key.Key_PageUp:
            self.value_step.emit(10 * mag)
            event.accept()
        elif event.key() == Qt.Key.Key_PageDown:
            self.value_step.emit(-10 * mag)
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        """Handle mouse wheel for value stepping"""
        mag = 1
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            mag = 10

        delta = event.angleDelta().y()
        if delta > 0:
            self.value_step.emit(mag)
            event.accept()
        elif delta < 0:
            self.value_step.emit(-mag)
            event.accept()


class PropIntegerControl(PropControlBase):
    """Control widget for integer properties"""

    prop: PropInteger

    def __init__(
        self, prop: PropInteger, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        self.slider = None
        self.spin = None
        self.edit = None

        self.representation_ = PropIntRepresentation.PURENUMBER
        self.min_ = 0
        self.max_ = 0
        self.inc_ = 1
        self.val_ = 0

        try:
            self.representation_ = self.prop.representation
            is_readonly = self.prop.is_readonly

            if self.representation_ in [
                PropIntRepresentation.MACADDRESS,
                PropIntRepresentation.IPV4ADDRESS,
            ]:
                self.edit = QLineEdit(self)
            elif self.representation_ == PropIntRepresentation.HEXNUMBER:
                if is_readonly:
                    self.edit = QLineEdit(self)
                else:
                    self.spin = QSpinBox(self)
                    self.spin.setDisplayIntegerBase(16)
                    self.spin.setPrefix("0x")
            elif self.representation_ in [
                PropIntRepresentation.LINEAR,
                PropIntRepresentation.LOGARITHMIC,
            ]:
                if is_readonly:
                    self.edit = QLineEdit(self)
                else:
                    self.slider = IntSlider(self)
                    self.spin = QSpinBox(self)
            elif self.representation_ == PropIntRepresentation.PURENUMBER:
                if is_readonly:
                    self.edit = QLineEdit(self)
                else:
                    self.spin = QSpinBox(self)
            elif self.representation_ == PropIntRepresentation.BOOLEAN:
                self.edit = QLineEdit(self)
            else:
                if is_readonly:
                    self.edit = QLineEdit(self)
                else:
                    self.spin = QSpinBox(self)
        except Exception:
            self.edit = QLineEdit(self)

        if self.slider:
            self.slider.value_changed.connect(self._set_value)
            self.slider.value_step.connect(self._value_step)
            self.slider.installEventFilter(self)
        if self.spin:
            self.spin.setKeyboardTracking(False)
            self.spin.valueChanged.connect(self._set_value_unchecked)
            self.spin.setMinimumWidth(120)
            try:
                unit = self.prop.unit
                if unit:
                    self.spin.setSuffix(unit)
            except Exception:
                pass
            self.spin.installEventFilter(self)
        if self.edit:
            self.edit.setReadOnly(True)
            self.edit.installEventFilter(self)

        self.update_all()

        if layout := self.layout():
            if self.slider:
                layout.addWidget(self.slider)
            if self.spin:
                layout.addWidget(self.spin)
            if self.edit:
                layout.addWidget(self.edit)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            if watched in (self.slider, self.spin, self.edit):
                self.on_prop_selected()
        return super().eventFilter(watched, event)

    @staticmethod
    def value_to_string(val: int, rep: PropIntRepresentation) -> str:
        """Convert value to string based on representation"""
        if rep == PropIntRepresentation.BOOLEAN:
            return "True" if val else "False"
        elif rep == PropIntRepresentation.HEXNUMBER:
            return f"0x{val:x}"
        elif rep == PropIntRepresentation.MACADDRESS:
            return ":".join([f"{(val >> (40 - i * 8)) & 0xFF:02x}" for i in range(6)])
        elif rep == PropIntRepresentation.IPV4ADDRESS:
            return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"
        else:
            return str(val)

    def _set_value_unchecked(self, new_val: int):
        """Set value directly (matches C++ set_value_unchecked)"""

        def set_func(val):
            self.prop.value = val

        if not self.prop_set_value(new_val, set_func):
            QMessageBox.critical(self, "", "Failed to set property value")
            self.update_all()

    def _value_step(self, step: int):
        """Handle value stepping (matches C++ value_step)"""
        try:
            new_val = self.val_
            step *= self.inc_

            if step < 0:
                if self.val_ > self.min_ - step:
                    new_val = self.val_ + step
                else:
                    new_val = self.min_
            elif step > 0:
                if self.val_ < self.max_ - step:
                    new_val = self.val_ + step
                else:
                    new_val = self.max_

            self._set_value_unchecked(new_val)
        except Exception:
            pass

    def _set_value(self, new_pos: int):
        """Set value from slider, snap to increment (matches C++ set_value)"""
        try:
            new_val = max(self.min_, min(self.max_, new_pos))

            if self.inc_ > 1 and (new_val - self.min_) % self.inc_:
                fixed_val = self.min_ + (new_val - self.min_) // self.inc_ * self.inc_
                if fixed_val == self.val_:
                    if new_val > self.val_:
                        new_val = self.val_ + self.inc_
                    elif new_val < self.val_:
                        new_val = self.val_ - self.inc_
                else:
                    new_val = fixed_val

            self._set_value_unchecked(new_val)
        except Exception:
            pass

    def _show_error(self):
        """Show error state (matches C++ show_error)"""
        if self.spin:
            self.spin.blockSignals(True)
            self.spin.setEnabled(False)
            self.spin.setSpecialValueText("<Error>")
            self.spin.setValue(self.spin.minimum())
            self.spin.blockSignals(False)
        if self.edit:
            self.edit.blockSignals(True)
            self.edit.setEnabled(False)
            self.edit.setText("<Error>")
            self.edit.blockSignals(False)

    def update_all(self):
        """Update control from property value (matches C++ update_all)"""
        try:
            self.min_ = self.prop.minimum
        except Exception:
            return self._show_error()

        try:
            self.max_ = self.prop.maximum
        except Exception:
            return self._show_error()

        try:
            self.inc_ = self.prop.increment
        except Exception:
            self.inc_ = 1

        try:
            self.val_ = self.prop.value
        except Exception:
            return self._show_error()

        is_locked = self.should_display_as_locked()
        try:
            is_readonly = self.prop.is_readonly
        except Exception:
            is_readonly = True

        if self.slider:
            self.slider.blockSignals(True)
            self.slider.setRange(int(self.min_), int(self.max_))
            self.slider.setValue(int(self.val_))
            self.slider.setEnabled(not is_locked)
            self.slider.blockSignals(False)

        if self.spin:
            self.spin.blockSignals(True)
            self.spin.setSpecialValueText("")
            min_clamped = max(-2147483648, self.min_)
            max_clamped = min(2147483647, self.max_)
            self.spin.setMinimum(int(min_clamped))
            self.spin.setMaximum(int(max_clamped))
            self.spin.setSingleStep(int(self.inc_))
            self.spin.setValue(int(self.val_))
            self.spin.setEnabled(True)
            self.spin.setReadOnly(is_locked or is_readonly)
            self.spin.setButtonSymbols(
                QAbstractSpinBox.ButtonSymbols.NoButtons
                if is_readonly
                else QAbstractSpinBox.ButtonSymbols.UpDownArrows
            )
            self.spin.blockSignals(False)

        if self.edit:
            self.edit.blockSignals(True)
            self.edit.setText(self.value_to_string(self.val_, self.representation_))
            self.edit.setEnabled(True)
            self.edit.setReadOnly(is_locked or is_readonly)
            self.edit.blockSignals(False)
