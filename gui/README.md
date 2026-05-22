# app/

PyQt6 GUI for the Yb magnetometer experiment. Originally adapted from [ic4-examples/python/qt6/demoapp](https://github.com/TheImagingSource/ic4-examples/tree/master/python/qt6/demoapp).

## Entry Point

```bash
python ./app/app.py
```

`Library.init_context()` (IC4 SDK) wraps the entire GUI lifecycle — already handled in `app.py`. Do not instantiate `MainWindow` outside this context.

## Structure

| Path | Description |
|------|-------------|
| `app.py` | Entry point |
| `mainwindow.py` | Main UI (700+ lines), IC4 `Grabber`/`QueueSink`, custom `QEvent` types |
| `display_roi.py` | ROI display widget |
| `hdr.py` | HDR exposure utilities |
| `dc_power.py` | DC power utilities |
| `settings/settings.json` | Hand-editable config (main) |
| `settings/device.json` | IC4 auto-generated — do not edit |
| `settings/codecconfig.json` | IC4 auto-generated — do not edit |
| `resources/style_manager.py` | Singleton theme management (light/dark/auto) |
| `resources/styles/` | QSS stylesheets (base, dark override, light override) |
| `dialogs/` | All device dialogs + reusable controls |
| `dialogs/controls/` | Reusable widgets (`BasicSlider`, property tree, etc.) |

## Dialog Pattern

Each dialog in `dialogs/` wraps a driver from `devices/` using this pattern:

1. `ThreadPoolExecutor(max_workers=1)` owns all device I/O
2. Poll timer fires `_on_poll_tick()` on the main thread
3. `_on_poll_tick()` submits `_poll_worker()` to the executor (background thread)
4. `_poll_worker()` calls `driver.poll_all()` and returns a snapshot dataclass
5. `_on_poll_finished()` receives the snapshot and updates UI — **only place that touches widgets**
6. `closeEvent()` cancels the executor and calls `driver.disconnect()`

Dialogs are lazy-instantiated on toolbar/menu click, not in `MainWindow.__init__`.

## Adding a New Device

1. Create `devices/new_device.py` — see [`../devices/README.md`](../devices/README.md) for the driver contract.
2. Create `app/dialogs/new_device_dialog.py` following the dialog pattern above.
3. Export from `app/dialogs/__init__.py`.
4. Add a toolbar/menu entry in `mainwindow.py` with lazy instantiation:
   ```python
   self._new_device_dialog: NewDeviceDialog | None = None
   # in menu handler:
   if self._new_device_dialog is None:
       self._new_device_dialog = NewDeviceDialog(self)
   self._new_device_dialog.show()
   ```

## Notable YbMag Additions (vs. ic4-demoapp)

- Dynamic light/dark/auto theming via `resources/style_manager.py`
- Thorlabs ELL6 rotary motor dialog (laser polarization tuning)
- Rigol DP832A power supply dialog (static B-field coil control)
- Digilent Analog Discovery 2 dialog (trigger signal control)
- Custom camera overlays and ROI selection
- PySide6 dialogs from the C++ ic4-examples ported to PyQt6
