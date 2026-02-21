from threading import Lock
import gc

# PyQT6 imports
from PyQt6.QtCore import (
    QStandardPaths,
    QDir,
    QTimer,
    QEvent,
    QFileInfo,
    Qt,
    QCoreApplication,
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
from imagingcontrol4.properties import Property

from resources.resourceselector import get_resource_selector
from resources.style_manager import get_style_manager, ThemeMode

# local imports
from displaywindow import EnhancedDisplayWidget
from dialogs import PropertyDialog, DeviceSelectionDialog, SettingsDialog

GOT_PHOTO_EVENT = QEvent.Type(QEvent.Type.User + 1)
DEVICE_LOST_EVENT = QEvent.Type(QEvent.Type.User + 2)


class GotPhotoEvent(QEvent):
    def __init__(self, buffer: ImageBuffer):
        QEvent.__init__(self, GOT_PHOTO_EVENT)
        self.buffer = buffer  # Store buffer as attribute


class MainWindow(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)

        # Make sure the %appdata%/demoapp directory exists
        appdata_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        QDir(appdata_directory).mkpath(".")

        self.save_pictures_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        self.save_videos_directory = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.MoviesLocation
        )

        self.device_file = appdata_directory + "/device.json"
        self.codec_config_file = appdata_directory + "/codecconfig.json"

        self.shoot_photo_mutex = Lock()
        self.shoot_photo = False

        self.capture_to_video = False
        self.video_capture_pause = False

        self.device_property_map = None
        self._trigger_mode_prop = None
        self._trigger_mode_notify = None

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
        device_menu.addAction(self.close_device_act)

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
        toolbar.addAction(self.shoot_photo_act)
        toolbar.addSeparator()
        toolbar.addAction(self.record_act)
        toolbar.addAction(self.record_stop_act)

        self.video_widget = EnhancedDisplayWidget()
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
        if self._trigger_mode_prop is not None and self._trigger_mode_notify is not None:
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
            for tree in self.property_dialog._trees.values():
                tree.clear_model()
            self.property_dialog._map = None
            self.property_dialog._grabber = None

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
        self.updateControls()

    def closeEvent(self, ev: QCloseEvent):
        if self.grabber.is_streaming:
            self.grabber.stream_stop()

        if self.grabber.is_device_valid:
            self.grabber.device_save_state_to_file(self.device_file)

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
        self.device_properties_act.setChecked(False)

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
        if not self.grabber.is_device_valid:
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
