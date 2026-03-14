"""
Digilent Dialog — Qt6 front-end for Analog Discovery 2.

Provides a full-featured GUI for digital pattern generation with real-time
waveform preview, scope acquisition, and cross-trigger support.  Wraps the
Qt-free ``devices/digilent.py`` driver using the project's standard patterns:
``ThreadPoolExecutor`` background polling, ``_PollSignals`` for cross-thread
communication, and ``BasicSlider`` for feedback-loop-safe controls.

Widgets:
- ``_ConnectionWidget``: Device discovery, selection, and connect/disconnect controls.
- ``_DigitalChannelWidget``: Controls for one digital output channel.
- ``_ChannelSettingsPanel``: Scrollable panel containing digital channel widgets + Add button.
- ``_WaveformPreviewWidget``: Custom-painted waveform display showing the programmed digital patterns.
- (Planned) ``_ScopeDisplayWidget``: Custom-painted scope display showing acquired waveforms.
- (Planned) Trigger configuration panel with support for all trigger sources and types.

"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QObject
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
    QWheelEvent,
    QMouseEvent,
    QPaintEvent,
    QResizeEvent,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from devices.digilent import (
    Digilent,
    DigitalChannelConfig,
    PatternState,
    ScopeAcquisition,
    ScopeChannelConfig,
    ScopeThresholdTrigger,
    WavegenChannelConfig,
    enumerate_devices,
    TRIGSRC_NONE,
    TRIGSRC_PC,
    TRIGSRC_ANALOG_IN,
    TRIGSRC_DIGITAL_IN,
    TRIGSRC_EXTERNAL_1,
    TRIGSRC_EXTERNAL_2,
    WAVEGEN_SINE,
)
from dialogs.controls.basic_slider import BasicSlider
from dialogs.controls.engineering_slider import (
    EngineeringSlider,
    SI_FREQ_PREFIXES,
    SI_TIME_PREFIXES,
)
from resources.style_manager import get_style_manager

SETTINGS_PATH = Path(__file__).parent.parent / "settings" / "settings.json"

# Channel colors (matching plan §3.2)
CHANNEL_COLORS = [
    "#4ea1ff",  # CH0 blue (accent)
    "#ff6b6b",  # CH1 red
    "#4ecdc4",  # CH2 teal
    "#ffe66d",  # CH3 yellow
    "#c084fc",  # CH4 purple
    "#fb923c",  # CH5 orange
    "#34d399",  # CH6 emerald
    "#f472b6",  # CH7 pink
]

TRIGGER_SOURCES = [
    ("None (Free Run)", TRIGSRC_NONE),
    ("Software (PC)", TRIGSRC_PC),
    ("Analog In", TRIGSRC_ANALOG_IN),
    ("Digital In", TRIGSRC_DIGITAL_IN),
    ("External 1", TRIGSRC_EXTERNAL_1),
    ("External 2", TRIGSRC_EXTERNAL_2),
]


def _channel_color(index: int) -> QColor:
    """Return a color for channel *index*, generating algorithmically beyond 8."""
    if index < len(CHANNEL_COLORS):
        return QColor(CHANNEL_COLORS[index])
    hue = (index * 137) % 360  # golden-angle spread
    return QColor.fromHsl(hue, 200, 160)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _load_settings() -> Dict[str, Any]:
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: Dict[str, Any]) -> None:
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def _digilent_settings() -> Dict[str, Any]:
    return _load_settings().get("digilent", {})


def _format_time(seconds: float) -> str:
    """Format a time value with appropriate SI unit."""
    s = abs(seconds)
    if s == 0:
        return "0"
    elif s < 1e-6:
        return f"{seconds * 1e9:.1f} ns"
    elif s < 1e-3:
        return f"{seconds * 1e6:.1f} \u00b5s"
    elif s < 1.0:
        return f"{seconds * 1e3:.2f} ms"
    else:
        return f"{seconds:.3f} s"


def _format_freq(hz: float) -> str:
    if hz == 0:
        return "0 Hz"
    elif hz >= 1e6:
        return f"{hz / 1e6:.2f} MHz"
    elif hz >= 1e3:
        return f"{hz / 1e3:.2f} kHz"
    else:
        return f"{hz:.1f} Hz"


# ---------------------------------------------------------------------------
# Cross-thread signal carrier
# ---------------------------------------------------------------------------


class _PollSignals(QObject):
    """Carrier for background → main-thread signals."""

    pattern_status = pyqtSignal()
    scope_data = pyqtSignal(int)
    connection_changed = pyqtSignal(bool)
    error = pyqtSignal(str)


# ---------------------------------------------------------------------------
# Connection widget
# ---------------------------------------------------------------------------


class _ConnectionWidget(QWidget):
    """Device discovery, selection, and connect/disconnect controls."""

    connected = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._devices: List[Dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        layout.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(220)
        layout.addWidget(self._device_combo, stretch=1)

        self._refresh_btn = QToolButton()
        self._refresh_btn.setText("\u21bb")
        self._refresh_btn.setToolTip("Refresh device list")
        self._refresh_btn.clicked.connect(self.refresh_devices)
        layout.addWidget(self._refresh_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedWidth(100)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self._connect_btn)

        self._status_label = QLabel("\u25cf Disconnected")
        self._status_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self._status_label)

    def refresh_devices(self) -> None:
        print("[DigilentDialog] refresh_devices called")
        self._device_combo.clear()
        try:
            self._devices = enumerate_devices()
            print(
                f"[DigilentDialog] enumerate_devices returned {len(self._devices)} device(s): {self._devices}"
            )
        except Exception as e:
            print(f"[DigilentDialog] enumerate_devices exception: {e}")
            self._devices = []

        if not self._devices:
            self._device_combo.addItem("No devices found")
            self._connect_btn.setEnabled(False)
            return

        self._connect_btn.setEnabled(True)
        last_serial = _digilent_settings().get("last_device_serial", "")
        select_idx = 0
        for i, dev in enumerate(self._devices):
            label = f"{dev['name']} \u2014 SN:{dev['serial']}"
            self._device_combo.addItem(label, dev["index"])
            if dev["serial"] == last_serial:
                select_idx = i
        self._device_combo.setCurrentIndex(select_idx)

    def _on_connect_clicked(self) -> None:
        print("[DigilentDialog] _on_connect_clicked fired")
        self._connect_btn.setEnabled(False)  # prevent double-click
        self.connected.emit(True)

    def selected_device_index(self) -> int:
        data = self._device_combo.currentData()
        return data if data is not None else -1

    def selected_serial(self) -> str:
        idx = self._device_combo.currentIndex()
        if 0 <= idx < len(self._devices):
            return self._devices[idx].get("serial", "")
        return ""

    def set_connected(self, is_connected: bool) -> None:
        self._connect_btn.setEnabled(True)
        if is_connected:
            self._status_label.setText("\u25cf Connected")
            self._status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
            self._connect_btn.setText("Disconnect")
        else:
            self._status_label.setText("\u25cf Disconnected")
            self._status_label.setStyleSheet("color: #888; font-weight: bold;")
            self._connect_btn.setText("Connect")


# ---------------------------------------------------------------------------
# Digital channel widget
# ---------------------------------------------------------------------------


class _DigitalChannelWidget(QFrame):
    """Controls for one digital output channel."""

    configChanged = pyqtSignal(int)

    def __init__(
        self,
        channel: int,
        config: DigitalChannelConfig,
        name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._channel = channel
        self._color = _channel_color(channel)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui(config, name)

    def _build_ui(self, config: DigitalChannelConfig, name: str) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 6, 8, 6)
        main.setSpacing(4)

        # -- Header row
        header = QHBoxLayout()
        # Color swatch
        swatch = QWidget()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(
            f"background-color: {self._color.name()}; border-radius: 2px;"
        )
        header.addWidget(swatch)

        # Channel number (non-editable, bold) with color swatch
        ch_label = QLabel(f"CH{self._channel}", parent=self)
        # set color to match swatch, but darker for contrast
        ch_label.setStyleSheet(f"font-weight: bold; color: {self._color.name()};")
        header.addWidget(ch_label)

        # Channel name (editable)
        self._name_edit = QLineEdit(name if name else f"CH{self._channel}", parent=self)
        self._name_edit.setMaximumWidth(140)
        self._name_edit.setStyleSheet("font-weight: bold;")
        self._name_edit.editingFinished.connect(self._emit_changed)
        header.addWidget(self._name_edit)

        header.addStretch()

        self._enable_btn = QPushButton("ON" if config.enabled else "OFF")
        self._enable_btn.setCheckable(True)
        self._enable_btn.setChecked(config.enabled)
        self._enable_btn.setFixedWidth(52)
        self._enable_btn.toggled.connect(self._on_enable_toggled)
        self._style_enable_btn(config.enabled)
        header.addWidget(self._enable_btn)

        self._remove_btn = QToolButton()
        self._remove_btn.setText("\u00d7")
        self._remove_btn.setToolTip("Remove channel")
        header.addWidget(self._remove_btn)
        main.addLayout(header)

        # -- Frequency slider
        p_row = QHBoxLayout()
        p_row.addWidget(QLabel("  Freq"))
        init_freq = 1.0 / config.period if config.period > 0 else 1000.0
        self._freq_slider = EngineeringSlider(
            SI_FREQ_PREFIXES,
            unit="Hz",
            default=init_freq,
        )
        self._freq_slider.valueChanged.connect(self._on_param_changed)
        self._freq_slider.valueChanged.connect(self._on_freq_changed)
        p_row.addWidget(self._freq_slider, stretch=1)
        self._period_label = QLabel()
        self._period_label.setMinimumWidth(90)
        self._period_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._period_label.setStyleSheet("font-family: monospace; color: #888;")
        p_row.addWidget(self._period_label)
        main.addLayout(p_row)

        # -- Pulse width slider
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("    PW"))
        init_pw = config.period * config.duty_cycle
        self._pw_slider = EngineeringSlider(
            SI_TIME_PREFIXES,
            unit="s",
            default=init_pw,
            max_value=config.period if config.period > 0 else 1.0,
        )
        self._pw_slider.valueChanged.connect(self._on_param_changed)
        d_row.addWidget(self._pw_slider, stretch=1)
        self._duty_label = QLabel()
        self._duty_label.setMinimumWidth(90)
        self._duty_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._duty_label.setStyleSheet("font-family: monospace; color: #888;")
        d_row.addWidget(self._duty_label)
        main.addLayout(d_row)

        # -- Delay slider
        dl_row = QHBoxLayout()
        dl_row.addWidget(QLabel("Delay"))
        self._delay_slider = EngineeringSlider(
            SI_TIME_PREFIXES,
            unit="s",
            default=config.delay,
        )
        self._delay_slider.valueChanged.connect(self._on_param_changed)
        dl_row.addWidget(self._delay_slider, stretch=1)
        main.addLayout(dl_row)

        # -- Bottom row: pulse count + idle
        bot = QHBoxLayout()
        bot.addWidget(QLabel("Pulses"))
        self._pulse_spin = QSpinBox()
        self._pulse_spin.setRange(0, 1_000_000)
        self._pulse_spin.setSpecialValueText("Continuous")
        self._pulse_spin.setValue(config.pulse_count)
        self._pulse_spin.valueChanged.connect(self._on_param_changed)
        bot.addWidget(self._pulse_spin)

        bot.addSpacing(16)
        bot.addWidget(QLabel("Idle"))
        self._idle_combo = QComboBox()
        self._idle_combo.addItems(["LOW", "HIGH"])
        self._idle_combo.setCurrentIndex(1 if config.idle_state else 0)
        self._idle_combo.currentIndexChanged.connect(self._on_param_changed)
        bot.addWidget(self._idle_combo)
        bot.addStretch()
        main.addLayout(bot)

        self._update_readouts()

    # -- Accessors --

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def remove_button(self) -> QToolButton:
        return self._remove_btn

    def channel_name(self) -> str:
        return self._name_edit.text()

    def get_config(self) -> DigitalChannelConfig:
        freq = self._freq_slider.value
        period = 1.0 / freq if freq > 0 else 1.0
        pw = self._pw_slider.value
        duty = max(1e-9, min(0.99, pw / period)) if period > 0 else 0.5
        return DigitalChannelConfig(
            channel=self._channel,
            enabled=self._enable_btn.isChecked(),
            period=period,
            duty_cycle=duty,
            delay=self._delay_slider.value,
            pulse_count=self._pulse_spin.value(),
            idle_state=self._idle_combo.currentIndex() == 1,
        )

    def set_config(self, config: DigitalChannelConfig) -> None:
        self._freq_slider.set_value(
            1.0 / config.period if config.period > 0 else 1000.0
        )
        self._pw_slider.set_value(config.period * config.duty_cycle)
        self._delay_slider.set_value(config.delay)
        self._pulse_spin.setValue(config.pulse_count)
        self._idle_combo.setCurrentIndex(1 if config.idle_state else 0)
        self._enable_btn.setChecked(config.enabled)
        self._style_enable_btn(config.enabled)
        self._update_readouts()

    # -- Internal --

    def _on_enable_toggled(self, on: bool) -> None:
        self._style_enable_btn(on)
        self._emit_changed()

    def _style_enable_btn(self, on: bool) -> None:
        if on:
            self._enable_btn.setText("ON")
            self._enable_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; "
                "border-radius: 4px; padding: 2px 8px; font-weight: bold; }"
            )
        else:
            self._enable_btn.setText("OFF")
            self._enable_btn.setStyleSheet(
                "QPushButton { background-color: #555; color: #ccc; "
                "border-radius: 4px; padding: 2px 8px; }"
            )

    def _on_freq_changed(self, freq: float) -> None:
        """Update pulse-width max to the period (1/freq)."""
        if freq > 0:
            self._pw_slider.max = 1.0 / freq

    def _on_param_changed(self, _=None) -> None:
        self._update_readouts()
        self._emit_changed()

    def _update_readouts(self) -> None:
        freq = self._freq_slider.value
        period = 1.0 / freq if freq > 0 else 1.0
        pw = self._pw_slider.value
        duty = pw / period if period > 0 else 0.5
        self._period_label.setText(f"({_format_time(period)})")
        self._duty_label.setText(f"({duty * 100:.1f}% duty)")

    def _emit_changed(self) -> None:
        self.configChanged.emit(self._channel)


# ---------------------------------------------------------------------------
# Channel settings panel (scrollable list of channel widgets)
# ---------------------------------------------------------------------------


class _ChannelSettingsPanel(QWidget):
    """Scrollable panel containing digital channel widgets + Add button."""

    configChanged = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._channel_widgets: List[_DigitalChannelWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll)

        self._add_btn = QPushButton("+ Add Channel")
        self._add_btn.clicked.connect(self._on_add_channel)
        outer.addWidget(self._add_btn)

    def add_channel(
        self, channel: int, config: DigitalChannelConfig, name: str = ""
    ) -> _DigitalChannelWidget:
        w = _DigitalChannelWidget(channel, config, name)
        w.configChanged.connect(self._on_config_changed)
        w.remove_button.clicked.connect(lambda: self._remove_channel(w))
        self._scroll_layout.addWidget(w)
        self._channel_widgets.append(w)
        return w

    def _remove_channel(self, widget: _DigitalChannelWidget) -> None:
        self._channel_widgets.remove(widget)
        widget.setParent(None)
        widget.deleteLater()
        self.configChanged.emit(-1)

    def _on_add_channel(self) -> None:
        used = {w.channel for w in self._channel_widgets}
        for i in range(16):
            if i not in used:
                cfg = DigitalChannelConfig(channel=i, enabled=True, period=1e-3)
                self.add_channel(i, cfg)
                self.configChanged.emit(i)
                return

    def _on_config_changed(self, channel: int) -> None:
        self.configChanged.emit(channel)

    def get_all_configs(self) -> List[DigitalChannelConfig]:
        return [w.get_config() for w in self._channel_widgets]

    def get_all_names(self) -> Dict[str, str]:
        return {str(w.channel): w.channel_name() for w in self._channel_widgets}

    def widgets(self) -> List[_DigitalChannelWidget]:
        return list(self._channel_widgets)

    def clear(self) -> None:
        for w in self._channel_widgets:
            w.setParent(None)
            w.deleteLater()
        self._channel_widgets.clear()


# ---------------------------------------------------------------------------
# Waveform preview (computed, not live)
# ---------------------------------------------------------------------------


class _WaveformPreviewWidget(QWidget):
    """Custom-painted waveform display showing the programmed digital patterns."""

    CHANNEL_HEIGHT = 40
    CHANNEL_SPACING = 8
    MARGIN_LEFT = 70
    MARGIN_RIGHT = 10
    MARGIN_TOP = 10
    MARGIN_BOTTOM = 30

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._configs: List[DigitalChannelConfig] = []
        self._channel_names: List[str] = []
        self._channel_colors: List[QColor] = []

        self._time_start: float = 0.0
        self._time_span: float = 2e-3
        self._cursor_time: Optional[float] = None

        self._dragging = False
        self._drag_start_x: float = 0
        self._drag_start_time: float = 0.0

        self._is_dark = True
        self._update_theme_colors()

        self.setMinimumSize(300, 120)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_dark_mode(self, dark: bool) -> None:
        self._is_dark = dark
        self._update_theme_colors()
        self.update()

    def _update_theme_colors(self) -> None:
        if self._is_dark:
            self._bg_color = QColor("#1a1a2e")
            self._grid_color = QColor("#2a2a3e")
            self._text_color = QColor("#e6e6e6")
            self._axis_color = QColor("#666680")
        else:
            self._bg_color = QColor("#f8f9fa")
            self._grid_color = QColor("#dee2e6")
            self._text_color = QColor("#1f2328")
            self._axis_color = QColor("#adb5bd")

    def update_channels(
        self,
        configs: List[DigitalChannelConfig],
        names: List[str],
        colors: List[QColor],
    ) -> None:
        self._configs = configs
        self._channel_names = names
        self._channel_colors = colors
        self.update()

    def fit_all(self) -> None:
        t_start, t_end = self._auto_fit_time_range()
        self._time_start = t_start
        self._time_span = t_end - t_start
        self.update()

    def _auto_fit_time_range(self) -> Tuple[float, float]:
        if not self._configs:
            return (0.0, 1e-3)
        max_time = 0.0
        for cfg in self._configs:
            if not cfg.enabled:
                continue
            if cfg.pulse_count > 0:
                end = cfg.delay + cfg.pulse_count * cfg.period
            else:
                end = cfg.delay + 3 * cfg.period
            max_time = max(max_time, end)
        if max_time <= 0:
            return (0.0, 1e-3)
        pad = max_time * 0.1
        return (0.0, max_time + pad)

    # -- Edge computation --

    def _compute_edges(
        self, config: DigitalChannelConfig, t_start: float, t_end: float
    ) -> List[Tuple[float, bool]]:
        """Return (time, is_rising) transitions in the visible window."""
        edges: List[Tuple[float, bool]] = []
        if not config.enabled:
            return edges

        period = config.period
        pw = config.pulse_width
        delay = config.delay

        if period <= 0 or pw <= 0:
            return edges

        # Maximum edges to compute
        max_edges = 10_000

        if t_start > delay:
            first_cycle = int((t_start - delay) / period)
        else:
            first_cycle = 0

        for i in range(first_cycle, first_cycle + max_edges // 2 + 1):
            if config.pulse_count > 0 and i >= config.pulse_count:
                break

            rise = delay + i * period
            fall = rise + pw

            if rise > t_end:
                break
            if rise >= t_start:
                edges.append((rise, True))
            if t_start <= fall <= t_end:
                edges.append((fall, False))

        return edges

    # -- Paint --

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Background
        p.fillRect(0, 0, w, h, self._bg_color)

        if not self._configs:
            p.setPen(QPen(self._text_color))
            p.drawText(
                QRectF(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "No channels configured",
            )
            p.end()
            return

        plot_left = self.MARGIN_LEFT
        plot_right = w - self.MARGIN_RIGHT
        plot_w = plot_right - plot_left
        plot_top = self.MARGIN_TOP
        plot_bottom = h - self.MARGIN_BOTTOM

        t0 = self._time_start
        t_span = self._time_span
        if t_span <= 0:
            t_span = 1e-3

        def t_to_x(t: float) -> float:
            return plot_left + (t - t0) / t_span * plot_w

        # Grid lines
        self._draw_grid(p, plot_left, plot_right, plot_top, plot_bottom, t0, t_span)

        # Per-channel waveform
        enabled = [c for c in self._configs if c.enabled]
        n_ch = len(enabled)
        if n_ch == 0:
            p.setPen(QPen(self._text_color))
            p.drawText(
                QRectF(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter,
                "All channels disabled",
            )
            p.end()
            return

        available_h = plot_bottom - plot_top
        row_h = min(
            self.CHANNEL_HEIGHT,
            (available_h - (n_ch - 1) * self.CHANNEL_SPACING) / max(n_ch, 1),
        )
        row_h = max(20, row_h)

        for idx, cfg in enumerate(enabled):
            ci = self._configs.index(cfg)
            color = (
                self._channel_colors[ci]
                if ci < len(self._channel_colors)
                else _channel_color(ci)
            )
            name = (
                self._channel_names[ci]
                if ci < len(self._channel_names)
                else f"CH {cfg.channel}"
            )

            y_top = plot_top + idx * (row_h + self.CHANNEL_SPACING)
            y_bot = y_top + row_h
            y_high = y_top + 4
            y_low = y_bot - 4

            # Channel label
            p.setPen(QPen(color))
            font = p.font()
            font.setPointSize(8)
            p.setFont(font)
            p.drawText(
                QRectF(4, y_top, plot_left - 8, row_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                name,
            )

            # Baseline
            pen = QPen(self._grid_color)
            pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawLine(QPointF(plot_left, y_low), QPointF(plot_right, y_low))

            # Edges
            edges = self._compute_edges(cfg, t0, t0 + t_span)

            # Determine initial state at t0
            if cfg.delay > t0:
                state = cfg.idle_state
            elif edges and edges[0][1]:
                state = cfg.idle_state
            else:
                state = not cfg.idle_state

            fill_color = QColor(color)
            fill_color.setAlpha(80)
            edge_pen = QPen(color, 1.5)

            prev_x = plot_left
            for t_edge, is_rising in edges:
                x = t_to_x(t_edge)
                x = max(plot_left, min(x, plot_right))

                # Draw segment from prev_x to x at current state
                if state:
                    p.fillRect(
                        QRectF(prev_x, y_high, x - prev_x, y_low - y_high), fill_color
                    )
                    p.setPen(edge_pen)
                    p.drawLine(QPointF(prev_x, y_high), QPointF(x, y_high))
                else:
                    p.setPen(edge_pen)
                    p.drawLine(QPointF(prev_x, y_low), QPointF(x, y_low))

                # Transition line
                p.setPen(edge_pen)
                p.drawLine(QPointF(x, y_high), QPointF(x, y_low))

                state = is_rising
                prev_x = x

            # Draw remaining segment to right edge
            if state:
                p.fillRect(
                    QRectF(prev_x, y_high, plot_right - prev_x, y_low - y_high),
                    fill_color,
                )
                p.setPen(edge_pen)
                p.drawLine(QPointF(prev_x, y_high), QPointF(plot_right, y_high))
            else:
                p.setPen(edge_pen)
                p.drawLine(QPointF(prev_x, y_low), QPointF(plot_right, y_low))

        # Time axis
        self._draw_time_axis(p, plot_left, plot_right, plot_bottom, t0, t_span)

        # Cursor
        if self._cursor_time is not None:
            cx = t_to_x(self._cursor_time)
            if plot_left <= cx <= plot_right:
                pen = QPen(QColor("#ffffff" if self._is_dark else "#333333"), 1)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawLine(QPointF(cx, plot_top), QPointF(cx, plot_bottom))
                # Time readout
                p.setPen(QPen(self._text_color))
                font = p.font()
                font.setPointSize(7)
                p.setFont(font)
                p.drawText(
                    QPointF(cx + 4, plot_top + 10), _format_time(self._cursor_time)
                )

        p.end()

    def _draw_grid(
        self,
        p: QPainter,
        left: float,
        right: float,
        top: float,
        bottom: float,
        t0: float,
        t_span: float,
    ) -> None:
        pen = QPen(self._grid_color)
        pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)

        # Compute grid spacing
        raw_step = t_span / 6
        magnitude = 10 ** math.floor(math.log10(max(raw_step, 1e-15)))
        nice = [1, 2, 5, 10]
        step = magnitude * min(nice, key=lambda n: abs(n * magnitude - raw_step))

        t = math.ceil(t0 / step) * step
        while t <= t0 + t_span:
            x = left + (t - t0) / t_span * (right - left)
            if left <= x <= right:
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
            t += step

    def _draw_time_axis(
        self,
        p: QPainter,
        left: float,
        right: float,
        y: float,
        t0: float,
        t_span: float,
    ) -> None:
        p.setPen(QPen(self._axis_color))
        p.drawLine(QPointF(left, y), QPointF(right, y))

        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        p.setPen(QPen(self._text_color))

        raw_step = t_span / 6
        magnitude = 10 ** math.floor(math.log10(max(raw_step, 1e-15)))
        nice = [1, 2, 5, 10]
        step = magnitude * min(nice, key=lambda n: abs(n * magnitude - raw_step))

        t = math.ceil(t0 / step) * step
        while t <= t0 + t_span:
            x = left + (t - t0) / t_span * (right - left)
            if left <= x <= right:
                p.drawLine(QPointF(x, y), QPointF(x, y + 4))
                p.drawText(QPointF(x - 20, y + 16), _format_time(t))
            t += step

    # -- Interaction --

    def wheelEvent(self, ev: QWheelEvent) -> None:
        delta = ev.angleDelta().y()
        factor = 0.8 if delta > 0 else 1.25
        # Zoom centered on mouse
        pos_x = ev.position().x()
        plot_w = self.width() - self.MARGIN_LEFT - self.MARGIN_RIGHT
        if plot_w <= 0:
            return
        frac = (pos_x - self.MARGIN_LEFT) / plot_w
        frac = max(0.0, min(1.0, frac))
        t_mouse = self._time_start + frac * self._time_span
        new_span = max(1e-9, self._time_span * factor)
        self._time_start = t_mouse - frac * new_span
        self._time_span = new_span
        self.update()

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_x = ev.position().x()
            self._drag_start_time = self._time_start

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        pos_x = ev.position().x()
        plot_w = self.width() - self.MARGIN_LEFT - self.MARGIN_RIGHT
        if self._dragging and plot_w > 0:
            dx = pos_x - self._drag_start_x
            dt = -dx / plot_w * self._time_span
            self._time_start = self._drag_start_time + dt
            self.update()
        else:
            # Cursor tracking
            if plot_w > 0:
                frac = (pos_x - self.MARGIN_LEFT) / plot_w
                self._cursor_time = self._time_start + frac * self._time_span
                self.update()

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._dragging = False

    def mouseDoubleClickEvent(self, ev: QMouseEvent) -> None:
        self.fit_all()

    def leaveEvent(self, ev) -> None:
        self._cursor_time = None
        self.update()


# ---------------------------------------------------------------------------
# Global controls (Start / Stop / Trigger)
# ---------------------------------------------------------------------------


class _GlobalControlsWidget(QWidget):
    """Start/Stop/Trigger controls and trigger source selection."""

    startRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    restartRequested = pyqtSignal()
    triggerRequested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Trigger source
        layout.addWidget(QLabel("Trigger:"))
        self._trigger_combo = QComboBox()
        for label, _ in TRIGGER_SOURCES:
            self._trigger_combo.addItem(label)
        layout.addWidget(self._trigger_combo)

        layout.addSpacing(12)

        # Repeat count
        layout.addWidget(QLabel("Repeat:"))
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(0, 1_000_000)
        self._repeat_spin.setSpecialValueText("Infinite")
        self._repeat_spin.setValue(0)
        layout.addWidget(self._repeat_spin)

        layout.addStretch()

        # Action buttons — single toggle for Start/Stop
        self._running = False
        self._toggle_btn = QPushButton("\u25b6 Start")
        self._toggle_btn.setFixedWidth(100)
        self._style_toggle(False)
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self._toggle_btn)

        self._restart_btn = QPushButton("\u21bb Restart")
        self._restart_btn.setEnabled(False)
        self._restart_btn.clicked.connect(self.restartRequested.emit)
        layout.addWidget(self._restart_btn)

        self._trigger_btn = QPushButton("Trigger")
        self._trigger_btn.setEnabled(False)
        self._trigger_btn.setToolTip("Send software trigger (T)")
        self._trigger_btn.clicked.connect(self.triggerRequested.emit)
        layout.addWidget(self._trigger_btn)

    @property
    def trigger_source_index(self) -> int:
        return TRIGGER_SOURCES[self._trigger_combo.currentIndex()][1]

    @property
    def repeat_count(self) -> int:
        return self._repeat_spin.value()

    def _on_toggle_clicked(self) -> None:
        if self._running:
            self.stopRequested.emit()
        else:
            self.startRequested.emit()

    def _style_toggle(self, running: bool) -> None:
        if running:
            self._toggle_btn.setText("\u25a0 Stop")
            self._toggle_btn.setStyleSheet(
                "QPushButton { background-color: #c62828; color: white; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold; }"
            )
        else:
            self._toggle_btn.setText("\u25b6 Start")
            self._toggle_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold; }"
            )

    def update_running(self, running: bool) -> None:
        self._running = running
        self._style_toggle(running)
        self._restart_btn.setEnabled(running)
        is_pc_trigger = self._trigger_combo.currentIndex() == 1  # Software (PC)
        self._trigger_btn.setEnabled(running and is_pc_trigger)


# ---------------------------------------------------------------------------
# Scope panel (collapsible)
# ---------------------------------------------------------------------------


class _ScopeTraceWidget(QWidget):
    """Custom-painted scope trace display."""

    TRACE_COLORS = [QColor("#FFD700"), QColor("#00CED1")]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._traces: Dict[int, ScopeAcquisition] = {}
        self._ranges: Dict[int, float] = {0: 5.0, 1: 5.0}
        self._is_dark = True
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_dark_mode(self, dark: bool) -> None:
        self._is_dark = dark
        self.update()

    def update_trace(self, channel: int, acq: ScopeAcquisition) -> None:
        self._traces[channel] = acq
        self.update()

    def set_range(self, channel: int, range_v: float) -> None:
        self._ranges[channel] = range_v
        self.update()

    def clear(self) -> None:
        self._traces.clear()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        bg = QColor("#1a1a2e") if self._is_dark else QColor("#f8f9fa")
        p.fillRect(0, 0, w, h, bg)

        margin = 40
        plot_w = w - 2 * margin
        plot_h = h - 2 * margin

        if plot_w <= 0 or plot_h <= 0:
            p.end()
            return

        # Grid
        grid_pen = QPen(QColor("#2a2a3e") if self._is_dark else QColor("#dee2e6"))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(grid_pen)
        for i in range(5):
            y = margin + i * plot_h / 4
            p.drawLine(QPointF(margin, y), QPointF(w - margin, y))
        for i in range(9):
            x = margin + i * plot_w / 8
            p.drawLine(QPointF(x, margin), QPointF(x, h - margin))

        # Traces
        for ch, acq in self._traces.items():
            if acq is None or len(acq.samples) == 0:
                continue
            color = (
                self.TRACE_COLORS[ch]
                if ch < len(self.TRACE_COLORS)
                else QColor("#ffffff")
            )
            pen = QPen(color, 1.5)
            p.setPen(pen)

            range_v = self._ranges.get(ch, 5.0)
            n = len(acq.samples)
            path = QPainterPath()

            # Subsample if many points
            step = max(1, n // (plot_w * 2))
            for i in range(0, n, step):
                x = margin + (i / n) * plot_w
                y = margin + plot_h / 2 - (acq.samples[i] / range_v) * (plot_h / 2)
                y = max(margin, min(y, h - margin))
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.drawPath(path)

        # Axis labels
        text_color = QColor("#e6e6e6") if self._is_dark else QColor("#1f2328")
        p.setPen(QPen(text_color))
        font = p.font()
        font.setPointSize(7)
        p.setFont(font)
        p.drawText(QPointF(4, margin + plot_h / 2 + 4), "0 V")

        p.end()


class _ScopePanel(QGroupBox):
    """Collapsible scope control panel."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("\u25b6 Scope Channels  (click to expand)", parent)
        self.setCheckable(True)
        self.setChecked(False)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)

        # Scope channel controls
        ch_grid = QGridLayout()
        self._scope_enables: List[QCheckBox] = []
        self._scope_ranges: List[QComboBox] = []
        self._scope_couplings: List[QComboBox] = []

        range_options = ["0.5 V", "1 V", "2 V", "5 V", "10 V", "25 V", "50 V"]
        range_values = [0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]

        for ch in range(2):
            row = ch
            cb = QCheckBox(f"CH{ch + 1}")
            ch_grid.addWidget(cb, row, 0)
            self._scope_enables.append(cb)

            ch_grid.addWidget(QLabel("Range:"), row, 1)
            range_combo = QComboBox()
            range_combo.addItems(range_options)
            range_combo.setCurrentIndex(3)  # default 5V
            ch_grid.addWidget(range_combo, row, 2)
            self._scope_ranges.append(range_combo)

            ch_grid.addWidget(QLabel("Coupling:"), row, 3)
            coup_combo = QComboBox()
            coup_combo.addItems(["DC", "AC"])
            ch_grid.addWidget(coup_combo, row, 4)
            self._scope_couplings.append(coup_combo)

        content_layout.addLayout(ch_grid)

        # Trigger controls
        trig_row = QHBoxLayout()
        trig_row.addWidget(QLabel("Trigger:"))
        self._trig_mode = QComboBox()
        self._trig_mode.addItems(["Auto", "Normal", "Single"])
        trig_row.addWidget(self._trig_mode)

        trig_row.addWidget(QLabel("Level:"))
        self._trig_level = BasicSlider(
            -25.0, 25.0, 0.0, 0.1, float_precision=1, unit="V"
        )
        trig_row.addWidget(self._trig_level, stretch=1)

        trig_row.addWidget(QLabel("Edge:"))
        self._trig_edge = QComboBox()
        self._trig_edge.addItems(["\u2197 Rising", "\u2198 Falling"])
        trig_row.addWidget(self._trig_edge)
        content_layout.addLayout(trig_row)

        # Action buttons
        scope_btn_row = QHBoxLayout()
        self._arm_btn = QPushButton("Arm Scope")
        self._arm_btn.clicked.connect(self._on_arm)
        scope_btn_row.addWidget(self._arm_btn)
        self._stop_scope_btn = QPushButton("Stop Scope")
        scope_btn_row.addWidget(self._stop_scope_btn)
        scope_btn_row.addStretch()
        content_layout.addLayout(scope_btn_row)

        # Trace display
        self._trace_widget = _ScopeTraceWidget()
        content_layout.addWidget(self._trace_widget)

        layout = QVBoxLayout(self)
        layout.addWidget(self._content)
        self._content.setVisible(False)

        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._content.setVisible(checked)
        title_prefix = "\u25bc" if checked else "\u25b6"
        self.setTitle(f"{title_prefix} Scope Channels")

    def _on_arm(self) -> None:
        pass  # Connected by dialog

    @property
    def trace_widget(self) -> _ScopeTraceWidget:
        return self._trace_widget

    @property
    def arm_button(self) -> QPushButton:
        return self._arm_btn

    @property
    def stop_button(self) -> QPushButton:
        return self._stop_scope_btn

    RANGE_VALUES = [0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]

    def get_scope_configs(self) -> List[ScopeChannelConfig]:
        configs = []
        for ch in range(2):
            configs.append(
                ScopeChannelConfig(
                    channel=ch,
                    enabled=self._scope_enables[ch].isChecked(),
                    range_volts=self.RANGE_VALUES[
                        self._scope_ranges[ch].currentIndex()
                    ],
                    coupling=(
                        "AC" if self._scope_couplings[ch].currentIndex() == 1 else "DC"
                    ),
                )
            )
        return configs

    def get_trigger_config(self) -> dict:
        return {
            "mode": self._trig_mode.currentText().lower(),
            "level": self._trig_level.value,
            "rising": self._trig_edge.currentIndex() == 0,
        }


# ---------------------------------------------------------------------------
# Wavegen panel
# ---------------------------------------------------------------------------


class _WavegenPanel(QWidget):
    """Always-visible 10 MHz sine-wave toggle on W1.

    If `set_amplitude` is provided, the amplitude slider is hidden and the wavegen is fixed at that amplitude.
    """

    startRequested = pyqtSignal(object)  # WavegenChannelConfig
    stopRequested = pyqtSignal(int)  # channel index

    def __init__(self, parent: Optional[QWidget] = None, set_amplitude: float = 2.0):
        super().__init__(parent)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        # left align
        row.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Color swatch
        swatch = QWidget()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet("background-color: #f59e0b; border-radius: 2px;")
        row.addWidget(swatch)
        row.addWidget(QLabel("W1"))
        lbl = QLabel("10 MHz Reference")
        # color border of label to match swatch
        lbl.setStyleSheet(
            "font-weight: bold; border: 1px solid #f59e0b; padding: 2px 4px; border-radius: 4px;"
        )
        row.addWidget(lbl)

        # row.addStretch()

        self._toggle_btn = QPushButton("OFF")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setFixedWidth(64)
        self._toggle_btn.toggled.connect(self._on_toggled)
        self._style_btn(False)
        row.addWidget(self._toggle_btn)

        # Amplitude slider
        self._amplitude = set_amplitude or 0.0
        if not set_amplitude:
            amp_row = QHBoxLayout()
            amp_row.addWidget(QLabel("Amplitude"))
            self._amp_slider = BasicSlider(
                1.0, 10.0, 3.0, 0.1, float_precision=1, unit="V"
            )
            self._amp_slider.valueChanged.connect(self._on_amplitude_changed)
            amp_row.addWidget(self._amp_slider, stretch=1)
            row.addLayout(amp_row)

    # -- ON/OFF --
    @property
    def amplitude(self):
        if self._amplitude:
            return self._amplitude
        return self._amp_slider.value

    def _on_toggled(self, on: bool) -> None:
        self._style_btn(on)
        if on:
            cfg = WavegenChannelConfig(
                channel=0,
                enabled=True,
                function=WAVEGEN_SINE,
                frequency=10e6,
                amplitude=self.amplitude,
            )
            self.startRequested.emit(cfg)
        else:
            self.stopRequested.emit(0)

    def _on_amplitude_changed(self, _value: float) -> None:
        """only used with amplitude slider visible"""
        if self._toggle_btn.isChecked():
            cfg = WavegenChannelConfig(
                channel=0,
                enabled=True,
                function=WAVEGEN_SINE,
                frequency=10e6,
                amplitude=self.amplitude,
            )
            self.startRequested.emit(cfg)

    def _style_btn(self, on: bool) -> None:
        if on:
            self._toggle_btn.setText("ON")
            self._toggle_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; "
                "border-radius: 4px; padding: 2px 8px; font-weight: bold; }"
            )
        else:
            self._toggle_btn.setText("OFF")
            self._toggle_btn.setStyleSheet(
                "QPushButton { background-color: #555; color: #ccc; "
                "border-radius: 4px; padding: 2px 8px; }"
            )

    def set_on(self, on: bool) -> None:
        """Programmatically set the toggle state without emitting signals."""
        self._toggle_btn.blockSignals(True)
        self._toggle_btn.setChecked(on)
        self._style_btn(on)
        self._toggle_btn.blockSignals(False)


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------


class _StatusBar(QWidget):
    """Bottom status bar showing running state, clock, elapsed time."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)

        self._state_label = QLabel("\u25cf Idle")
        self._state_label.setStyleSheet("font-weight: bold; color: #888;")
        layout.addWidget(self._state_label)

        layout.addSpacing(20)
        self._clock_label = QLabel("Clock: --")
        self._clock_label.setStyleSheet("font-family: monospace; color: #888;")
        layout.addWidget(self._clock_label)

        layout.addSpacing(20)
        self._elapsed_label = QLabel("Elapsed: --")
        self._elapsed_label.setStyleSheet("font-family: monospace; color: #888;")
        layout.addWidget(self._elapsed_label)

        layout.addStretch()

    def update_state(self, state: PatternState) -> None:
        if state.running:
            self._state_label.setText("\u25cf Running")
            self._state_label.setStyleSheet("font-weight: bold; color: #4caf50;")
            self._elapsed_label.setText(f"Elapsed: {state.elapsed_time:.1f}s")
        else:
            self._state_label.setText("\u25cf Idle")
            self._state_label.setStyleSheet("font-weight: bold; color: #888;")
            self._elapsed_label.setText("Elapsed: --")

    def set_clock(self, hz: float) -> None:
        self._clock_label.setText(f"Clock: {_format_freq(hz)}")


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class DigilentDialog(QDialog):
    """Dialog for controlling a Digilent Analog Discovery 2."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._digilent: Optional[Digilent] = None
        self._is_connected = False

        self._executor = ThreadPoolExecutor(max_workers=1)
        self._poll_signals = _PollSignals()
        self._poll_signals.pattern_status.connect(self._on_pattern_status)
        self._poll_signals.scope_data.connect(self._on_scope_data)
        self._poll_signals.connection_changed.connect(self._on_connection_changed)
        self._poll_signals.error.connect(self._on_error)
        self._poll_busy = False

        self._latest_scope_data: Dict[int, ScopeAcquisition] = {}

        self._build_ui()
        self._load_last_session()

        # Status polling timer
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._on_status_tick)
        self._status_timer.start(100)

        # Populate device list and auto-connect if a device is found
        self._connection.refresh_devices()
        if self._connection.selected_device_index() >= 0:
            self._connect()

    def _build_ui(self) -> None:
        self.setWindowTitle("Digilent Controller (disconnects on close)")
        self.setMinimumSize(800, 550)
        self.resize(1050, 700)

        root = QVBoxLayout(self)
        root.setSpacing(4)

        # Connection
        self._connection = _ConnectionWidget()
        self._connection.connected.connect(self._on_connect_toggle)
        root.addWidget(self._connection)

        # Wavegen (10 MHz reference) — always visible, right under connection
        self._wavegen_panel = _WavegenPanel()
        self._wavegen_panel.startRequested.connect(self._on_wavegen_start)
        self._wavegen_panel.stopRequested.connect(self._on_wavegen_stop)
        root.addWidget(self._wavegen_panel)

        # Splitter: channel settings | waveform preview
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._channel_panel = _ChannelSettingsPanel()
        self._channel_panel.configChanged.connect(self._on_channel_config_changed)
        self._splitter.addWidget(self._channel_panel)

        self._waveform_preview = _WaveformPreviewWidget()
        self._splitter.addWidget(self._waveform_preview)

        self._splitter.setSizes([380, 620])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, stretch=1)

        # Global controls
        self._global_controls = _GlobalControlsWidget()
        self._global_controls.startRequested.connect(self._on_start)
        self._global_controls.stopRequested.connect(self._on_stop)
        self._global_controls.restartRequested.connect(self._on_restart)
        self._global_controls.triggerRequested.connect(self._on_trigger)
        root.addWidget(self._global_controls)

        # Scope panel (collapsible)
        self._scope_panel = _ScopePanel()
        self._scope_panel.arm_button.clicked.connect(self._on_arm_scope)
        self._scope_panel.stop_button.clicked.connect(self._on_stop_scope)
        root.addWidget(self._scope_panel)

        # Preset buttons
        preset_row = QHBoxLayout()
        preset_row.addStretch()
        self._save_preset_btn = QPushButton("Save Preset")
        self._save_preset_btn.clicked.connect(self._on_save_preset)
        preset_row.addWidget(self._save_preset_btn)
        self._load_preset_btn = QPushButton("Load Preset")
        self._load_preset_btn.clicked.connect(self._on_load_preset)
        preset_row.addWidget(self._load_preset_btn)
        root.addLayout(preset_row)

        # Status bar
        self._status_bar = _StatusBar()
        root.addWidget(self._status_bar)

    # -- Connection --

    def _on_connect_toggle(self, _: bool) -> None:
        print(f"[DigilentDialog] _on_connect_toggle, is_connected={self._is_connected}")
        if self._is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        idx = self._connection.selected_device_index()
        print(f"[DigilentDialog] _connect called, selected device index={idx}")
        if idx < 0:
            print("[DigilentDialog] _connect: no device selected (idx < 0), aborting")
            return

        try:
            print(f"[DigilentDialog] creating Digilent(device_index={idx})")
            self._digilent = Digilent(device_index=idx)
            print(f"[DigilentDialog] calling Digilent.open({idx})")
            self._digilent.open(idx)
            print(
                f"[DigilentDialog] open() succeeded, hdwf={self._digilent._hdwf.value}"
            )
            self._is_connected = True
            self._connection.set_connected(True)
            self._status_bar.set_clock(self._digilent._internal_clock_hz)
            print(
                f"[DigilentDialog] connected, clock={self._digilent._internal_clock_hz} Hz"
            )

            # Save last device serial
            serial = self._connection.selected_serial()
            if serial:
                settings = _load_settings()
                settings.setdefault("digilent", {})["last_device_serial"] = serial
                _save_settings(settings)
                print(f"[DigilentDialog] saved last_device_serial={serial}")

        except Exception as e:
            print(f"[DigilentDialog] _connect exception: {e}")
            QMessageBox.critical(self, "Connection Error", str(e))
            self._digilent = None

    def _disconnect(self) -> None:
        print("[DigilentDialog] _disconnect called")
        if self._digilent:
            try:
                self._digilent.stop_all()
            except Exception as e:
                print(f"[DigilentDialog] stop_all() exception (ignored): {e}")
            self._digilent.close()
            print("[DigilentDialog] device closed")
            self._digilent = None
        self._is_connected = False
        self._connection.set_connected(False)
        self._global_controls.update_running(False)
        self._wavegen_panel.set_on(False)

    # -- Channel config changes --

    def _on_channel_config_changed(self, channel: int) -> None:
        self._refresh_waveform_preview()

        if self._digilent and self._is_connected and channel >= 0:
            widgets = self._channel_panel.widgets()
            for w in widgets:
                if w.channel == channel:
                    config = w.get_config()
                    self._executor.submit(self._apply_config_worker, config)
                    break

    def _apply_config_worker(self, config: DigitalChannelConfig) -> None:
        try:
            d = self._digilent
            if not d or not d.connected:
                return
            was_running = d.is_running
            if was_running:
                d.stop()
            d.configure_digital_channel(config)
            if was_running:
                d.start()
                self._poll_signals.pattern_status.emit()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    def _refresh_waveform_preview(self) -> None:
        configs = self._channel_panel.get_all_configs()
        names = [w.channel_name() for w in self._channel_panel.widgets()]
        colors = [_channel_color(w.channel) for w in self._channel_panel.widgets()]
        self._waveform_preview.update_channels(configs, names, colors)

    # -- Start / Stop / Trigger --

    def _on_start(self) -> None:
        if not self._digilent or not self._is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to a device first.")
            return
        self._executor.submit(self._start_worker)

    def _start_worker(self) -> None:
        try:
            d = self._digilent
            if not d:
                print("[DigilentDialog] _start_worker: no device")
                return
            print("[DigilentDialog] _start_worker: configuring channels")
            configs = self._channel_panel.get_all_configs()
            d.configure_all_digital(configs)
            d.set_trigger_source(self._global_controls.trigger_source_index)
            d.set_repeat_count(self._global_controls.repeat_count)
            print("[DigilentDialog] _start_worker: starting")
            d.start()
            self._poll_signals.pattern_status.emit()
            print("[DigilentDialog] _start_worker: started successfully")
        except Exception as e:
            print(f"[DigilentDialog] _start_worker exception: {e}")
            self._poll_signals.error.emit(str(e))

    def _on_stop(self) -> None:
        if self._digilent:
            self._executor.submit(self._stop_worker)

    def _on_restart(self) -> None:
        """Stop then start pattern generation."""
        if self._digilent and self._is_connected:
            self._executor.submit(self._restart_worker)

    def _restart_worker(self) -> None:
        try:
            if self._digilent:
                self._digilent.stop()
                self._poll_signals.pattern_status.emit()
                # Re-configure and start
                configs = self._channel_panel.get_all_configs()
                self._digilent.configure_all_digital(configs)
                self._digilent.set_trigger_source(
                    self._global_controls.trigger_source_index
                )
                self._digilent.set_repeat_count(self._global_controls.repeat_count)
                self._digilent.start()
                self._poll_signals.pattern_status.emit()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    def _stop_worker(self) -> None:
        try:
            if self._digilent:
                self._digilent.stop()
                self._poll_signals.pattern_status.emit()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    def _on_trigger(self) -> None:
        if self._digilent:
            self._executor.submit(self._trigger_worker)

    def _trigger_worker(self) -> None:
        try:
            if self._digilent:
                self._digilent.trigger()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    # -- Wavegen --

    def _on_wavegen_start(self, config: WavegenChannelConfig) -> None:
        if not self._digilent or not self._is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to a device first.")
            self._wavegen_panel.set_on(False)
            return
        self._executor.submit(self._wavegen_start_worker, config)

    def _wavegen_start_worker(self, config: WavegenChannelConfig) -> None:
        try:
            if self._digilent and self._digilent.connected:
                self._digilent.generate_wavegen(config)
                wg = self._digilent.get_wavegen_state()
                print(f"[wavegen] started: {wg}")
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    def _on_wavegen_stop(self, channel: int) -> None:
        if self._digilent and self._is_connected:
            self._executor.submit(self._wavegen_stop_worker, channel)

    def _wavegen_stop_worker(self, channel: int) -> None:
        try:
            if self._digilent and self._digilent.connected:
                self._digilent.stop_wavegen(channel)
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    # -- Scope --

    def _on_arm_scope(self) -> None:
        if not self._digilent or not self._is_connected:
            return
        self._executor.submit(self._arm_scope_worker)

    def _arm_scope_worker(self) -> None:
        try:
            d = self._digilent
            if not d:
                return
            for cfg in self._scope_panel.get_scope_configs():
                if cfg.enabled:
                    d.configure_scope_channel(cfg)

            trig = self._scope_panel.get_trigger_config()
            d.configure_scope_trigger(
                level_volts=trig["level"],
                rising=trig["rising"],
                auto_timeout=1.0 if trig["mode"] == "auto" else 0.0,
            )
            d.start_scope()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    def _on_stop_scope(self) -> None:
        if self._digilent:
            self._executor.submit(self._stop_scope_worker)

    def _stop_scope_worker(self) -> None:
        try:
            if self._digilent:
                self._digilent.stop_scope()
        except Exception as e:
            self._poll_signals.error.emit(str(e))

    # -- Background polling --

    def _on_status_tick(self) -> None:
        if self._poll_busy or not self._digilent or not self._is_connected:
            return
        self._poll_busy = True
        self._executor.submit(self._poll_worker)

    def _poll_worker(self) -> None:
        try:
            d = self._digilent
            if d and d.connected:
                _ = d.is_running
                self._poll_signals.pattern_status.emit()

                # Scope polling
                if self._scope_panel.isChecked():
                    for ch in range(2):
                        acq = d.poll_scope(ch)
                        if acq is not None:
                            self._latest_scope_data[ch] = acq
                            self._poll_signals.scope_data.emit(ch)
        except Exception as e:
            print(f"[DigilentDialog] poll_worker exception: {e}")
            self._poll_signals.error.emit(str(e))
        finally:
            self._poll_busy = False

    def _on_pattern_status(self) -> None:
        if self._digilent:
            state = self._digilent.get_pattern_state()
            self._status_bar.update_state(state)
            self._global_controls.update_running(state.running)

    def _on_scope_data(self, channel: int) -> None:
        acq = self._latest_scope_data.get(channel)
        if acq:
            self._scope_panel.trace_widget.update_trace(channel, acq)

    def _on_connection_changed(self, connected: bool) -> None:
        self._is_connected = connected
        self._connection.set_connected(connected)
        if not connected:
            self._global_controls.update_running(False)

    def _on_error(self, msg: str) -> None:
        self._status_bar._state_label.setText(f"\u25cf Error")
        self._status_bar._state_label.setStyleSheet(
            "font-weight: bold; color: #f44336;"
        )
        self._status_bar._elapsed_label.setText(msg[:60])

    # -- Presets --

    def _on_save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        settings = _load_settings()
        dig = settings.setdefault("digilent", {})
        presets = dig.setdefault("presets", {})
        presets[name] = {
            "digital_channels": [
                {
                    "channel": c.channel,
                    "enabled": c.enabled,
                    "period": c.period,
                    "duty_cycle": c.duty_cycle,
                    "delay": c.delay,
                    "pulse_count": c.pulse_count,
                    "idle_state": c.idle_state,
                }
                for c in self._channel_panel.get_all_configs()
            ],
            "channel_names": self._channel_panel.get_all_names(),
            "trigger_source": self._global_controls.trigger_source_index,
            "repeat_count": self._global_controls.repeat_count,
        }
        _save_settings(settings)

    def _on_load_preset(self) -> None:
        settings = _load_settings()
        presets = settings.get("digilent", {}).get("presets", {})
        if not presets:
            QMessageBox.information(self, "Load Preset", "No presets saved yet.")
            return
        name, ok = QInputDialog.getItem(
            self, "Load Preset", "Select preset:", list(presets.keys()), 0, False
        )
        if not ok:
            return
        self._apply_preset(presets[name])

    def _apply_preset(self, preset: dict) -> None:
        self._channel_panel.clear()
        names = preset.get("channel_names", {})
        for ch_data in preset.get("digital_channels", []):
            cfg = DigitalChannelConfig(**ch_data)
            ch_name = names.get(str(cfg.channel), f"CH {cfg.channel}")
            self._channel_panel.add_channel(cfg.channel, cfg, ch_name)
        self._refresh_waveform_preview()
        self._waveform_preview.fit_all()

    # -- Session persistence --

    def _load_last_session(self) -> None:
        settings = _load_settings()
        dig = settings.get("digilent", {})
        last = dig.get("presets", {}).get("_last_session")
        if last:
            self._apply_preset(last)
        else:
            # Default: two channels
            cfg0 = DigitalChannelConfig(
                channel=0, enabled=True, period=1e-3, duty_cycle=0.5
            )
            cfg1 = DigitalChannelConfig(
                channel=1, enabled=True, period=4e-5, duty_cycle=0.25, pulse_count=50
            )
            ch_names = dig.get("channel_names", {})
            self._channel_panel.add_channel(0, cfg0, ch_names.get("0", "Trigger"))
            self._channel_panel.add_channel(1, cfg1, ch_names.get("1", "Burst"))
            self._refresh_waveform_preview()
            self._waveform_preview.fit_all()

    def _save_session(self) -> None:
        settings = _load_settings()
        dig = settings.setdefault("digilent", {})
        presets = dig.setdefault("presets", {})
        presets["_last_session"] = {
            "digital_channels": [
                {
                    "channel": c.channel,
                    "enabled": c.enabled,
                    "period": c.period,
                    "duty_cycle": c.duty_cycle,
                    "delay": c.delay,
                    "pulse_count": c.pulse_count,
                    "idle_state": c.idle_state,
                }
                for c in self._channel_panel.get_all_configs()
            ],
            "channel_names": self._channel_panel.get_all_names(),
        }
        dig["channel_names"] = self._channel_panel.get_all_names()
        _save_settings(settings)

    # -- Theme --

    def apply_theme(self) -> None:
        sm = get_style_manager()
        is_dark = sm._resolve_theme() == "dark"
        self._waveform_preview.set_dark_mode(is_dark)
        self._scope_panel.trace_widget.set_dark_mode(is_dark)

    # -- Lifecycle --

    def cleanup(self) -> None:
        """Release device resources. Called before close."""
        self._status_timer.stop()
        self._save_session()
        self._disconnect()
        self._executor.shutdown(wait=False)

    def closeEvent(self, ev) -> None:
        self.cleanup()
        super().closeEvent(ev)

    # -- Keyboard shortcuts --

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        if key == Qt.Key.Key_Space:
            if self._digilent and self._digilent.is_running:
                self._on_stop()
            else:
                self._on_start()
        elif key == Qt.Key.Key_T:
            self._on_trigger()
        elif key == Qt.Key.Key_F:
            self._waveform_preview.fit_all()
        else:
            super().keyPressEvent(ev)
