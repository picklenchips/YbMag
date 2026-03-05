import math

from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QMainWindow,
    QLabel,
)
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtCore import Qt, pyqtSignal


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

        validator = QDoubleValidator(self.min, self.max, self.float_precision, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
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

    def get_value(self) -> float:
        return self.slider.value() * self.step + self.min

    def set_value(self, value: float) -> None:
        """Programmatically set the slider position without emitting
        ``valueChanged``."""
        value = max(self.min, min(value, self.max))
        tick = int(round((value - self.min) / self.step))
        formatted = self._format_value_text(value)

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
        self.value_edit.setText(self._format_value_text(self.get_value()))

    def _on_slider_changed(self) -> None:
        """Internal handler for QSlider.valueChanged."""
        val = self.get_value()
        formatted = self._format_value_text(val)
        if not self.value_edit.hasFocus() and self.value_edit.text() != formatted:
            self.value_edit.setText(formatted)
        if not self._programmatic:
            self.valueChanged.emit(val)

    def _on_text_edited(self) -> None:
        """Internal handler for QLineEdit return pressed."""
        try:
            val = float(self.value_edit.text().strip())
            # Clamp to valid range
            val = max(self.min, min(val, self.max))
            prev = self.get_value()
            self.set_value(val)
            if abs(val - prev) > self._epsilon:
                self.valueChanged.emit(val)
        except ValueError:
            # Invalid input, revert to current value
            self.value_edit.setText(self._format_value_text(self.get_value()))

    def _format_value_text(self, value: float | int) -> str:
        """Format value for display in numeric text field."""
        if isinstance(value, float):
            return f"{value:.{self.float_precision}f}"
        else:
            return str(value)
