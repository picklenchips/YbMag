# dialogs/

PyQt6 `QDialog` subclasses — one per hardware device or camera subsystem. All follow the poll pattern described in [`../README.md`](../README.md): device I/O runs in `ThreadPoolExecutor(max_workers=1)`, UI updates only in `_on_poll_finished()`. Dialogs are lazy-instantiated on toolbar/menu click.

## Exports

| Class | File | Description |
|-------|------|-------------|
| `PropertyDialog` | `camera_property_dialog.py` | IC4 property tree browser for the active camera |
| `DeviceSelectionDialog` | `camera_selection_dialog.py` | IC4 device picker (lists available cameras) |
| `CameraSettingsDialog` | `camera_settings_dialog.py` | Binning, decimation, and capture settings |
| `SettingsDialog` | `settings_dialog.py` | Editor for `settings/settings.json` |
| `PowerSupplyDialog` | `power_supply_dialog.py` | Rigol DP832A coil supply control |
| `HDRDialog` | `hdr_dialog.py` | HDR exposure-stack acquisition control |
| `RotaryMotorDialog` | `rotary_motor.py` | Thorlabs ELL6 rotary motor (laser polarization) |
| `DigilentDialog` | `digilent_dialog.py` | Digilent Analog Discovery 2 trigger/waveform |
| `DisplayWidget` | `display.py` | Live IC4 camera display widget |
| `SaveSettingsDialog` | `save_settings_dialog.py` | Save / load IC4 device settings to file |

Reusable sub-widgets live in [`controls/`](controls/).
