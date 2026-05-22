"""Engineering-notation scroll-wheel control: [integer].[fraction] [prefix]unit.

Two scroll-wheel digits (0–999 each, configurable) form the number,
a third scroll wheel selects the SI prefix, and a static label shows the unit.
Clicking any wheel opens a text editor for direct metric-notation entry.
"""

import re

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QLabel, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QEvent, QTimer
from PyQt6.QtGui import QWheelEvent, QMouseEvent, QFontMetrics, QFont

# Common prefix ladders (label, multiplier), ordered smallest → largest
SI_TIME_PREFIXES = [
    ("n", 1e-9),
    ("\u00b5", 1e-6),
    ("m", 1e-3),
    ("", 1.0),
]

SI_FREQ_PREFIXES = [
    ("", 1.0),
    ("k", 1e3),
    ("M", 1e6),
]

# Lookup from typed prefix character → multiplier (case-insensitive input)
_TYPED_PREFIXES = {"n": 1e-9, "u": 1e-6, "\u00b5": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}
_METRIC_RE = re.compile(r"^([+-]?\d*\.?\d*)([num\u00b5kM])([\d.]*)$", re.IGNORECASE)

# Base font size for the wheels (pt).  Changing this scales the entire control.
_BASE_FONT_PT = 15  # ~1.5× default 10pt

_WHEEL_STYLE = (
    "QLabel {"
    f"  font-size: {_BASE_FONT_PT}pt;"
    "  border: 1px solid #666; border-radius: 3px; padding: 2px 4px;"
    "  font-family: monospace;"
    "}"
)

# Drag-to-scroll constants
_DRAG_TIMER_MS = 50  # How often drag ticks fire
_DRAG_DEADZONE_PX = 6  # Pixels of movement before drag kicks in
_DRAG_PX_PER_STEP = 5  # Pixels of distance for 1 step per tick
_DRAG_MAX_STEPS = 999  # Cap per tick


class _NumericWheel(QLabel):
    """Scroll-wheel label displaying an integer in ``[0, max_val]``.

    Supports mouse-wheel scrolling (±1 per notch) and click-drag scrolling
    where the step rate increases with distance from the press origin.

    Signals
    -------
    valueChanged(int)
        Emitted on user scroll.  Not emitted by ``set_value()``.
    overflowUp
        Emitted when scrolling up past *max_val*.
    overflowDown
        Emitted when scrolling down past 0.
    clicked
        Emitted on mouse press (used to open the inline editor).
    """

    valueChanged = pyqtSignal(int)
    overflowUp = pyqtSignal()
    overflowDown = pyqtSignal()
    clicked = pyqtSignal()

    def __init__(
        self,
        max_val: int = 999,
        alignment=Qt.AlignmentFlag.AlignRight,
        digits: int = 3,
        parent=None,
    ):
        super().__init__(parent)
        self._max = max_val
        self._value = 0
        self._digits = digits
        self._update_text()
        self.setAlignment(alignment)
        # Use scaled font for metrics
        font = QFont("monospace", _BASE_FONT_PT)
        fm = QFontMetrics(font)
        char_w = fm.horizontalAdvance("0")
        self.setFixedWidth(char_w * (digits + 1) + 12)  # digits + padding
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Scroll to change value; drag up/down for fast adjust")
        self.setStyleSheet(_WHEEL_STYLE)

        # Drag state
        self._drag_active = False
        self._drag_origin_y = 0
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(_DRAG_TIMER_MS)
        self._drag_timer.timeout.connect(self._drag_tick)

    @property
    def max_val(self):
        return self._max

    @max_val.setter
    def max_val(self, v: int):
        self._max = v
        if self._value > v:
            self._value = v
            self._update_text()

    def get_value(self) -> int:
        return self._value

    def set_value(self, v: int) -> None:
        v = max(0, min(v, self._max))
        if v != self._value:
            self._value = v
            self._update_text()

    def _update_text(self):
        self.setText(str(self._value).zfill(self._digits))

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta > 0:
            self._step(1)
        elif delta < 0:
            self._step(-1)
        ev.accept()

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._drag_origin_y = ev.globalPosition().y()
        ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            dy = self._drag_origin_y - ev.globalPosition().y()
            if not self._drag_active and abs(dy) > _DRAG_DEADZONE_PX:
                self._drag_active = True
                self._drag_timer.start()
                QApplication.setOverrideCursor(Qt.CursorShape.SizeVerCursor)
        ev.accept()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self._drag_active:
                self._drag_timer.stop()
                self._drag_active = False
                QApplication.restoreOverrideCursor()
            else:
                # Short click — open editor
                self.clicked.emit()
        ev.accept()

    def _drag_tick(self):
        """Called periodically while dragging. Step count ∝ distance from origin."""
        cur_y = self.cursor().pos().y()
        dy = self._drag_origin_y - cur_y  # positive = dragged up = increase
        abs_dy = abs(dy) - _DRAG_DEADZONE_PX
        if abs_dy <= 0:
            return
        steps = min(int(abs_dy / _DRAG_PX_PER_STEP) + 1, _DRAG_MAX_STEPS)
        direction = 1 if dy > 0 else -1
        for _ in range(steps):
            self._step(direction)

    def _step(self, direction: int):
        """Apply a single +1 or -1 step with overflow signals."""
        if direction > 0:
            if self._value >= self._max:
                self._value = 0
                self._update_text()
                self.overflowUp.emit()
                self.valueChanged.emit(self._value)
            else:
                self._value += 1
                self._update_text()
                self.valueChanged.emit(self._value)
        else:
            if self._value <= 0:
                self._value = self._max
                self._update_text()
                self.overflowDown.emit()
                self.valueChanged.emit(self._value)
            else:
                self._value -= 1
                self._update_text()
                self.valueChanged.emit(self._value)


class _PrefixWheel(QLabel):
    """Narrow scroll wheel cycling through SI prefix characters only.

    Signals
    -------
    indexChanged(int)
        Emitted on user scroll.
    clicked
        Emitted on mouse press.
    """

    indexChanged = pyqtSignal(int)
    clicked = pyqtSignal()

    def __init__(self, prefixes, initial_index=0, parent=None):
        super().__init__(parent)
        self._prefixes = prefixes
        self._index = max(0, min(initial_index, len(prefixes) - 1))
        self._update_text()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("monospace", _BASE_FONT_PT)
        fm = QFontMetrics(font)
        # Width for one character + padding
        self.setFixedWidth(max(fm.horizontalAdvance("M") + 14, 24))
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Scroll to change SI prefix; drag up/down for fast adjust")
        self.setStyleSheet(_WHEEL_STYLE)

        # Drag state
        self._drag_active = False
        self._drag_origin_y = 0
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(_DRAG_TIMER_MS)
        self._drag_timer.timeout.connect(self._drag_tick)

    @property
    def index(self):
        return self._index

    @property
    def multiplier(self):
        return self._prefixes[self._index][1]

    @property
    def label(self):
        return self._prefixes[self._index][0]

    def set_index(self, idx: int, *, emit=True) -> bool:
        """Set prefix index.  Returns True if the index actually changed."""
        idx = max(0, min(idx, len(self._prefixes) - 1))
        if idx != self._index:
            self._index = idx
            self._update_text()
            if emit:
                self.indexChanged.emit(idx)
            return True
        return False

    def increment(self, *, emit=True) -> bool:
        return self.set_index(self._index + 1, emit=emit)

    def decrement(self, *, emit=True) -> bool:
        return self.set_index(self._index - 1, emit=emit)

    def _update_text(self):
        label = self._prefixes[self._index][0]
        # Show a visible placeholder when prefix is empty (base unit)
        self.setText(label if label else "\u2013")

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta > 0:
            self.set_index(self._index + 1)
        elif delta < 0:
            self.set_index(self._index - 1)
        ev.accept()

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._drag_origin_y = ev.globalPosition().y()
        ev.accept()

    def mouseMoveEvent(self, ev: QMouseEvent):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            dy = self._drag_origin_y - ev.globalPosition().y()
            if not self._drag_active and abs(dy) > _DRAG_DEADZONE_PX:
                self._drag_active = True
                self._drag_timer.start()
                QApplication.setOverrideCursor(Qt.CursorShape.SizeVerCursor)
        ev.accept()

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self._drag_active:
                self._drag_timer.stop()
                self._drag_active = False
                QApplication.restoreOverrideCursor()
            else:
                self.clicked.emit()
        ev.accept()

    def _drag_tick(self):
        """Step prefix by drag distance (1 step per tick, direction only)."""
        cur_y = self.cursor().pos().y()
        dy = self._drag_origin_y - cur_y
        if abs(dy) <= _DRAG_DEADZONE_PX:
            return
        if dy > 0:
            self.set_index(self._index + 1)
        else:
            self.set_index(self._index - 1)


class EngineeringSlider(QWidget):
    """Scroll-wheel engineering-notation control: ``[integer].[fraction] [prefix]unit``.

    Two scroll wheels (0–999 each by default) represent the integer and fractional
    parts.  A third narrow wheel selects the SI prefix.  The unit string is a
    static label to the right.

    Overflow is linked:
    - Mantissa (fraction) overflow/underflow increments/decrements the integer wheel.
    - Integer overflow/underflow increments/decrements the prefix wheel.

    Clicking any wheel opens a text editor spanning the wheels, accepting metric
    notation (e.g. ``999u999``).

    Parameters
    ----------
    prefixes : list[tuple[str, float]]
        Ordered prefix ladder, e.g. ``SI_TIME_PREFIXES``.
    unit : str
        Unit label shown after the prefix wheel (e.g. ``"Hz"``, ``"s"``).
    default : float
        Starting value.
    digits : int
        Number of digits for each scroll wheel (default 3 → 0–999).
    min_value, max_value : float or None
        Clamping bounds for the represented value.

    Signals
    -------
    valueChanged(float)
        Emitted on user interaction only.  Not emitted by ``set_value()``.
    """

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        prefixes: list[tuple[str, float]],
        unit: str = "",
        default: float = 0.0,
        digits: int = 3,
        min_value: float | None = None,
        max_value: float | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._prefixes = prefixes
        self._digits = digits
        self._wheel_max = 10**digits - 1  # e.g. 999 for 3 digits
        self._programmatic = False
        self._editing = False
        self._min_value = min_value
        self._max_value = max_value

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Integer wheel (right-aligned digits)
        self._int_wheel = _NumericWheel(
            max_val=self._wheel_max,
            alignment=Qt.AlignmentFlag.AlignRight,
            digits=digits,
        )
        layout.addWidget(self._int_wheel)

        # Decimal point label
        dot = QLabel(".")
        dot.setStyleSheet(
            f"font-family: monospace; font-size: {_BASE_FONT_PT}pt; padding: 0 1px;"
        )
        dot.setFixedWidth(
            QFontMetrics(QFont("monospace", _BASE_FONT_PT)).horizontalAdvance(".") + 4
        )
        layout.addWidget(dot)

        # Fraction/mantissa wheel (left-aligned digits)
        self._frac_wheel = _NumericWheel(
            max_val=self._wheel_max,
            alignment=Qt.AlignmentFlag.AlignLeft,
            digits=digits,
        )
        layout.addWidget(self._frac_wheel)

        layout.addSpacing(4)

        # Prefix scroll wheel (narrow, single-char)
        self._prefix_wheel = _PrefixWheel(prefixes, parent=self)
        layout.addWidget(self._prefix_wheel)

        # Unit label (static)
        self._unit_label = QLabel(unit)
        self._unit_label.setStyleSheet(
            f"font-family: monospace; font-size: {_BASE_FONT_PT}pt; padding-left: 1px;"
        )
        layout.addWidget(self._unit_label)

        layout.addStretch()

        # Inline text editor (hidden; overlays the wheels on click)
        self._edit = QLineEdit(self)
        self._edit.setStyleSheet(
            f"QLineEdit {{ font-family: monospace; font-size: {_BASE_FONT_PT}pt;"
            " border: 1px solid #09f; border-radius: 3px; padding: 2px 4px; }"
        )
        self._edit.hide()
        self._edit.returnPressed.connect(self._on_edit_committed)
        self._edit.installEventFilter(self)

        self.setLayout(layout)

        # Wire up scroll wheels
        self._int_wheel.valueChanged.connect(self._on_wheel_changed)
        self._frac_wheel.valueChanged.connect(self._on_wheel_changed)
        self._prefix_wheel.indexChanged.connect(self._on_wheel_changed)

        # Overflow linking: frac → int → prefix
        self._frac_wheel.overflowUp.connect(self._on_frac_overflow_up)
        self._frac_wheel.overflowDown.connect(self._on_frac_overflow_down)
        self._int_wheel.overflowUp.connect(self._on_int_overflow_up)
        self._int_wheel.overflowDown.connect(self._on_int_overflow_down)

        # Click-to-edit
        self._int_wheel.clicked.connect(self._open_editor)
        self._frac_wheel.clicked.connect(self._open_editor)
        self._prefix_wheel.clicked.connect(self._open_editor)

        self.set_value(default)

    # -- Public properties --

    @property
    def min(self) -> float | None:
        return self._min_value

    @min.setter
    def min(self, v: float | None):
        self._min_value = v
        if v is not None and self.value < v:
            self.set_value(v)

    @property
    def max(self) -> float | None:
        return self._max_value

    @max.setter
    def max(self, v: float | None):
        self._max_value = v
        if v is not None and self.value > v:
            self.set_value(v)

    @property
    def value(self) -> float:
        """Current value = (integer + fraction / 10**digits) × prefix multiplier."""
        integer = self._int_wheel.get_value()
        frac = self._frac_wheel.get_value()
        mantissa = integer + frac / (10**self._digits)
        return mantissa * self._prefix_wheel.multiplier

    def set_value(self, val: float) -> None:
        """Programmatically set value, auto-selecting the best prefix.

        Does NOT emit ``valueChanged``.
        """
        self._programmatic = True
        val = self._clamp(val)
        abs_val = abs(val)

        # Pick best prefix: largest multiplier where mantissa >= 0.001
        best_idx = 0
        for i, (_label, mult) in enumerate(self._prefixes):
            if mult == 0:
                continue
            m = abs_val / mult
            if m <= self._wheel_max + self._wheel_max / 10**self._digits + 0.0005:
                best_idx = i
                # Keep going — prefer larger prefixes that still fit
        # Fallback: pick prefix minimizing error
        best_error = float("inf")
        for i, (_label, mult) in enumerate(self._prefixes):
            if mult == 0:
                continue
            m = abs_val / mult
            if 0 <= m <= self._wheel_max + self._wheel_max / 10**self._digits + 0.0005:
                # Representable mantissa
                int_part = int(m)
                frac_part = round((m - int_part) * 10**self._digits)
                reconstructed = (int_part + frac_part / 10**self._digits) * mult
                error = abs(abs_val - reconstructed)
                if error < best_error:
                    best_error = error
                    best_idx = i

        self._prefix_wheel.set_index(best_idx, emit=False)
        mult = self._prefix_wheel.multiplier
        mantissa = val / mult if mult else 0.0
        int_part = int(mantissa)
        frac_part = round((mantissa - int_part) * 10**self._digits)
        # Handle rounding overflow (e.g. 0.9999... → 1.000)
        if frac_part > self._wheel_max:
            frac_part = 0
            int_part += 1
        int_part = max(0, min(int_part, self._wheel_max))
        frac_part = max(0, min(frac_part, self._wheel_max))

        self._int_wheel.set_value(int_part)
        self._frac_wheel.set_value(frac_part)
        self._programmatic = False

    # -- Clamping --

    def _clamp(self, val: float) -> float:
        if self._min_value is not None and val < self._min_value:
            val = self._min_value
        if self._max_value is not None and val > self._max_value:
            val = self._max_value
        return val

    def _emit_if_user(self) -> None:
        """Clamp and emit if this is a user action."""
        if self._programmatic:
            return
        val = self.value
        clamped = self._clamp(val)
        if clamped != val:
            self._programmatic = True
            self.set_value(clamped)
            self._programmatic = False
        self.valueChanged.emit(self.value)

    # -- Overflow linking --

    def _on_frac_overflow_up(self):
        """Fraction scrolled past max → increment integer."""
        if self._programmatic:
            return
        old_int = self._int_wheel.get_value()
        if old_int >= self._wheel_max:
            # Integer also overflows → try incrementing prefix
            if self._prefix_wheel.increment(emit=False):
                self._int_wheel.set_value(0)
            else:
                # At maximum prefix — clamp frac back
                self._frac_wheel.set_value(self._wheel_max)
                self._int_wheel.set_value(self._wheel_max)
        else:
            self._int_wheel.set_value(old_int + 1)

    def _on_frac_overflow_down(self):
        """Fraction scrolled below 0 → decrement integer."""
        if self._programmatic:
            return
        old_int = self._int_wheel.get_value()
        if old_int <= 0:
            # Integer also underflows → try decrementing prefix
            if self._prefix_wheel.decrement(emit=False):
                self._int_wheel.set_value(self._wheel_max)
            else:
                # At minimum prefix — clamp
                self._frac_wheel.set_value(0)
                self._int_wheel.set_value(0)
        else:
            self._int_wheel.set_value(old_int - 1)

    def _on_int_overflow_up(self):
        """Integer scrolled past max → try incrementing prefix."""
        if self._programmatic:
            return
        if not self._prefix_wheel.increment(emit=False):
            # Can't go higher — clamp
            self._int_wheel.set_value(self._wheel_max)

    def _on_int_overflow_down(self):
        """Integer scrolled below 0 → try decrementing prefix."""
        if self._programmatic:
            return
        if not self._prefix_wheel.decrement(emit=False):
            # Can't go lower — clamp
            self._int_wheel.set_value(0)

    # -- Wheel change handler --

    def _on_wheel_changed(self, *_args):
        self._emit_if_user()

    # -- Click-to-edit --

    def _open_editor(self):
        if self._editing:
            return
        self._editing = True
        # Position the editor to span from integer wheel to prefix wheel
        left = self._int_wheel.geometry().left()
        right = self._prefix_wheel.geometry().right()
        top = self._int_wheel.geometry().top()
        height = self._int_wheel.geometry().height()
        self._edit.setGeometry(left, top, right - left, height)

        # Format current value as metric notation (e.g. "123u456")
        integer = self._int_wheel.get_value()
        frac = self._frac_wheel.get_value()
        prefix_label = self._prefix_wheel.label
        # Use 'u' for micro sign in typing
        editable_prefix = "u" if prefix_label == "\u00b5" else prefix_label
        frac_str = str(frac).zfill(self._digits)
        if editable_prefix:
            self._edit.setText(f"{integer}{editable_prefix}{frac_str}")
        else:
            self._edit.setText(f"{integer}.{frac_str}")
        self._edit.raise_()
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _close_editor(self):
        self._edit.hide()
        self._editing = False

    def _on_edit_committed(self):
        raw = self._edit.text().strip()
        parsed = self._parse_metric_input(raw)
        if parsed is not None:
            self.set_value(parsed)
            self.valueChanged.emit(self.value)
        else:
            # Try parsing as a plain float (assumed in current prefix)
            try:
                m = float(raw)
                # Treat as mantissa in current prefix
                val = m * self._prefix_wheel.multiplier
                self.set_value(val)
                self.valueChanged.emit(self.value)
            except ValueError:
                pass  # Invalid input — do nothing
        self._close_editor()

    def _parse_metric_input(self, text: str) -> float | None:
        """Parse e.g. '1k1' → 1100.0, '4u7' → 4.7e-6.  Returns absolute value or None."""
        match = _METRIC_RE.match(text)
        if not match:
            return None
        integer_part = match.group(1) or "0"
        prefix_char = match.group(2)
        frac = match.group(3)
        mantissa = float(f"{integer_part}.{frac}") if frac else float(integer_part)
        key = prefix_char if prefix_char == "M" else prefix_char.lower()
        # Normalise µ typed as u
        if key == "u":
            key = "u"
        mult = _TYPED_PREFIXES.get(key)
        if mult is None:
            return None
        return mantissa * mult

    def eventFilter(self, obj, event):
        """Close the inline editor on Escape or focus loss."""
        if obj is self._edit:
            if (
                event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self._close_editor()
                return True
            if event.type() == QEvent.Type.FocusOut:
                # Commit on focus loss
                if self._editing:
                    self._on_edit_committed()
                return False
        return super().eventFilter(obj, event)
