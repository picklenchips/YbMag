from PyQt6.QtCore import QTimer, pyqtSignal, QEvent, QTime
from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget, QHBoxLayout, QLabel, QComboBox, QSizePolicy
from typing import Optional

from imagingcontrol4.properties import PropInteger, PropertyVisibility
from imagingcontrol4.propconstants import PropId
from imagingcontrol4.grabber import Grabber, StreamSetupOption

from .props.prop_control_base import StreamRestartInfo, StreamRestartFilterFunction

class BinningDecimationControl(QWidget):
    """
    Single combo box for binning/decimation control. 
    Options: "None", "2x2 Binning", "2x2 Decimation".
    Sets both properties using _set_property_value.
    Both are :py:class:`imagingcontrol4.properties.PropInt` with int_value representing the current setting (1 for off, 2 for x2).
    """
    
    UPDATE_ALL = QEvent.Type.User + 1
    valueChanged = pyqtSignal(int, int)  # Emits (binning_value, decimation_value) on user change

    def __init__(
        self,
        grabber: Grabber,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self.grabber = grabber
        self.prop_map = grabber.device_property_map
        self.binning_vertical: PropInteger = self.prop_map.find(PropId.BINNING_VERTICAL)  # type: ignore
        self.binning_horizontal: PropInteger = self.prop_map.find(PropId.BINNING_HORIZONTAL)  # type: ignore
        self.decimation_vertical: PropInteger = self.prop_map.find(PropId.DECIMATION_VERTICAL)  # type: ignore
        self.decimation_horizontal: PropInteger = self.prop_map.find(PropId.DECIMATION_HORIZONTAL)  # type: ignore
        self.props: list[PropInteger] = [self.binning_vertical, self.binning_horizontal, self.decimation_vertical, self.decimation_horizontal]

        self.restart_filter_func: Optional[StreamRestartFilterFunction] = None

        self._is_destroyed = False
        self._block_signals = False

        self.combo = QComboBox(self)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.addWidget(QLabel("Binning/Decimation", self))
        layout.addWidget(self.combo)
        self.setLayout(layout)

        self.combo.addItem("None")
        self.combo.addItem("2x2 Binning")
        self.combo.addItem("2x2 Decimation")

        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.combo.installEventFilter(self)
        self.destroyed.connect(self._on_destroyed)

        #
        # Base prop control methods and timers for delayed updates (matches PropControlBase logic)
        #
        # set up timer for delayed updates
        self.prev_update = QTime.currentTime()
        self.final_update = QTimer()
        self.final_update.setSingleShot(True)
        self.final_update.setInterval(100)
        self.final_update.timeout.connect(self._on_final_update_timeout)
        
        # Register for property notifications
        try:
            self.notifications = []
            for prop in self.props:
                notify = prop.event_add_notification(
                    lambda prop: self._schedule_update()
                )
                self.notifications.append(notify)
        except Exception:
            pass
        #
        #
        # Initialize combo state based on current property values
        #
        self.update_all()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.FocusIn:
            if watched == self.combo:
                self.on_prop_selected()
        return super().eventFilter(watched, event)

    def on_prop_selected(self):
        # Emit a custom signal or perform an action to indicate this control is selected
        pass

    def _on_destroyed(self):
        self._is_destroyed = True

    def restart_stream(self, restart_info: StreamRestartInfo) -> bool:
        """Restart stream with given info"""
        if not self.grabber:
            return True

        if not restart_info.do_restart:
            return True

        info = restart_info

        if self.restart_filter_func:
            info = self.restart_filter_func(self.grabber, info)

        try:
            self.grabber.stream_setup(info.sink, info.display, info.stream_start_option)
            return True
        except Exception:
            return False

    def _on_final_update_timeout(self):
        """Timer callback for delayed update (matches C++ final_update_ callback)"""
        if self._is_destroyed:
            return

        try:
            QApplication.removePostedEvents(self, self.UPDATE_ALL)
            QApplication.postEvent(self, QEvent(self.UPDATE_ALL))
        except RuntimeError:
            self._is_destroyed = True

    def customEvent(self, event: QEvent):
        """Handle custom events (matches C++ customEvent)"""
        if event.type() == self.UPDATE_ALL:
            if self._is_destroyed:
                return

            current_time = QTime.currentTime()
            if current_time > self.prev_update.addMSecs(66):
                try:
                    self.update_all()
                except Exception:
                    pass
                self.prev_update = current_time
                self.final_update.stop()
            else:
                self.final_update.start()
    
    def stop_stream_if_required(self) -> StreamRestartInfo:
        """Stop stream if property is locked by it"""
        if not self.grabber:
            return StreamRestartInfo()

        try:
            if not self.prop.is_likely_locked_by_stream:
                return StreamRestartInfo()

            if not self.grabber.is_streaming:
                return StreamRestartInfo()

            start_option = (
                StreamSetupOption.ACQUISITION_START
                if self.grabber.is_acquisition_active
                else StreamSetupOption.DEFER_ACQUISITION_START
            )

            try:
                display = self.grabber.display
            except Exception:
                display = None

            try:
                sink = self.grabber.sink
            except Exception:
                sink = None

            self.grabber.stream_stop()

            return StreamRestartInfo(True, start_option, sink, display)
        except Exception:
            return StreamRestartInfo()
    
    def _prop_set_value(self, value: Any, set_func: Callable) -> bool:
        """Set property value with stream restart handling"""
        restart_info = self.stop_stream_if_required()

        try:
            set_func(value)
            return self.restart_stream(restart_info)
        except Exception as e:
            self.restart_stream(restart_info)
            return False
    
    def _set_property_value(self, prop: PropInteger, value):
        def set_func(val):
            prop.value = val

        try:
            if self.grabber and prop.is_likely_locked_by_stream:
                if self.grabber.is_streaming:
                    self.grabber.stream_stop()
            if not self._prop_set_value(value, set_func):
                QMessageBox.critical(self, "", "Failed to set property value")
            prop.value = value
            if self.grabber:
                self.grabber.stream_setup(None, None)
            return True
        except Exception:
            return False

    def _on_combo_changed(self, idx):
        if self._block_signals or idx < 0:
            return
        # None: set all to 1
        if idx == 0:
            self._set_property_value(self.binning_vertical, 1)
            self._set_property_value(self.binning_horizontal, 1)
            self._set_property_value(self.decimation_vertical, 1)
            self._set_property_value(self.decimation_horizontal, 1)
            self.valueChanged.emit(1, 1)
        # 2x2 Binning: binning=2, decimation=1
        elif idx == 1:
            self._set_property_value(self.decimation_vertical, 1)
            self._set_property_value(self.decimation_horizontal, 1)
            self._set_property_value(self.binning_vertical, 2)
            self._set_property_value(self.binning_horizontal, 2)
            self.valueChanged.emit(2, 1)
        # 2x2 Decimation: binning=1, decimation=2
        elif idx == 2:
            self._set_property_value(self.binning_vertical, 1)
            self._set_property_value(self.binning_horizontal, 1)
            self._set_property_value(self.decimation_vertical, 2)
            self._set_property_value(self.decimation_horizontal, 2)
            self.valueChanged.emit(1, 2)
        else:
            self.update_all()

    def update_all(self):
        self._block_signals = True
        try:
            # Set combo index based on current property values
            binning_val = None
            decimation_val = None
            try:
                binning_val = self.binning_vertical.value
            except Exception:
                pass
            try:
                decimation_val = self.decimation_vertical.value
            except Exception:
                pass
            idx = 0
            if binning_val == 2 and decimation_val == 1:
                idx = 1
            elif binning_val == 1 and decimation_val == 2:
                idx = 2
            self.combo.setCurrentIndex(idx)
        finally:
            self._block_signals = False

    #
    # PropControlBase Imports
    #
    #
    def _schedule_update(self):
        """Schedule a UI update (matches C++ notification callback)"""
        if self._is_destroyed:
            return

        try:
            from PyQt6.QtWidgets import QApplication

            QApplication.removePostedEvents(self, PropControlBase.UPDATE_ALL)
            QApplication.postEvent(self, QEvent(PropControlBase.UPDATE_ALL))
        except RuntimeError:
            self._is_destroyed = True