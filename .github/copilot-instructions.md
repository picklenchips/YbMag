# AI Coding Agent Instructions

This document guides AI coding agents working on the Yb Magnetometer Control & Simulation project.

## Project Overview

A PyQt6-based experimental control GUI for the Ytterbium magnetometer with support for:
- **Camera control** via IC4 SDK (The Imaging Source) - fully integrated into MainWindow
- **Power supply control** via Rigol DP832A (USB/SCPI via PyVISA)
- **Motor control** via ELL6 rotary motors (.NET/pythonnet via clr)
- **Trigger signals** via Digilent Analog Discovery 2 (DWF SDK via ctypes)
- **Real-time image acquisition** and video recording with ROI support
- **Property inspection** for IC4 camera features (native IC4 PropertyMap API)
- **Dynamic theming** (light/dark/auto modes)

**Entry point**: `python ./app/app.py`
**Key file**: `app/mainwindow.py` (700+ lines: camera acquisition, UI layout, event handling, dialog management)

## Architecture Patterns

### 1. Device Drivers (Qt-Free, Root Level)

**Location**: `devices/{rigol_dp832a.py, camera.py, digilent.py, ell_motor.py}`

**Pattern**: Pure Python drivers with **zero PyQt6 dependency**. Fully thread-safe with per-device locks.

**Implementation Details**:
- `rigol_dp832a.py`: Wraps PyVISA for SCPI communication. Exports `RigolDP832A` (single supply) and `PowerSupplyManager` (discovery/multi-device). Uses `@dataclass` snapshots (`ChannelInfo`) to avoid shared state.
- `digilent.py`: Wraps DWF SDK (ctypes). Provides `DigitalChannelConfig` dataclass + `DigilentAnalogDiscovery2` class. Zero .NET dependencies.
- `ell_motor.py`: Wraps Thorlabs .NET DLL via pythonnet (clr). Dataclass `MotorInfo` for state snapshots. Only this driver has .NET dependency.
- `camera.py`: **DEPRECATED** — marked with TODO. Camera control is now fully integrated into `mainwindow.py` via IC4 SDK's `Grabber`, `QueueSink`, `PropertyMap` APIs.

**Why This Pattern**:
- Enables unit testing without GUI overhead
- Allows REPL/Jupyter use and standalone scripts
- Decouples device I/O from UI thread concerns

**Critical Constraint**: Device drivers **must not import PyQt6** or any Qt binding. Even importing `from PyQt6.QtCore import pyqtSignal` breaks the reusability contract.

---

### 2. UI Layer (Dialogs Wrapping Drivers)

**Location**: `app/dialogs/{power_supply_dialog.py, rotary_motor.py, digilent_dialog.py, camera_property_dialog.py, settings_dialog.py}`

**Pattern**: PyQt6 QDialog subclasses that:
1. Instantiate pure Python drivers (no blocking on main thread)
2. Use `ThreadPoolExecutor` for background polling
3. Emit Qt signals when data arrives
4. Use `self.finished.connect()` for cleanup on close

**Critical Principle**: **Never block the main thread**. All device I/O must run in a background thread via `ThreadPoolExecutor`.

**Signal Emission Strategy**.
- Emit Qt signals ONLY across thread boundaries (e.g., background thread → main thread)
- Use `pyqtSignal()` on a helper `QObject()` (not the dialog itself) to keep threading intent clear
- Signal emission is thread-safe and queued; the main thread processes it via the event loop

**Cleanup Pattern**: Use `finished.connect()` in `MainWindow` to trigger cleanup (e.g., `self._executor.shutdown(wait=True)`) when dialogs close. This ensures background threads finish gracefully and don't try to access closed Qt objects.

---

### 3. Settings Management (JSON Configuration)

**Location**: `app/settings/{settings.json, device.json, codecconfig.json}`

**Pattern**: Single JSON file (`settings.json`) for user-editable config. Companion files (`device.json`, `codecconfig.json`) for IC4 SDK state persistence.

**Architecture**:
- `settings.json`: Hand-edited config for devices, polling intervals, themes, waypoints, presets
- `device.json` & `codecconfig.json`: Auto-generated IC4 snapshots; **do not edit directly**

**Actual Structure** (from project):
```json
{
  "theme": "auto|light|dark",
  "tabbed_properties": false,
  "power_supply_poll_interval_ms": 500,
  
  "power_supplies": {
    "DP8B240900562": {
      "name": "bottom",
      "model": "DP832A",
      "channels": {
        "1": {"name": "+x"},
        "2": {"name": "-y"},
        "3": {"name": "+y"}
      }
    }
  },
  
  "rotary_motors": {
    "port": 3,
    "11400178_0": {
      "waypoints": {
        "90": 90.00251116071429,
        "180": 180.01004464285714
      }
    }
  },
  
  "digilent": {
    "last_device_serial": "",
    "channel_names": {"0": "Trigger", "1": "Burst"},
    "presets": {
      "_last_session": {
        "digital_channels": [...]
      }
    }
  }
}
```

**Usage Pattern**:
```python
def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json. Called every time; no caching."""
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# Access with defaults
settings = _load_settings()
poll_ms = settings.get("power_supply_poll_interval_ms", 500)
supply_name = settings\
    .get("power_supplies", {})\
    .get(serial_number, {})\
    .get("name", serial_number)  # Fall back to serial if not configured
```

**No Caching Strategy**: Each dialog calls `_load_settings()` on use (not at init). This avoids stale config and allows external edits (e.g., manual JSON updates) to take effect without restarting.

---

### 4. Global Singleton Services

**Location**: `app/resources/style_manager.py`

**Implementation**:
```python
def get_style_manager() -> StyleManager:
    """Thread-safe lazy factory. Returns the global instance."""
    global _style_manager_instance
    if _style_manager_instance is None:
        _style_manager_instance = StyleManager()
    return _style_manager_instance

class StyleManager:
    """Load and apply QSS stylesheets for light/dark/auto themes."""
    def set_theme(self, mode: ThemeMode):        # "auto" | "light" | "dark"
    def get_theme_background_color(self, mode=None) -> QColor:
    def apply_stylesheet(self, app: QApplication):
```

**Usage**:
```python
# From any dialog (no parent ref needed)
style_mgr = get_style_manager()
style_mgr.set_theme("dark")
QApplication.instance().setStyleSheet(style_mgr.apply_stylesheet(QApplication.instance()))
```

**Why**:
- Avoids passing service references through constructor chains
- Ensures single instance across all dialogs
- Simplifies UI initialization in `MainWindow.__init__()`

**One-off services** (not frequently instantiated) use this pattern. Prefer explicit dependency injection for services created multiple times.

---

### 5. Reusable UI Components (Controls)

**Location**: `app/dialogs/controls/{basic_slider.py, property_tree_widget.py, property_tree_model.py, tabbed_property_widget.py}`

**Pattern**: `QWidget` subclasses with clear public interfaces. **Signals emit ONLY on user interaction, never on programmatic updates.**

**Example** (`basic_slider.py`):
```python
class BasicSlider(QWidget):
    """Slider + editable text box. Emits valueChanged ONLY on user interaction."""
    
    valueChanged = pyqtSignal(float)
    
    def __init__(self, min, max, default, step, unit="", parent=None):
        super().__init__(parent)
        self._programmatic = False  # Guard to prevent signal loops
        
        # UI setup...
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.value_edit.returnPressed.connect(self._on_text_edited)
    
    def set_value(self, val: float):
        """Update slider/text WITHOUT emitting valueChanged."""
        self._programmatic = True
        self.slider.setValue(int(round((val - self.min) / self.step)))
        self.value_edit.setText(self._format_value_text(val))
        self._programmatic = False
    
    def _on_slider_changed(self, idx: int):
        """Slider moved by USER → emit signal."""
        if not self._programmatic:
            val = self.min + idx * self.step
            self.value_edit.setText(self._format_value_text(val))
            self.valueChanged.emit(val)  # <-- Emitted here
```

**Why This Design**:
- **No feedback loops**: Setting voltage from polled data doesn't trigger a spurious "voltage changed by user" event
- **Clear intent**: Callers can distinguish user edits (catch `valueChanged`) from external updates (call `set_value()`)
- **Reusability**: Controls work in any context (dialogs, standalone apps, tests)

**Critical Rule for Controls**: `valueChanged` signals are **reserved for user intent**. If you need to notify external listeners of programmatic changes, emit a different signal (e.g., `externalUpdate`).

---

### 6. IC4 PropertyMap & Camera Feature Management

**Location**: `app/mainwindow.py` (camera integration), `app/dialogs/camera_property_dialog.py` (properties UI)

**Pattern**: IC4's `PropertyMap` API handles feature discovery and control. `PropertyDialog` wraps `PropertyTreeWidget` for hierarchical display.

**Key Classes**:
- `Grabber`: Image acquisition (single stream)
- `QueueSink`: Receives `ImageBuffer` callbacks for each frame
- `PropertyMap`: Factory for `Property` objects (read device capabilities)
- `Property`, `PropInteger`, `PropFloat`, etc.: Feature access

**Critical Issue - Memory Management**:
The IC4 library requires careful cleanup of `PropertyMap` objects **before** the `Library` context is closed.

**Problem**: PropertyMap objects held in reference dicts aren't garbage-collected until the dialog is destroyed *after* `Library.init_context()` exits.

**Solution** (already implemented):
```python
# In PropertyDialog.clear_all() and TabbedPropertyWidget._clear_tabs():
self.additional_maps.clear()  # Clear dict of PropertyMap refs
self._additional_maps.clear()

# In MainWindow.closeEvent():
self.property_dialog.clear_all()  # Explicit cleanup before exit
```

**Why This Works**: Clearing the reference dicts allows PropertyMaps to be garbage-collected *while* the Library context is still active, avoiding `RuntimeError: Library.init was not called` in `__del__()`.

---

## Critical Workflows

### Running the Application
```powershell
cd C:\Shared\Yb\Dynamics\Control
python ./app/app.py
```
1. **Entry point**: `app.py` initializes `Library.init_context()` (IC4 SDK requirement)
2. Creates `MainWindow` (builds UI, starts camera acquisition if device available)
3. Dialogs lazy-load on toolbar/menu clicks (e.g., PowerSupplyDialog only created on button press)
4. **Exit**: `Library.init_context()` manager exits, cleans up IC4 resources

**Critical**: `Library.init_context()` must wrap the entire GUI lifecycle. Closing it early (e.g., in closeEvent before dialog cleanup) will cause `RuntimeError` in PropertyMap destructors.

---

### Adding a New Device Type

1. **Create Qt-free driver** at `devices/new_device.py`
   - Pure Python, no Qt imports
   - Thread-safe per-device lock (use `threading.Lock()`)
   - Export a dataclass for state snapshots (e.g., `ChannelInfo`)
   - Clean public API: `connect()`, `disconnect()`, `poll_all()`, properties

2. **Create dialog** at `app/dialogs/new_device_dialog.py`
   - Inherit from `QDialog`
   - Instantiate driver(s) in `__init__`
   - Implement `_on_poll_tick()` → `_poll_worker()` → `_on_poll_finished()` pattern
   - Use `ThreadPoolExecutor(max_workers=1)` for serialized polling
   - Add `closeEvent()` to stop timer and shutdown executor
   - Emit `finished` signal when closed

3. **Register dialog** in `app/dialogs/__init__.py`
   - Add import and `__all__` entry

4. **Launch from MainWindow** (in `app/mainwindow.py`)
   - Add toolbar button or menu item
   - Create dialog on button click (lazy instantiation)
   - Connect `dialog.finished` to cleanup handler

**Example Minimal Dialog**:
```python
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from devices.my_device import MyDevice

class MyDeviceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My Device")
        self._poll_signals = QObject()
        self._poll_signals.finished = pyqtSignal()
        self._poll_signals.finished.connect(self._on_poll_finished)
        
        self._device = MyDevice()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start(500)
    
    def _on_poll_tick(self):
        self._executor.submit(self._poll_worker)
    
    def _poll_worker(self):
        try:
            self._device.poll_all()
            self._poll_signals.finished.emit()
        except Exception as e:
            pass  # Log but don't crash background thread
    
    def _on_poll_finished(self):
        # Update UI from cached state
        pass
    
    def closeEvent(self, event):
        self._poll_timer.stop()
        self._executor.shutdown(wait=True)
        super().closeEvent(event)
```

---

### Updating Settings

1. Edit `app/settings/settings.json` directly (hand-editable; use valid JSON)
2. **No application restart needed**: Dialogs call `_load_settings()` on each poll cycle
3. Use serial numbers or device IDs as keys for lookups (enables multi-device configs)
4. Validate JSON with `python -m json.tool app/settings/settings.json`

**Never cache settings in module-level variables**. Each dialog should load afresh.

---

### Debugging Device Communication

- **Standalone testing**: Device drivers can be tested without GUI:
  ```powershell
  python -c "from devices.rigol_dp832a import RigolDP832A; s = RigolDP832A('USB0::...'); s.connect()"
  ```
- **PyVISA ResourceManager**: List available instruments:
  ```powershell
  python -c "from pyvisa import ResourceManager; print(ResourceManager().list_resources())"
  ```
- **Check connection state**: Use `device.is_connected` and `device.serial` properties
- **Thread safety**: Device methods use internal locking; safe to call from multiple threads
- **No GUI blocking**: Never call `device.poll_all()` from the main thread—use `ThreadPoolExecutor`

---

## Key Dependencies & Integration Points

| Component | Purpose | Integration | Notes |
|-----------|---------|-------------|-------|
| **PyQt6** | GUI framework | Event loops, signals/slots, threading | Use QTimer for background work triggers |
| **IC4 (imagingcontrol4)** | Camera SDK | Requires `Library.init_context()` in main | PropertyMap objects must be cleared before context closes |
| **PyVISA** | SCPI communication | USB-TMC for power supplies | Thread-safe per SCPI spec; supports multi-device discovery |
| **pythonnet (clr)** | .NET interop | ELL6 motor control | Only device driver with .NET dependency. Cross-platform limited to pythonnet availability |
| **cffi** | C interop | Digilent DWF SDK integration | Uses ctypes directly for lower-level control |
| **numpy, opencv** | Image processing | Camera image buffers from IC4 | Required for ROI operations and image analysis |
| **pyvisa** | Instrument control | Rigol power supply SCPI | Handles USB-TMC device enumeration and communication |

## Code Quality & Critical Patterns

### Critical Pattern: Settings Loading Behavior

**Current Implementation**: Dialogs call `_load_settings()` on every poll cycle (NOT cached at dialog init).

**Why This Is Correct**:
- Allows external JSON edits to take effect immediately without restarting
- Prevents stale configuration from persisting across dialog reopen
- Keeps UI in sync with source of truth

**Pattern to Maintain**: Do NOT cache settings at dialog initialization. Load fresh on each polling cycle.

---

### Critical Pattern: No Programmatic Signal Emission in Controls

**Rule**: Control widgets (e.g., BasicSlider) use `_programmatic` guard flags to prevent `valueChanged` signals during programmatic updates (e.g., `set_value()` calls).

**Why This Is Important**:
- Polling updates should not trigger UI feedback loops
- User events must be distinguishable from external updates
- Prevents spurious signal cascades that degrade performance

**Example Anti-pattern**:
```python
# BAD: Polling updates trigger valueChanged signals
def _on_poll_finished(self):
    self.voltage_slider.setValue(voltage)  # Triggers valueChanged! 
    # → User's change handler fires unexpectedly
```

**Correct Pattern**:
```python
# GOOD: Use set_value() which blocks signals
def _on_poll_finished(self):
    self.voltage_slider.set_value(voltage)  # NO signal emitted
```

---

### Critical Pattern: Thread-Safe Device Poll/Cache Architecture

**Design**: All device drivers use a **cache-and-poll** pattern:
1. `poll_all()` method runs in background thread, updates internal state
2. Properties expose cached state (no additional I/O)
3. UI reads from cache via `get_property()` or direct property access

**Why This Works**:
- Single `with self._lock:` block around updates prevents partial reads
- Background thread isolation prevents UI blocking
- Multiple UI threads can safely read cache simultaneously

**Example** (from `rigol_dp832a.py`):
```python
def poll_all(self):
    """Run in background thread; updates cached state."""
    with self._lock:
        for ch in self.channels:
            ch.meas_voltage = float(self._inst.query(...))  # Updates cache
            ch.output_enabled = bool(...)

@property
def channels(self) -> List[ChannelInfo]:
    """Safe read of cached state; no lock needed (generator access)."""
    with self._lock:
        return [dataclasses.replace(ch) for ch in self._channels]  # Copy snapshot
```

**When Adding Device Methods**: Always protect state access with `with self._lock:`. Use dataclass snapshots for returns to avoid shared references.

---

### Known Issues & Workarounds

#### 1. IC4 PropertyMap Cleanup
**Issue**: PropertyMap objects held in dicts aren't garbage-collected before Library context closes.
**Workaround**: Explicitly clear reference dicts in `PropertyDialog.clear_all()` and `TabbedPropertyWidget._clear_tabs()` before dialog closes.
**Files Affected**: `app/dialogs/camera_property_dialog.py`, `app/dialogs/controls/tabbed_property_widget.py`, `app/mainwindow.py`

#### 2. ELL Motor .NET Dependency
**Issue**: `ell_motor.py` requires pythonnet and Thorlabs DLL (Windows only).
**Current State**: Hardcoded DLL path at `C:\Program Files\Thorlabs\Elliptec\Thorlabs.Elliptec.ELLO_DLL.dll`. Raises `FileNotFoundError` if not installed.
**Recommendation**: Consider conditional import or graceful degradation for machines without Thorlabs software.

#### 3. Camera Driver Deprecation
**Issue**: `devices/camera.py` is marked TODO but still present. Camera is fully integrated into mainwindow.py via IC4.
**Action**: Safe to delete once confirmed no other code imports it. Check for any `from devices.camera import` statements first.

---

### Type Hints & Documentation

**Current State**: Most device drivers have good docstrings and type hints. Dialogs are less consistent.

**Guidelines**:
- Device drivers: **Mandatory** type hints on public methods
- Dialogs: **Recommended** type hints, especially for callback handlers that cross thread boundaries
- UI Controls: **Mandatory** docstrings with Signal documentation (see BasicSlider pattern)

---



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
├── pyproject.toml
├── requirements.txt
├── util.py                  # Shared utilities
│
├── app/
│   ├── app.py              # Entry point with Library.init_context()
│   ├── mainwindow.py       # Main UI (700+ lines), camera acquisition, event handling
│   ├── display_roi.py      # ROI display widget
│   ├── hdr.py              # HDR-related utilities
│   ├── dc_power.py         # DC power utilities
│   ├── requirements.txt
│   │
│   ├── settings/           # Persistent configuration & IC4 snapshots
│   │   ├── settings.json          # MAIN CONFIG: hand-editable JSON
│   │   ├── device.json            # Auto-generated by IC4 (do not edit)
│   │   └── codecconfig.json       # Auto-generated by IC4 (do not edit)
│   │
│   ├── resources/
│   │   ├── style_manager.py       # Singleton theme management (light/dark/auto)
│   │   ├── resourceselector.py    # Resource/capability detection
│   │   ├── images/
│   │   │   ├── +theme_dark/
│   │   │   └── +theme_light/
│   │   └── styles/
│   │       ├── base.qss           # Common QSS (colors, fonts, spacing)
│   │       ├── theme_dark.qss     # Dark theme overrides
│   │       └── theme_light.qss    # Light theme overrides
│   │
│   └── dialogs/
│       ├── __init__.py            # Exports all dialogs
│       ├── power_supply_dialog.py         # Rigol DP832A UI (polling + background threads)
│       ├── rotary_motor.py                # Thorlabs ELL6 motor UI
│       ├── digilent_dialog.py             # Digilent trigger signal UI
│       ├── camera_property_dialog.py      # IC4 camera features UI
│       ├── camera_selection_dialog.py     # Device picker for camera
│       ├── settings_dialog.py             # Theme/polling settings
│       ├── hdr_dialog.py                  # HDR exposure sequence
│       ├── display.py                     # Display configuration
│       │
│       └── controls/                      # Reusable UI components
│           ├── basic_slider.py            # Slider + text input (valueChanged on user only)
│           ├── property_controls.py       # Property-specific controls
│           ├── property_info_box.py       # Property metadata display
│           ├── property_tree_model.py     # PropertyMap → QAbstractItemModel
│           ├── property_tree_widget.py    # Tree view for properties
│           ├── tabbed_property_widget.py  # Tabbed layout for properties
│           └── props/                     # Property-specific UI (empty/placeholder)
│
├── devices/                  # Qt-free device drivers (root level: can be tested alone)
│   ├── rigol_dp832a.py       # RigolDP832A class + PowerSupplyManager
│   ├── camera.py             # TODO: DEPRECATED (camera now in mainwindow.py)
│   ├── digilent.py           # DigilentAnalogDiscovery2 (trigger signals)
│   └── ell_motor.py          # ELLMotor wrapper for Thorlabs .NET DLL
│
├── simulation/
│   └── ATSolver.py           # Physics/attenuation simulation
│
├── analysis/
│   ├── analyze_csv.py        # CSV data analysis
│   ├── analyze_pixels.py     # Pixel-level image analysis
│   └── export_pixels_widget.py
│
├── planning/                 # Dev docs / plans (not part of running app)
│   ├── gen_icons.py
│   ├── PLAN_dc_power.md
│   ├── PLAN_digilent_dialog.md
│   ├── PLAN_digilent_driver.md
│   └── ROI_RENDERING_CONTEXT.md
│
├── ic4-examples/             # Reference examples from The Imaging Source (not used)
│   └── (C++, C#, Python examples...)
│
└── .github/
    └── copilot-instructions.md   # This file
```

---

## When Adding Features

### Checklist for New Device Driver
- [ ] **Zero Qt imports** — Driver must be testable standalone in Python REPL
- [ ] **Thread-safe locks** — Guard all I/O and state access with `threading.Lock()`
- [ ] **Dataclass snapshots** — Return copies of state, not shared references (use `dataclasses.replace()`)
- [ ] **Public API** — Clean interface: `connect()`, `disconnect()`, `poll_all()`, properties
- [ ] **Exception handling** — Drivers should log/suppress exceptions, not crash threads
- [ ] **Device discovery** — Implement or expose a discovery mechanism (e.g., `PowerSupplyManager`)

### Checklist for New Dialog
- [ ] **Lazy instantiation** — Dialog created on button click, not at MainWindow init
- [ ] **ThreadPoolExecutor polling** — Background thread with `_on_poll_tick() → _poll_worker() → _on_poll_finished()` pattern
- [ ] **Signal cleanup** — `closeEvent()` stops timer and `executor.shutdown(wait=True)`
- [ ] **Settings integration** — Load config with `_load_settings()` (fresh on each poll)
- [ ] **No blocking calls** — All device I/O in `_poll_worker()`, never main thread
- [ ] **Register in `__init__.py`** — Add import and `__all__` entry

### Checklist for New UI Control
- [ ] **`_programmatic` guard** — Prevent signal loops during `set_value()` calls
- [ ] **Signal documentation** — Document when `valueChanged` is emitted (user interaction only)
- [ ] **Reusability** — Control should work in any PyQt6 context (tests, standalone, alternative UIs)
- [ ] **No device imports** — Controls must not depend on driver code

### Checklist for Settings Changes
- [ ] **Schema in `settings.json`** — Add new top-level key or nested structure
- [ ] **Validation** — Provide sensible defaults in code (`dict.get(key, default_value)`)
- [ ] **No startup caching** — Load fresh on each use
- [ ] **Device keys** — Use serial numbers or IDs for multi-device configs

---

## Testing & Validation

### Device Drivers (Qt-Free Testing)
```powershell
# Test driver without GUI
python -c "
from devices.rigol_dp832a import PowerSupplyManager
from pyvisa import ResourceManager

rm = ResourceManager()
print('Available instruments:', rm.list_resources())

# Manual instantiation and connection
if rm.list_resources():
    manager = PowerSupplyManager(rm)
    print('Discovered supplies:', [s.serial for s in manager.supplies])
"
```

### Dialogs (Integration Testing)
1. Run `python ./app/app.py`
2. Open each device dialog via toolbar/menu
3. Verify:
   - Devices discovered and initialized
   - Polling updates visible in UI (no stalls)
   - Settings load correctly on dialog reopen
   - Dialog closes cleanly without errors

### Settings Validation
```powershell
# Validate JSON syntax
python -m json.tool app/settings/settings.json

# Verify against expected keys
python -c "
import json
from pathlib import Path

settings = json.load(open('app/settings/settings.json'))
print('Theme:', settings.get('theme'))
print('Power supplies:', list(settings.get('power_supplies', {}).keys()))
print('Rotary motors config:', settings.get('rotary_motors', {}))
"
```

### Threading Verification
- **No GUI hangs**: Dialog operations should complete in <100ms (polling runs in background)
- **No memory leaks**: Run app for extended period; monitor memory with Task Manager
- **Executor cleanup**: Verify `executor.shutdown(wait=True)` in all dialog `closeEvent()` methods

---

