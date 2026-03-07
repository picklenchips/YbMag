# Digilent Driver (`devices/digilent.py`)

Thread-safe, Qt-free driver for the Digilent Analog Discovery 2, wrapping the Waveforms SDK (`dwf.dll`/`libdwf.so`) via `ctypes`.

## Capabilities

- **Multi-channel digital pattern generation** — per-channel period, duty cycle, delay, pulse count, idle state (DIO 0–15)
- **Analog scope acquisition** — 2 channels, configurable range/sample rate/buffer/coupling/trigger
- **Cross-domain triggering** — hardware route (scope threshold → digital output) or software fallback via `poll_and_cross_trigger()`
- **Thread-safe** — single `threading.Lock` guards all SDK calls
- **Typed ctypes** — all SDK functions have `argtypes`/`restype` to prevent silent corruption

## Quick Start

```python
from devices.digilent import Digilent, DigitalChannelConfig, enumerate_devices

print(enumerate_devices())   # list connected hardware
d = Digilent()               # no auto-connect
d.open()                     # explicit connection
d.setup_trigger_and_burst(trigger_channel=0, burst_channel=1, burst_count=50)
d.start()
# ...
d.stop()
d.close()
```

## Data Models

| Dataclass | Fields |
|-----------|--------|
| `DigitalChannelConfig` | `channel`, `enabled`, `period`, `duty_cycle`, `delay`, `pulse_count`, `idle_state` — plus derived `pulse_width`, `repetition_rate` properties |
| `ScopeChannelConfig` | `channel`, `enabled`, `range_volts`, `offset_volts`, `sample_rate`, `buffer_size`, `coupling` |
| `ScopeThresholdTrigger` | `scope_channel`, `threshold_volts`, `rising`, `digital_channel`, `response_config` |
| `PatternState` (frozen) | `running`, `channels`, `elapsed_time`, `trigger_source` |
| `ScopeAcquisition` (frozen) | `channel`, `samples` (numpy), `sample_rate`, `trigger_position`, `timestamp`, `clipped` |

## Public API

| Method | Description |
|--------|-------------|
| `open(device_index)` / `close()` | Connect / disconnect |
| `connected` | Property: connection state |
| `configure_digital_channel(config)` | Configure one DIO channel |
| `configure_all_digital(configs)` | Configure multiple DIO channels atomically (resets first) |
| `set_trigger_source(source)` | Master trigger routing (use `TRIGSRC_*` constants) |
| `set_repeat_count(n)` | Burst repeat count (0 = infinite) |
| `set_run_duration(sec)` | Total run time (0 = by repeat count) |
| `start()` / `stop()` | Arm/stop digital pattern generator |
| `trigger()` | Software trigger (when source is `TRIGSRC_PC`) |
| `is_running` | Property: queries hardware status |
| `get_pattern_state()` | Frozen snapshot of config + status |
| `configure_scope_channel(config)` | Configure one analog input channel |
| `configure_scope_trigger(...)` | Set scope trigger channel/level/edge/position/timeout |
| `start_scope()` / `stop_scope()` | Arm/stop scope acquisition |
| `poll_scope(ch)` | Non-blocking: returns `ScopeAcquisition` or `None` |
| `configure_scope_to_digital_trigger(rule)` | Hardware cross-trigger: scope threshold → digital output |
| `poll_and_cross_trigger()` | Software cross-trigger fallback (call in polling loop) |
| `setup_trigger_and_burst(...)` | Convenience: continuous trigger + finite burst on two channels |
| `export_config()` / `import_config(data)` | JSON-serializable config round-trip |
| `enumerate_devices()` | Module-level: list connected Digilent devices |

## Design Notes

- **`_load_dwf()`** loads the SDK DLL and declares `argtypes`/`restype` for every function used. Without this, ctypes silently passes Python `int` as 32-bit when many DWF functions expect `c_double`.
- **Timing** uses divider=1 with counter low/high tick counts derived from `FDwfDigitalOutInternalClockInfo` (100 MHz on AD2). Delay is implemented via `FDwfDigitalOutCounterInitSet`.
- **Cross-trigger** routes the scope trigger detector to the digital-out trigger bus (`TRIGSRC_ANALOG_IN`). The AD2 has a single shared trigger bus, so complex multi-trigger chains need the software fallback.
- **`_check_error()`** queries `FDwfGetLastError` — called after critical SDK calls, not in hot polling loops.
- `numpy` is lazily imported; the module loads without it (scope data methods require it).

## Dependencies

`ctypes`, `threading`, `dataclasses`, `time`, `os` (stdlib) + `numpy` (optional, required for scope).
6. **Standalone testable** — `python -c "from devices.digilent import Digilent; ..."` works

## Notes

**Key decisions:**
- Store `period` + `duty_cycle` as the canonical pair; derive `pulse_width` and `repetition_rate` as properties.
- `delay` is an absolute time offset from the pattern-generator start/trigger. This maps directly to `FDwfDigitalOutRunSet` + counter initial value manipulation in the SDK.
- `pulse_count = 0` means continuous; mirrors the SDK's `FDwfDigitalOutRepeatSet(hdwf, 0)` for infinite.
- `idle_state` controls what the pin does when not pulsing (SDK: `FDwfDigitalOutIdleSet`).

The Analog Discovery 2 supports inter-instrument triggering natively via the trigger bus. The scope's trigger detector output can be routed as the trigger source for the digital pattern generator. This enables: "when CH1 voltage exceeds 2.5 V rising, fire a pulse train on DIO 2."
- AD2 has a single trigger bus — all instruments share one trigger event at a time. Complex multi-trigger chains require software orchestration (poll scope, then manually fire digital).
- For the "software cross-trigger" fallback (when hardware routing is insufficient):