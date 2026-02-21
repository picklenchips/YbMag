"""
Base class for property controls
Translated from C++ PropControlBase.h
"""

from PyQt6.QtCore import QEvent, QTime, QTimer
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from typing import Callable, Optional, Any
from dataclasses import dataclass

from imagingcontrol4.grabber import Grabber, StreamSetupOption
from imagingcontrol4.sink import Sink
from imagingcontrol4.display import Display
from imagingcontrol4.properties import Property


@dataclass
class StreamRestartInfo:
    """Information for restarting a stream"""

    do_restart: bool = False
    stream_start_option: StreamSetupOption = StreamSetupOption.DEFER_ACQUISITION_START
    sink: Optional[Sink] = None
    display: Optional[Display] = None


StreamRestartFilterFunction = Callable[[Grabber, StreamRestartInfo], StreamRestartInfo]
PropSelectedFunction = Callable[[Property], None]


class PropControlBase(QWidget):
    """Base class for all property control widgets"""

    UPDATE_ALL = QEvent.Type.User + 1

    def __init__(
        self,
        prop: Property,
        parent: Optional[QWidget],
        grabber: Optional[Grabber],
    ):
        super().__init__(parent)

        self.prop = prop
        self.grabber = grabber
        self.notify = None
        self._is_destroyed = False  # Flag to track if widget is being destroyed

        self.setLayout(QHBoxLayout(self))
        if layout := self.layout():
            layout.setSpacing(4)
            layout.setContentsMargins(8, 7, 0, 7)

        self.prev_update = QTime.currentTime()
        self.final_update = QTimer()
        self.final_update.setSingleShot(True)
        self.final_update.setInterval(100)
        self.final_update.timeout.connect(self._on_final_update_timeout)

        self.restart_filter_func: Optional[StreamRestartFilterFunction] = None
        self.prop_selected_func: Optional[PropSelectedFunction] = None

        # Connect to destroyed signal to ensure cleanup
        self.destroyed.connect(self._on_destroyed)

        # Register for property notifications
        try:
            self.notify = self.prop.event_add_notification(
                lambda prop: self._schedule_update()
            )
        except Exception:
            pass

    def _on_destroyed(self):
        """Called when widget is being destroyed"""
        self._is_destroyed = True
        # Stop any pending updates
        if self.final_update:
            self.final_update.stop()
        self._unregister_notification()

    def _unregister_notification(self):
        """Unregister property notification"""
        if self.notify is not None:
            try:
                self.prop.event_remove_notification(self.notify)
                self.notify = None
            except Exception:
                pass

    def __del__(self):
        """Python destructor - unregister notification"""
        self._unregister_notification()

    def register_prop_selected(self, fn: PropSelectedFunction):
        """Register callback for when property is selected"""
        self.prop_selected_func = fn

    def register_stream_restart_filter(self, fn: StreamRestartFilterFunction):
        """Register callback for stream restart filtering"""
        self.restart_filter_func = fn

    def on_prop_selected(self):
        """Called when property control gains focus"""
        if self.prop_selected_func:
            self.prop_selected_func(self.prop)

    def should_display_as_locked(self) -> bool:
        """Check if property should be displayed as locked"""
        try:
            prop_is_locked = self.prop.is_locked

            if self.grabber and prop_is_locked:
                if self.grabber.is_streaming and self.prop.is_likely_locked_by_stream:
                    return False

            return prop_is_locked
        except Exception:
            return True

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

    def prop_set_value(self, value: Any, set_func: Callable) -> bool:
        """Set property value with stream restart handling"""
        restart_info = self.stop_stream_if_required()

        try:
            set_func(value)
            return self.restart_stream(restart_info)
        except Exception as e:
            self.restart_stream(restart_info)
            return False

    def prop_execute(self, execute_func: Callable) -> bool:
        """Execute property command with stream restart handling"""
        restart_info = self.stop_stream_if_required()

        try:
            execute_func()
            return self.restart_stream(restart_info)
        except Exception:
            self.restart_stream(restart_info)
            return False

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

    def _on_final_update_timeout(self):
        """Timer callback for delayed update (matches C++ final_update_ callback)"""
        if self._is_destroyed:
            return

        try:
            from PyQt6.QtWidgets import QApplication

            QApplication.removePostedEvents(self, PropControlBase.UPDATE_ALL)
            QApplication.postEvent(self, QEvent(PropControlBase.UPDATE_ALL))
        except RuntimeError:
            self._is_destroyed = True

    def customEvent(self, event: QEvent):
        """Handle custom events (matches C++ customEvent)"""
        if event.type() == PropControlBase.UPDATE_ALL:
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

    def update_all(self):
        """Update all UI elements - must be implemented by subclasses"""
        raise NotImplementedError("Subclass must implement update_all()")
