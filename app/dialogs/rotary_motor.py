"""
Rotary Motor Dialog — Qt6 front-end for Thorlabs Elliptec ELLO rotary motors.

Provides controls for:
- Position (absolute) with target/current display
- Speed (jog step size) adjustment
- Jog forward/backward buttons
- Homing
- Saving/loading position waypoints
- Real-time feedback from the device via background polling
"""

from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QGroupBox,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
)

from devices.ell_motor import ELLMotor
from dialogs.controls.basic_slider import BasicSlider
from resources.style_manager import get_style_manager


# ---------------------------------------------------------------------------
# Helper: Settings loader
# ---------------------------------------------------------------------------


def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    settings_path = Path(__file__).parent.parent / "resources" / "settings.json"
    try:
        with open(settings_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to settings.json."""
    settings_path = Path(__file__).parent.parent / "resources" / "settings.json"
    try:
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helper: poll results carrier (thread → main)
# ---------------------------------------------------------------------------


class _PollSignals(QObject):
    """Carrier for cross-thread signal."""

    finished = pyqtSignal()


class _MaintenanceSignals(QObject):
    """Signals for maintenance operations."""

    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)


class _ConnectionSignals(QObject):
    """Signals for connection operations."""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)


# ---------------------------------------------------------------------------
# Motor Control Widget
# ---------------------------------------------------------------------------


class MotorControlWidget(QWidget):
    """Controls for motor position, speed, and jog operations."""

    def __init__(self, motor: ELLMotor, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._motor = motor
        self._pending_jog_step = None  # Store slider value without sending to motor
        self._build_ui()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # -- Device info section
        info_group = QGroupBox("Device Information")
        info_layout = QVBoxLayout(info_group)

        info_text = (
            f"<b>Device:</b> {self._motor.device_type}<br>"
            f"<b>Serial:</b> {self._motor.serial_number}<br>"
            f"<b>Address:</b> {self._motor.address}<br>"
            f"<b>Variant:</b> {self._motor.variant}<br>"
        )

        unit_type = "degrees" if "Rotator" in self._motor.device_type else "mm"
        info_text += f"<b>Travel:</b> {self._motor.travel:.2f} {unit_type}<br>"

        info_label = QLabel(info_text)
        info_label.setStyleSheet("padding: 4px;")
        info_layout.addWidget(info_label)
        main.addWidget(info_group)

        # -- Position control section
        pos_group = QGroupBox("Position Control")
        pos_layout = QVBoxLayout(pos_group)

        # Current position display
        pos_display_layout = QHBoxLayout()
        pos_display_layout.addWidget(QLabel("Current Position:"))
        pos_display_layout.addStretch()
        self.pos_display = QLabel("-- --")
        self.pos_display.setStyleSheet(
            "font-family: monospace; font-size: 14px; font-weight: bold;"
        )
        self.pos_display.setMinimumWidth(100)
        pos_display_layout.addWidget(self.pos_display)
        pos_layout.addLayout(pos_display_layout)

        # Target position input
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("Target Position:"))
        self.target_spinbox = QDoubleSpinBox()
        self.target_spinbox.setRange(-720.0, 720.0)
        self.target_spinbox.setValue(0.0)
        self.target_spinbox.setDecimals(2)
        self.target_spinbox.setSingleStep(1.0)
        self.target_spinbox.setMinimumWidth(100)
        target_layout.addStretch()
        target_layout.addWidget(self.target_spinbox)
        pos_layout.addLayout(target_layout)

        # Move buttons
        move_btn_layout = QHBoxLayout()
        self.move_btn = QPushButton("Move to Target")
        self.move_btn.clicked.connect(self._on_move_to_target)
        move_btn_layout.addWidget(self.move_btn)

        self.home_btn = QPushButton("Home")
        self.home_btn.clicked.connect(self._on_home)
        move_btn_layout.addWidget(self.home_btn)

        pos_layout.addLayout(move_btn_layout)
        main.addWidget(pos_group)

        # -- Speed/Jog control section
        speed_group = QGroupBox("Speed & Jog Control")
        speed_layout = QVBoxLayout(speed_group)

        # Jog step size
        jog_layout = QHBoxLayout()
        jog_layout.addWidget(QLabel("Jog Step Size:"))
        self.jog_slider = BasicSlider(
            0.1, 720.0, 1.0, 0.1, float_precision=2, unit="", parent=self
        )
        self.jog_slider.valueChanged.connect(self._on_jog_step_changed)
        jog_layout.addWidget(self.jog_slider, stretch=1)
        speed_layout.addLayout(jog_layout)

        # Jog buttons
        jog_btn_layout = QHBoxLayout()
        self.jog_back_btn = QPushButton("← Jog Backward")
        self.jog_back_btn.clicked.connect(self._on_jog_backward)
        jog_btn_layout.addWidget(self.jog_back_btn)

        self.jog_fwd_btn = QPushButton("Jog Forward →")
        self.jog_fwd_btn.clicked.connect(self._on_jog_forward)
        jog_btn_layout.addWidget(self.jog_fwd_btn)

        speed_layout.addLayout(jog_btn_layout)
        main.addWidget(speed_group)

        main.addStretch()

    def _on_move_to_target(self) -> None:
        """Move motor to target position."""
        target = self.target_spinbox.value()
        if self._motor.move_absolute(target):
            self.pos_display.setText(f"{target:.2f}")
        else:
            QMessageBox.warning(
                self, "Move Failed", "Failed to move to target position"
            )

    def _on_home(self) -> None:
        """Home the motor."""
        if not self._motor.is_busy():
            if self._motor.home():
                self.pos_display.setText("Homing...")
            else:
                QMessageBox.warning(self, "Home Failed", "Failed to home motor")
        else:
            QMessageBox.warning(
                self, "Motor Busy", "Motor is busy or in thermal lockout"
            )

    def _on_jog_forward(self) -> None:
        """Jog forward one step."""
        # Apply pending jog step size if changed
        if self._pending_jog_step is not None:
            self._motor.jog_step_size = self._pending_jog_step
            self._pending_jog_step = None

        if self._motor.jog_forward():
            pass  # Position will be updated by polling
        else:
            QMessageBox.warning(self, "Jog Failed", "Failed to jog forward")

    def _on_jog_backward(self) -> None:
        """Jog backward one step."""
        # Apply pending jog step size if changed
        if self._pending_jog_step is not None:
            self._motor.jog_step_size = self._pending_jog_step
            self._pending_jog_step = None

        if self._motor.jog_backward():
            pass  # Position will be updated by polling
        else:
            QMessageBox.warning(self, "Jog Failed", "Failed to jog backward")

    def _on_jog_step_changed(self, step: float) -> None:
        """Store jog step size without sending to motor (lazy update)."""
        self._pending_jog_step = step

    def update_position(self, position: float) -> None:
        """Update position display from polled data."""
        self.pos_display.setText(f"{position:.2f}")

    def update_jog_step(self, step: float) -> None:
        """Update jog step display from polled data."""
        # Only update if we don't have a pending change
        if self._pending_jog_step is None:
            self.jog_slider.set_value(step)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all controls."""
        self.move_btn.setEnabled(enabled)
        self.home_btn.setEnabled(enabled)
        self.jog_fwd_btn.setEnabled(enabled)
        self.jog_back_btn.setEnabled(enabled)
        self.target_spinbox.setEnabled(enabled)
        self.jog_slider.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Waypoints Widget
# ---------------------------------------------------------------------------


class WaypointsWidget(QWidget):
    """Widget for saving and loading position waypoints."""

    def __init__(self, motor: ELLMotor, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._motor = motor
        self._waypoints: Dict[str, float] = self._load_waypoints()
        self._build_ui()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # Group box
        waypoints_group = QGroupBox("Position Waypoints")
        group_layout = QVBoxLayout(waypoints_group)

        # Waypoint name input + save button
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Waypoint Name:"))
        self.waypoint_name_input = QComboBox()
        self.waypoint_name_input.setEditable(True)
        self.waypoint_name_input.addItems(list(self._waypoints.keys()))
        input_layout.addWidget(self.waypoint_name_input, stretch=1)

        self.save_waypoint_btn = QPushButton("Save Current")
        self.save_waypoint_btn.clicked.connect(self._on_save_waypoint)
        input_layout.addWidget(self.save_waypoint_btn)

        group_layout.addLayout(input_layout)

        # Waypoints list
        self.waypoints_list = QListWidget()
        self.waypoints_list.itemDoubleClicked.connect(self._on_load_waypoint)
        self._populate_list()
        group_layout.addWidget(self.waypoints_list)

        # Delete button
        delete_layout = QHBoxLayout()
        delete_layout.addStretch()
        self.delete_waypoint_btn = QPushButton("Delete Selected")
        self.delete_waypoint_btn.clicked.connect(self._on_delete_waypoint)
        delete_layout.addWidget(self.delete_waypoint_btn)
        group_layout.addLayout(delete_layout)

        main.addWidget(waypoints_group)

    def _load_waypoints(self) -> Dict[str, float]:
        """Load waypoints from settings."""
        settings = _load_settings()
        motor_key = f"{self._motor.serial_number}_{self._motor.address}"
        return settings.get("rotary_motors", {}).get(motor_key, {}).get("waypoints", {})

    def _save_waypoints(self) -> bool:
        """Save waypoints to settings."""
        settings = _load_settings()
        if "rotary_motors" not in settings:
            settings["rotary_motors"] = {}

        motor_key = f"{self._motor.serial_number}_{self._motor.address}"
        if motor_key not in settings["rotary_motors"]:
            settings["rotary_motors"][motor_key] = {}

        # Convert waypoint values to floats for JSON serialization
        waypoints_dict = {name: float(pos) for name, pos in self._waypoints.items()}
        settings["rotary_motors"][motor_key]["waypoints"] = waypoints_dict

        return _save_settings(settings)

    def _populate_list(self) -> None:
        """Populate the waypoints list widget."""
        self.waypoints_list.clear()
        for name, position in sorted(self._waypoints.items()):
            item_text = f"{name}: {position:.2f}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, name)  # Store name for retrieval
            self.waypoints_list.addItem(item)

    def _on_save_waypoint(self) -> None:
        """Save current motor position as a waypoint."""
        name = self.waypoint_name_input.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Empty Name", "Please enter a waypoint name")
            return

        # Get current position
        self._motor.get_position()
        position = self._motor.position

        self._waypoints[name] = position
        if self._save_waypoints():
            # Update combo box
            if self.waypoint_name_input.findText(name) == -1:
                self.waypoint_name_input.addItem(name)
            self._populate_list()
            QMessageBox.information(
                self, "Saved", f"Waypoint '{name}' saved at position {position:.2f}"
            )
        else:
            QMessageBox.critical(self, "Save Failed", "Failed to save settings")

    def _on_load_waypoint(self, item: QListWidgetItem) -> None:
        """Load a waypoint and move to it."""
        name = item.data(Qt.ItemDataRole.UserRole)
        if name in self._waypoints:
            position = self._waypoints[name]
            if self._motor.move_absolute(position):
                QMessageBox.information(
                    self, "Moving", f"Moving to waypoint '{name}' at {position:.2f}"
                )
            else:
                QMessageBox.warning(self, "Move Failed", "Failed to move to waypoint")

    def _on_delete_waypoint(self) -> None:
        """Delete selected waypoint."""
        current_item = self.waypoints_list.currentItem()
        if current_item is None:
            QMessageBox.warning(
                self, "No Selection", "Please select a waypoint to delete"
            )
            return

        name = current_item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete waypoint '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            del self._waypoints[name]
            if self._save_waypoints():
                self._populate_list()
            else:
                QMessageBox.critical(self, "Save Failed", "Failed to save settings")

    def refresh_waypoints(self) -> None:
        """Reload waypoints from settings (for sync if changed externally)."""
        self._waypoints = self._load_waypoints()
        self._populate_list()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all controls."""
        self.waypoint_name_input.setEnabled(enabled)
        self.save_waypoint_btn.setEnabled(enabled)
        self.waypoints_list.setEnabled(enabled)
        self.delete_waypoint_btn.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Maintenance Widget
# ---------------------------------------------------------------------------


class MaintenanceWidget(QWidget):
    """Widget for motor maintenance operations."""

    def __init__(self, motor: ELLMotor, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._motor = motor
        self._maintenance_thread = None
        self._current_operation = None
        self._maintenance_signals = _MaintenanceSignals()
        self._maintenance_signals.started.connect(self._on_maintenance_started)
        self._maintenance_signals.finished.connect(self._on_maintenance_finished)
        self._maintenance_signals.error.connect(self._on_maintenance_error)
        self._build_ui()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(12)

        # Group box
        maint_group = QGroupBox("Maintenance Operations")
        group_layout = QVBoxLayout(maint_group)

        # Warning label
        warning = QLabel(
            "⚠️ <b>Warning:</b> Wait at least 30 minutes between operations."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #ff9800; padding: 4px;")
        group_layout.addWidget(warning)

        # Buttons
        btn_layout = QHBoxLayout()

        self.clean_btn = QPushButton("Clean")
        self.clean_btn.clicked.connect(lambda: self._start_maintenance("clean"))
        btn_layout.addWidget(self.clean_btn)

        self.optimize_btn = QPushButton("Optimize")
        self.optimize_btn.clicked.connect(lambda: self._start_maintenance("optimize"))
        btn_layout.addWidget(self.optimize_btn)

        self.clean_optimize_btn = QPushButton("Clean & Optimize")
        self.clean_optimize_btn.clicked.connect(
            lambda: self._start_maintenance("clean_and_optimize")
        )
        btn_layout.addWidget(self.clean_optimize_btn)

        group_layout.addLayout(btn_layout)
        main.addWidget(maint_group)

    def _start_maintenance(self, operation: str) -> None:
        """Start a maintenance operation with confirmation."""
        # Confirm with user
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Confirm Maintenance")

        if operation == "clean":
            msg.setText("Start cleaning cycle?")
            msg.setInformativeText(
                "This will run a cleaning cycle.\n\n"
                "⚠️ Wait at least 30 minutes between maintenance operations.\n\n"
                "This operation can be stopped by clicking the button again."
            )
        elif operation == "optimize":
            msg.setText("Start optimization cycle?")
            msg.setInformativeText(
                "This will run an optimization cycle.\n\n"
                "⚠️ Wait at least 30 minutes between maintenance operations.\n\n"
                "This operation can be stopped by clicking the button again."
            )
        else:  # clean_and_optimize
            msg.setText("Start cleaning and optimization cycle?")
            msg.setInformativeText(
                "This will run a full cleaning and optimization cycle (10-15 min).\n\n"
                "⚠️ Wait at least 30 minutes between maintenance operations.\n\n"
                "This operation can be stopped by clicking the button again."
            )

        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        # Start operation in thread
        self._current_operation = operation
        self._maintenance_signals.started.emit()

        from threading import Thread

        self._maintenance_thread = Thread(
            target=self._run_maintenance, args=(operation,)
        )
        self._maintenance_thread.start()

    def _run_maintenance(self, operation: str) -> None:
        """Run maintenance operation in background thread."""
        try:
            if operation == "clean":
                self._motor.clean()
            elif operation == "optimize":
                self._motor.optimize()
            else:  # clean_and_optimize
                self._motor.clean_and_optimize()
            self._maintenance_signals.finished.emit()
        except Exception as e:
            self._maintenance_signals.error.emit(str(e))

    def _stop_maintenance(self) -> None:
        """Stop ongoing maintenance operation."""
        if self._motor.stop_cleaning():
            QMessageBox.information(self, "Stopped", "Maintenance operation stopped.")
        else:
            QMessageBox.warning(
                self, "Stop Failed", "Failed to stop maintenance operation."
            )

    def _on_maintenance_started(self) -> None:
        """Handle maintenance operation started."""
        # Update button text and functionality
        if self._current_operation == "clean":
            self.clean_btn.setText("Cleaning...")
            self.clean_btn.setToolTip("Click to stop cleaning")
            try:
                self.clean_btn.clicked.disconnect()
            except TypeError:
                pass  # Nothing was connected
            self.clean_btn.clicked.connect(self._stop_maintenance)
        elif self._current_operation == "optimize":
            self.optimize_btn.setText("Optimizing...")
            self.optimize_btn.setToolTip("Click to stop optimizing")
            try:
                self.optimize_btn.clicked.disconnect()
            except TypeError:
                pass  # Nothing was connected
            self.optimize_btn.clicked.connect(self._stop_maintenance)
        else:  # clean_and_optimize
            self.clean_optimize_btn.setText("Cleaning & Optimizing...")
            self.clean_optimize_btn.setToolTip("Click to stop")
            try:
                self.clean_optimize_btn.clicked.disconnect()
            except TypeError:
                pass  # Nothing was connected
            self.clean_optimize_btn.clicked.connect(self._stop_maintenance)

        # Disable other buttons
        self._set_other_buttons_enabled(False)

    def _on_maintenance_finished(self) -> None:
        """Handle maintenance operation finished."""
        # Reset buttons
        self._reset_buttons()
        QMessageBox.information(
            self, "Complete", "Maintenance operation completed successfully."
        )

    def _on_maintenance_error(self, error: str) -> None:
        """Handle maintenance operation error."""
        self._reset_buttons()
        QMessageBox.critical(self, "Error", f"Maintenance operation failed:\n{error}")

    def _reset_buttons(self) -> None:
        """Reset all buttons to initial state."""
        self.clean_btn.setText("Clean")
        self.clean_btn.setToolTip("")
        try:
            self.clean_btn.clicked.disconnect()
        except TypeError:
            pass  # Nothing was connected
        self.clean_btn.clicked.connect(lambda: self._start_maintenance("clean"))

        self.optimize_btn.setText("Optimize")
        self.optimize_btn.setToolTip("")
        try:
            self.optimize_btn.clicked.disconnect()
        except TypeError:
            pass  # Nothing was connected
        self.optimize_btn.clicked.connect(lambda: self._start_maintenance("optimize"))

        self.clean_optimize_btn.setText("Clean & Optimize")
        self.clean_optimize_btn.setToolTip("")
        try:
            self.clean_optimize_btn.clicked.disconnect()
        except TypeError:
            pass  # Nothing was connected
        self.clean_optimize_btn.clicked.connect(
            lambda: self._start_maintenance("clean_and_optimize")
        )

        self._set_other_buttons_enabled(True)
        self._current_operation = None

    def _set_other_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable buttons not involved in current operation."""
        if self._current_operation != "clean":
            self.clean_btn.setEnabled(enabled)
        if self._current_operation != "optimize":
            self.optimize_btn.setEnabled(enabled)
        if self._current_operation != "clean_and_optimize":
            self.clean_optimize_btn.setEnabled(enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all maintenance controls."""
        self.clean_btn.setEnabled(enabled)
        self.optimize_btn.setEnabled(enabled)
        self.clean_optimize_btn.setEnabled(enabled)

    def is_running(self) -> bool:
        """Check if a maintenance operation is running."""
        return self._current_operation is not None


# ---------------------------------------------------------------------------
# Top-level dialog
# ---------------------------------------------------------------------------


class RotaryMotorDialog(QDialog):
    """Dialog for controlling Thorlabs Elliptec rotary motors."""

    _POLL_INTERVAL_MS = 500  # background poll rate

    def __init__(
        self,
        port: Optional[int] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._port = port
        self._motor: Optional[ELLMotor] = None
        self._is_connected = False

        self._executor = ThreadPoolExecutor(max_workers=2)
        self._poll_signals = _PollSignals()
        self._poll_signals.finished.connect(self._on_poll_finished)
        self._poll_busy = False

        self._connection_signals = _ConnectionSignals()
        self._connection_signals.connected.connect(self._on_connected)
        self._connection_signals.disconnected.connect(self._on_disconnected)
        self._connection_signals.error.connect(self._on_connection_error)

        self._create_ui()

        # Start polling timer (will skip if not connected)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start(self._POLL_INTERVAL_MS)

    def _create_ui(self) -> None:
        self.setWindowTitle("Rotary Motor Control")
        self.setMinimumSize(500, 600)
        self.resize(600, 750)

        root = QVBoxLayout(self)

        # Connection control bar
        connection_bar = QHBoxLayout()
        connection_bar.setContentsMargins(8, 8, 8, 8)

        self.connection_status = QLabel("Disconnected")
        self.connection_status.setStyleSheet("font-weight: bold; color: #888;")
        connection_bar.addWidget(self.connection_status)
        connection_bar.addStretch()

        self.connect_btn = QPushButton(
            f"Connect to Port {self._port if self._port else '(auto)'}"
        )
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        connection_bar.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        self.disconnect_btn.setEnabled(False)
        connection_bar.addWidget(self.disconnect_btn)

        root.addLayout(connection_bar)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(separator)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(self.scroll_widget)
        scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_layout.setSpacing(12)

        # Disconnected placeholder
        self.disconnected_widget = QWidget()
        disconnected_layout = QVBoxLayout(self.disconnected_widget)
        disconnected_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disconnected_label = QLabel("Motor not connected\n\nClick 'Connect' to start")
        disconnected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disconnected_label.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        disconnected_layout.addWidget(disconnected_label)
        scroll_layout.addWidget(self.disconnected_widget)

        # Motor control widgets (initially hidden)
        self.control_widget = None
        self.waypoints_widget = None
        self.maintenance_widget = None

        scroll.setWidget(self.scroll_widget)
        root.addWidget(scroll)

    # -- connection management ----------------------------------------------

    def _on_connect_clicked(self) -> None:
        """Handle connect button click."""
        if self._is_connected:
            return

        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting...")
        self.connection_status.setText("Connecting...")
        self.connection_status.setStyleSheet("font-weight: bold; color: #ff9800;")

        # Connect in background thread
        self._executor.submit(self._connect_worker)

    def _connect_worker(self) -> None:
        """Connect to motor in background thread."""
        try:
            self._motor = ELLMotor(port=self._port, verbose=False)
            self._connection_signals.connected.emit()
        except Exception as e:
            self._connection_signals.error.emit(str(e))

    def _on_connected(self) -> None:
        """Handle successful connection."""
        assert self._motor is not None  # Type guard
        self._is_connected = True
        self.connection_status.setText(f"Connected — {self._motor.serial_number}")
        self.connection_status.setStyleSheet("font-weight: bold; color: #4caf50;")
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.setWindowTitle(f"Rotary Motor — {self._motor.serial_number}")

        # Build motor control UI
        self._build_motor_widgets()

        # Initial position query
        self._on_poll_tick()

    def _on_disconnect_clicked(self) -> None:
        """Handle disconnect button click."""
        if not self._is_connected:
            return

        self.disconnect_btn.setEnabled(False)
        self.connection_status.setText("Disconnecting...")
        self.connection_status.setStyleSheet("font-weight: bold; color: #ff9800;")

        # Disconnect in background thread
        self._executor.submit(self._disconnect_worker)

    def _disconnect_worker(self) -> None:
        """Disconnect from motor in background thread."""
        try:
            if self._motor:
                self._motor.disconnect()
            self._connection_signals.disconnected.emit()
        except Exception as e:
            self._connection_signals.error.emit(str(e))

    def _on_disconnected(self) -> None:
        """Handle successful disconnection."""
        self._is_connected = False
        self._motor = None
        self.connection_status.setText("Disconnected")
        self.connection_status.setStyleSheet("font-weight: bold; color: #888;")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText(
            f"Connect to Port {self._port if self._port else '(auto)'}"
        )
        self.disconnect_btn.setEnabled(False)
        self.setWindowTitle("Rotary Motor Control")

        # Remove motor control widgets
        if self.control_widget:
            self.control_widget.deleteLater()
            self.control_widget = None
        if self.waypoints_widget:
            self.waypoints_widget.deleteLater()
            self.waypoints_widget = None
        if self.maintenance_widget:
            self.maintenance_widget.deleteLater()
            self.maintenance_widget = None

        # Show disconnected placeholder
        self.disconnected_widget.setVisible(True)

    def _on_connection_error(self, error: str) -> None:
        """Handle connection error."""
        self.connection_status.setText("Connection failed")
        self.connection_status.setStyleSheet("font-weight: bold; color: #f44336;")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText(
            f"Connect to Port {self._port if self._port else '(auto)'}"
        )
        self.disconnect_btn.setEnabled(False)

        QMessageBox.critical(
            self, "Connection Error", f"Failed to connect to motor:\n{error}"
        )

    def _build_motor_widgets(self) -> None:
        """Build motor control widgets after connection."""
        assert self._motor is not None  # Type guard

        # Hide disconnected placeholder
        self.disconnected_widget.setVisible(False)

        # Get the scroll widget layout
        scroll_layout = self.scroll_widget.layout()
        assert scroll_layout is not None  # Type guard

        # Motor control widget
        self.control_widget = MotorControlWidget(self._motor, parent=self.scroll_widget)
        scroll_layout.addWidget(self.control_widget)

        # Waypoints widget
        self.waypoints_widget = WaypointsWidget(self._motor, parent=self.scroll_widget)
        scroll_layout.addWidget(self.waypoints_widget)

        # Maintenance widget
        self.maintenance_widget = MaintenanceWidget(
            self._motor, parent=self.scroll_widget
        )
        scroll_layout.addWidget(self.maintenance_widget)

    # -- background polling -------------------------------------------------

    def _on_poll_tick(self) -> None:
        """Timer tick — submit background poll."""
        if self._poll_busy or not self._is_connected or not self._motor:
            return
        self._poll_busy = True
        self._executor.submit(self._poll_worker)

    def _poll_worker(self) -> None:
        """Runs in background thread — query device state."""
        try:
            if self._motor:
                self._motor.get_position()
                self._motor.get_jog_step_size()
        except Exception:
            pass  # Silent fail on query errors
        # Signal main thread
        self._poll_signals.finished.emit()

    def _on_poll_finished(self) -> None:
        """Main-thread handler: update UI from polled data."""
        self._poll_busy = False

        if not self._is_connected or not self._motor or not self.control_widget:
            return

        self.control_widget.update_position(self._motor.position)
        self.control_widget.update_jog_step(self._motor.jog_step_size)

        # Disable controls if maintenance is running
        assert (
            self.maintenance_widget is not None and self.waypoints_widget is not None
        )  # Type guard
        if self.maintenance_widget.is_running():
            self.control_widget.set_enabled(False)
            self.waypoints_widget.set_enabled(False)
        else:
            self.control_widget.set_enabled(True)
            self.waypoints_widget.set_enabled(True)

    # -- lifecycle ----------------------------------------------------------

    def closeEvent(self, ev):
        """Clean up on close (but don't disconnect motor)."""
        self._poll_timer.stop()
        self._executor.shutdown(wait=False)
        # Don't disconnect - let connection persist
        super().closeEvent(ev)

    def cleanup(self) -> None:
        """Cleanup method for app shutdown - disconnects motor."""
        self._poll_timer.stop()
        self._executor.shutdown(wait=True)
        try:
            if self._motor:
                self._motor.disconnect()
        except Exception:
            pass

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog."""
        style_manager = get_style_manager()
        # Theme application can be customized here if needed
