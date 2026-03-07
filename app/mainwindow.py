from threading import Lock
import gc
from pathlib import Path
from typing import cast

# PyQT6 imports
from PyQt6.QtCore import (
    QStandardPaths,
    QDir,
    QTimer,
    QEvent,
    QFileInfo,
    Qt,
)
from PyQt6.QtGui import QAction, QKeySequence, QCloseEvent
from PyQt6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QLabel,
    QPushButton,
    QApplication,
    QFileDialog,
    QToolBar,
)

# ImagingControl4, direct import for typing
from imagingcontrol4.imagebuffer import ImageBuffer
from imagingcontrol4.grabber import Grabber
from imagingcontrol4.queuesink import (
    QueueSinkListener,
    QueueSink,
)
from imagingcontrol4.imagetype import ImageType
from imagingcontrol4.videowriter import (
    VideoWriter,
    VideoWriterType,
)
from imagingcontrol4.ic4exception import IC4Exception
from imagingcontrol4.display import DisplayRenderPosition
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.properties import Property, PropInteger

from resources.resourceselector import get_resource_selector
from resources.style_manager import get_style_manager, ThemeMode

# local imports
from display_roi import DisplayWidgetROI
from dialogs import (
    PropertyDialog,
    DeviceSelectionDialog,
    SettingsDialog,
    PowerSupplyDialog,
    HDRDialog,
    RotaryMotorDialog,
    DigilentDialog,
)
from devices.rigol_dp832a import PowerSupplyManager

GOT_PHOTO_EVENT = QEvent.Type(QEvent.Type.User + 1)
DEVICE_LOST_EVENT = QEvent.Type(QEvent.Type.User + 2)
SETTINGS_PATH = Path(__file__).parent / "settings" / "settings.json"


class GotPhotoEvent(QEvent):
    def __init__(self, buffer: ImageBuffer):
        QEvent.__init__(self, GOT_PHOTO_EVENT)
        self.buffer = buffer  # Store buffer as attribute


class MainWindow(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)

        # Make sure the %appdata%/demoapp directory exists
        self.save_pictures_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        self.save_videos_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MoviesLocation
        )

        # Store device and codec config files locally in settings folder
        settings_dir = Path(__file__).parent / "settings"
        settings_dir.mkdir(exist_ok=True)
        self.device_file = str(settings_dir / "device.json")
        self.codec_config_file = str(settings_dir / "codecconfig.json")

        self.shoot_photo_mutex = Lock()
        self.shoot_photo = False

        self.capture_to_video = False
        self.video_capture_pause = False

        self.device_property_map = None
        self._trigger_mode_prop = None
        self._trigger_mode_notify = None

        # ROI history for undo/redo (stores tuples of offset_x, offset_y, width, height)
        self.roi_history = []  # Stack of previous ROI states
        self.roi_redo_stack = []  # Stack for redo operations

        self.grabber = Grabber()
        self.grabber.event_add_device_lost(
            lambda g: QApplication.postEvent(self, QEvent(DEVICE_LOST_EVENT))
        )

        # Capture outer self for use in inner Listener class
        main_window = self

        class Listener(QueueSinkListener):
            def sink_connected(
                self,
                sink: QueueSink,
                image_type: ImageType,
                min_buffers_required: int,
            ) -> bool:
                # Allocate more buffers than suggested, because we temporarily take some buffers
                # out of circulation when saving an image or video files.
                sink.alloc_and_queue_buffers(min_buffers_required + 2)
                return True

            def sink_disconnected(self, sink: QueueSink):
                pass

            def frames_queued(self, sink: QueueSink):
                buf = sink.pop_output_buffer()

                # Update display widget with current buffer for pixel inspection
                main_window.video_widget.set_current_buffer(buf)

                # Connect the buffer's chunk data to the device's property map
                # This allows for properties backed by chunk data to be updated
                assert main_window.device_property_map is not None
                main_window.device_property_map.connect_chunkdata(buf)

                with main_window.shoot_photo_mutex:
                    if main_window.shoot_photo:
                        main_window.shoot_photo = False

                        # Send an event to the main thread with a reference to
                        # the main thread of our GUI.
                        QApplication.postEvent(main_window, GotPhotoEvent(buf))

                if main_window.capture_to_video and not main_window.video_capture_pause:
                    try:
                        main_window.video_writer.add_frame(buf)
                    except IC4Exception as ex:
                        pass

        self.sink = QueueSink(Listener())

        self.property_dialog = None
        self.device_selection_dialog = None
        self.settings_dialog = None
        self.power_supply_dialog = None
        self.rotary_motor_dialog = None
        self.hdr_dialog = None
        self.digilent_dialog = None

        # Power supply manager (Qt-free backend)
        self.power_supply_manager = PowerSupplyManager()

        self.video_writer = VideoWriter(VideoWriterType.MP4_H264)

        self.createUI()

        try:
            self.display = self.video_widget.as_display()
            self.display.set_render_position(DisplayRenderPosition.STRETCH_CENTER)
        except Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

        if QFileInfo.exists(self.device_file):
            try:
                self.grabber.device_open_from_state_file(self.device_file)
                self.onDeviceOpened()
            except Exception as e:
                QMessageBox.information(
                    self,
                    "",
                    f"Loading last used device failed: {e}",
                    QMessageBox.StandardButton.Ok,
                )

        if QFileInfo.exists(self.codec_config_file):
            try:
                self.video_writer.property_map.deserialize_from_file(
                    self.codec_config_file
                )
            except Exception as e:
                QMessageBox.information(
                    self,
                    "",
                    f"Loading last codec configuration failed: {e}",
                    QMessageBox.StandardButton.Ok,
                )

        self.updateControls()

    def createUI(self):
        self.resize(1024, 768)

        selector = get_resource_selector()

        self.device_select_act = QAction(
            selector.loadIcon("images/camera.png"), "&Select", self
        )
        self.device_select_act.setStatusTip("Select a video capture device")
        self.device_select_act.setShortcut(QKeySequence.StandardKey.Open)
        self.device_select_act.triggered.connect(self.onSelectDevice)

        self.device_properties_act = QAction(
            selector.loadIcon("images/imgset.png"), "&Properties", self
        )
        self.device_properties_act.setStatusTip("Show device property dialog")
        self.device_properties_act.setCheckable(True)
        self.device_properties_act.triggered.connect(self.onDeviceProperties)

        self.device_driver_properties_act = QAction("&Driver Properties", self)
        self.device_driver_properties_act.setStatusTip(
            "Show device driver property dialog"
        )
        self.device_driver_properties_act.triggered.connect(
            self.onDeviceDriverProperties
        )

        self.trigger_mode_act = QAction(
            selector.loadIcon("images/triggermode.png"), "&Trigger Mode", self
        )
        self.trigger_mode_act.setStatusTip("Enable and disable trigger mode")
        self.trigger_mode_act.setCheckable(True)
        self.trigger_mode_act.triggered.connect(self.onToggleTriggerMode)

        # Combined livestream button with play/pause toggle
        self.stream_act = QAction(
            selector.loadIcon("images/green_play.png"), "&Live Stream", self
        )
        self.stream_act.setStatusTip("Start and stop the live stream")
        self.stream_act.setCheckable(True)
        self.stream_act.triggered.connect(self._on_stream_toggle)
        self.stream_pause_icon = selector.loadIcon("images/green_pause.png")
        self.stream_play_icon = selector.loadIcon("images/green_play.png")

        self.shoot_photo_act = QAction(
            selector.loadIcon("images/photo.png"), "&Shoot Photo", self
        )
        self.shoot_photo_act.setStatusTip("Shoot and save a photo")
        self.shoot_photo_act.triggered.connect(self.onShootPhoto)

        # Combined recording button with record/pause toggle
        self.record_act = QAction(
            selector.loadIcon("images/recordstart.png"), "&Capture Video", self
        )
        self.record_act.setToolTip("Capture video into MP4 file")
        self.record_act.setCheckable(True)
        self.record_act.triggered.connect(self._on_record_toggle)
        self.record_pause_icon = selector.loadIcon("images/recordpause.png")
        self.record_start_icon = selector.loadIcon("images/recordstart.png")
        self.record_stop_icon = selector.loadIcon("images/recordstop.png")

        self.record_stop_act = QAction(
            selector.loadIcon("images/recordstop.png"), "&Stop Capture Video", self
        )
        self.record_stop_act.setStatusTip("Stop video capture")
        self.record_stop_act.triggered.connect(self.onStopCaptureVideo)

        self.close_device_act = QAction("Close", self)
        self.close_device_act.setStatusTip("Close the currently opened device")
        self.close_device_act.setShortcuts(QKeySequence.StandardKey.Close)
        self.close_device_act.triggered.connect(self.onCloseDevice)

        self.power_supply_act = QAction(
            selector.loadIcon("images/power.png"), "&Power Supplies", self
        )
        self.power_supply_act.setStatusTip("Open power supply controls")
        self.power_supply_act.setCheckable(True)
        self.power_supply_act.triggered.connect(self.onPowerSupplies)

        self.rotary_motor_act = QAction(
            selector.loadIcon("images/rotary.png"), "&Rotary Motor", self
        )
        self.rotary_motor_act.setStatusTip("Open rotary motor controls")
        self.rotary_motor_act.setCheckable(True)
        self.rotary_motor_act.triggered.connect(self.onRotaryMotor)

        self.digilent_act = QAction(
            selector.loadIcon("images/digilent.png"), "&Digilent", self
        )
        self.digilent_act.setStatusTip("Open Digilent pattern generator")
        self.digilent_act.setCheckable(True)
        self.digilent_act.triggered.connect(self.onDigilent)

        self.hdr_act = QAction(
            selector.loadIcon("images/photo.png"), "&HDR Capture", self
        )
        self.hdr_act.setStatusTip("Open HDR image capture dialog")
        self.hdr_act.setCheckable(True)
        self.hdr_act.triggered.connect(self.onHDRCapture)

        self.apply_roi_act = QAction(
            selector.loadIcon("images/crop.png"), "Apply &ROI to Camera", self
        )
        self.apply_roi_act.setStatusTip("Apply drawn ROI to camera sensor region")
        self.apply_roi_act.setShortcut(QKeySequence("Ctrl+K"))
        self.apply_roi_act.triggered.connect(self.onApplyROI)

        self.reset_roi_act = QAction(
            selector.loadIcon("images/fullsize.png"), "Reset Camera R&OI", self
        )
        self.reset_roi_act.setStatusTip("Reset camera to full sensor region")
        self.reset_roi_act.triggered.connect(self.onResetROI)

        self.undo_roi_act = QAction("&Undo Crop", self)
        self.undo_roi_act.setStatusTip("Undo last ROI crop")
        self.undo_roi_act.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_roi_act.triggered.connect(self.onUndoROI)

        self.redo_roi_act = QAction("&Redo Crop", self)
        self.redo_roi_act.setStatusTip("Redo last undone ROI crop")
        self.redo_roi_act.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_roi_act.triggered.connect(self.onRedoROI)

        settings_act = QAction("&UI Settings", self)
        settings_act.setStatusTip("Configure UI settings (theme, etc.)")
        settings_act.triggered.connect(self.onUISettings)

        exit_act = QAction("E&xit", self)
        exit_act.setShortcut(QKeySequence.StandardKey.Quit)
        exit_act.setStatusTip("Exit program")
        exit_act.triggered.connect(self.close)
        menubar = self.menuBar()
        assert menubar is not None
        file_menu = menubar.addMenu("&File")
        assert file_menu is not None
        file_menu.addAction(settings_act)
        file_menu.addSeparator()
        file_menu.addAction(exit_act)

        device_menu = menubar.addMenu("&Device")
        assert device_menu is not None
        device_menu.addAction(self.device_select_act)
        device_menu.addAction(self.device_properties_act)
        device_menu.addAction(self.device_driver_properties_act)
        device_menu.addAction(self.trigger_mode_act)
        device_menu.addAction(self.stream_act)
        device_menu.addSeparator()
        device_menu.addAction(self.apply_roi_act)
        device_menu.addAction(self.reset_roi_act)
        device_menu.addAction(self.undo_roi_act)
        device_menu.addAction(self.redo_roi_act)
        device_menu.addSeparator()
        device_menu.addAction(self.close_device_act)

        instruments_menu = menubar.addMenu("&Instruments")
        assert instruments_menu is not None
        instruments_menu.addAction(self.power_supply_act)
        instruments_menu.addAction(self.rotary_motor_act)
        instruments_menu.addAction(self.digilent_act)
        instruments_menu.addAction(self.hdr_act)

        capture_menu = menubar.addMenu("&Capture")
        assert capture_menu is not None
        capture_menu.addAction(self.shoot_photo_act)
        capture_menu.addAction(self.record_act)
        capture_menu.addAction(self.record_stop_act)

        toolbar = QToolBar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        toolbar.addAction(self.device_select_act)
        toolbar.addAction(self.device_properties_act)
        toolbar.addSeparator()
        toolbar.addAction(self.trigger_mode_act)
        toolbar.addSeparator()
        toolbar.addAction(self.stream_act)
        toolbar.addSeparator()
        toolbar.addAction(self.apply_roi_act)
        toolbar.addAction(self.reset_roi_act)
        toolbar.addSeparator()
        toolbar.addAction(self.shoot_photo_act)
        toolbar.addSeparator()
        toolbar.addAction(self.record_act)
        toolbar.addAction(self.record_stop_act)
        toolbar.addSeparator()
        toolbar.addAction(self.power_supply_act)
        toolbar.addAction(self.rotary_motor_act)
        toolbar.addAction(self.digilent_act)
        toolbar.addAction(self.hdr_act)

        self.video_widget = DisplayWidgetROI()
        self.video_widget.setMinimumSize(640, 480)
        self.setCentralWidget(self.video_widget)

        # Connect ROI selection signal
        self.video_widget.roi_selected.connect(self.onROISelected)

        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage("Ready")
        self.statistics_label = QLabel("", status_bar)
        status_bar.addPermanentWidget(self.statistics_label)
        status_bar.addPermanentWidget(QLabel("  "))

        # Pixel info label (right side of status bar, after statistics)
        self.pixel_info_label = QLabel("", status_bar)
        self.pixel_info_label.setStyleSheet("color: #888; font-family: monospace;")
        status_bar.addPermanentWidget(self.pixel_info_label)

        # Connect pixel info signal
        self.video_widget.pixel_info.connect(self.pixel_info_label.setText)
        status_bar.addPermanentWidget(QLabel("  "))

        # Camera label as clickable button
        self.camera_label = QPushButton("No Device", status_bar)
        self.camera_label.setFlat(True)
        self.camera_label.setCheckable(True)
        self.camera_label.setObjectName("cameraLabel")
        self.camera_label.clicked.connect(self.onCameraLabelClicked)
        status_bar.addPermanentWidget(self.camera_label)

        self.update_statistics_timer = QTimer()
        self.update_statistics_timer.timeout.connect(self.onUpdateStatisticsTimer)
        self.update_statistics_timer.start()

        # Apply the initial theme (important for dark mode on startup)
        selector = get_resource_selector()
        style_manager = get_style_manager()
        style_manager.apply_theme(selector.get_theme())

    def onCloseDevice(self):
        print(
            f"[onCloseDevice] is_device_open={self.grabber.is_device_open}, is_streaming={self.grabber.is_streaming}"
        )

        if self.capture_to_video:
            self.onStopCaptureVideo()

        # Always attempt stream_stop, even if is_streaming reports False,
        # to handle edge cases where the flag is stale.
        try:
            self.grabber.stream_stop()
            print("[onCloseDevice] stream_stop() succeeded")
        except Exception as e:
            print(f"[onCloseDevice] stream_stop() error (may be expected): {e}")

        # Release ALL references to IC4 native objects before device_close().
        # The IC4 C library ref-counts native handles; if any Python object still
        # wraps one, the driver considers the device "in use" and a subsequent
        # device_open() will fail with "Device already opened".

        # 1. Clear the ImageBuffer held by the display widget (set every frame)
        self.video_widget.set_current_buffer(None)

        # 2. Unregister trigger-mode notification and release the Property ref
        if (
            self._trigger_mode_prop is not None
            and self._trigger_mode_notify is not None
        ):
            try:
                self._trigger_mode_prop.event_remove_notification(
                    self._trigger_mode_notify
                )
            except Exception:
                pass
        self._trigger_mode_prop = None
        self._trigger_mode_notify = None

        # 3. If the property dialog is alive, clear its model so it drops all
        #    Property / PropertyMap handles
        if self.property_dialog is not None:
            self.property_dialog.clear_all()

        # 4. Clear our own property map reference
        self.device_property_map = None

        # 5. Tell the display to drop its current buffer
        self.display.display_buffer(None)

        # 6. Force GC so Python releases the C handles
        gc.collect()

        try:
            self.grabber.device_close()
            print(
                f"[onCloseDevice] device_close() succeeded, is_device_open={self.grabber.is_device_open}"
            )
            print("[onCloseDevice] *** DEVICE CLOSED ***")
        except Exception as e:
            print(f"[onCloseDevice] device_close() FAILED: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to close device: {e}",
                QMessageBox.StandardButton.Ok,
            )

        self.updateCameraLabel()
        self.video_widget.set_pixel_coord_offset(0, 0)
        self.updateControls()

    def closeEvent(self, ev: QCloseEvent):
        """Handle window close event - make sure to stop streaming and close device cleanly."""
        # Stop the statistics timer first to prevent callbacks after cleanup
        if hasattr(self, "update_statistics_timer"):
            self.update_statistics_timer.stop()

        if self.grabber.is_streaming:
            self.grabber.stream_stop()

        if self.grabber.is_device_valid:
            self.grabber.device_save_state_to_file(self.device_file)

        # Clear property dialog models so PropertyMap refs are released
        # before the Library context is torn down
        if self.property_dialog is not None:
            # Clear all IC4 object references first
            self.property_dialog.clear_all()
            # Close the dialog if it's still visible
            if self.property_dialog.isVisible():
                self.property_dialog.close()
            self.property_dialog = None

        # Clear device selection dialog so DeviceInfo / Interface / PropertyMap
        # refs are released before the Library context is torn down.
        if self.device_selection_dialog is not None:
            self.device_selection_dialog.clear_all()
            if self.device_selection_dialog.isVisible():
                self.device_selection_dialog.close()
            self.device_selection_dialog = None

        # Cleanup rotary motor dialog (disconnects motor)
        if self.rotary_motor_dialog is not None:
            self.rotary_motor_dialog.cleanup()
            self.rotary_motor_dialog.close()
            self.rotary_motor_dialog = None

        # Cleanup Digilent dialog
        if self.digilent_dialog is not None:
            self.digilent_dialog.cleanup()
            self.digilent_dialog.close()
            self.digilent_dialog = None

        # Explicitly clean up IC4 objects *before* Library context closes
        # This prevents "Library.init was not called" errors in __del__ methods
        del self.display
        del self.video_writer
        del self.sink
        del self.grabber

        # Force cyclic GC so PropertyMap / Property pointers wrapped by
        # PropertyTreeNode (which have parent<->children cycles) are freed
        # while the IC4 Library context is still alive.
        gc.collect()

    def customEvent(self, ev: QEvent):
        if ev.type() == DEVICE_LOST_EVENT:
            self.onDeviceLost()
        elif ev.type() == GOT_PHOTO_EVENT:
            assert isinstance(ev, GotPhotoEvent)  # for typing
            self.savePhoto(ev.buffer)

    def onCameraLabelClicked(self):
        """Handle camera label button click"""
        if self.camera_label.isChecked():
            self.onSelectDevice()
        else:
            # Close device selection dialog if open
            if self.device_selection_dialog is not None:
                self.device_selection_dialog.close()

    def onSelectDevice(self):
        # If dialog already open, close it
        if (
            self.device_selection_dialog is not None
            and self.device_selection_dialog.isVisible()
        ):
            self.device_selection_dialog.close()
            return

        selector = get_resource_selector()
        self.device_selection_dialog = DeviceSelectionDialog(
            self.grabber, parent=self, resource_selector=selector
        )
        self.device_selection_dialog.apply_theme()
        self.device_selection_dialog.finished.connect(self._onDeviceSelectionClosed)
        self.device_selection_dialog.accepted.connect(self._onDeviceSelected)
        self.camera_label.setChecked(True)
        self.device_selection_dialog.show()

    def _onDeviceSelected(self):
        """Handle device selection accepted"""
        if not self.property_dialog is None:
            self.property_dialog.update_grabber(self.grabber)

        self.onDeviceOpened()
        self.updateControls()

    def _onDeviceSelectionClosed(self):
        """Handle device selection dialog closed"""
        self.camera_label.setChecked(False)
        if self.device_selection_dialog is not None:
            self.device_selection_dialog.clear_all()
        self.device_selection_dialog = None

    def onDeviceProperties(self):
        # If dialog already open, close it
        if self.property_dialog is not None and self.property_dialog.isVisible():
            self.property_dialog.close()
            return

        if self.property_dialog is None:
            selector = get_resource_selector()
            # Include codec properties in a separate tab
            additional_maps = {"Codec Settings": self.video_writer.property_map}
            self.property_dialog = PropertyDialog(
                self.grabber,
                parent=self,
                title="Device Properties",
                resource_selector=selector,
                additional_maps=additional_maps,
                tabbed=selector.get_tabbed_properties(),
            )
            self.property_dialog.apply_theme()
            self.property_dialog.finished.connect(self._onPropertyDialogClosed)
            # set default vis

        self.device_properties_act.setChecked(True)
        self.property_dialog.show()

    def _onPropertyDialogClosed(self):
        """Handle property dialog closed"""
        # Save codec config when properties dialog closes
        self.video_writer.property_map.serialize_to_file(self.codec_config_file)
        # Release IC4 object references to allow proper garbage collection
        if self.property_dialog is not None:
            self.property_dialog.clear_all()
        self.device_properties_act.setChecked(False)
        self.property_dialog = None

    def onDeviceDriverProperties(self):
        selector = get_resource_selector()
        dlg = PropertyDialog(
            self.grabber.driver_property_map,
            parent=self,
            title="Device Driver Properties",
            resource_selector=selector,
        )
        dlg.apply_theme()
        # set default vis

        dlg.exec()

        self.updateControls()

    def onToggleTriggerMode(self):
        try:
            if self.device_property_map is None:
                raise Exception("Device property map is None")
            self.device_property_map.set_value(
                PropId.TRIGGER_MODE, self.trigger_mode_act.isChecked()
            )
        except Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

    def onShootPhoto(self):
        with self.shoot_photo_mutex:
            self.shoot_photo = True

    def _get_current_roi_state(self) -> tuple[int, int, int, int] | None:
        """Get current camera ROI state as (offset_x, offset_y, width, height)."""
        if not self.grabber.is_device_valid:
            return None
        try:
            prop_map = self.grabber.device_property_map
            offset_x = prop_map.get_value_int(PropId.OFFSET_X)
            offset_y = prop_map.get_value_int(PropId.OFFSET_Y)
            width = prop_map.get_value_int(PropId.WIDTH)
            height = prop_map.get_value_int(PropId.HEIGHT)
            return (offset_x, offset_y, width, height)
        except Exception as e:
            print(f"Error getting ROI state: {e}")
            return None

    def _save_roi_to_history(self):
        """Save current ROI state to history before changing it."""
        current_state = self._get_current_roi_state()
        if current_state:
            self.roi_history.append(current_state)
            # Clear redo stack when new action is taken
            self.roi_redo_stack.clear()

    def _sync_pixel_coord_offset(self):
        """Sync display pixel coordinate offset with current camera ROI offset."""
        if not self.grabber.is_device_valid:
            self.video_widget.set_pixel_coord_offset(0, 0)
            return

        try:
            prop_map = self.grabber.device_property_map
            offset_x = prop_map.get_value_int(PropId.OFFSET_X)
            offset_y = prop_map.get_value_int(PropId.OFFSET_Y)
            self.video_widget.set_pixel_coord_offset(offset_x, offset_y)
        except Exception:
            self.video_widget.set_pixel_coord_offset(0, 0)

    def _apply_roi_state(self, offset_x: int, offset_y: int, width: int, height: int):
        """Apply specific ROI state to camera (low-level helper)."""
        if not self.grabber.is_device_valid:
            return False

        # Stop stream if running
        was_streaming = self.grabber.is_streaming
        if was_streaming:
            try:
                self.grabber.stream_stop()
            except Exception as e:
                print(f"Error stopping stream: {e}")
                return False

        try:
            prop_map = self.grabber.device_property_map
            prop_map.set_value(PropId.OFFSET_AUTO_CENTER, "Off")

            width_prop = prop_map.find(PropId.WIDTH)
            height_prop = prop_map.find(PropId.HEIGHT)
            offset_x_prop = prop_map.find(PropId.OFFSET_X)
            offset_y_prop = prop_map.find(PropId.OFFSET_Y)

            if not all(
                isinstance(p, PropInteger)
                for p in (width_prop, height_prop, offset_x_prop, offset_y_prop)
            ):
                raise RuntimeError("Missing integer ROI properties on camera")

            width_prop = cast(PropInteger, width_prop)
            height_prop = cast(PropInteger, height_prop)
            offset_x_prop = cast(PropInteger, offset_x_prop)
            offset_y_prop = cast(PropInteger, offset_y_prop)

            def _align_down(value: int, increment: int, base: int) -> int:
                if increment <= 1:
                    return value
                return base + ((value - base) // increment) * increment

            def _align_up(value: int, increment: int, base: int) -> int:
                if increment <= 1:
                    return value
                return base + ((value - base + increment - 1) // increment) * increment

            width_inc = max(1, width_prop.increment)
            height_inc = max(1, height_prop.increment)
            off_x_inc = max(1, offset_x_prop.increment)
            off_y_inc = max(1, offset_y_prop.increment)

            requested_width = width
            requested_height = height

            # If requested ROI is smaller than minimum, expand size and shift offsets
            # so ROI center stays approximately the same.
            if requested_width < width_prop.minimum:
                delta_w = width_prop.minimum - requested_width
                offset_x -= delta_w // 2
                width = width_prop.minimum
            if requested_height < height_prop.minimum:
                delta_h = height_prop.minimum - requested_height
                offset_y -= delta_h // 2
                height = height_prop.minimum

            # Enforce min/max and increment for width/height.
            width = max(width_prop.minimum, min(width, width_prop.maximum))
            height = max(height_prop.minimum, min(height, height_prop.maximum))
            width = _align_up(width, width_inc, width_prop.minimum)
            height = _align_up(height, height_inc, height_prop.minimum)
            width = min(
                width, _align_down(width_prop.maximum, width_inc, width_prop.minimum)
            )
            height = min(
                height,
                _align_down(height_prop.maximum, height_inc, height_prop.minimum),
            )

            # Compute legal offset bounds that also keep ROI inside full sensor.
            sensor_width = width_prop.maximum
            sensor_height = height_prop.maximum
            max_offset_x_by_size = sensor_width - width
            max_offset_y_by_size = sensor_height - height

            offset_x_min = offset_x_prop.minimum
            offset_y_min = offset_y_prop.minimum
            offset_x_max = min(offset_x_prop.maximum, max_offset_x_by_size)
            offset_y_max = min(offset_y_prop.maximum, max_offset_y_by_size)

            # Clip + align offsets to valid range/increment.
            offset_x = max(offset_x_min, min(offset_x, offset_x_max))
            offset_y = max(offset_y_min, min(offset_y, offset_y_max))
            offset_x = _align_down(offset_x, off_x_inc, offset_x_min)
            offset_y = _align_down(offset_y, off_y_inc, offset_y_min)
            offset_x = max(offset_x_min, min(offset_x, offset_x_max))
            offset_y = max(offset_y_min, min(offset_y, offset_y_max))

            # Apply dimensions first, then offsets.
            prop_map.set_value(PropId.WIDTH, width)
            prop_map.set_value(PropId.HEIGHT, height)
            prop_map.set_value(PropId.OFFSET_X, offset_x)
            prop_map.set_value(PropId.OFFSET_Y, offset_y)

            # Clear the overlay ROI
            self.video_widget.clear_roi()

            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(
                    f"ROI: Offset ({offset_x}, {offset_y}), Size {width}x{height}",
                    3000,
                )

            self._sync_pixel_coord_offset()
            return True
        except Exception as e:
            QMessageBox.critical(
                self, "Error Applying ROI", f"Failed to apply ROI to camera:\n{str(e)}"
            )
            return False
        finally:
            # Restart stream if it was running
            if was_streaming:
                try:
                    self.grabber.stream_setup(self.sink, self.display)
                except Exception as e:
                    print(f"Error restarting stream: {e}")

    def onApplyROI(self):
        """Apply the drawn ROI to the camera's actual sensor region."""
        # Get ROI from display widget
        roi = self.video_widget.get_roi_camera_coords()
        if roi is None:
            QMessageBox.warning(
                self,
                "No ROI Selected",
                "Please draw an ROI on the image first by clicking and dragging.",
            )
            return

        # Save current state to history before changing
        self._save_roi_to_history()

        # Get current camera offsets to account for already-cropped view
        try:
            current_offset_x = self.grabber.device_property_map.get_value_int(
                PropId.OFFSET_X
            )
            current_offset_y = self.grabber.device_property_map.get_value_int(
                PropId.OFFSET_Y
            )
        except Exception:
            current_offset_x = 0
            current_offset_y = 0

        # Apply the new ROI, adjusting for current camera offset
        # (ROI coordinates are relative to the currently displayed image)
        roi_offset_x, roi_offset_y, width, height = roi
        absolute_offset_x = current_offset_x + roi_offset_x
        absolute_offset_y = current_offset_y + roi_offset_y

        self._apply_roi_state(absolute_offset_x, absolute_offset_y, width, height)

    def onResetROI(self):
        """Reset camera to full sensor region."""
        if not self.grabber.is_device_valid:
            QMessageBox.warning(self, "No Device", "Please open a camera device first.")
            return

        # Save current state to history before resetting
        self._save_roi_to_history()

        try:
            prop_map = self.grabber.device_property_map

            # Get maximum width and height
            width_prop = prop_map.find(PropId.WIDTH)
            height_prop = prop_map.find(PropId.HEIGHT)

            # Cast to PropInteger to access maximum attribute
            max_width = 1920  # default fallback
            max_height = 1080  # default fallback
            if width_prop and isinstance(width_prop, PropInteger):
                max_width = width_prop.maximum
            if height_prop and isinstance(height_prop, PropInteger):
                max_height = height_prop.maximum

            # Apply full sensor ROI
            self._apply_roi_state(0, 0, max_width, max_height)

        except Exception as e:
            QMessageBox.critical(
                self, "Error Resetting ROI", f"Failed to reset camera ROI:\n{str(e)}"
            )

    def onUndoROI(self):
        """Undo the last ROI crop operation."""
        if not self.roi_history:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("No ROI history to undo", 2000)
            return

        # Save current state to redo stack
        current_state = self._get_current_roi_state()
        if current_state:
            self.roi_redo_stack.append(current_state)

        # Pop and apply previous state
        previous_state = self.roi_history.pop()
        offset_x, offset_y, width, height = previous_state
        if self._apply_roi_state(offset_x, offset_y, width, height):
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("Undid ROI crop", 2000)

    def onRedoROI(self):
        """Redo the last undone ROI crop operation."""
        if not self.roi_redo_stack:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("No ROI changes to redo", 2000)
            return

        # Save current state to history
        current_state = self._get_current_roi_state()
        if current_state:
            self.roi_history.append(current_state)

        # Pop and apply redo state
        redo_state = self.roi_redo_stack.pop()
        offset_x, offset_y, width, height = redo_state
        if self._apply_roi_state(offset_x, offset_y, width, height):
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("Redid ROI crop", 2000)

    def onROISelected(self, offset_x: int, offset_y: int, width: int, height: int):
        """Handle ROI selection from the display widget.

        Args:
            offset_x: X offset of ROI in camera coordinates
            offset_y: Y offset of ROI in camera coordinates
            width: Width of ROI in pixels
            height: Height of ROI in pixels
        """
        print(
            f"ROI Selected - Offset: ({offset_x}, {offset_y}), Size: {width}x{height}"
        )

        # TODO: Add UI to confirm and apply ROI to camera
        # For now, just print the values
        # Future implementation could:
        # 1. Show a dialog to confirm the ROI
        # 2. Set camera properties: PropId.OFFSET_X, PropId.OFFSET_Y, PropId.WIDTH, PropId.HEIGHT
        # 3. Restart the stream with new ROI settings

    def onUpdateStatisticsTimer(self):
        if self.grabber is None or not self.grabber.is_device_valid:
            return

        try:
            stats = self.grabber.stream_statistics
            text = f"Frames Delivered: {stats.sink_delivered} Dropped: {stats.device_transmission_error}/{stats.device_underrun}/{stats.transform_underrun}/{stats.sink_underrun}"
            self.statistics_label.setText(text)
            tooltip = (
                f"Frames Delivered: {stats.sink_delivered}"
                f"Frames Dropped:"
                f"  Device Transmission Error: {stats.device_transmission_error}"
                f"  Device Underrun: {stats.device_underrun}"
                f"  Transform Underrun: {stats.transform_underrun}"
                f"  Sink Underrun: {stats.sink_underrun}"
            )
            self.statistics_label.setToolTip(tooltip)
        except Exception:
            pass

    def onDeviceLost(self):
        QMessageBox.warning(
            self,
            "",
            f"The video capture device is lost!",
            QMessageBox.StandardButton.Ok,
        )

        # stop video

        self.updateCameraLabel()
        self.updateControls()

    def onDeviceOpened(self):
        self.device_property_map = self.grabber.device_property_map

        trigger_mode = self.device_property_map.find(PropId.TRIGGER_MODE)
        self._trigger_mode_prop = trigger_mode
        self._trigger_mode_notify = trigger_mode.event_add_notification(
            self.updateTriggerControl
        )

        self.updateCameraLabel()
        self._sync_pixel_coord_offset()

        # if start_stream_on_open
        self.startStopStream()

    def updateTriggerControl(self, p: "Property | None") -> None:
        if not self.grabber.is_device_valid:
            self.trigger_mode_act.setChecked(False)
            self.trigger_mode_act.setEnabled(False)
        else:
            try:
                if self.device_property_map is None:
                    raise Exception("Device property map is None")
                self.trigger_mode_act.setChecked(
                    self.device_property_map.get_value_str(PropId.TRIGGER_MODE) == "On"
                )
                self.trigger_mode_act.setEnabled(True)
            except Exception:
                self.trigger_mode_act.setChecked(False)
                self.trigger_mode_act.setEnabled(False)

    def updateControls(self):
        if not self.grabber.is_device_open:
            self.statistics_label.clear()

        self.device_properties_act.setEnabled(self.grabber.is_device_valid)
        self.device_driver_properties_act.setEnabled(self.grabber.is_device_valid)
        self.stream_act.setEnabled(self.grabber.is_device_valid)
        self.stream_act.setChecked(self.grabber.is_streaming)
        self._update_stream_icon()
        self.shoot_photo_act.setEnabled(self.grabber.is_streaming)
        self.record_stop_act.setEnabled(self.capture_to_video)
        self.record_act.setChecked(self.capture_to_video)
        self._update_record_icon()
        self.close_device_act.setEnabled(self.grabber.is_device_open)

        self.updateTriggerControl(None)

    def updateCameraLabel(self):
        try:
            info = self.grabber.device_info
            self.camera_label.setText(f"{info.model_name} {info.serial}")
            self.camera_label.setEnabled(True)
        except Exception:
            self.camera_label.setText("No Device")
            self.camera_label.setEnabled(True)

    def onPauseCaptureVideo(self):
        self.video_capture_pause = not self.video_capture_pause
        self._update_record_icon()

    def _update_stream_icon(self):
        """Update the livestream button icon based on state"""
        if self.grabber.is_streaming:
            self.stream_act.setIcon(self.stream_pause_icon)
            self.stream_act.setText("&Pause Stream")
        else:
            self.stream_act.setIcon(self.stream_play_icon)
            self.stream_act.setText("&Live Stream")

    def _update_record_icon(self):
        """Update the recording button icon based on state"""
        if self.capture_to_video:
            if self.video_capture_pause:
                self.record_act.setIcon(self.record_start_icon)
                self.record_act.setText("&Resume Video")
            else:
                self.record_act.setIcon(self.record_pause_icon)
                self.record_act.setText("&Pause Video")
        else:
            self.record_act.setIcon(self.record_start_icon)
            self.record_act.setText("&Capture Video")

    def _on_stream_toggle(self):
        """Handle livestream button toggle"""
        self.startStopStream()
        self._update_stream_icon()

    def _on_record_toggle(self):
        """Handle recording button toggle"""
        if self.capture_to_video:
            # If already recording, toggle pause
            self.video_capture_pause = not self.video_capture_pause
            self._update_record_icon()
        else:
            # Start new recording
            self.onStartStopCaptureVideo()

    def onStartStopCaptureVideo(self):
        filters = ["MP4 Video Files (*.mp4)"]

        dialog = QFileDialog(self, "Capture Video")
        dialog.setNameFilters(filters)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDirectory(self.save_videos_directory)

        if dialog.exec():
            full_path = dialog.selectedFiles()[0]
            self.save_videos_directory = QFileInfo(full_path).absolutePath()

            fps = float(25)
            try:
                if self.device_property_map is not None:
                    fps = self.device_property_map.get_value_float(
                        PropId.ACQUISITION_FRAME_RATE
                    )
            except:
                pass

            try:
                self.video_writer.begin_file(
                    full_path, self.sink.output_image_type, fps
                )
            except Exception as e:
                QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)
                return

            self.capture_to_video = True
            self.video_capture_pause = False

        self.updateControls()

    def onStopCaptureVideo(self):
        self.capture_to_video = False
        self.video_capture_pause = False
        self.video_writer.finish_file()
        self.updateControls()

    def _reload_icons(self):
        """Reload all icons for the current theme"""
        selector = get_resource_selector()

        # Reload all action icons
        self.device_select_act.setIcon(selector.loadIcon("images/camera.png"))
        self.device_properties_act.setIcon(selector.loadIcon("images/imgset.png"))
        self.trigger_mode_act.setIcon(selector.loadIcon("images/triggermode.png"))
        self.shoot_photo_act.setIcon(selector.loadIcon("images/photo.png"))
        self.power_supply_act.setIcon(selector.loadIcon("images/power.png"))
        self.rotary_motor_act.setIcon(selector.loadIcon("images/rotary.png"))

        # Reload stream icons
        self.stream_play_icon = selector.loadIcon("images/green_play.png")
        self.stream_pause_icon = selector.loadIcon("images/green_pause.png")
        if self.grabber.is_streaming:
            self.stream_act.setIcon(self.stream_pause_icon)
        else:
            self.stream_act.setIcon(self.stream_play_icon)

        # Reload record icons
        self.record_start_icon = selector.loadIcon("images/recordstart.png")
        self.record_pause_icon = selector.loadIcon("images/recordpause.png")
        self.record_stop_icon = selector.loadIcon("images/recordstop.png")
        if self.capture_to_video:
            if self.video_capture_pause:
                self.record_act.setIcon(self.record_start_icon)
            else:
                self.record_act.setIcon(self.record_pause_icon)
        else:
            self.record_act.setIcon(self.record_start_icon)
        self.record_stop_act.setIcon(self.record_stop_icon)

    def _on_theme_changed(self, theme: ThemeMode):
        """Handle theme change from settings dialog"""
        resource_selector = get_resource_selector()
        style_manager = get_style_manager()

        # Reload icons for new theme
        self._reload_icons()

        # Apply theme to main window and all widgets
        style_manager.apply_theme(theme)

        # Apply theme to open dialogs
        if self.property_dialog is not None and self.property_dialog.isVisible():
            self.property_dialog.apply_theme()
        if (
            self.device_selection_dialog is not None
            and self.device_selection_dialog.isVisible()
        ):
            self.device_selection_dialog.apply_theme()
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            style_manager.apply_theme(theme)
        if (
            self.power_supply_dialog is not None
            and self.power_supply_dialog.isVisible()
        ):
            self.power_supply_dialog.apply_theme()
        if (
            self.rotary_motor_dialog is not None
            and self.rotary_motor_dialog.isVisible()
        ):
            self.rotary_motor_dialog.apply_theme()

    def onUISettings(self):
        """Open the UI settings dialog"""
        # If dialog already open, focus it
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return

        resource_selector = get_resource_selector()
        self.settings_dialog = SettingsDialog(
            resource_selector,
            parent=self,
            on_theme_changed=self._on_theme_changed,  # type: ignore
        )
        # Apply current theme to the settings dialog
        get_style_manager().apply_theme(resource_selector.get_theme())
        self.settings_dialog.finished.connect(self._onSettingsDialogClosed)
        self.settings_dialog.show()

    def _onSettingsDialogClosed(self):
        """Handle settings dialog closed"""
        self.settings_dialog = None

    # -- Power Supplies -----------------------------------------------------

    def onPowerSupplies(self):
        """Open or close the power supply dialog."""
        if (
            self.power_supply_dialog is not None
            and self.power_supply_dialog.isVisible()
        ):
            self.power_supply_dialog.close()
            return

        # Scan on first open
        self.power_supply_manager.scan()

        selector = get_resource_selector()
        self.power_supply_dialog = PowerSupplyDialog(
            self.power_supply_manager, parent=self, resource_selector=selector
        )
        self.power_supply_dialog.apply_theme()
        self.power_supply_dialog.finished.connect(self._onPowerSupplyDialogClosed)
        self.power_supply_act.setChecked(True)
        self.power_supply_dialog.show()

    def _onPowerSupplyDialogClosed(self):
        """Handle power supply dialog closed."""
        self.power_supply_act.setChecked(False)
        self.power_supply_dialog = None

    def onRotaryMotor(self):
        """Open or close the rotary motor dialog."""
        # Create dialog on first use
        if self.rotary_motor_dialog is None:
            # Load motor port from settings
            import json

            port = None
            try:
                with open(SETTINGS_PATH, "r") as f:
                    settings = json.load(f)
                    port = settings.get("rotary_motors", {}).get("port")
            except Exception:
                pass

            self.rotary_motor_dialog = RotaryMotorDialog(port=port, parent=self)
            self.rotary_motor_dialog.apply_theme()
            self.rotary_motor_dialog.finished.connect(self._onRotaryMotorDialogClosed)

        # Toggle visibility
        if self.rotary_motor_dialog.isVisible():
            self.rotary_motor_dialog.hide()
            self.rotary_motor_act.setChecked(False)
        else:
            self.rotary_motor_dialog.show()
            self.rotary_motor_act.setChecked(True)

    def _onRotaryMotorDialogClosed(self):
        """Handle rotary motor dialog closed."""
        self.rotary_motor_act.setChecked(False)

    def onDigilent(self):
        """Open or close the Digilent pattern generator dialog."""
        if self.digilent_dialog is not None and self.digilent_dialog.isVisible():
            self.digilent_dialog.close()
            return

        self.digilent_dialog = DigilentDialog(parent=self)
        self.digilent_dialog.apply_theme()
        self.digilent_dialog.finished.connect(self._onDigilentDialogClosed)
        self.digilent_act.setChecked(True)
        self.digilent_dialog.show()

    def _onDigilentDialogClosed(self):
        """Handle Digilent dialog closed."""
        self.digilent_act.setChecked(False)
        self.digilent_dialog = None

    def onHDRCapture(self):
        """Open or close the HDR capture dialog."""
        if self.hdr_dialog is not None and self.hdr_dialog.isVisible():
            self.hdr_dialog.close()
            return

        if not self.grabber.is_device_valid:
            QMessageBox.warning(
                self,
                "HDR Capture",
                "No device selected. Please select a camera first.",
                QMessageBox.StandardButton.Ok,
            )
            self.hdr_act.setChecked(False)
            return

        self.hdr_dialog = HDRDialog(self.grabber, parent=self)
        self.hdr_dialog.apply_theme()
        self.hdr_dialog.finished.connect(self._onHDRDialogClosed)
        self.hdr_act.setChecked(True)
        self.hdr_dialog.show()

    def _onHDRDialogClosed(self):
        """Handle HDR dialog closed."""
        self.hdr_act.setChecked(False)
        self.hdr_dialog = None

    def startStopStream(self):
        try:
            if self.grabber.is_device_valid:
                if self.grabber.is_streaming:
                    self.grabber.stream_stop()
                    if self.capture_to_video:
                        self.onStopCaptureVideo()
                else:
                    self.grabber.stream_setup(self.sink, self.display)

        except Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

        self.updateControls()

    def savePhoto(self, image_buffer: "ImageBuffer") -> None:
        filters = [
            "Bitmap(*.bmp)",
            "JPEG (*.jpg)",
            "Portable Network Graphics (*.png)",
            "TIFF (*.tif)",
        ]

        dialog = QFileDialog(self, "Save Photo")
        dialog.setNameFilters(filters)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDirectory(self.save_pictures_directory)

        if dialog.exec():
            selected_filter = dialog.selectedNameFilter()

            full_path = dialog.selectedFiles()[0]
            self.save_pictures_directory = QFileInfo(full_path).absolutePath()

            try:
                if selected_filter == filters[0]:
                    image_buffer.save_as_bmp(full_path)
                elif selected_filter == filters[1]:
                    image_buffer.save_as_jpeg(full_path)
                elif selected_filter == filters[2]:
                    image_buffer.save_as_png(full_path)
                else:
                    image_buffer.save_as_tiff(full_path)
            except Exception as e:
                QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)
