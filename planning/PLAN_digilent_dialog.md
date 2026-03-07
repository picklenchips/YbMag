# Digilent Dialog (`app/dialogs/digilent_dialog.py`)

## Summary

A PyQt6 dialog providing a full-featured GUI for the Digilent Analog Discovery 2, wrapping the Qt-free `devices/digilent.py` driver. **Implemented** following project patterns:
- `ThreadPoolExecutor` for background polling (100 ms status tick)
- `_PollSignals(QObject)` for cross-thread communication
- `BasicSlider` for value controls with no feedback loops
- Singleton `StyleManager` for theming (dark/light aware waveform + scope)
- Settings persistence via `settings.json` (presets, channel names, last session)

The dialog is a **self-contained, modeless window** (like `PowerSupplyDialog`) opened via Instruments menu / toolbar.

---

## Layout

```
┌─ Digilent Pattern Generator ──────────────────────────────────────────────┐
│  Connection: [Device combo ▼]  [↻] [Connect]   ● Connected                │
├───────────────────────────┬───────────────────────────────────────────────┤
│  Channel Settings (scroll)│  Waveform Preview (custom QPainter)           │
│                           │                                               │
│  ■ CH 0 "Trigger"   [ON]  │   ┊     ┌──┐     ┌──┐     ┌──┐                │
│   Period  [slider] 1 ms   │   ┊─────┘  └─────┘  └─────┘                   │
│   Duty    [slider] 50 %   │   ┊                                           │
│   Delay   [slider] 0 µs   │   ┊     ┌┐  ┌┐  ┌┐                            │
│   Pulses  [Continuous]    │   ┊─────┘└──┘└──┘└──────────                  │
│   Idle    [LOW ▼]         │   0        0.5        1.0 ms                  │
│                           │  Scroll=zoom, Drag=pan, DblClick=fit          │
│  ■ CH 1 "Burst"    [ON]   │                                               │
│   ...                     │                                               │
│  [+ Add Channel]          │                                               │
├───────────────────────────┴───────────────────────────────────────────────┤
│  Trigger: [None ▼]  Repeat: [Infinite]     [▶ Start] [■ Stop] [Trigger]  │
├───────────────────────────────────────────────────────────────────────────┤
│  ▶ Scope Channels (collapsible)                                          │
│    CH1 [✓] Range [5V] Coupling [DC]   CH2 [ ] Range [5V] Coupling [DC]    │
│    Trigger: [Auto] Level [0.0V] Edge [↗ Rising]                           │
│    [Arm Scope] [Stop Scope]                                               │
│    ┌─ Scope Trace (QPainter) ──────────────────────────────────────────┐  │
│    │  CH1=gold  CH2=cyan  Grid  Trigger marker                         │  │
│    └───────────────────────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────────────────────────┤
│                                          [Save Preset] [Load Preset]      │
├───────────────────────────────────────────────────────────────────────────┤
│  ● Running | Clock: 100 MHz | Elapsed: 2.34s                              │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Widget Hierarchy

| Widget | Class | Purpose |
|--------|-------|---------|
| `DigilentDialog` | `QDialog` | Main shell, threading, lifecycle |
| `_ConnectionWidget` | `QWidget` | Device combo, connect/disconnect, status dot |
| `_ChannelSettingsPanel` | `QWidget` | Scrollable list of channel widgets + "Add Channel" |
| `_DigitalChannelWidget` | `QFrame` | Per-channel: name, enable, period/duty/delay sliders, pulse count, idle |
| `_WaveformPreviewWidget` | `QWidget` | Computed waveform display (edge-based rendering, zoom/pan/cursor) |
| `_GlobalControlsWidget` | `QWidget` | Trigger source, repeat count, Start/Stop/Trigger buttons |
| `_ScopePanel` | `QGroupBox` | Collapsible scope with channel config, trigger, arm/stop |
| `_ScopeTraceWidget` | `QWidget` | Real-time scope trace display (QPainter, CH1=gold CH2=cyan) |
| `_StatusBar` | `QWidget` | Running indicator, clock frequency, elapsed time |

---

## Key Features

### Digital Pattern Generator
- **Up to 16 channels** with individual period, duty cycle, delay, pulse count, idle state
- **Editable channel names** persisted in settings
- **Color-coded** channels (blue, red, teal, yellow, purple, orange, emerald, pink + HSL generation)
- **Frequency/pulse-width readouts** next to sliders

### Waveform Preview
- **Computed (not live)** — renders mathematically from channel configs, works without device
- **Edge-based rendering** — efficient, caps at 10,000 edges per channel
- **Interactive**: scroll-wheel zoom (centered on cursor), drag to pan, double-click to fit all
- **Cursor tracking** with time readout on hover
- **Theme-aware**: dark (#1a1a2e bg) / light (#f8f9fa bg) with matching grid/text colors
- **Auto-scaled time axis** with adaptive SI unit ticks (ns/µs/ms/s)

### Scope
- **Collapsible panel** — starts collapsed to keep dialog compact
- **2 analog channels**: configurable range (0.5V–50V), DC/AC coupling
- **Trigger**: Auto/Normal/Single modes, level slider, rising/falling edge
- **Real-time trace** with subsampled rendering for performance

### Threading
- `ThreadPoolExecutor(max_workers=1)` for all background I/O
- `_PollSignals(QObject)` with signals: `pattern_status`, `scope_data`, `connection_changed`, `error`
- 100 ms status timer for responsive UI updates
- `_poll_busy` guard prevents overlapping polls

### Settings & Presets
- **Auto-save on close** as `_last_session` preset, restored on next open
- **Named presets** via Save/Load dialogs (stored in `settings.json → digilent.presets`)
- **Channel names** persisted globally and per-preset
- **Last device serial** remembered for auto-selection

### Keyboard Shortcuts
| Key | Action |
|-----|--------|
| `Space` | Start/Stop toggle |
| `T` | Software trigger |
| `F` | Fit all (auto-zoom waveform) |

---

## Files Modified/Created

| File | Action | Purpose |
|------|--------|---------|
| `app/dialogs/digilent_dialog.py` | **Created** | Dialog implementation (~900 lines) |
| `app/dialogs/__init__.py` | **Modified** | Added `DigilentDialog` export |
| `app/mainwindow.py` | **Modified** | Added toolbar action, menu entry, `onDigilent()` handler, closeEvent cleanup |
| `app/settings/settings.json` | **Modified** | Added `digilent` section with defaults |
| `devices/digilent.py` | **Existing** | Qt-free driver (unchanged, already complete) |

---

## Future Enhancements

These features are architecturally supported but not yet implemented:

| Feature | Notes |
|---------|-------|
| Arbitrary waveform data | `DigitalChannelConfig` could gain `custom_data: Optional[bytes]` |
| PWM sweep | Time-varying duty cycle via counter updates in a loop |
| Cross-trigger UI | Scope→digital trigger configuration in the scope panel |
| Multi-device support | Open multiple `DigilentDialog` instances for multiple devices |
| CSV import/export | Load timing data from CSV into channel configs |
| AWG channels | Analog output (CH_W1, CH_W2) — separate tab in dialog |
| Scope measurements | Vpp, Vmax, Vrms, frequency computed from samples |
| Waveform icon | Custom `waveform.png` for both `+theme_dark/` and `+theme_light/` |

---
