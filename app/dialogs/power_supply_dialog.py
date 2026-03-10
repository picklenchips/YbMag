"""
Power Supply Dialog — Qt6 front-end for DC power supplies.

Supports Rigol DP832A (USB-TMC) and HP 6653A (Prologix GPIB-USB).
Provides a collapsible panel per supply, with per-channel controls
(voltage slider, current slider, output toggle, live readback).
Polls measurement data in a background thread to keep the GUI responsive.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QCheckBox,
    QGroupBox,
    QSizePolicy,
    QToolButton,
    QGridLayout,
)

# Import from project root — works because app.py adds the parent to
from devices.power_supply_manager import PowerSupplyManager
from dialogs.controls.basic_slider import BasicSlider
from resources.style_manager import get_style_manager

SETTINGS_PATH = Path(__file__).parent.parent / "settings" / "settings.json"

# ---------------------------------------------------------------------------
# Helper: Settings loader
# ---------------------------------------------------------------------------


def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_power_supply_poll_interval_ms(default_ms: int = 350) -> int:
    """Get poll interval for power supply background updates from settings."""
    settings = _load_settings()

    # Prefer dedicated top-level key; allow nested fallback for compatibility.
    raw = settings.get(
        "power_supply_poll_interval_ms",
        settings.get("power_supplies", {}).get("poll_interval_ms", default_ms),
    )

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default_ms

    # Avoid pathological values that can starve the UI/event loop.
    return max(50, value)


def _find_supply_config(supply) -> tuple[str, Dict[str, Any]]:
    """Look up a supply's config by serial, then by resource_name.

    Returns (lookup_key, config_dict).  config_dict is {} if not found.
    """
    settings = _load_settings()
    supplies_config = settings.get("power_supplies", {})

    serial = supply.serial or supply.resource_name
    if serial in supplies_config:
        return serial, supplies_config[serial]
    # Fallback: try resource_name (useful for Prologix ASRL ports)
    res = supply.resource_name
    if res in supplies_config:
        return res, supplies_config[res]
    return serial, {}


def _get_supply_display_name(supply) -> str:
    """Get display name for a supply from settings or fall back to defaults."""
    key, config = _find_supply_config(supply)

    if config:
        supply_name = config.get("name", "").upper() if config.get("name") else key
        model = config.get("model", supply.model)
        return f"{supply_name} — {model} — {key}"

    return f"{key} ({supply.model})"


def _get_channel_display_name(supply, channel_num: int) -> str:
    """Get display name for a channel from settings or fall back to defaults."""
    _key, config = _find_supply_config(supply)

    if config:
        channels_config = config.get("channels", {})
        ch_key = str(channel_num)
        if ch_key in channels_config:
            return channels_config[ch_key].get("name", f"CH{channel_num}")

    return f"CH{channel_num}"


# ---------------------------------------------------------------------------
# Helper: poll results carrier (thread → main)
# ---------------------------------------------------------------------------


class _PollSignals(QObject):
    """Carrier for cross-thread signal."""

    finished = pyqtSignal()


# ---------------------------------------------------------------------------
# Per-channel widget
# ---------------------------------------------------------------------------


class ChannelControlWidget(QWidget):
    """Controls for a single channel: V slider, I slider, output toggle, readback."""

    def __init__(
        self,
        supply,
        ch_info,
        channel_name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._supply = supply
        self._ch = ch_info.number
        self._ch_info = ch_info
        self._channel_name = channel_name or f"CH{ch_info.number}"

        self._build_ui(ch_info)

    def _build_ui(self, ch) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 4, 8, 4)

        # -- header row: "CH1 — Channel Name" label + output toggle
        header = QHBoxLayout()
        ch_label = QLabel(f"{self._channel_name}")
        ch_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(ch_label)
        header.addStretch()

        self.output_btn = QPushButton("OFF")
        self.output_btn.setCheckable(True)
        self.output_btn.setChecked(ch.output_enabled)
        self._style_output_btn(ch.output_enabled)
        self.output_btn.setFixedWidth(52)
        self.output_btn.toggled.connect(self._on_output_toggled)
        header.addWidget(self.output_btn)
        main.addLayout(header)

        # -- voltage row
        v_row = QHBoxLayout()
        v_row.addWidget(QLabel("Voltage"))
        v_step = 0.01 if ch.max_voltage <= 6 else 0.1
        self.v_slider = BasicSlider(
            0.0,
            ch.max_voltage,
            ch.set_voltage,
            v_step,
            float_precision=3,
            unit="V",
            parent=self,
        )
        self.v_slider.valueChanged.connect(self._on_voltage_changed)
        v_row.addWidget(self.v_slider, stretch=1)
        self.v_meas = QLabel(f"{ch.meas_voltage:.4f} V")
        self.v_meas.setMinimumWidth(80)
        self.v_meas.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.v_meas.setStyleSheet("font-family: monospace;")
        v_row.addWidget(self.v_meas)
        main.addLayout(v_row)

        # -- current row
        i_row = QHBoxLayout()
        i_row.addWidget(QLabel("Current"))
        i_step = 0.001 if ch.max_current <= 1 else 0.01
        self.i_slider = BasicSlider(
            0.0,
            ch.max_current,
            ch.set_current,
            i_step,
            float_precision=3,
            unit="A",
            parent=self,
        )
        self.i_slider.valueChanged.connect(self._on_current_changed)
        i_row.addWidget(self.i_slider, stretch=1)
        self.i_meas = QLabel(f"{ch.meas_current:.4f} A")
        self.i_meas.setMinimumWidth(80)
        self.i_meas.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.i_meas.setStyleSheet("font-family: monospace;")
        i_row.addWidget(self.i_meas)
        main.addLayout(i_row)

        # -- power readback
        p_row = QHBoxLayout()
        p_row.addWidget(QLabel("Power"))
        p_row.addStretch()
        self.p_meas = QLabel(f"{ch.meas_power:.4f} W")
        self.p_meas.setMinimumWidth(80)
        self.p_meas.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.p_meas.setStyleSheet("font-family: monospace;")
        p_row.addWidget(self.p_meas)
        main.addLayout(p_row)

    # -- slots --------------------------------------------------------------

    def _on_voltage_changed(self, volts: float) -> None:
        self._supply.set_voltage(self._ch, volts)

    def _on_current_changed(self, amps: float) -> None:
        self._supply.set_current(self._ch, amps)

    def _on_output_toggled(self, on: bool) -> None:
        self._supply.set_output(self._ch, on)
        self._style_output_btn(on)

    def _style_output_btn(self, on: bool) -> None:
        if on:
            self.output_btn.setText("ON")
            self.output_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; "
                "border-radius: 4px; padding: 2px 8px; font-weight: bold; }"
            )
        else:
            self.output_btn.setText("OFF")
            self.output_btn.setStyleSheet(
                "QPushButton { background-color: #555; color: #ccc; "
                "border-radius: 4px; padding: 2px 8px; }"
            )

    # -- update from polled data -------------------------------------------

    def update_readback(self, ch) -> None:
        """Refresh labels & output button from a freshly-polled channel info."""
        self.v_meas.setText(f"{ch.meas_voltage:.4f} V")
        self.i_meas.setText(f"{ch.meas_current:.4f} A")
        self.p_meas.setText(f"{ch.meas_power:.4f} W")

        # Sync output button if hardware state changed externally
        if self.output_btn.isChecked() != ch.output_enabled:
            self.output_btn.blockSignals(True)
            self.output_btn.setChecked(ch.output_enabled)
            self._style_output_btn(ch.output_enabled)
            self.output_btn.blockSignals(False)

        # Sync sliders from device readback (in case changed on front panel)
        self.v_slider.set_value(ch.set_voltage)
        self.i_slider.set_value(ch.set_current)


# ---------------------------------------------------------------------------
# Collapsible section for one supply
# ---------------------------------------------------------------------------


class SupplySection(QWidget):
    """Collapsible section: clickable header + 3 × ChannelControlWidget."""

    def __init__(
        self,
        supply,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._supply = supply
        self._expanded = True
        self._channel_widgets: List[ChannelControlWidget] = []

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- header (clickable) --------------------------------------------
        self.header_btn = QToolButton()
        self.header_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.header_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._update_header_text()
        self.header_btn.setStyleSheet(
            "QToolButton { text-align: left; padding: 6px 8px; font-weight: bold; }"
        )
        self.header_btn.clicked.connect(self._toggle)
        outer.addWidget(self.header_btn)

        # -- status label (shown inside header area) -----------------------
        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            "padding: 0 8px 4px 24px; color: #888; font-size: 11px;"
        )
        self._update_status()
        outer.addWidget(self.status_label)

        # -- body (channel controls) ---------------------------------------
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(12, 0, 4, 8)

        for ch_info in self._supply.channels:
            # Get channel display name from settings
            channel_name = _get_channel_display_name(self._supply, ch_info.number)
            cw = ChannelControlWidget(
                self._supply, ch_info, channel_name=channel_name, parent=self.body
            )
            body_layout.addWidget(cw)
            self._channel_widgets.append(cw)

            # separator between channels (except after last)
            if ch_info.number < len(self._supply.channels):
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                body_layout.addWidget(line)

        outer.addWidget(self.body)

    # -- expand / collapse --------------------------------------------------

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.status_label.setVisible(
            not self._expanded or not self._supply.is_connected
        )
        self.header_btn.setArrowType(
            Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        )

    def _update_header_text(self) -> None:
        name = _get_supply_display_name(self._supply)
        self.header_btn.setText(name)

    def _update_status(self) -> None:
        s = self._supply
        if s.is_connected:
            self.status_label.setText(f"Connected  ●  {s.resource_name}")
            self.status_label.setStyleSheet(
                "padding: 0 8px 4px 24px; color: #4caf50; font-size: 11px;"
            )
        else:
            self.status_label.setText(f"Disconnected  ○  {s.resource_name}")
            self.status_label.setStyleSheet(
                "padding: 0 8px 4px 24px; color: #f44336; font-size: 11px;"
            )

    # -- public refresh -----------------------------------------------------

    def refresh(self) -> None:
        """Update all channel widgets + header from cached supply data."""
        self._update_status()
        if not self._supply.is_connected:
            return
        for cw, ch in zip(self._channel_widgets, self._supply.channels):
            cw.update_readback(ch)


# ---------------------------------------------------------------------------
# Top-level dialog
# ---------------------------------------------------------------------------


class PowerSupplyDialog(QDialog):
    """Dialog for controlling all connected DC power supplies."""

    _DEFAULT_POLL_INTERVAL_MS = 350

    def __init__(
        self,
        manager: PowerSupplyManager,
        parent: Optional[QWidget] = None,
        resource_selector=None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._resource_selector = resource_selector
        self._sections: List[SupplySection] = []

        self._executor = ThreadPoolExecutor(max_workers=1)
        self._poll_signals = _PollSignals()
        self._poll_signals.finished.connect(self._on_poll_finished)
        self._poll_busy = False
        self._poll_interval_ms = _get_power_supply_poll_interval_ms(
            self._DEFAULT_POLL_INTERVAL_MS
        )

        self._create_ui()
        self._populate()

        # Start polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start(self._poll_interval_ms)

    # -- UI -----------------------------------------------------------------

    def _create_ui(self) -> None:
        self.setWindowTitle("Power Supplies")
        self.setMinimumSize(520, 400)
        self.resize(560, 600)

        root = QVBoxLayout(self)

        # toolbar
        tb = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh (F5)")
        self._refresh_btn.setShortcut("F5")
        self._refresh_btn.clicked.connect(self._on_refresh)
        tb.addWidget(self._refresh_btn)
        tb.addStretch()
        self._status_lbl = QLabel("")
        tb.addWidget(self._status_lbl)
        root.addLayout(tb)

        # scrollable body
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_widget = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_widget)
        root.addWidget(self._scroll)

        # Persistent "no supplies" label — hidden until needed
        self._no_supplies_lbl = QLabel(
            "No power supplies found.\nAre they powered on?\n\n"
            "Click Refresh to scan again."
        )
        self._no_supplies_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_supplies_lbl.setWordWrap(True)
        self._no_supplies_lbl.hide()
        self._scroll_layout.addWidget(self._no_supplies_lbl)

    def _populate(self) -> None:
        """Build / rebuild supply sections from manager."""
        # Clear old sections and any stale stretch spacers
        for s in self._sections:
            s.setParent(None)
            s.deleteLater()
        self._sections.clear()

        # Remove spacer items (stretches) from previous populate calls
        for i in reversed(range(self._scroll_layout.count())):
            item = self._scroll_layout.itemAt(i)
            if item and item.widget() is None and item.layout() is None:
                self._scroll_layout.removeItem(item)

        supplies = self._manager.supplies
        if not supplies:
            self._no_supplies_lbl.show()
            self._status_lbl.setText("0 supplies")
            return

        self._no_supplies_lbl.hide()

        for supply in supplies:
            section = SupplySection(supply, parent=self._scroll_widget)
            self._scroll_layout.addWidget(section)
            self._sections.append(section)

        self._scroll_layout.addStretch()
        connected = sum(1 for s in supplies if s.is_connected)
        self._status_lbl.setText(f"{connected}/{len(supplies)} connected")

    # -- refresh ------------------------------------------------------------

    def _on_refresh(self) -> None:
        self._manager.scan()
        self._populate()

    # -- background polling -------------------------------------------------

    def _on_poll_tick(self) -> None:
        if self._poll_busy:
            return
        self._poll_busy = True
        self._executor.submit(self._poll_worker)

    def _poll_worker(self) -> None:
        """Runs in background thread — call poll_all on every supply."""
        for supply in self._manager.supplies:
            if supply.is_connected:
                supply.poll_all()
        # Signal main thread
        self._poll_signals.finished.emit()

    def _on_poll_finished(self) -> None:
        """Main-thread handler: push polled data into widgets."""
        self._poll_busy = False
        for section in self._sections:
            section.refresh()
        # Update status
        supplies = self._manager.supplies
        connected = sum(1 for s in supplies if s.is_connected)
        self._status_lbl.setText(f"{connected}/{len(supplies)} connected")

    # -- lifecycle ----------------------------------------------------------

    def closeEvent(self, ev):
        self._poll_timer.stop()
        self._executor.shutdown(wait=False)
        super().closeEvent(ev)

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog."""
        if self._resource_selector:
            style_manager = get_style_manager()
            style_manager.apply_theme(self._resource_selector.get_theme())
