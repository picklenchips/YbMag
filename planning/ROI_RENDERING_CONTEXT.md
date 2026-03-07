# ROI Rendering Context (Current State)

## Scope
This document summarizes the **current rendering paths** and the changes made to render ROI on top of the live OpenGL image.

## Entry Path (Top-Down)

1. `MainWindow` creates the video widget:
   - `app/mainwindow.py`: `from displaywindow import EnhancedDisplayWidget`
   - `app/mainwindow.py`: `self.video_widget = EnhancedDisplayWidget()`
2. `MainWindow` creates the display object:
   - `self.display = self.video_widget.as_display()`
3. Stream setup:
   - `self.grabber.stream_setup(self.sink, self.display)`
4. Per-frame callback updates buffer reference:
   - `main_window.video_widget.set_current_buffer(buf)`

## Display Class Structure (Current)

- `_DisplayWindow(QWindow)`
  - Owns `QOpenGLContext`
  - Calls ImagingControl display render (`ExternalOpenGLDisplay.render(...)`)
  - Contains ROI overlay state (`_roi_start`, `_roi_end`, `_roi_is_drawing`)
  - Draws ROI with `QOpenGLPaintDevice + QPainter`

- `DisplayWidget(QWidget)`
  - Wraps `_DisplayWindow` via `QWidget.createWindowContainer(...)`
  - Forwards mouse events from QWindow to QWidget via `eventFilter`

- `EnhancedDisplayWidget(DisplayWidget)`
  - Holds ROI interaction and pixel readback logic
  - Updates `_DisplayWindow` overlay state via `set_roi_overlay(...)`

## Active Render Path in `_DisplayWindow`

In `_DisplayWindow._render_now(...)`:

1. `makeCurrent()`
2. Compute device-pixel size (`w`, `h`)
3. Optional viewport reset (if GL functions are available)
4. Camera image render: `self._display.render(w, h)`
5. ROI overlay draw: `_draw_roi_overlay(w, h, ratio)`
6. Optional viewport reset again
7. `swapBuffers()`
8. `doneCurrent()`
9. `requestUpdate()` (continuous update loop)

## ROI Overlay Draw Path (Updated: 2026-02-27)

`_DisplayWindow._draw_roi_overlay(...)`:

- **NOW USES RAW OPENGL** (replaced QPainter to fix rendering issues)
- **Saves shader program explicitly** with `glGetIntegerv(GL_CURRENT_PROGRAM)` (not part of attribute stack)
- Saves full GL state with `glPushAttrib(GL_ALL_ATTRIB_BITS)` and matrix stacks
- Sets up 2D orthographic projection: `glOrtho(0, device_width, device_height, 0, -1, 1)`
- Scales ROI points from logical pixels to physical pixels via device ratio
- **Disables shader program** with `glUseProgram(0)` to enable fixed-function pipeline for `glColor4f`
- Disables texturing and lighting: `glDisable(GL_TEXTURE_2D)`, `glDisable(GL_LIGHTING)`
- Enables blending for transparency: `glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)`
- Draws:
  - Blue border outline (`GL_LINE_LOOP` with 2px line width, RGB: 0, 100, 255)
  - Optional translucent blue fill while dragging (`GL_QUADS` with 20% alpha)
- Restores all GL state with `glPopMatrix()` and `glPopAttrib()`
- **Restores shader program explicitly** with `glUseProgram(current_program)`

## Mouse/ROI Interaction Path

In `EnhancedDisplayWidget`:

- `mousePressEvent`: sets start/end, marks drawing true, calls `set_roi_overlay(...)`
- `mouseMoveEvent`: updates end while drawing, calls `set_roi_overlay(...)`
- `mouseReleaseEvent`: marks drawing false, calls `set_roi_overlay(...)`, computes camera-space ROI and emits `roi_selected`
- `clear_roi`: clears ROI and calls `set_roi_overlay(None, None, False)`

## Pixel Readback Path

- `set_current_buffer(buf)` stores current frame reference
- If mouse has a last position, pixel info is recomputed immediately for live updates
- `_get_pixel_value_at(...)` maps window coords to image coords and reads from `numpy_wrap()`
- `_format_pixel_info(...)` squeezes single-element values and formats text for status display

## What Changed to Render ROI on Top of OpenGL (Updated: 2026-02-27)

1. Added OpenGL-overlay state to `_DisplayWindow`:
   - `_roi_start`, `_roi_end`, `_roi_is_drawing`
2. Added `_DisplayWindow.set_roi_overlay(...)` to update overlay state and trigger redraw
3. **Implemented `_DisplayWindow._draw_roi_overlay(...)` using raw OpenGL calls**:
   - Replaced QPainter/QOpenGLPaintDevice with direct GL primitives
   - **Manually saves and restores active shader program** (not part of `glPushAttrib` stack)
   - Uses `glPushAttrib(GL_ALL_ATTRIB_BITS)` to save complete GL state
   - Calls `glUseProgram(0)` to disable camera renderer's shader and enable fixed-function `glColor4f`
   - Sets up 2D orthographic projection for overlay rendering
   - Uses `GL_LINE_LOOP` for outline and `GL_QUADS` for optional fill
   - Restores shader program explicitly with `glUseProgram(current_program)`
   - Restores all GL state after drawing to avoid interference
4. Integrated overlay drawing into `_DisplayWindow._render_now(...)` after camera image render and before swap
5. Added try/except guard around overlay draw so overlay failures do not permanently kill camera rendering
6. Added viewport-reset calls before/after overlay draw as additional safety measure
7. Removed legacy `_ROIPaintOverlay` QWidget class path from this file
8. **Removed QPainter, QPen, QColor, QOpenGLPaintDevice imports** (replaced with OpenGL.GL)
9. **Added PyOpenGL dependency** to requirements.txt

## Fix Applied (2026-02-27)

**Previous Issue #1**: ROI appeared, but beginning ROI draw caused camera image to stop rendering.

**Root Cause #1**: GL state interference from `QOpenGLPaintDevice/QPainter` interactions with the camera renderer's OpenGL state. QPainter modifies various GL state (projection matrices, shaders, blend modes, etc.) that were not fully restored, breaking the camera renderer.

**Previous Issue #2**: After switching to raw OpenGL, ROI rectangle appeared as solid black instead of blue.

**Root Cause #2**: Camera renderer leaves shader program active, which ignores fixed-function `glColor4f` calls.

**Previous Issue #3**: After disabling shader with `glUseProgram(0)`, camera image stopped rendering completely.

**Root Cause #3**: Shader programs are NOT saved/restored by `glPushAttrib(GL_ALL_ATTRIB_BITS)`. The camera renderer's shader program was being disabled but never restored, breaking subsequent frames.

**Complete Solution Implemented**:
1. Replaced `QOpenGLPaintDevice + QPainter` with raw OpenGL calls in `_DisplayWindow._draw_roi_overlay()`
2. **Manually save active shader program** with `glGetIntegerv(GL_CURRENT_PROGRAM)` before state changes
3. Use `glPushAttrib(GL_ALL_ATTRIB_BITS)` to save other GL state
4. Set up dedicated 2D orthographic projection for overlay rendering
5. Call `glUseProgram(0)` to disable shaders and enable fixed-function pipeline
6. Disable texturing and lighting to ensure `glColor4f` works correctly
7. Draw ROI using `GL_LINE_LOOP` (outline) and `GL_QUADS` (optional fill) with proper blue color
8. Restore all GL state with `glPopAttrib()` and matrix stack pops
9. **Manually restore shader program** with `glUseProgram(current_program)` to re-enable camera renderer's shader

**Result**: ✅ Camera image renders continuously, ROI overlay displays in proper blue color (RGB: 0, 100, 255) with semi-transparent fill while drawing and transparent area after completion. No GL state pollution between frames.
