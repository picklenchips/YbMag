# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Working Directory

All code edits target **`/Users/benkroul/Documents/Physics/hollberg/YbMag/`**.

**Ignore root-level scripts** outside this directory (e.g. `pulser_control.ipynb`, `pulser_analysis.ipynb` — standalone experiment notebooks, not part of this project).

## Current Focus

**Overarching goal:** Demonstrate measurement of dynamic B fields at the 875 ns Yb excited-state lifetime timescale via stroboscopic imaging, automate vector B field imaging, and unify all controls in the GUI.

Active software development spans:
- **`gui/`** (currently `app/`) — GUI bugs (see below) and new feature work (camera settings tab, image analysis integration, arbitrary script pipeline).
- **`devices/`** — EllMotor and power supply fixes (see Known Bugs).
- **`magtorch/`** — differentiable PyTorch ML pipeline for fluorescence simulation. Read [`magtorch/README.md`](magtorch/README.md) before working here.

## Known Bugs

- **Camera settings dialog:** `PROPENUMERATIONCONTROL` node type not rendering — camera exposure/enum controls missing from UI.
- **ROI after decimation:** binning/decimation offsets not applied when computing ROI measurements; exiting crop mode after decimation breaks the selection.
- **EllMotor (`devices/ell_motor.py`):** step completes correctly but GUI reports "error: did not finish" — likely an off-by-tolerance race on the done signal. Fix: detect near-target condition and retry in the same direction rather than surfacing an error.
- **Power supplies:** no "toggle all on/off" quick action (supplies retain internal settings when toggled; this is just a missing UI control).

## Project Overview

YbMag is a PyQt6 experimental control GUI + physics simulation for a Ytterbium magnetometer experiment. Entry point: `python app.py` at repo root (`Library.init_context()` from the IC4 SDK wraps the entire GUI lifecycle — already handled in `app.py`).

## Dependencies

See [`requirements.txt`](requirements.txt) for the full list.

**Option A — uv** ([install](https://docs.astral.sh/uv/getting-started/installation/)):
```bash
uv pip install -r requirements.txt
```

**Option B — Anaconda** ([install](https://www.anaconda.com/download)):
```bash
conda create -n ybmag python=3.12
conda activate ybmag
pip install -r requirements.txt
```

> The ELL6 motor driver (`devices/ell_motor.py`) requires pythonnet and the Thorlabs Elliptec DLL — Windows only.

## Module Map

| Module | README | Description |
|--------|--------|-------------|
| `gui/` | [`gui/README.md`](gui/README.md) | PyQt6 GUI: mainwindow, dialogs, resources, settings |
| `devices/` | [`devices/README.md`](devices/README.md) | Qt-free hardware drivers |
| `pipeline/` | — | Coordination layer: HDR, ROI, DC power (bridges devices ↔ GUI) |
| `simulation/` | [`simulation/README.md`](simulation/README.md) | QuTiP Lindblad physics simulation |
| `analysis/` | [`analysis/README.md`](analysis/README.md) | Qt-free data analysis scripts |
| `magtorch/` | [`magtorch/README.md`](magtorch/README.md) | ML pipeline for fluorescence simulation **(current focus)** |

## Architecture — Four-Layer Pattern

**Layer 1 — Device Drivers** (`devices/`): Pure Python, zero PyQt6 imports. Thread-safe via `threading.Lock()`. Return `@dataclass` snapshots from `poll_all()` — never live references. Testable standalone or in a REPL.

**Layer 2 — Pipeline** (`pipeline/`): Future home for coordination modules that orchestrate device calls and image operations without owning UI — e.g., automated B-field zeroing, HDR acquisition sequencing, stroboscopic timing control. Currently empty. No PyQt6 signals or widgets.

**Layer 3 — Dialogs** (`gui/dialogs/`): `QDialog` subclasses wrapping drivers and pipeline modules. All device I/O runs in `ThreadPoolExecutor(max_workers=1)` via `_on_poll_tick() → _poll_worker() → _on_poll_finished()`. UI updates only in `_on_poll_finished()`. Lazy-instantiated on toolbar/menu click.

**Layer 4 — MainWindow** (`gui/mainwindow.py`): Owns camera acquisition via IC4 `Grabber`/`QueueSink`. Uses custom `QEvent` types (`GotPhotoEvent`, `DeviceLostEvent`) for thread-safe frame delivery.

## Critical Invariants

- **Never block the main thread.** All device I/O through `ThreadPoolExecutor`.
- **Settings are never cached.** `_load_settings()` reads `gui/settings/settings.json` on every poll cycle. Never store settings in module-level variables or dialog `__init__`.
- **`valueChanged` signals are user-only.** Reusable controls use a `_programmatic` bool guard. `set_value()` suppresses signals to prevent poll-update feedback loops.
- **IC4 PropertyMap cleanup.** `PropertyMap` objects must be explicitly `.clear()`'d in `PropertyDialog.clear_all()` before `closeEvent()` finishes, or `Library.init_context()` exits with `RuntimeError`.
- **Device drivers must not import PyQt6.** Even `pyqtSignal` breaks the reusability contract.
- **`pipeline/` must not import PyQt6.** Same contract as `devices/` — these modules must remain testable without a display.
- **`analysis/` must not import PyQt6.** Any widget code belongs in `gui/dialogs/` instead.

## Settings File

`gui/settings/settings.json` — hand-editable. `device.json` and `codecconfig.json` are IC4 auto-generated (do not edit).

Access pattern:
```python
settings = _load_settings()
val = settings.get("power_supply_poll_interval_ms", 500)
name = settings.get("power_supplies", {}).get(serial, {}).get("name", serial)
```

