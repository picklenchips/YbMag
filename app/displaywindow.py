r"""
Window displaying image data from a stream.
2/18/2026
Original source: C:\ProgramData\miniconda3\envs\control\Lib\site-packages\imagingcontrol4\pyside6\display.py
1. Refactored from PySide6 to PyQt6
2. Added :py:attr:`_DisplayWindow._display` for easier access to the display object
3. General typing cleanup and code comments
"""

from weakref import ref

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QCoreApplication,
    QPoint,
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QMainWindow, QLabel
from PyQt6.QtGui import (
    QWindow,
    QOpenGLContext,
    QSurface,
    QExposeEvent,
    QPlatformSurfaceEvent,
    QPainter,
    QPen,
    QColor,
    QMouseEvent,
)

from imagingcontrol4.display import Display, ExternalOpenGLDisplay
from imagingcontrol4.imagebuffer import ImageBuffer


class _DisplayWindow(QWindow):
    _owner: QWidget
    _context: QOpenGLContext
    _displayRef: ref[ExternalOpenGLDisplay] | None = None
    _is_initialized: bool = False

    def __init__(self, owner: QWidget):
        QWindow.__init__(self)
        self._owner = owner
        self._context = QOpenGLContext(self)
        self.setSurfaceType(QSurface.SurfaceType.OpenGLSurface)

    @property
    def _display(self) -> ExternalOpenGLDisplay | None:
        """Dereferenced :py:attr:`_displayRef`"""
        if self._displayRef is not None:
            return self._displayRef()
        return None

    def _lazy_initialize(self):
        if self._display is None:  # object was destroyed
            self._is_initialized = False
        elif not self._is_initialized:
            # not initialized AND display object exists -> initialize
            self._context.setFormat(self.requestedFormat())
            self._context.create()
            self._context.makeCurrent(self)
            self._display.initialize()
            self._context.doneCurrent()
            self._is_initialized = True
        return self._is_initialized

    def _uninitialize(self):
        if self._display is not None:
            self._display.notify_window_closed()
        self._is_initialized = False

    def _render_now(self, force: bool = False):
        """Render the display if the window is exposed, or if force=True."""
        if not self.isExposed() and not force:
            return

        if self._lazy_initialize():
            self._context.makeCurrent(self)

            ratio = self._owner.devicePixelRatio()
            w = int(self.width() * ratio)
            h = int(self.height() * ratio)

            if self._display is not None:
                self._display.render(w, h)

            self._context.swapBuffers(self)
            self._context.doneCurrent()

        self.requestUpdate()

    def event(self, ev: QEvent) -> bool:
        """Handle window events for initialization, rendering, and cleanup."""
        if ev.type() == QEvent.Type.PlatformSurface:
            assert isinstance(ev, QPlatformSurfaceEvent)  # for typing
            if (
                ev.surfaceEventType()
                == QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated
            ):
                self._lazy_initialize()
            else:
                self._uninitialize()
            return QWindow.event(self, ev)
        if ev.type() == QEvent.Type.UpdateRequest:
            self._render_now()
            return True
        return QWindow.event(self, ev)

    def exposeEvent(self, ev: QExposeEvent):
        self._render_now()

    def as_display(self) -> Display:
        if self._display is None:
            display = ExternalOpenGLDisplay()
            self._displayRef = ref(display)
            return display
        else:
            return self._display


class DisplayWidget(QWidget):
    """A Qt display widget

    Use :meth:`.as_display` to get a :class:`.Display` representing the display. The display can then be passed to :meth:`.Grabber.stream_setup`.
    """

    _display_window: _DisplayWindow
    _display_container: QWidget

    def __init__(self):
        QWidget.__init__(self)

        self._display_window = _DisplayWindow(self)
        self._display_container = QWidget.createWindowContainer(
            self._display_window, self
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._display_container, 1)
        self.setLayout(layout)

        self._display_window.installEventFilter(self)

    def as_display(self) -> Display:
        """Returns a :class:`.Display` to connect this display widget to a data stream.

        Returns:
            Display: A :class:`.Display` for this display widget.

        Pass the return value of this function to :meth:`.Grabber.stream_setup` to display live video on this display widget.
        """
        return self._display_window.as_display()

    def eventFilter(self, object: QObject, event: QEvent) -> bool:
        if object != self._display_window:
            return False

        if (
            event.type() == QEvent.Type.MouseButtonPress
            or event.type() == QEvent.Type.MouseButtonRelease
        ):
            QCoreApplication.sendEvent(self, event)
            return False  # // Let QWindow see the up/down events so that it can generate the ContextMenu event if required
        elif (
            event.type() == QEvent.Type.ContextMenu
            or event.type() == QEvent.Type.MouseMove
            or event.type() == QEvent.Type.MouseButtonDblClick
            or event.type() == QEvent.Type.Wheel
        ):
            QCoreApplication.sendEvent(self, event)
            return True
        else:
            return False


class _ROIPaintOverlay(QWidget):
    """Transparent overlay widget that paints the ROI rectangle."""

    def __init__(self, parent: "EnhancedDisplayWidget"):
        super().__init__(parent)
        self.enhanced_display = parent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)

    def leaveEvent(self, event):
        """Handle mouse leave to clear pixel info."""
        super().leaveEvent(event)
        self.enhanced_display.pixel_info.emit("")

    def paintEvent(self, event):
        """Paint the ROI rectangle on top of the display."""
        # Don't call super() to avoid clearing/painting background

        # Draw ROI rectangle if exists
        if (
            self.enhanced_display._roi_start_window is not None
            and self.enhanced_display._roi_end_window is not None
        ):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Draw rectangle
            pen = QPen(QColor(0, 255, 0), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)

            rect = QRect(
                self.enhanced_display._roi_start_window,
                self.enhanced_display._roi_end_window,
            ).normalized()
            painter.drawRect(rect)

            # Draw semi-transparent fill if currently drawing
            if self.enhanced_display._is_drawing_roi:
                painter.fillRect(rect, QColor(0, 255, 0, 30))

            painter.end()


class EnhancedDisplayWidget(DisplayWidget):
    """Enhanced display widget with ROI selection and pixel info on hover.

    Features:
    - Shows pixel coordinates and values when hovering over the image
    - Allows drawing a rectangular ROI by clicking and dragging
    - Emits roi_selected signal with camera coordinates (offset_x, offset_y, width, height)
    - Emits pixel_info signal with pixel coordinates and values
    """

    roi_selected = pyqtSignal(
        int, int, int, int
    )  # offset_x, offset_y, width, height in camera coords
    pixel_info = pyqtSignal(str)  # pixel info string: "px (x, y) = value"

    def __init__(self):
        super().__init__()

        self._current_buffer: ImageBuffer | None = None
        self._roi_start_window: QPoint | None = None
        self._roi_end_window: QPoint | None = None
        self._is_drawing_roi: bool = False

        # Enable mouse tracking to get move events without button press
        self._display_container.setMouseTracking(True)
        self.setMouseTracking(True)

        # Create transparent overlay widget for ROI drawing
        # This must be done AFTER the parent __init__ so we have access to _display_container
        self._roi_overlay = _ROIPaintOverlay(self)
        # Set overlay to fill the entire widget
        self._roi_overlay.setGeometry(0, 0, self.width(), self.height())
        self._roi_overlay.raise_()  # Bring to front above display container

    def set_current_buffer(self, buffer: ImageBuffer | None):
        """Store reference to currently displayed buffer for pixel inspection.

        Call this method whenever a new buffer is displayed to enable pixel value inspection.

        Args:
            buffer: The ImageBuffer currently being displayed, or None to clear
        """
        self._current_buffer = buffer

    def get_roi_camera_coords(self) -> tuple[int, int, int, int] | None:
        """Get ROI rectangle in camera/image pixel coordinates.

        Returns:
            Tuple of (offset_x, offset_y, width, height) in image pixel coordinates,
            or None if no valid ROI is defined
        """
        if (
            self._roi_start_window is None
            or self._roi_end_window is None
            or self._current_buffer is None
        ):
            return None

        # Get image dimensions
        img_type = self._current_buffer.image_type
        img_width = img_type.width
        img_height = img_type.height

        # Get window dimensions
        win_width = self._display_container.width()
        win_height = self._display_container.height()

        # Convert window coords to image coords
        x1, y1 = self._window_to_image_coords(
            self._roi_start_window.x(),
            self._roi_start_window.y(),
            win_width,
            win_height,
            img_width,
            img_height,
        )
        x2, y2 = self._window_to_image_coords(
            self._roi_end_window.x(),
            self._roi_end_window.y(),
            win_width,
            win_height,
            img_width,
            img_height,
        )

        # Ensure correct order and bounds
        x_min = max(0, min(x1, x2))
        y_min = max(0, min(y1, y2))
        x_max = min(img_width, max(x1, x2))
        y_max = min(img_height, max(y1, y2))

        width = x_max - x_min
        height = y_max - y_min

        # Only return valid ROI (non-zero area)
        if width > 0 and height > 0:
            return (x_min, y_min, width, height)
        return None

    def clear_roi(self):
        """Clear the current ROI selection."""
        self._roi_start_window = None
        self._roi_end_window = None
        self._is_drawing_roi = False
        self._roi_overlay.update()  # Trigger repaint to clear ROI

    def _window_to_image_coords(
        self, win_x: int, win_y: int, win_w: int, win_h: int, img_w: int, img_h: int
    ) -> tuple[int, int]:
        """Convert window coordinates to image pixel coordinates.

        Assumes image is scaled to fit window while maintaining aspect ratio (FIT mode).
        """
        # Calculate aspect ratios
        win_aspect = win_w / win_h if win_h > 0 else 1
        img_aspect = img_w / img_h if img_h > 0 else 1

        if win_aspect > img_aspect:
            # Window is wider - image is constrained by height
            scale = win_h / img_h if img_h > 0 else 1
            img_display_w = img_w * scale
            img_display_h = win_h
            offset_x = (win_w - img_display_w) / 2
            offset_y = 0
        else:
            # Window is taller - image is constrained by width
            scale = win_w / img_w if img_w > 0 else 1
            img_display_w = win_w
            img_display_h = img_h * scale
            offset_x = 0
            offset_y = (win_h - img_display_h) / 2

        # Convert to image coordinates
        img_x = int((win_x - offset_x) / scale) if scale > 0 else 0
        img_y = int((win_y - offset_y) / scale) if scale > 0 else 0

        return (img_x, img_y)

    def _get_pixel_value_at(
        self, win_x: int, win_y: int
    ) -> tuple[int, int, object] | None:
        """Get pixel value at window coordinates.

        Returns:
            Tuple of (image_x, image_y, pixel_value) or None if out of bounds
        """
        if not self._current_buffer:
            return None

        img_type = self._current_buffer.image_type
        img_width = img_type.width
        img_height = img_type.height
        win_width = self._display_container.width()
        win_height = self._display_container.height()

        img_x, img_y = self._window_to_image_coords(
            win_x, win_y, win_width, win_height, img_width, img_height
        )

        # Check bounds
        if img_x < 0 or img_x >= img_width or img_y < 0 or img_y >= img_height:
            return None

        # Get numpy array and read pixel
        try:
            np_array = self._current_buffer.numpy_wrap()
            pixel_value = np_array[img_y, img_x]
            return (img_x, img_y, pixel_value)
        except Exception:
            return None

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for ROI drawing and pixel info display."""
        super().mouseMoveEvent(event)

        # Update ROI rectangle if drawing
        if self._is_drawing_roi:
            self._roi_end_window = event.pos()
            self._roi_overlay.update()  # Trigger repaint of overlay

        # Update pixel info
        if self._current_buffer:
            pixel_info = self._get_pixel_value_at(event.pos().x(), event.pos().y())
            if pixel_info:
                img_x, img_y, value = pixel_info

                # Format value based on type
                try:
                    if hasattr(value, "__len__") and not isinstance(
                        value, (str, bytes)
                    ):  # Multi-channel (e.g., RGB)
                        # Convert numpy array to tuple of native Python ints
                        try:
                            value_tuple = tuple(int(v.item()) if hasattr(v, "item") else int(v) for v in value)  # type: ignore
                            value_str = str(value_tuple)
                        except Exception:
                            value_str = str(tuple(value))  # type: ignore
                    else:
                        # Convert numpy scalar to native Python type
                        if hasattr(value, "item"):
                            value_str = str(int(value.item()))  # type: ignore
                        else:
                            value_str = str(
                                int(value) if isinstance(value, (int, float)) else value
                            )
                except Exception:
                    value_str = str(value)

                info_text = f"px ({img_x}, {img_y}) = {value_str}"
                # Emit signal instead of showing label
                self.pixel_info.emit(info_text)
            else:
                self.pixel_info.emit("")
        else:
            self.pixel_info.emit("")

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press to start ROI selection."""
        super().mousePressEvent(event)

        if event.button() == Qt.MouseButton.LeftButton:
            self._roi_start_window = event.pos()
            self._roi_end_window = event.pos()
            self._is_drawing_roi = True
            self._roi_overlay.update()  # Trigger paint event

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release to complete ROI selection."""
        super().mouseReleaseEvent(event)

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_roi:
            self._is_drawing_roi = False
            self._roi_end_window = event.pos()
            self._roi_overlay.update()  # Trigger paint event

            # Emit signal with camera coordinates
            roi = self.get_roi_camera_coords()
            if roi:
                print(
                    f"ROI selected: offset_x={roi[0]}, offset_y={roi[1]}, width={roi[2]}, height={roi[3]}"
                )
                self.roi_selected.emit(*roi)

    def leaveEvent(self, event):
        """Clear pixel info when mouse leaves widget."""
        super().leaveEvent(event)
        self.pixel_info.emit("")
        # Also forward to overlay
        if self._roi_overlay:
            self._roi_overlay.leaveEvent(event)

    def resizeEvent(self, event):
        """Handle resize events to keep overlay in sync."""
        super().resizeEvent(event)
        # Resize overlay to match this widget
        if self._roi_overlay:
            self._roi_overlay.setGeometry(0, 0, self.width(), self.height())


class DisplayWindow(QMainWindow):
    """A Qt display window

    Use :meth:`.as_display` to get a :class:`.Display` representing the display. The display can then be passed to :meth:`.Grabber.stream_setup`.
    """

    _display_widget: DisplayWidget

    def __init__(self, **kwargs):
        QMainWindow.__init__(self, **kwargs)

        self._display_widget = DisplayWidget()
        self.setCentralWidget(self._display_widget)

    def as_display(self) -> Display:
        """Returns a :class:`.Display` to connect this display window to a data stream.

        Returns:
            Display: A :class:`.Display` for this display window.

        Pass the return value of this function to :meth:`.Grabber.stream_setup` to display live video on this display window.
        """
        return self._display_widget.as_display()
