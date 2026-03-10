import math
import re

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QMainWindow,
    QLabel,
)
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal

# Metric prefix multipliers for engineering notation input
_METRIC_PREFIXES = {"k": 1e3, "m": 1e-3, "u": 1e-6}
_METRIC_RE = re.compile(r"^([+-]?\d*\.?\d*)([kmu])(\d*)$", re.IGNORECASE)


def parse_metric_value(text: str) -> float | None:
    """Parse engineering notation: ``'1k1'`` → 1100, ``'100m'`` → 0.1, ``'4u7'`` → 4.7e-6.

    Returns *None* if *text* doesn't match metric notation.
    """
    m = _METRIC_RE.match(text.strip())
    if not m:
        return None
    integer_part = m.group(1) or "0"
    prefix = m.group(2).lower()
    frac = m.group(3)
    value = float(f"{integer_part}.{frac}") if frac else float(integer_part)
    return value * _METRIC_PREFIXES[prefix]


class BasicSlider(QWidget):
    """A slider with an editable text field showing the current value.

    The slider has a range from *min* to *maximum* with a specified *step* size.
    An optional *unit* string (e.g. ``"V"``, ``"A"``) is shown in a separate label
    to the right of the text field so the edit box always stays numeric.

    Signals
    -------
    valueChanged(float)
        Emitted whenever the slider is moved **by the user** or the text field is edited.
        Not emitted by programmatic ``set_value()`` calls so you can update the slider
        from polled data without triggering feedback loops.
    """

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        min: float | int,
        maximum: float | int,
        default: float | int,
        step: float | int,
        float_precision: int = 2,
        unit: str = "",
        parent: QWidget | QMainWindow | None = None,
    ):
        """
        Create a slider with an editable text field that shows the current value.
        Slider range is from min to max with nsteps increments of step size.
        """
        super().__init__(parent)
        self.min = min
        self.max = maximum
        self.default = default
        self.step = step
        self.unit = unit
        step_precision = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        self.float_precision = max(float_precision, step_precision)
        self.nsteps = (maximum - min) / step
        self._epsilon = max(float(step) * 1e-6, 1e-12)

        self._programmatic = False  # guard against signal loops

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Editable text field for value
        self.value_edit = QLineEdit(parent=self)
        self.value_edit.setText(self._format_value_text(self.default))
        self.value_edit.returnPressed.connect(self._on_text_edited)
        self.value_edit.setMinimumWidth(80)
        self.value_edit.setMaximumWidth(100)
        self.value_edit.setAlignment(Qt.AlignmentFlag.AlignRight)

        validator = QRegularExpressionValidator(
            QRegularExpression(r"^[+-]?\d*\.?\d*[kmuKMU]?\d*$"), self
        )
        self.value_edit.setValidator(validator)

        # Horizontal slider: stretches to fill available width
        self.slider = QSlider(orientation=Qt.Orientation.Horizontal, parent=self)
        self.slider.setRange(0, int(self.nsteps))  # Start at 0 to allow dragging to min
        self.slider.setMinimumHeight(40)  # 80% of typical 50px height
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.setValue(int(round((self.default - self.min) / self.step)))
        layout.addWidget(self.slider, stretch=1)  # Takes all available horizontal space
        layout.addWidget(self.value_edit)  # Fixed size based on content
        if self.unit:
            self.unit_label = QLabel(self.unit, parent=self)
            self.unit_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.unit_label.setMinimumWidth(12)
            layout.addWidget(self.unit_label)
        else:
            self.unit_label = None

        self.setLayout(layout)

    @property
    def value(self) -> float:
        """Current value based on slider position."""
        return self.slider.value() * self.step + self.min

    def set_value(self, value: float) -> None:
        """Programmatically set the slider position without emitting
        ``valueChanged``."""
        value = max(self.min, min(value, self.max))  # Clamp to range
        tick = int(round((value - self.min) / self.step))  # Snap to nearest step
        snapped = tick * self.step + self.min
        formatted = self._format_value_text(snapped)

        # Keep user typing stable: do not overwrite text while the edit box has focus.
        editing_text = self.value_edit.hasFocus()

        self._programmatic = True
        if self.slider.value() != tick:
            self.slider.setValue(tick)
        if not editing_text and self.value_edit.text() != formatted:
            self.value_edit.setText(formatted)
        self._programmatic = False

    # keep old name as internal alias
    def on_change(self) -> None:
        self.value_edit.setText(self._format_value_text(self.value))

    def _on_slider_changed(self) -> None:
        """Internal handler for QSlider.valueChanged."""
        val = self.value
        formatted = self._format_value_text(val)
        if not self.value_edit.hasFocus() and self.value_edit.text() != formatted:
            self.value_edit.setText(formatted)
        if not self._programmatic:
            self.valueChanged.emit(val)

    def _on_text_edited(self) -> None:
        """Internal handler for QLineEdit return pressed."""
        raw = self.value_edit.text().strip()
        try:
            val = parse_metric_value(raw)
            if val is None:
                val = float(raw)
            val = max(self.min, min(val, self.max))
            prev = self.value
            self.set_value(val)
            snapped = self.value  # actual step-snapped value
            if abs(snapped - prev) > self._epsilon:
                self.valueChanged.emit(snapped)
        except ValueError:
            self.value_edit.setText(self._format_value_text(self.value))

    def _format_value_text(self, value: float | int) -> str:
        """Format value for display in numeric text field."""
        if isinstance(value, float):
            return f"{value:.{self.float_precision}f}"
        else:
            return str(value)
