from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QTextCursor, QAction
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QDoubleSpinBox,
    QLabel,
    QPlainTextEdit,
    QMainWindow,
    QDialog,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
)
from collections import deque
import cv2
import os, sys, time
import ctypes
import numpy as np
from camera import Camera
from digilent import DigilentController


class AcquisitionWorker(QThread):
    """
    Worker thread to run the experiment acquisition loop, controlling the Digilent device and camera.
    """
    image_saved = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, digilent, camera, pulse_width, rep_rate):
        super().__init__()
        self.digilent = digilent
        self.camera = camera
        self.pulse_width = pulse_width
        self.rep_rate = rep_rate
        self.running = True

    def run(self):
        if not self.digilent.connected:
            self.digilent.open()
            if not self.digilent.connected:
                self.status.emit("Failed to connect to Digilent device")
                return
        self.status.emit("Starting experiment")

        self.digilent.configure(self.pulse_width, self.rep_rate)
        self.digilent.start()
        self.camera.initialize()

        shot = 0
        os.makedirs("data", exist_ok=True)
        while self.running:
            img = self.camera.acquire()

            fname = f"data/shot_{shot:04d}.png"
            # just write image with os
            cv2.imwrite(fname, img)

            self.image_saved.emit(fname)
            shot += 1

        self.digilent.stop()
        self.camera.shutdown()
        self.status.emit("Experiment stopped")

    def stop(self):
        self.running = False


class ExperimentController:
    def __init__(self):
        self.digilent = DigilentController()
        self.camera = Camera()
        self.worker = None

    def start(self, pulse_width, rep_rate):
        self.worker = AcquisitionWorker(
            self.digilent, self.camera, pulse_width, rep_rate
        )
        return self.worker

    def shutdown(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self.digilent.close()


class ExperimentGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.controller = ExperimentController()
        self.worker = None
        self.log_messages = deque(maxlen=100)
        self.last_camera_connected = None
        self.last_digilent_connected = None

        self.setWindowTitle("Experiment Control")
        self.layout = QVBoxLayout(self)  # type: ignore
        assert isinstance(self.layout, QVBoxLayout)

        self.pw = QDoubleSpinBox()
        self.pw.setDecimals(9)
        self.pw.setValue(5e-6)
        self.pw.setPrefix("Pulse Width (s): ")

        self.rr = QDoubleSpinBox()
        self.rr.setRange(1, 1e6)
        self.rr.setValue(20000)
        self.rr.setPrefix("Rep Rate (Hz): ")

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")

        self.status = QLabel("Idle")

        self.layout.addWidget(self.pw)
        self.layout.addWidget(self.rr)
        self.layout.addWidget(self.start_btn)
        self.layout.addWidget(self.stop_btn)
        self.layout.addWidget(self.status)

        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)

        self.camera_status_label = QLabel("")
        self.digilent_status_label = QLabel("")
        self.connect_camera_button = QPushButton("Connect Camera")
        self.grab_image_button = QPushButton("Grab Image")

        self.layout.addWidget(self.camera_status_label)
        self.layout.addWidget(self.digilent_status_label)
        self.layout.addWidget(self.connect_camera_button)
        self.layout.addWidget(self.grab_image_button)

        self.message_log = MessageLogWidget()
        self.layout.addWidget(self.message_log)

        self.connect_camera_button.clicked.connect(self.connect_camera)
        self.grab_image_button.clicked.connect(self.show_image)

        self.update_status_labels()
        self.log_message("Ready")

    def start(self):
        self.worker = self.controller.start(self.pw.value(), self.rr.value())

        self.worker.image_saved.connect(lambda f: self.status.setText(f"Saved {f}"))
        self.worker.status.connect(self.status.setText)
        self.worker.status.connect(self.log_message)
        self.worker.status.connect(lambda _: self.update_status_labels())

        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()

    def shutdown(self):
        self.controller.shutdown()

    def connect_camera(self):
        self.controller.camera.connect()
        self.update_status_labels()

    def show_image(self):
        image = self.controller.camera.grab_image()
        if image is not None:
            # Code to display the image in the GUI
            pass
        else:
            print("No image grabbed")

    def update_status_labels(self):
        camera_connected = self.controller.camera.connected
        digilent_connected = self.controller.digilent.connected

        self.camera_status_label.setText(
            "Camera Status: Connected" if camera_connected else "Camera Status: Disconnected"
        )
        self.digilent_status_label.setText(
            "Digilent Status: Connected"
            if digilent_connected
            else "Digilent Status: Disconnected"
        )

        if camera_connected != self.last_camera_connected:
            state = "connected" if camera_connected else "disconnected"
            self.log_message(f"Camera {state}")
            self.last_camera_connected = camera_connected

        if digilent_connected != self.last_digilent_connected:
            state = "connected" if digilent_connected else "disconnected"
            self.log_message(f"Digilent {state}")
            self.last_digilent_connected = digilent_connected

    def log_message(self, message: str):
        if not message:
            return
        cleaned = " ".join(str(message).splitlines()).strip()
        if not cleaned:
            return
        timestamp = time.strftime("%H:%M:%S")
        self.log_messages.append(f"{timestamp} {cleaned}")
        self.message_log.update_messages(self.log_messages)

    def set_log_capacity(self, capacity: int):
        capacity = max(1, int(capacity))
        trimmed = list(self.log_messages)[-capacity:]
        self.log_messages = deque(trimmed, maxlen=capacity)
        self.message_log.update_messages(self.log_messages)

    def get_log_capacity(self) -> int:
        return self.log_messages.maxlen or 0


class SettingsDialog(QDialog):
    def __init__(self, current_log_size: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.log_size_spin = QSpinBox()
        self.log_size_spin.setRange(1, 10000)
        self.log_size_spin.setValue(current_log_size)

        form = QFormLayout(self)
        form.addRow("Log size (messages):", self.log_size_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addWidget(buttons)

    def log_size(self) -> int:
        return int(self.log_size_spin.value())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Experiment Control")
        self.gui = ExperimentGUI()
        self.setCentralWidget(self.gui)
        self._build_menu()

    def _build_menu(self):
        settings_menu = self.menuBar().addMenu("Settings")
        open_settings = QAction("Preferences...", self)
        open_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(open_settings)

    def open_settings(self):
        dialog = SettingsDialog(self.gui.get_log_capacity(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.gui.set_log_capacity(dialog.log_size())
            self.gui.log_message("Log size updated")

    def closeEvent(self, event):
        self.gui.shutdown()
        event.accept()


class MessageLogWidget(QPlainTextEdit):
    def __init__(self, collapsed_lines=1, expanded_lines=5):
        super().__init__()
        self.collapsed_lines = collapsed_lines
        self.expanded_lines = expanded_lines
        self.expanded = False
        self._messages = []
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setPlaceholderText("No messages")
        self._apply_height()

    def update_messages(self, messages):
        self._messages = list(messages)
        if self.expanded:
            text = "\n".join(self._messages)
        else:
            text = self._messages[-1] if self._messages else ""
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.ensureCursorVisible()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.expanded = not self.expanded
            self._apply_height()
            self.update_messages(self._messages)
        super().mousePressEvent(event)

    def _apply_height(self):
        lines = self.expanded_lines if self.expanded else self.collapsed_lines
        line_height = self.fontMetrics().lineSpacing()
        padding = self.frameWidth() * 2 + 6
        self.setFixedHeight(line_height * lines + padding)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
