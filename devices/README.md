# devices/

Qt-free hardware device drivers. Each driver can be instantiated and tested standalone in a REPL without launching the GUI.

## Driver Contract

Every driver must:
- Have **zero PyQt6 imports** (even `pyqtSignal` breaks reusability)
- Use `threading.Lock()` for thread safety
- Return `@dataclass` snapshots from `poll_all()` — never live references
- Expose `connect()` / `disconnect()` / `poll_all()` as the primary API

## Current Drivers

| File | Device | Notes |
|------|--------|-------|
| `rigol_dp832a.py` | Rigol DP832A power supply | Includes `PowerSupplyManager` for multi-supply |
| `digilent.py` | Digilent Analog Discovery 2 | Trigger signal generation |
| `ell_motor.py` | Thorlabs ELL6 rotary motor | Requires pythonnet + Thorlabs DLL, Windows only |
| `hp6653a.py` | HP 6653A power supply | |

## Adding a New Driver

1. Create `devices/new_device.py` with `connect()` / `disconnect()` / `poll_all()`.
2. Use `threading.Lock()` around any state shared between threads.
3. Return a `@dataclass` snapshot from `poll_all()`, never a mutable reference.
4. See [`../app/README.md`](../app/README.md) for wiring a dialog to the new driver.
