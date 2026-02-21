"""
Float property control
Translated from C++ PropFloatControl.h
"""

from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QSlider,
    QAbstractSpinBox,
    QMessageBox,
    QWidget,
)
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtGui import QKeyEvent
from typing import Optional
import math

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.properties import PropFloat
from .prop_control_base import PropControlBase


SLIDER_MIN = 0
SLIDER_MAX = 200
SLIDER_TICKS = SLIDER_MAX - SLIDER_MIN


class FormattingDoubleSpinBox(QDoubleSpinBox):
    """Custom spinbox with notation-aware formatting (matches C++ FormattingDoubleSpinBox)"""

    def __init__(self, parent, notation, precision):
        super().__init__(parent)
        self.notation_ = notation
        self.precision_ = precision

        self.editingFinished.connect(self._on_editing_finished)

    def textFromValue(self, value: float) -> str:
        return PropFloatControl.text_from_value(value, self.notation_, self.precision_)

    def _on_editing_finished(self):
        if self.isReadOnly():
            return
        text = self.lineEdit().text()
        try:
            val = self.valueFromText(text)
            self.setValue(val)
        except Exception:
            pass

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.editingFinished.emit()
            e.setAccepted(True)
            self.selectAll()
            return
        if e.key() == Qt.Key.Key_Escape:
            blk = QSignalBlocker(self)  # noqa: F841
            self.setValue(self.value())
            e.setAccepted(True)
            return
        super().keyPressEvent(e)


class PropFloatControl(PropControlBase):
    """Control widget for float properties (matches C++ PropFloatControl)"""

    prop: PropFloat

    def __init__(
        self, prop: PropFloat, parent: Optional[QWidget], grabber: Optional[Grabber]
    ):
        super().__init__(prop, parent, grabber)

        is_readonly = prop.is_readonly

        self.slider: Optional[QSlider] = None
        self.spin: Optional[FormattingDoubleSpinBox] = None

        self.min_ = 0.0
        self.max_ = 1.0

        # Get display properties
        try:
            self.notation_ = prop.display_notation
        except Exception:
            self.notation_ = None
        try:
            self.precision_ = prop.display_precision
        except Exception:
            self.precision_ = 6
        try:
            self.representation_ = prop.representation
        except Exception:
            self.representation_ = None

        rep_name = str(self.representation_).upper() if self.representation_ else ""

        # Create controls based on representation (matches C++ switch)
        if "PURENUMBER" in rep_name or "PURE_NUMBER" in rep_name:
            self.spin = FormattingDoubleSpinBox(self, self.notation_, self.precision_)
        elif "LINEAR" in rep_name:
            if not is_readonly:
                self.slider = QSlider(Qt.Orientation.Horizontal, self)
            self.spin = FormattingDoubleSpinBox(self, self.notation_, self.precision_)
        elif "LOGARITHMIC" in rep_name:
            if not is_readonly:
                self.slider = QSlider(Qt.Orientation.Horizontal, self)
            self.spin = FormattingDoubleSpinBox(self, self.notation_, self.precision_)
            self.spin.setStepType(QAbstractSpinBox.StepType.AdaptiveDecimalStepType)
        else:
            # Default
            self.spin = FormattingDoubleSpinBox(self, self.notation_, self.precision_)

        if self.slider:
            self.slider.valueChanged.connect(self._slider_moved)
        if self.spin:
            self.spin.setKeyboardTracking(False)
            self.spin.setDecimals(3)
            self.spin.valueChanged.connect(self._spin_value_changed)
            self.spin.setMinimumWidth(120)
            try:
                unit = prop.unit
                if unit:
                    self.spin.setSuffix(f" {unit}")
            except Exception:
                pass

        self.update_all()

        if layout := self.layout():
            if self.slider:
                layout.addWidget(self.slider)
            if self.spin:
                layout.addWidget(self.spin)

    @staticmethod
    def text_from_value(value: float, notation=None, precision: int = 6) -> str:
        """Format float value (matches C++ PropFloatControl::textFromValue)"""
        notation_name = str(notation).upper() if notation else ""
        if "SCIENTIFIC" in notation_name:
            return f"{value:.{precision}E}"
        if value >= math.pow(10, precision):
            return f"{value:.0f}"
        return f"{value:.{precision}g}"

    def _set_value_unchecked(self, new_val: float):
        def set_func(val):
            self.prop.value = val

        if not self.prop_set_value(new_val, set_func):
            QMessageBox.critical(self, "", "Failed to set property value")
            self.update_all()

    def _slider_moved(self, new_pos: int):
        """Handle slider movement (matches C++ slider_moved)"""
        rep_name = str(self.representation_).upper() if self.representation_ else ""

        if "LOGARITHMIC" in rep_name and self.min_ > 0 and self.max_ > 0:
            f = math.log
            g = math.exp
        else:
            f = lambda x: x
            g = lambda x: x

        try:
            range_len = f(self.max_) - f(self.min_)
            val = g(f(self.min_) + range_len / SLIDER_TICKS * new_pos)
            clamped_val = max(self.min_, min(self.max_, val))
        except (ValueError, ZeroDivisionError):
            clamped_val = self.min_

        self._set_value_unchecked(clamped_val)

    def _slider_position(self, val: float) -> int:
        """Calculate slider position for value (matches C++ slider_position)"""
        rep_name = str(self.representation_).upper() if self.representation_ else ""

        if "LOGARITHMIC" in rep_name and self.min_ > 0 and self.max_ > 0 and val > 0:
            f = math.log
        else:
            f = lambda x: x

        try:
            range_len = f(self.max_) - f(self.min_)
            if range_len == 0:
                return 0
            p = SLIDER_TICKS / range_len * (f(val) - f(self.min_))
            return int(p + 0.5)
        except (ValueError, ZeroDivisionError):
            return 0

    def _spin_value_changed(self, val: float):
        clamped = max(self.min_, min(self.max_, val))
        self._set_value_unchecked(clamped)

    def _show_error(self):
        """Show error state (matches C++ show_error)"""
        if self.spin:
            blk = QSignalBlocker(self.spin)  # noqa: F841
            self.spin.setEnabled(False)
            self.spin.setSpecialValueText("<Error>")
            self.spin.setValue(self.min_)
        if self.slider:
            self.slider.setEnabled(False)

    def update_all(self):
        """Update all UI elements (matches C++ update_all)"""
        inc = 1.0
        val = 0.0
        has_increment = False

        try:
            self.min_ = self.prop.minimum
        except Exception:
            return self._show_error()

        try:
            self.max_ = self.prop.maximum
        except Exception:
            return self._show_error()

        try:
            inc_mode = self.prop.increment_mode
            inc_mode_name = str(inc_mode).upper()
            has_increment = "INCREMENT" in inc_mode_name and "NONE" not in inc_mode_name
            if has_increment:
                inc = self.prop.increment
        except Exception:
            pass

        try:
            val = self.prop.value
        except Exception:
            return self._show_error()

        is_locked = self.should_display_as_locked()
        try:
            is_readonly = self.prop.is_readonly
        except Exception:
            is_readonly = True

        if self.slider:
            blk = QSignalBlocker(self.slider)  # noqa: F841
            self.slider.setMinimum(SLIDER_MIN)
            self.slider.setMaximum(SLIDER_MAX)
            self.slider.setValue(self._slider_position(val))
            self.slider.setEnabled(not is_locked)

        if self.spin:
            blk = QSignalBlocker(self.spin)  # noqa: F841
            self.spin.setSpecialValueText("")
            self.spin.setMinimum(self.min_)
            self.spin.setMaximum(self.max_)
            if has_increment:
                self.spin.setSingleStep(inc)
            self.spin.setValue(val)
            self.spin.setEnabled(True)
            self.spin.setReadOnly(is_locked or is_readonly)
            self.spin.setButtonSymbols(
                QAbstractSpinBox.ButtonSymbols.NoButtons
                if is_readonly
                else QAbstractSpinBox.ButtonSymbols.UpDownArrows
            )
