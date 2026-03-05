"""
Digilent Analog Discovery 2 driver.

Multi-channel digital pattern generation and analog scope acquisition via the
Digilent Waveforms SDK (dwf.dll / libdwf.so) using ctypes.

Zero Qt dependency — suitable for scripts, REPL, and GUI wrappers alike.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# DWF SDK constants (from dwf.h)
# ---------------------------------------------------------------------------

# Trigger sources
TRIGSRC_NONE = 0
TRIGSRC_PC = 1
TRIGSRC_DETECT_POS = 2
TRIGSRC_DETECT_NEG = 3
TRIGSRC_ANALOG_IN = 4
TRIGSRC_DIGITAL_IN = 5
TRIGSRC_DIGITAL_OUT = 6
TRIGSRC_EXTERNAL_1 = 8
TRIGSRC_EXTERNAL_2 = 9

# Digital‑out types
_DWFDIGITALOUT_TYPE_PULSE = 1

# Digital‑out idle levels
_DWFDIGITALOUT_IDLE_LOW = 0
_DWFDIGITALOUT_IDLE_HIGH = 1

# Instrument states
_DWFSTATE_READY = 0
_DWFSTATE_ARMED = 1
_DWFSTATE_DONE = 2
_DWFSTATE_RUNNING = 3
_DWFSTATE_TRIGGERED = 3  # alias used in some contexts

# Trigger conditions
_TRIGCOND_RISING = 0
_TRIGCOND_FALLING = 1

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DigitalChannelConfig:
    """Configuration for one digital output channel (0–15)."""

    channel: int
    enabled: bool = False
    period: float = 1e-3
    duty_cycle: float = 0.5
    delay: float = 0.0
    pulse_count: int = 0
    idle_state: bool = False

    @property
    def pulse_width(self) -> float:
        """HIGH time in seconds."""
        return self.period * self.duty_cycle

    @property
    def repetition_rate(self) -> float:
        """Frequency in Hz."""
        return 1.0 / self.period if self.period > 0 else 0.0


@dataclass
class ScopeChannelConfig:
    """Configuration for one analog scope channel (0 or 1)."""

    channel: int
    enabled: bool = False
    range_volts: float = 5.0
    offset_volts: float = 0.0
    sample_rate: float = 1e6
    buffer_size: int = 8192
    coupling: str = "DC"


@dataclass
class ScopeThresholdTrigger:
    """Rule: when scope channel crosses threshold, fire a digital channel."""

    scope_channel: int
    threshold_volts: float
    rising: bool = True
    digital_channel: int = -1
    response_config: Optional[DigitalChannelConfig] = None


@dataclass(frozen=True)
class PatternState:
    """Immutable snapshot of the pattern generator status."""

    running: bool
    channels: Tuple[DigitalChannelConfig, ...]
    elapsed_time: float
    trigger_source: str


@dataclass(frozen=True)
class ScopeAcquisition:
    """Immutable snapshot of a completed scope acquisition."""

    channel: int
    samples: np.ndarray
    sample_rate: float
    trigger_position: int
    timestamp: float
    clipped: bool


# ---------------------------------------------------------------------------
# DWF SDK loader
# ---------------------------------------------------------------------------

_P_INT = ctypes.POINTER(ctypes.c_int)
_P_DOUBLE = ctypes.POINTER(ctypes.c_double)


def _load_dwf() -> ctypes.CDLL:
    """Load the Digilent Waveforms SDK and declare function signatures."""
    if os.name == "nt":
        dwf = ctypes.cdll.LoadLibrary("dwf.dll")
    else:
        dwf = ctypes.cdll.LoadLibrary("libdwf.so")

    # --- Device management ---
    dwf.FDwfEnum.argtypes = [ctypes.c_int, _P_INT]
    dwf.FDwfEnum.restype = ctypes.c_int

    dwf.FDwfEnumDeviceName.argtypes = [ctypes.c_int, ctypes.c_char_p]
    dwf.FDwfEnumDeviceName.restype = ctypes.c_int

    dwf.FDwfEnumSN.argtypes = [ctypes.c_int, ctypes.c_char_p]
    dwf.FDwfEnumSN.restype = ctypes.c_int

    dwf.FDwfDeviceOpen.argtypes = [ctypes.c_int, _P_INT]
    dwf.FDwfDeviceOpen.restype = ctypes.c_int

    dwf.FDwfDeviceClose.argtypes = [ctypes.c_int]
    dwf.FDwfDeviceClose.restype = ctypes.c_int

    dwf.FDwfGetLastError.argtypes = [_P_INT]
    dwf.FDwfGetLastError.restype = ctypes.c_int

    dwf.FDwfGetLastErrorMsg.argtypes = [ctypes.c_char_p]
    dwf.FDwfGetLastErrorMsg.restype = ctypes.c_int

    dwf.FDwfDeviceTriggerPC.argtypes = [ctypes.c_int]
    dwf.FDwfDeviceTriggerPC.restype = ctypes.c_int

    # --- Digital Out ---
    dwf.FDwfDigitalOutReset.argtypes = [ctypes.c_int]
    dwf.FDwfDigitalOutReset.restype = ctypes.c_int

    dwf.FDwfDigitalOutInternalClockInfo.argtypes = [ctypes.c_int, _P_DOUBLE]
    dwf.FDwfDigitalOutInternalClockInfo.restype = ctypes.c_int

    dwf.FDwfDigitalOutTriggerSourceSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutTriggerSourceSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutRunSet.argtypes = [ctypes.c_int, ctypes.c_double]
    dwf.FDwfDigitalOutRunSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutRepeatSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutRepeatSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutRepeatTriggerSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutRepeatTriggerSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutEnableSet.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutEnableSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutTypeSet.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutTypeSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutIdleSet.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutIdleSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutDividerSet.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    dwf.FDwfDigitalOutDividerSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutCounterSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    dwf.FDwfDigitalOutCounterSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutCounterInitSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    dwf.FDwfDigitalOutCounterInitSet.restype = ctypes.c_int

    dwf.FDwfDigitalOutConfigure.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfDigitalOutConfigure.restype = ctypes.c_int

    dwf.FDwfDigitalOutStatus.argtypes = [ctypes.c_int, _P_INT]
    dwf.FDwfDigitalOutStatus.restype = ctypes.c_int

    # --- Analog In (Scope) ---
    dwf.FDwfAnalogInReset.argtypes = [ctypes.c_int]
    dwf.FDwfAnalogInReset.restype = ctypes.c_int

    dwf.FDwfAnalogInChannelEnableSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    dwf.FDwfAnalogInChannelEnableSet.restype = ctypes.c_int

    dwf.FDwfAnalogInChannelRangeSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    dwf.FDwfAnalogInChannelRangeSet.restype = ctypes.c_int

    dwf.FDwfAnalogInChannelOffsetSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    dwf.FDwfAnalogInChannelOffsetSet.restype = ctypes.c_int

    dwf.FDwfAnalogInFrequencySet.argtypes = [ctypes.c_int, ctypes.c_double]
    dwf.FDwfAnalogInFrequencySet.restype = ctypes.c_int

    dwf.FDwfAnalogInBufferSizeSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfAnalogInBufferSizeSet.restype = ctypes.c_int

    dwf.FDwfAnalogInChannelFilterSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    dwf.FDwfAnalogInChannelFilterSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerSourceSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfAnalogInTriggerSourceSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerChannelSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfAnalogInTriggerChannelSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerLevelSet.argtypes = [ctypes.c_int, ctypes.c_double]
    dwf.FDwfAnalogInTriggerLevelSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerConditionSet.argtypes = [ctypes.c_int, ctypes.c_int]
    dwf.FDwfAnalogInTriggerConditionSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerPositionSet.argtypes = [ctypes.c_int, ctypes.c_double]
    dwf.FDwfAnalogInTriggerPositionSet.restype = ctypes.c_int

    dwf.FDwfAnalogInTriggerAutoTimeoutSet.argtypes = [ctypes.c_int, ctypes.c_double]
    dwf.FDwfAnalogInTriggerAutoTimeoutSet.restype = ctypes.c_int

    dwf.FDwfAnalogInConfigure.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    dwf.FDwfAnalogInConfigure.restype = ctypes.c_int

    dwf.FDwfAnalogInStatus.argtypes = [ctypes.c_int, ctypes.c_int, _P_INT]
    dwf.FDwfAnalogInStatus.restype = ctypes.c_int

    dwf.FDwfAnalogInStatusData.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
    ]
    dwf.FDwfAnalogInStatusData.restype = ctypes.c_int

    return dwf


# ---------------------------------------------------------------------------
# Module‑level helpers
# ---------------------------------------------------------------------------


def enumerate_devices() -> List[Dict[str, int | str]]:
    """Return list of connected Digilent devices with name, serial, index."""
    dwf = _load_dwf()
    count = ctypes.c_int()
    dwf.FDwfEnum(ctypes.c_int(0), ctypes.byref(count))
    devices: List[Dict[str, int | str]] = []
    for i in range(count.value):
        name = ctypes.create_string_buffer(64)
        serial = ctypes.create_string_buffer(64)
        dwf.FDwfEnumDeviceName(ctypes.c_int(i), name)
        dwf.FDwfEnumSN(ctypes.c_int(i), serial)
        devices.append(
            {
                "index": i,
                "name": name.value.decode(),
                "serial": serial.value.decode(),
            }
        )
    return devices


# ---------------------------------------------------------------------------
# Digilent driver
# ---------------------------------------------------------------------------


class Digilent:
    """
    Thread-safe driver for the Digilent Analog Discovery 2.

    Supports multi-channel digital pattern generation, analog scope
    acquisition, and cross-domain (scope→digital) triggering.

    Lifecycle::

        d = Digilent()
        d.open()          # connect to hardware
        # ... configure & run ...
        d.close()         # release hardware
    """

    NUM_DIGITAL_CHANNELS = 16
    NUM_SCOPE_CHANNELS = 2

    def __init__(self, device_index: int = -1) -> None:
        self._dwf = _load_dwf()
        self._hdwf = ctypes.c_int(0)
        self._lock = threading.Lock()
        self._device_index = device_index
        self._connected = False
        self._running = False
        self._start_time: float = 0.0

        self._digital_configs: List[DigitalChannelConfig] = [
            DigitalChannelConfig(channel=i) for i in range(self.NUM_DIGITAL_CHANNELS)
        ]
        self._scope_configs: List[ScopeChannelConfig] = [
            ScopeChannelConfig(channel=i) for i in range(self.NUM_SCOPE_CHANNELS)
        ]
        self._threshold_triggers: List[ScopeThresholdTrigger] = []

        self._internal_clock_hz: float = 0.0
        self._trigger_source: int = TRIGSRC_NONE

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

    def _check_error(self) -> None:
        """Query the SDK for the last error and raise if non-zero."""
        code = ctypes.c_int()
        self._dwf.FDwfGetLastError(ctypes.byref(code))
        if code.value != 0:
            msg = ctypes.create_string_buffer(512)
            self._dwf.FDwfGetLastErrorMsg(msg)
            raise RuntimeError(f"DWF error {code.value}: {msg.value.decode()}")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def open(self, device_index: Optional[int] = None) -> None:
        """Open connection to a Digilent device."""
        with self._lock:
            idx = device_index if device_index is not None else self._device_index
            self._dwf.FDwfDeviceOpen(ctypes.c_int(idx), ctypes.byref(self._hdwf))
            if self._hdwf.value == 0:
                szerr = ctypes.create_string_buffer(512)
                self._dwf.FDwfGetLastErrorMsg(szerr)
                raise RuntimeError(
                    f"Failed to open Digilent device: {szerr.value.decode()}"
                )
            self._connected = True

            freq = ctypes.c_double()
            self._dwf.FDwfDigitalOutInternalClockInfo(self._hdwf, ctypes.byref(freq))
            self._internal_clock_hz = freq.value

    @property
    def connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        """Close device handle and release resources."""
        with self._lock:
            if self._connected:
                self._dwf.FDwfDeviceClose(self._hdwf)
                self._hdwf.value = 0
                self._connected = False
                self._running = False

    # ------------------------------------------------------------------
    # Digital output — per-channel configuration
    # ------------------------------------------------------------------

    def configure_digital_channel(self, config: DigitalChannelConfig) -> None:
        """Apply settings for one digital output channel."""
        with self._lock:
            self._configure_digital_channel_locked(config)

    def _configure_digital_channel_locked(self, config: DigitalChannelConfig) -> None:
        """Internal: configure a channel while the lock is already held."""
        ch = ctypes.c_int(config.channel)

        self._dwf.FDwfDigitalOutEnableSet(
            self._hdwf, ch, ctypes.c_int(int(config.enabled))
        )

        if not config.enabled:
            self._digital_configs[config.channel] = config
            return

        # Pulse output type
        self._dwf.FDwfDigitalOutTypeSet(
            self._hdwf, ch, ctypes.c_int(_DWFDIGITALOUT_TYPE_PULSE)
        )

        # Idle level
        idle = (
            _DWFDIGITALOUT_IDLE_HIGH if config.idle_state else _DWFDIGITALOUT_IDLE_LOW
        )
        self._dwf.FDwfDigitalOutIdleSet(self._hdwf, ch, ctypes.c_int(idle))

        # Timing: divider=1 for maximum resolution; counter for waveform shape
        total_ticks = max(1, int(self._internal_clock_hz * config.period))
        high_ticks = max(1, int(total_ticks * config.duty_cycle))
        low_ticks = max(1, total_ticks - high_ticks)

        self._dwf.FDwfDigitalOutDividerSet(self._hdwf, ch, ctypes.c_uint(1))
        self._dwf.FDwfDigitalOutCounterSet(
            self._hdwf, ch, ctypes.c_uint(low_ticks), ctypes.c_uint(high_ticks)
        )

        # Delay via counter initial value
        if config.delay > 0:
            delay_ticks = int(self._internal_clock_hz * config.delay)
            # Start LOW, count down delay_ticks before first pulse
            self._dwf.FDwfDigitalOutCounterInitSet(
                self._hdwf, ch, ctypes.c_int(0), ctypes.c_uint(delay_ticks)
            )
        else:
            # Start HIGH immediately (first half cycle is the pulse)
            self._dwf.FDwfDigitalOutCounterInitSet(
                self._hdwf, ch, ctypes.c_int(1), ctypes.c_uint(0)
            )

        self._digital_configs[config.channel] = config

    def configure_all_digital(self, configs: List[DigitalChannelConfig]) -> None:
        """Apply settings for multiple channels atomically."""
        with self._lock:
            self._dwf.FDwfDigitalOutReset(self._hdwf)
            for cfg in configs:
                self._configure_digital_channel_locked(cfg)

    # ------------------------------------------------------------------
    # Digital output — trigger & repeat
    # ------------------------------------------------------------------

    def set_trigger_source(self, source: int = TRIGSRC_PC) -> None:
        """Set the master trigger source for the digital pattern generator."""
        with self._lock:
            self._dwf.FDwfDigitalOutTriggerSourceSet(self._hdwf, ctypes.c_int(source))
            self._trigger_source = source

    def set_repeat_count(self, count: int = 0) -> None:
        """Set number of pattern repetitions. 0 = infinite."""
        with self._lock:
            self._dwf.FDwfDigitalOutRepeatSet(self._hdwf, ctypes.c_int(count))

    def set_run_duration(self, seconds: float = 0.0) -> None:
        """Set total run duration. 0 = determined by repeat count."""
        with self._lock:
            self._dwf.FDwfDigitalOutRunSet(self._hdwf, ctypes.c_double(seconds))

    # ------------------------------------------------------------------
    # Digital output — start / stop / status
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Arm and start the digital pattern generator."""
        with self._lock:
            self._dwf.FDwfDigitalOutConfigure(self._hdwf, ctypes.c_int(1))
            self._running = True
            self._start_time = time.monotonic()

    def stop(self) -> None:
        """Stop the digital pattern generator."""
        with self._lock:
            self._dwf.FDwfDigitalOutConfigure(self._hdwf, ctypes.c_int(0))
            self._running = False

    def trigger(self) -> None:
        """Send a software trigger (when trigger source is PC)."""
        with self._lock:
            self._dwf.FDwfDeviceTriggerPC(self._hdwf)

    @property
    def is_running(self) -> bool:
        """Query whether the pattern generator is currently active."""
        with self._lock:
            if not self._connected:
                return False
            sts = ctypes.c_int()
            self._dwf.FDwfDigitalOutStatus(self._hdwf, ctypes.byref(sts))
            self._running = sts.value == _DWFSTATE_RUNNING
            return self._running

    def get_pattern_state(self) -> PatternState:
        """Return an immutable snapshot of the current pattern generator state."""
        with self._lock:
            elapsed = time.monotonic() - self._start_time if self._running else 0.0
            source_names = {
                TRIGSRC_NONE: "none",
                TRIGSRC_PC: "pc",
                TRIGSRC_ANALOG_IN: "analog_in",
                TRIGSRC_DIGITAL_IN: "digital_in",
                TRIGSRC_DIGITAL_OUT: "digital_out",
                TRIGSRC_EXTERNAL_1: "external_1",
                TRIGSRC_EXTERNAL_2: "external_2",
            }
            return PatternState(
                running=self._running,
                channels=tuple(self._digital_configs),
                elapsed_time=elapsed,
                trigger_source=source_names.get(
                    self._trigger_source, str(self._trigger_source)
                ),
            )

    # ------------------------------------------------------------------
    # Analog input — scope configuration
    # ------------------------------------------------------------------

    def configure_scope_channel(self, config: ScopeChannelConfig) -> None:
        """Configure one analog input (scope) channel."""
        with self._lock:
            ch = ctypes.c_int(config.channel)
            self._dwf.FDwfAnalogInChannelEnableSet(
                self._hdwf, ch, ctypes.c_int(int(config.enabled))
            )
            self._dwf.FDwfAnalogInChannelRangeSet(
                self._hdwf, ch, ctypes.c_double(config.range_volts)
            )
            self._dwf.FDwfAnalogInChannelOffsetSet(
                self._hdwf, ch, ctypes.c_double(config.offset_volts)
            )
            self._dwf.FDwfAnalogInFrequencySet(
                self._hdwf, ctypes.c_double(config.sample_rate)
            )
            self._dwf.FDwfAnalogInBufferSizeSet(
                self._hdwf, ctypes.c_int(config.buffer_size)
            )
            coupling = 1 if config.coupling == "AC" else 0
            self._dwf.FDwfAnalogInChannelFilterSet(
                self._hdwf, ch, ctypes.c_int(coupling)
            )
            self._scope_configs[config.channel] = config

    def configure_scope_trigger(
        self,
        channel: int = 0,
        level_volts: float = 0.0,
        rising: bool = True,
        position_seconds: float = 0.0,
        auto_timeout: float = 1.0,
    ) -> None:
        """Configure the analog-in trigger for scope acquisition."""
        with self._lock:
            src = TRIGSRC_DETECT_POS if rising else TRIGSRC_DETECT_NEG
            self._dwf.FDwfAnalogInTriggerSourceSet(self._hdwf, ctypes.c_int(src))
            self._dwf.FDwfAnalogInTriggerChannelSet(self._hdwf, ctypes.c_int(channel))
            self._dwf.FDwfAnalogInTriggerLevelSet(
                self._hdwf, ctypes.c_double(level_volts)
            )
            cond = _TRIGCOND_RISING if rising else _TRIGCOND_FALLING
            self._dwf.FDwfAnalogInTriggerConditionSet(self._hdwf, ctypes.c_int(cond))
            self._dwf.FDwfAnalogInTriggerPositionSet(
                self._hdwf, ctypes.c_double(position_seconds)
            )
            self._dwf.FDwfAnalogInTriggerAutoTimeoutSet(
                self._hdwf, ctypes.c_double(auto_timeout)
            )

    # ------------------------------------------------------------------
    # Analog input — acquisition
    # ------------------------------------------------------------------

    def start_scope(self) -> None:
        """Arm the scope for acquisition (waits for trigger)."""
        with self._lock:
            self._dwf.FDwfAnalogInConfigure(
                self._hdwf, ctypes.c_int(1), ctypes.c_int(1)
            )

    def poll_scope(self, channel: int = 0) -> Optional[ScopeAcquisition]:
        """
        Non-blocking check: if scope acquisition is complete, return data.

        Returns ``None`` if still acquiring.  Designed to be called from a
        polling loop (e.g. ``ThreadPoolExecutor``).
        """
        with self._lock:
            sts = ctypes.c_int()
            self._dwf.FDwfAnalogInStatus(self._hdwf, ctypes.c_int(1), ctypes.byref(sts))
            if sts.value != _DWFSTATE_DONE:
                return None

            config = self._scope_configs[channel]
            n = config.buffer_size
            samples = (ctypes.c_double * n)()
            self._dwf.FDwfAnalogInStatusData(
                self._hdwf, ctypes.c_int(channel), samples, ctypes.c_int(n)
            )

            return ScopeAcquisition(
                channel=channel,
                samples=np.ctypeslib.as_array(samples).copy(),
                sample_rate=config.sample_rate,
                trigger_position=n // 2,
                timestamp=time.monotonic(),
                clipped=False,
            )

    def stop_scope(self) -> None:
        """Stop scope acquisition."""
        with self._lock:
            self._dwf.FDwfAnalogInConfigure(
                self._hdwf, ctypes.c_int(0), ctypes.c_int(0)
            )

    # ------------------------------------------------------------------
    # Cross-trigger: scope → digital
    # ------------------------------------------------------------------

    def configure_scope_to_digital_trigger(self, rule: ScopeThresholdTrigger) -> None:
        """
        Set up a cross-trigger: scope threshold → digital output channel.

        1. Configure scope trigger on the specified channel/threshold
        2. Route scope trigger detector to digital-out trigger source
        3. Configure the target digital channel with ``response_config``
        """
        self.configure_scope_trigger(
            channel=rule.scope_channel,
            level_volts=rule.threshold_volts,
            rising=rule.rising,
        )
        with self._lock:
            self._dwf.FDwfDigitalOutTriggerSourceSet(
                self._hdwf, ctypes.c_int(TRIGSRC_ANALOG_IN)
            )
            self._trigger_source = TRIGSRC_ANALOG_IN

        if rule.response_config is not None and rule.digital_channel >= 0:
            self.configure_digital_channel(rule.response_config)

        self._threshold_triggers.append(rule)

    def clear_threshold_triggers(self) -> None:
        """Remove all scope→digital trigger rules."""
        self._threshold_triggers.clear()

    def poll_and_cross_trigger(self) -> bool:
        """
        Software cross-trigger: poll scope, if threshold crossed, fire digital.

        Returns ``True`` if a trigger event was detected and acted on.
        Call from a background polling loop for software-based threshold triggers.
        """
        for rule in self._threshold_triggers:
            acq = self.poll_scope(rule.scope_channel)
            if acq is not None:
                if rule.rising:
                    triggered = bool(
                        np.any(np.diff(np.sign(acq.samples - rule.threshold_volts)) > 0)
                    )
                else:
                    triggered = bool(
                        np.any(np.diff(np.sign(acq.samples - rule.threshold_volts)) < 0)
                    )
                if triggered:
                    self.trigger()
                    return True
        return False

    # ------------------------------------------------------------------
    # Convenience presets
    # ------------------------------------------------------------------

    def setup_trigger_and_burst(
        self,
        trigger_channel: int = 0,
        trigger_rate_hz: float = 1000.0,
        burst_channel: int = 1,
        burst_on_us: float = 10.0,
        burst_off_us: float = 30.0,
        burst_count: int = 50,
        burst_delay: float = 0.0,
    ) -> None:
        """
        Convenience: set up a continuous trigger signal + synchronized burst.

        Example use case:

        - CH0: 1 kHz continuous trigger (50 % duty)
        - CH1: 50 reps of 10 µs on / 30 µs off, starting at trigger edge
        """
        trigger_cfg = DigitalChannelConfig(
            channel=trigger_channel,
            enabled=True,
            period=1.0 / trigger_rate_hz,
            duty_cycle=0.5,
            pulse_count=0,
        )

        burst_period = (burst_on_us + burst_off_us) * 1e-6
        burst_duty = burst_on_us / (burst_on_us + burst_off_us)

        burst_cfg = DigitalChannelConfig(
            channel=burst_channel,
            enabled=True,
            period=burst_period,
            duty_cycle=burst_duty,
            pulse_count=burst_count,
            delay=burst_delay,
        )

        self.configure_all_digital([trigger_cfg, burst_cfg])

    # ------------------------------------------------------------------
    # Configuration export / import
    # ------------------------------------------------------------------

    def export_config(self) -> dict:
        """Export current configuration as a JSON-serializable dict."""
        return {
            "digital_channels": [
                {
                    "channel": c.channel,
                    "enabled": c.enabled,
                    "period": c.period,
                    "duty_cycle": c.duty_cycle,
                    "delay": c.delay,
                    "pulse_count": c.pulse_count,
                    "idle_state": c.idle_state,
                }
                for c in self._digital_configs
            ],
            "scope_channels": [
                {
                    "channel": s.channel,
                    "enabled": s.enabled,
                    "range_volts": s.range_volts,
                    "offset_volts": s.offset_volts,
                    "sample_rate": s.sample_rate,
                    "buffer_size": s.buffer_size,
                    "coupling": s.coupling,
                }
                for s in self._scope_configs
            ],
        }

    def import_config(self, data: dict) -> None:
        """Import configuration from a dict (e.g. loaded from settings)."""
        for ch_data in data.get("digital_channels", []):
            cfg = DigitalChannelConfig(**ch_data)
            self.configure_digital_channel(cfg)
        for sc_data in data.get("scope_channels", []):
            cfg = ScopeChannelConfig(**sc_data)
            self.configure_scope_channel(cfg)


if __name__ == "__main__":
    # Example usage: print connected devices and run a simple pattern
    print("Connected Digilent devices:")
    for dev in enumerate_devices():
        print(f"  {dev['index']}: {dev['name']} (SN: {dev['serial']})")

    d = Digilent()
    d.open()
    try:
        d.setup_trigger_and_burst()
        d.start()
        print("Pattern generator started. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        d.stop()
        d.close()
