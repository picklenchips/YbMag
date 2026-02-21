from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSlider, QMainWindow
from PyQt6.QtCore import Qt


class BasicSlider(QWidget):
    """A slider with a label that shows the current value. The slider has a range from min to max, with a specified step size."""

    def __init__(
        self,
        min: float | int,
        max: float | int,
        default: float | int,
        step: float | int,
        float_precision: int = 2,
        parent: QWidget | QMainWindow | None = None,
    ):
        """
        Create a slider with label, which has 100 steps and a
        range from min to max.
        """
        super().__init__(parent)
        self.min = min
        self.max = max
        self.default = default
        self.step = step
        self.float_precision = float_precision
        self.nsteps = (max - min) / step

        layout = QHBoxLayout()
        self.label = QLabel(self._format_value(self.default), parent=self)
        self.slider = QSlider(orientation=Qt.Orientation.Horizontal, parent=self)
        self.slider.setRange(1, int(self.nsteps) + 1)
        self.slider.valueChanged.connect(self.on_change)
        self.slider.setValue(int(self.default / self.step))
        layout.addWidget(self.slider)
        layout.addWidget(self.label)
        self.setMaximumSize(200, 50)
        self.setLayout(layout)  # sets self.layout() to the new layout

    def get_value(self) -> float:
        return self.slider.value() * self.step + self.min

    def on_change(self):
        self.label.setText(self._format_value(self.get_value()))

    def _format_value(self, value: float | int) -> str:
        if isinstance(value, float):
            return f"{value:.{self.float_precision}f}"
        else:
            return str(value)
