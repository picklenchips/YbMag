"""
HDR Image Capture Dialog — Qt6 front-end for Still Image HDR acquisition.

Provides frame capture with multiple exposure times and HDR merging using OpenCV.
Works with the main camera stream from MainWindow without interfering with livestream.
"""

from __future__ import annotations

import time
import threading
import cv2
import numpy as np
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QRadioButton,
    QMessageBox,
    QLabel,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

from imagingcontrol4.grabber import Grabber
from imagingcontrol4.queuesink import QueueSinkListener, QueueSink
from imagingcontrol4.imagebuffer import ImageBuffer
from imagingcontrol4.imagetype import ImageType, PixelFormat
from imagingcontrol4.display import DisplayRenderPosition
from imagingcontrol4.bufferpool import BufferPool
from imagingcontrol4.properties import PropertyMap
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.ic4exception import IC4Exception

from .display import DisplayWidget
from .controls.basic_slider import BasicSlider
from resources.style_manager import get_style_manager


# ---------------------------------------------------------------------------
# Helper: poll results carrier (thread → main)
# ---------------------------------------------------------------------------


class _PollSignals(QObject):
    """Carrier for cross-thread signals."""

    finished = pyqtSignal()
    error = pyqtSignal(str)


# ---------------------------------------------------------------------------
# Frame Listener
# ---------------------------------------------------------------------------


class HDRListener(QueueSinkListener):
    """Listens to image queue and captures frames for HDR processing."""

    buffer_list: list[ImageBuffer]

    def __init__(self):
        self.counter = 0
        self.frames_to_capture = 0
        self.capture = False
        self.buffer_list = []
        self.capture_end_event = threading.Event()

    def sink_connected(
        self,
        sink: QueueSink,
        image_type: ImageType,
        min_buffers_required: int,
    ) -> bool:
        sink.alloc_and_queue_buffers(min_buffers_required + 8)
        return True

    def start_capture(self, frames: int):
        """Start the image capture into the buffer_list
        :param frames: Number of frames to be saved in self.buffer_list
        """
        self.counter = 0
        self.buffer_list.clear()
        self.frames_to_capture = frames
        self.capture_end_event.clear()
        self.capture = True

    def frames_queued(self, sink: QueueSink):
        """If self.capture is true, the wanted number of images
        are stored into self.buffer_list
        """
        buffer = sink.pop_output_buffer()

        if self.capture:
            self.counter = self.counter + 1
            print(f"HDR: Captured image {self.counter}/{self.frames_to_capture}")
            self.buffer_list.append(buffer)
            # End capture after desired number of frames.
            if self.counter >= self.frames_to_capture:
                self.capture_end_event.set()
                self.capture = False
                print("HDR: Capture complete")


# ---------------------------------------------------------------------------
# HDR Dialog
# ---------------------------------------------------------------------------


class HDRDialog(QDialog):
    """Dialog for capturing and processing Still Image HDR."""

    _hdr_result: np.typing.NDArray[Any]

    def __init__(
        self, grabber: Grabber, parent: QWidget | None = None, resource_selector=None
    ):
        QDialog.__init__(self, parent)
        self.setWindowTitle("Still Image HDR Capture")
        self.setGeometry(100, 100, 1400, 600)

        self.grabber = grabber
        self.resource_selector = resource_selector

        # The buffer pool is used to display the resulting HDR image
        self.pool = BufferPool()

        self.listener = HDRListener()

        self.queue_sink = QueueSink(self.listener, [PixelFormat.BGR8])

        self._poll_signals = _PollSignals()
        self._poll_signals.finished.connect(self._on_capture_finished)
        self._poll_signals.error.connect(self._on_capture_error)

        self.create_gui()
        self.apply_theme()

    def create_gui(self):
        """Create the user interface"""
        main_layout = QHBoxLayout()

        # Left side: display area
        left_layout = QVBoxLayout()

        # Create a widget to display the result
        self.result_widget = DisplayWidget()
        self.result_display = self.result_widget.as_display()
        self.result_display.set_render_position(DisplayRenderPosition.STRETCH_CENTER)

        left_layout.addWidget(self.result_widget)
        main_layout.addLayout(left_layout, 3)

        # Right side: controls
        btn_layout = QVBoxLayout()

        # Frame count selection
        self.radio_frames2 = QRadioButton("2 Frames")
        self.radio_frames4 = QRadioButton("4 Frames")
        self.radio_frames4.setChecked(True)

        self.radio_frames2.clicked.connect(self.on_frames_clicked)
        self.radio_frames4.clicked.connect(self.on_frames_clicked)

        btn_layout.addWidget(QLabel("Frame Count:"))
        btn_layout.addWidget(self.radio_frames2)
        btn_layout.addWidget(self.radio_frames4)
        btn_layout.addSpacing(15)

        # Exposure time multiplier sliders
        btn_layout.addWidget(QLabel("Exposure Factors:"))

        self.factors = []
        self.factors.append(BasicSlider(0.01, 32.0, 0.5, 0.01, parent=self))
        self.factors.append(BasicSlider(0.01, 32.0, 2.0, 0.01, parent=self))
        self.factors.append(BasicSlider(0.01, 32.0, 8.0, 0.01, parent=self))
        self.factors.append(BasicSlider(0.01, 32.0, 32.0, 0.01, parent=self))

        for i, sld in enumerate(self.factors):
            btn_layout.addWidget(QLabel(f"Factor {i}"))
            btn_layout.addWidget(sld)

        btn_layout.addSpacing(15)

        # Capture button
        self.btn_snap = QPushButton("Snap & Process HDR")
        self.btn_snap.setMinimumHeight(40)
        self.btn_snap.clicked.connect(self.on_snap)
        btn_layout.addWidget(self.btn_snap)

        btn_layout.addSpacing(10)

        # Save images checkbox info
        btn_layout.addWidget(QLabel("Images saved to current directory"))

        btn_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(btn_layout, 1)

        self.setLayout(main_layout)

        # Show factor 1 and 2 initially (for 4 frame mode)
        self.on_frames_clicked()

    def apply_theme(self) -> None:
        """Apply the current theme to this dialog."""
        if self.resource_selector:
            style_manager = get_style_manager()
            style_manager.apply_theme(self.resource_selector.get_theme())

    def on_frames_clicked(self):
        """Show the exposure factor sliders depending on
        whether 2 or 4 frames are to be captured.
        """
        if self.radio_frames4.isChecked():
            self.factors[1].setVisible(True)
            self.factors[2].setVisible(True)
        else:
            self.factors[1].setVisible(False)
            self.factors[2].setVisible(False)

    def on_snap(self):
        """Start the snap and HDR calculation process"""
        if not self.grabber.is_device_valid:
            QMessageBox.warning(
                self,
                "HDR Capture",
                "No device selected.",
                QMessageBox.StandardButton.Ok,
            )
            return

        self.btn_snap.setEnabled(False)
        self.snap_and_process()

    def calc_exposure_times(self, exposure_time: float) -> list[float]:
        """Create a list of exposure times for the images to be captured.

        Args:
            exposure_time (float): Current exposure time

        Returns:
            list[float]: Array containing the exposure times
        """
        times = []

        if self.radio_frames2.isChecked():
            times.append(exposure_time * self.factors[0].get_value())
            times.append(exposure_time * self.factors[3].get_value())
        else:
            times = [exposure_time * f.get_value() for f in self.factors]

        return times

    def acquire_multi_frame_output_mode(
        self, prop_map: PropertyMap, exposure_times: list[float]
    ) -> list[ImageBuffer]:
        """Setup the multi frame output mode and capture images. The number
        of captured images is determined by length of exposure_times array.

        Args:
            prop_map (PropertyMap): The camera's device property map
            exposure_times (list[float]): Array of exposure times to be used

        Returns:
            list[ImageBuffer]: List of the captured images
        """
        buffer_list = []
        prop_map.set_value(PropId.MULTI_FRAME_SET_OUTPUT_MODE_ENABLE, True)

        prop_map.set_value(
            PropId.MULTI_FRAME_SET_OUTPUT_MODE_EXPOSURE_TIME0,
            exposure_times[0],
        )
        prop_map.set_value(
            PropId.MULTI_FRAME_SET_OUTPUT_MODE_EXPOSURE_TIME1,
            exposure_times[1],
        )

        if len(exposure_times) == 4:
            prop_map.set_value(
                PropId.MULTI_FRAME_SET_OUTPUT_MODE_FRAME_COUNT, "4 Frames"
            )
            prop_map.set_value(
                PropId.MULTI_FRAME_SET_OUTPUT_MODE_EXPOSURE_TIME2,
                exposure_times[2],
            )
            prop_map.set_value(
                PropId.MULTI_FRAME_SET_OUTPUT_MODE_EXPOSURE_TIME3,
                exposure_times[3],
            )
        else:
            prop_map.set_value(
                PropId.MULTI_FRAME_SET_OUTPUT_MODE_FRAME_COUNT, "2 Frames"
            )

        prop_map.set_value(PropId.MULTI_FRAME_SET_OUTPUT_MODE_CUSTOM_GAIN, False)

        # We need to wait for three images to be sure, the new settings
        # are effective in the camera.
        self.listener.start_capture(3)
        self.listener.capture_end_event.wait(3)

        self.listener.start_capture(len(exposure_times))

        success = self.listener.capture_end_event.wait(5)

        if success:
            for buffer in self.listener.buffer_list:
                buffer_list.append(buffer)
        else:
            print("Timeout during multi-frame capture")

        prop_map.set_value(PropId.MULTI_FRAME_SET_OUTPUT_MODE_ENABLE, False)

        return buffer_list

    def snap_single_frame(
        self,
        exposure_time: float,
        prop_map: PropertyMap,
        buffer_list: list[ImageBuffer],
    ) -> None:
        """Snap a single frame on software trigger.

        Args:
            exposure_time (float): Exposure time to be used for the frame.
            prop_map (PropertyMap): The device property map of self.grabber.
            buffer_list (list[ImageBuffer]): The list of buffers,
            that receives the image
        """
        prop_map.set_value(PropId.EXPOSURE_TIME, exposure_time)
        self.listener.start_capture(1)
        prop_map.execute_command(PropId.TRIGGER_SOFTWARE)

        success = self.listener.capture_end_event.wait(2)

        if success:
            buffer_list.append(self.listener.buffer_list[0])
        else:
            print("Timeout during software trigger capture")

    def acquire_software_trigger(
        self, prop_map: PropertyMap, exposure_times: list[float]
    ) -> list[ImageBuffer]:
        """Capture a number of images using software trigger.

        Args:
            prop_map (PropertyMap): The cameras's device property map.
            exposure_times (list[float]): The list of exposure times to use. Its
            length determines the number of images to capture.

        Returns:
            list[ImageBuffer]: A list of captured images.
        """
        buffer_list = []
        prop_map.set_value(PropId.TRIGGER_MODE, "On")
        # Wait a moment for the camera getting ready for triggering.
        fps = prop_map.get_value_float(PropId.ACQUISITION_FRAME_RATE)
        time.sleep(2.0 / fps)

        for exposure in exposure_times:
            self.snap_single_frame(exposure, prop_map, buffer_list)

        prop_map.set_value(PropId.TRIGGER_MODE, "Off")

        return buffer_list

    def enable_automatics(self, prop_map: PropertyMap, value: str) -> None:
        """Turn the automatics of the camera off or on

        Args:
            prop_map (PropertyMap): The device property map of the camera
            value (str): Value to be set. Can be "Off" or "Continuous"
        """
        prop_map.set_value(PropId.EXPOSURE_AUTO, value)
        prop_map.set_value(PropId.GAIN_AUTO, value)
        prop_map.try_set_value(PropId.BALANCE_WHITE_AUTO, value)

        # Iris is on motorized zoom cameras only.
        prop_map.try_set_value(PropId.IRIS_AUTO, value)

    def snap_and_process(self):
        """Snap an image with different exposure times and process them to an HDR image.
        Steps are:
        - Disable camera automatics and get current exposure time.
        - Calculate the different exposure times. That indicates the count of images to capture too.
        - Capture images, try to use multi frame output mode. If that fails, use software trigger instead.
        - Process the images into an HDR image.
        - Save and display the images.
        - Enable camera automatics.
        """

        def worker():
            try:
                start = time.time()
                prop_map = self.grabber.device_property_map

                self.enable_automatics(prop_map, "Off")

                current_exposure_time = prop_map.get_value_float(PropId.EXPOSURE_TIME)

                exposure_times = self.calc_exposure_times(current_exposure_time)

                try:
                    buffer_list = self.acquire_multi_frame_output_mode(
                        prop_map, exposure_times
                    )

                except IC4Exception:
                    buffer_list = self.acquire_software_trigger(
                        prop_map, exposure_times
                    )

                if not buffer_list:
                    self._poll_signals.error.emit("No images captured")
                    return

                wrap_list = [b.numpy_wrap() for b in buffer_list]
                print(f"Time taken to capture images was {time.time()-start} seconds")

                # Merge Mertens is used as HDR image merger
                merger = cv2.createMergeMertens()
                res_merger = merger.process(wrap_list)
                res_8bit = np.clip(res_merger * 255, 0, 255).astype("uint8")

                print(f"Time taken to run the code was {time.time()-start} seconds")

                # Save the captured and processed images
                for i, b in enumerate(buffer_list):
                    b.save_as_jpeg(f"hdr_capture_{i+1}.jpg")

                cv2.imwrite("hdr_fusion_mertens.jpg", res_8bit)

                # Restore previous exposure time that was determined by exposure auto
                prop_map.set_value(PropId.EXPOSURE_TIME, current_exposure_time)

                self.enable_automatics(prop_map, "Continuous")

                # Show the result (pass it through the signal)
                self._hdr_result = res_8bit
                self._poll_signals.finished.emit()

            except Exception as e:
                self._poll_signals.error.emit(str(e))

        # Run in background thread
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_capture_finished(self):
        """Called when HDR capture and processing is complete."""
        self.show_hdr_image(self._hdr_result)
        self.btn_snap.setEnabled(True)
        QMessageBox.information(
            self,
            "HDR Capture Complete",
            "HDR image has been processed and saved.",
            QMessageBox.StandardButton.Ok,
        )

    def _on_capture_error(self, error_msg: str):
        """Called when an error occurs during capture."""
        self.btn_snap.setEnabled(True)
        QMessageBox.critical(
            self,
            "HDR Capture Error",
            f"An error occurred: {error_msg}",
            QMessageBox.StandardButton.Ok,
        )

    def show_hdr_image(self, image: np.typing.NDArray[Any]):
        """Show the numpy image on the result display.
        An ic4 display is used for this, therefore
        the image must be copied into a buffer of a
        buffer pool

        Args:
            image (np.typing.NDArray[Any]): The numpy array containing the image
        """
        poolbuffer = self.pool.get_buffer(
            ImageType(PixelFormat.BGR8, image.shape[1], image.shape[0])
        )
        matdest = poolbuffer.numpy_wrap()

        mask = np.full(image.shape, 255, dtype=np.uint8)
        cv2.copyTo(image, mask, matdest)

        self.result_display.display_buffer(poolbuffer)
