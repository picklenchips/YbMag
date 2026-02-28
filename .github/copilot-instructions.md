# AI Coding Agent Instructions

This document guides AI coding agents working on the Yb Magnetometer Control & Simulation project.

## Project Overview

A PyQt6-based experimental control GUI for the Ytterbium magnetometer with support for:
- **Camera control** via IC4 (The Imaging Source)
- **Power supply control** via Rigol DP832A (USB/SCPI)
- **Motor control** via ELL6 rotary motors (.NET/pythonnet)
- **Trigger signals** via Digilent USB devices (cffi)
- **Real-time image acquisition** and video recording
- **Property inspection** for camera and device features
- **Dynamic theming** (light/dark modes)

**Entry point**: `python ./app/app.py`

## Architecture Patterns

### 1. Device Drivers (Qt-Free, Root Level)

**Location**: `{rigol_dp832a.py, camera.py, digilent.py, ELL6_rotary_motor.py}`

**Pattern**: Pure Python drivers with NO PyQt6 dependency. Thread-safe with per-device locks.

- **Example**: `rigol_dp832a.py`
  - Zero Qt imports
  - Thread-safe SCPI communication via PyVISA
  - Dataclass snapshots (`ChannelInfo`) avoid shared state
  - Public interface: `connect()`, `poll_all()`, properties (voltage, current, etc.)

**Why**: Enables use in scripts, Jupyter notebooks, and alternative UIs without GUI overhead.

**Convention**: When adding device drivers, keep them Qt-independent.

### 2. UI Layer (Dialogs Wrapping Drivers)

**Location**: `app/dialogs/{power_supply_dialog.py, property_dialog.py, device_selection_dialog.py}`

**Pattern**: PyQt6 dialog classes that:
1. Instantiate pure Python drivers
2. Use `ThreadPoolExecutor` for background polling
3. Emit Qt signals when data arrives
4. Use event posting for thread-safe GUI updates

**Example Pattern** (from `power_supply_dialog.py`):
```python
class PowerSupplyDialog(QDialog):
    def _on_poll_tick(self):
        # Background thread polls devices
        self._executor.submit(self._poll_worker)
    
    def _poll_worker(self):
        # Runs in thread: call device methods
        for supply in self._manager.supplies:
            supply.poll_all()  # Updates cached state
        self._poll_signals.finished.emit()  # Signal main thread
    
    def _on_poll_finished(self):
        # Main thread: update widgets from cached state
        for section in self._sections:
            section.refresh()
```

**Convention**: Never block the GUI thread. Always use background threads for I/O.

### 3. Settings Management (JSON Configuration)

**Location**: `app/resources/settings.json`

**Pattern**: Single JSON file for persistent configuration with typed structure.

**Current Structure**:
```json
{
  "theme": "auto|light|dark",
  "tabbed_properties": true,
  "power_supplies": {
    "DP8B240900562": {
      "name": "right",
      "model": "DP832A",
      "channels": {
        "1": {"name": "Channel 1"},
        ...
      }
    }
  }
}
```

**Usage Pattern**:
- Load with `json.load(open(settings_path))`
- Use `dict.get()` with defaults for safe access
- Reload settings on user interaction (no caching issues)
- Store device serial numbers as keys for lookups

### 4. Global Singleton Services

**Location**: `app/resources/style_manager.py`

**Pattern**: Factory function returns global instance.

```python
def get_style_manager() -> StyleManager:
    global _style_manager_instance
    if _style_manager_instance is None:
        _style_manager_instance = StyleManager()
    return _style_manager_instance
```

**Use**: Access from any dialog without passing parent references.

**Convention**: For one-off services (theming, resource selection), use singleton factory pattern.

### 5. Reusable UI Components

**Location**: `app/dialogs/controls/{basic_slider.py, property_tree_widget.py, etc.}`

**Pattern**: QWidget subclasses with clear public interfaces.

**Example** (`basic_slider.py`):
- Constructor defines behavior: range, step, callback
- `valueChanged` signal for user interactions only (programmatic `set_value()` doesn't emit)
- Separates value storage from display logic

**Convention**: Signals emit ONLY on user interaction, not programmatic updates—prevents feedback loops.

## Critical Workflows

### Running the Application
```powershell
cd C:\Shared\Yb\Dynamics\Control
python ./app/app.py
```
- Initializes IC4 library context
- Creates MainWindow (camera acquisition, property dialogs)
- Dialogs lazy-load (e.g., PowerSupplyDialog opens on toolbar click)

### Adding a New Device Type
1. Create Qt-free driver at root level (e.g., `new_device.py`)
   - Pure Python, thread-safe locks, dataclass snapshots
   - No imports that require GUI
2. Create dialog in `app/dialogs/new_device_dialog.py`
   - Wrap driver with ThreadPoolExecutor polling
   - Use `_PollSignals` for cross-thread communication
3. Register in `app/dialogs/__init__.py`
4. Add toolbar button/menu item in `mainwindow.py`

### Updating Settings
- Edit `app/resources/settings.json` directly
- Reload in code with `_load_settings()` (no caching)
- Use serial numbers or resource IDs as keys for device-specific configs

### Debugging Device Communication
- Drivers can be tested standalone: `python -c "from rigol_dp832a import RigolDP832A; ..."`
- Use PyVISA resource string (e.g., `"USB0::0x1AB1::0x0E21::..."`) to target specific devices
- Check `supply.serial` and `supply.is_connected` for initial diagnostics

## Key Dependencies & Integration Points

| Component | Purpose | Integration |
|-----------|---------|-------------|
| **PyQt6** | GUI framework | Event loops, signals/slots, threading |
| **IC4 (imagingcontrol4)** | Camera SDK | Requires `Library.init_context()` in main |
| **PyVISA** | SCPI communication | USB-TMC for power supplies |
| **pythonnet** | .NET interop | ELL motor control |
| **cffi** | C interop | Digilent trigger signals |
| **numpy, opencv** | Image processing | Camera image buffers |

## Common Code Patterns to Follow

### Thread-Safe Device Access
```python
# In driver (e.g., rigol_dp832a.py)
with self._lock:
    self._inst.write("VOLT 5.0")
    value = self._inst.query("VOLT?")
```

### Cross-Thread Signal Communication
```python
# In dialog
self._poll_signals = QObject()
self._poll_signals.finished = pyqtSignal()
self._poll_signals.finished.connect(self._on_poll_finished)

# Background thread
self._poll_signals.finished.emit()  # Queued delivery to main thread
```

### Fallback Configuration
```python
# Load with defaults
config = settings.get("power_supplies", {})
supply_name = config.get(serial, {}).get("name", serial)  # Falls back to serial if not configured
```

### Event-Safe GUI Updates
```python
# Use QApplication.postEvent for thread-safe GUI updates
QApplication.postEvent(self, GotPhotoEvent(buf))

# Handle custom events in MainWindow.eventFilter() or customEvent()
class GotPhotoEvent(QEvent):
    def __init__(self, buffer):
        super().__init__(GOT_PHOTO_EVENT)
        self.buffer = buffer
```

## Project Structure Reference

```
Control/
├── app/
│   ├── demoapp.py              # Entry point with Library.init_context()
│   ├── mainwindow.py           # Main UI, camera acquisition, event handling
│   ├── displaywindow.py        # Video display widget
│   ├── dialogs/
│   │   ├── power_supply_dialog.py    # Device management pattern
│   │   ├── property_dialog.py        # Camera properties UI
│   │   ├── device_selection_dialog.py
│   │   ├── settings_dialog.py
│   │   └── controls/           # Reusable components
│   │       ├── basic_slider.py # Pattern: value + programmatic set
│   │       ├── property_tree_widget.py
│   │       └── property_info_box.py
│   └── resources/
│       ├── settings.json       # Single source of truth for config
│       ├── style_manager.py    # Global singleton theming
│       ├── resourceselector.py
│       ├── images/             # icons
│       └── styles/             # QSS theme files
├── devices/
│   ├── rigol_dp832a.py         # Qt-free driver (PowerSupplyManager, RigolDP832A)
│   ├── camera.py               # Qt-free camera wrapper
│   ├── digilent.py             # Qt-free trigger control
│   ├── ell_motor.py            # Qt-free motor control (.NET)
├── simulation/
│   └── ATSolver.py
└── analysis/                   # Image analysis scripts
```

## When Adding Features

- **New device support?** → Create Qt-free driver + PyQt6 dialog wrapper
- **New UI control?** → Add to `app/dialogs/controls/`, ensure `set_value()` doesn't emit signals
- **New settings?** → Add schema to `app/resources/settings.json`, load with `json.load()` on use
- **Background task?** → Use `ThreadPoolExecutor`, emit Qt signals on completion
- **Global service?** → Use singleton factory pattern in `app/resources/`

## Testing & Validation

- Device drivers: Test standalone in Python REPL (no GUI required)
- Dialogs: Run `python ./app/demoapp.py` and interact with UI
- Settings changes: Verify JSON format with `json.tool` and reload in GUI
- Threading: Use `threading.Thread` profiling to ensure no GUI hangs

