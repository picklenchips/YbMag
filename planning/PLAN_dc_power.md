# Rigol DP832A Power Supply Integration — Architecture Plan

## Goal

Integrate control of multiple Rigol DP832A DC power supplies into the existing Qt6 camera-control application, with per-channel voltage/current sliders, real-time readback, and a collapsible UI per supply.

---

## Architecture Decision: Separated Backend + Qt Frontend

### Why not a monolithic Qt class?

A single class mixing pyvisa SCPI communication with Qt widgets would:

- **Tightly couple** hardware I/O to the GUI toolkit — impossible to reuse the driver in scripts, tests, or a CLI.
- **Block the main thread** — VISA queries take 10-50 ms each; doing them synchronously inside a QWidget method would freeze the UI, especially with multiple supplies polled in a loop.
- **Break the established pattern** — The existing codebase cleanly separates hardware (`Grabber`) from UI (`DeviceSelectionDialog`, `PropertyDialog`). A monolithic class would be the odd one out.

### Chosen approach

| Layer | Class | Responsibility |
|-------|-------|----------------|
| **Hardware driver** | `RigolDP832A` (in `rigol_dp832a.py`, top-level) | Single-supply pyvisa wrapper: connect, disconnect, set/get voltage & current, enable/disable output, query limits. Pure Python, **zero Qt dependency**. |
| **Device manager** | `PowerSupplyManager` (same file or `power_supply_manager.py`) | Auto-detect all DP832A units on USB, maintain a list of `RigolDP832A` instances, reconnect on loss. |
| **Qt dialog** | `PowerSupplyDialog` (in `app/dialogs/power_supply_dialog.py`) | `QDialog` with one collapsible section per supply. Each section shows connection info header + 3 channel panels with `BasicSlider`-based voltage/current controls and live readback labels. Polls via `QTimer`. |
| **MainWindow glue** | additions to `mainwindow.py` | "Power Supplies" toolbar button + menu entry; opens/manages the `PowerSupplyDialog` instance (same lifecycle pattern as `DeviceSelectionDialog`). |

This mirrors the Grabber ↔ DeviceSelectionDialog separation and keeps every layer independently testable.

---

## File Plan

### 1. `rigol_dp832a.py` (top-level, next to `rigol_dc.py`)

```
class ChannelInfo:
    number: int          # 1, 2, 3
    max_voltage: float   # queried on connect
    max_current: float
    set_voltage: float   # last commanded
    set_current: float
    meas_voltage: float  # last polled
    meas_current: float
    meas_power: float
    output_enabled: bool

class RigolDP832A:
    """Thread-safe, Qt-free driver for one Rigol DP832A."""

    def __init__(self, resource_name: str, resource_manager: pyvisa.ResourceManager)
    def connect(self) -> None
    def disconnect(self) -> None
    @property
    def is_connected(self) -> bool
    @property
    def identity(self) -> str            # *IDN? cached
    @property
    def serial(self) -> str
    @property
    def channels(self) -> list[ChannelInfo]

    # Per-channel commands (ch = 1, 2, 3)
    def set_voltage(self, ch: int, volts: float) -> None
    def set_current(self, ch: int, amps: float) -> None
    def set_output(self, ch: int, on: bool) -> None
    def measure(self, ch: int) -> tuple[float, float, float]  # V, I, P
    def poll_all(self) -> None   # refresh all ChannelInfo in one burst

class PowerSupplyManager:
    """Discover and manage all connected DP832A supplies."""

    def __init__(self)
    def scan(self) -> list[RigolDP832A]
    @property
    def supplies(self) -> list[RigolDP832A]
    def close_all(self) -> None
```

**Key design notes:**

- Every SCPI call is wrapped in a `threading.Lock` per instrument so the `QTimer` poll and user-initiated set commands don't collide.
- `poll_all()` reads voltage/current/power for all three channels in a single burst (~6 SCPI queries ≈ 60 ms) and caches results in `ChannelInfo`, so the UI just reads cached values.
- Error handling: wrap every `inst.query()` / `inst.write()` in try/except; on `pyvisa.errors.VisaIOError`, mark `is_connected = False` and let the UI show a "disconnected" state.

### 2. `app/dialogs/power_supply_dialog.py`

```
class ChannelControlWidget(QWidget):
    """Per-channel panel: voltage slider, current slider, readback labels, output toggle."""
    Uses BasicSlider (or a derived version with set_value() for readback).

class SupplySection(QWidget):
    """Collapsible section for one supply: clickable header + 3 × ChannelControlWidget."""
    Header shows: model, serial, connection status (green/red indicator).
    Body: 3 ChannelControlWidgets stacked vertically.

class PowerSupplyDialog(QDialog):
    """Top-level dialog opened from MainWindow."""
    - Takes a PowerSupplyManager reference.
    - On show(): calls manager.scan(), builds one SupplySection per supply.
    - QTimer (200-500 ms): calls supply.poll_all() for each supply in a worker,
      then updates labels from cached ChannelInfo on the main thread.
    - "Refresh" button to re-scan USB.
    - apply_theme() for dark/light theming (same pattern as DeviceSelectionDialog).
    - finished signal wired to cleanup in MainWindow.
```

**Polling strategy (non-blocking):**

Use a `QTimer` that fires every ~300 ms. On each tick, run `poll_all()` for each supply on a `QThread` / `QRunnable` (or `concurrent.futures.ThreadPoolExecutor`), then emit a signal that the main thread catches to update the labels. This keeps the GUI responsive even with 2+ supplies.

Alternatively, if latency is acceptable, poll synchronously since each `poll_all()` is ~60 ms and with 2 supplies that's ~120 ms — borderline. A background thread is safer and future-proofs for more units.

### 3. `app/dialogs/__init__.py`

Add `PowerSupplyDialog` to the exports.

### 4. `app/mainwindow.py` changes

```python
# In createUI():
self.power_supply_act = QAction(
    selector.loadIcon("images/power.png"), "&Power Supplies", self
)
self.power_supply_act.setStatusTip("Open power supply controls")
self.power_supply_act.setCheckable(True)
self.power_supply_act.triggered.connect(self.onPowerSupplies)

# Add to toolbar and Device menu (or a new "Instruments" menu)
toolbar.addSeparator()
toolbar.addAction(self.power_supply_act)

# New members:
self.power_supply_dialog = None
self.power_supply_manager = PowerSupplyManager()

# New methods — same pattern as onDeviceProperties / onSelectDevice:
def onPowerSupplies(self):
    if self.power_supply_dialog is not None and self.power_supply_dialog.isVisible():
        self.power_supply_dialog.close()
        return
    self.power_supply_dialog = PowerSupplyDialog(
        self.power_supply_manager, parent=self, resource_selector=selector
    )
    self.power_supply_dialog.apply_theme()
    self.power_supply_dialog.finished.connect(self._onPowerSupplyDialogClosed)
    self.power_supply_act.setChecked(True)
    self.power_supply_dialog.show()

def _onPowerSupplyDialogClosed(self):
    self.power_supply_act.setChecked(False)
    self.power_supply_dialog = None
```

### 5. Icon

Add a `power.png` icon (simple lightning bolt / plug) to `app/resources/images/+theme_dark/` and `+theme_light/`. Can be a simple SVG-converted PNG or placeholder until a real icon is provided.

### 6. `BasicSlider` enhancement (if needed)

The current `BasicSlider` is output-only (user drags → value). For the power supply UI we also need:

- **`set_value(v)`** — programmatically move the slider (for readback / initial sync).
- **`valueChanged` signal** — so the dialog can wire it to `supply.set_voltage()`.
- **Optional unit label** (e.g. "V", "A") suffix on the readback text.

These are small, backward-compatible additions to the existing class.

---

## Execution Order

| Step | Task | Files |
|------|------|-------|
| 1 | Implement `RigolDP832A` + `PowerSupplyManager` with unit tests (no Qt needed) | `rigol_dp832a.py` |
| 2 | Enhance `BasicSlider` with `set_value()` and `valueChanged` signal | `app/dialogs/controls/basic_slider.py` |
| 3 | Build `ChannelControlWidget`, `SupplySection`, `PowerSupplyDialog` | `app/dialogs/power_supply_dialog.py` |
| 4 | Wire into `MainWindow` (action, menu, toolbar, dialog lifecycle) | `app/mainwindow.py`, `app/dialogs/__init__.py` |
| 5 | Add icons, test theme switching | `app/resources/images/…` |
| 6 | End-to-end test with real hardware | — |

---

## DP832A SCPI Command Reference (subset)

| Action | Command |
|--------|---------|
| Identify | `*IDN?` |
| Select channel | `:INST:NSEL {1\|2\|3}` or `:INST CH{1\|2\|3}` |
| Set voltage | `:SOUR{ch}:VOLT {value}` |
| Set current | `:SOUR{ch}:CURR {value}` |
| Enable output | `:OUTP CH{ch},ON` |
| Disable output | `:OUTP CH{ch},OFF` |
| Measure voltage | `:MEAS:VOLT? CH{ch}` |
| Measure current | `:MEAS:CURR? CH{ch}` |
| Measure power | `:MEAS:POWE? CH{ch}` |
| Query voltage range | `:SOUR{ch}:VOLT? MAX` |
| Query current range | `:SOUR{ch}:CURR? MAX` |
| Query output state | `:OUTP? CH{ch}` |

---

## Summary

**Separate backend from frontend.** The `RigolDP832A` class is a pure-Python pyvisa driver that can be used anywhere — scripts, notebooks, tests. The Qt dialog is a thin presentation layer that reads cached state and sends commands. This matches the Grabber/DeviceSelectionDialog split already in the codebase, keeps the code testable and maintainable, and avoids blocking the GUI thread.
