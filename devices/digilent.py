"""
Digilent Analog Discovery 2 driver.

Thread-safe, Qt-free driver wrapping the Digilent Waveforms SDK
(dwf.dll / libdwf.so) via ctypes.  Supports multi-channel digital pattern
generation, analog scope acquisition, and cross-domain (scope -> digital)
triggering.

Low-level SDK communication follows patterns established by the WF_SDK
reference library (waveforms/WF_SDK/), with added thread safety via a
per-device lock and typed ctypes declarations (argtypes/restype) for all
SDK functions to prevent silent 32-bit truncation.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import numpy as np

# ---------------------------------------------------------------------------
# DWF SDK loading  (refs: WF_SDK/device.py, WF_SDK/pattern.py)
# ---------------------------------------------------------------------------

if sys.platform.startswith("win"):
    _dwf = ctypes.cdll.dwf
    _constants_path = os.path.join(
        "C:" + os.sep,
        "Program Files (x86)",
        "Digilent",
        "WaveFormsSDK",
        "samples",
        "py",
    )
elif sys.platform.startswith("darwin"):
    _dwf = ctypes.cdll.LoadLibrary("/Library/Frameworks/dwf.framework/dwf")
    _constants_path = os.path.join(
        "/Applications",
        "WaveForms.app",
        "Contents",
        "Resources",
        "SDK",
        "samples",
        "py",
    )
else:
    _dwf = ctypes.cdll.LoadLibrary("libdwf.so")
    _constants_path = os.path.join(
        "/usr", "share", "digilent", "waveforms", "samples", "py"
    )

if _constants_path not in sys.path:
    sys.path.append(_constants_path)
import dwfconstants as _c  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Constant extraction helper
# ---------------------------------------------------------------------------


def _cval(c) -> int:
    """Extract int from a dwfconstants ctypes constant (c_ubyte / c_int)."""
    return int(c.value) if hasattr(c, "value") else int(c)


# ---------------------------------------------------------------------------
# Public constants  (refs: WF_SDK/pattern.py, WF_SDK/scope.py)
# ---------------------------------------------------------------------------

# Trigger sources
TRIGSRC_NONE = _cval(_c.trigsrcNone)
TRIGSRC_PC = _cval(_c.trigsrcPC)
TRIGSRC_ANALOG_IN = _cval(_c.trigsrcDetectorAnalogIn)  # scope trigger detector
TRIGSRC_DIGITAL_IN = _cval(_c.trigsrcDetectorDigitalIn)  # logic trigger detector
TRIGSRC_DIGITAL_OUT = _cval(_c.trigsrcDigitalOut)
TRIGSRC_EXTERNAL_1 = _cval(_c.trigsrcExternal1)
TRIGSRC_EXTERNAL_2 = _cval(_c.trigsrcExternal2)

# Wavegen waveform functions  (ref: WF_SDK/wavegen.py)
WAVEGEN_CUSTOM = _cval(_c.funcCustom)
WAVEGEN_SINE = _cval(_c.funcSine)
WAVEGEN_SQUARE = _cval(_c.funcSquare)
WAVEGEN_TRIANGLE = _cval(_c.funcTriangle)
WAVEGEN_NOISE = _cval(_c.funcNoise)
WAVEGEN_DC = _cval(_c.funcDC)
WAVEGEN_PULSE = _cval(_c.funcPulse)
WAVEGEN_TRAPEZIUM = _cval(_c.funcTrapezium)
WAVEGEN_SINE_POWER = _cval(_c.funcSinePower)
WAVEGEN_RAMP_UP = _cval(_c.funcRampUp)
WAVEGEN_RAMP_DOWN = _cval(_c.funcRampDown)

WAVEGEN_FUNCTION_NAMES: Dict[int, str] = {
    WAVEGEN_CUSTOM: "custom",
    WAVEGEN_SINE: "sine",
    WAVEGEN_SQUARE: "square",
    WAVEGEN_TRIANGLE: "triangle",
    WAVEGEN_NOISE: "noise",
    WAVEGEN_DC: "dc",
    WAVEGEN_PULSE: "pulse",
    WAVEGEN_TRAPEZIUM: "trapezium",
    WAVEGEN_SINE_POWER: "sine_power",
    WAVEGEN_RAMP_UP: "ramp_up",
    WAVEGEN_RAMP_DOWN: "ramp_down",
}

_WAVEGEN_FUNCTION_BY_NAME: Dict[str, int] = {
    v: k for k, v in WAVEGEN_FUNCTION_NAMES.items()
}

# ---------------------------------------------------------------------------
# Private constants
# ---------------------------------------------------------------------------

# Instrument states  (refs: WF_SDK/scope.py DwfStateDone)
_DWF_STATE_READY = 0
_DWF_STATE_ARMED = 1
_DWF_STATE_DONE = 2
_DWF_STATE_RUNNING = 3  # also "triggered"

# Digital-out type  (ref: WF_SDK/pattern.py function.pulse)
_DIGOUT_TYPE_PULSE = _cval(_c.DwfDigitalOutTypePulse)

# Digital-out idle  (ref: WF_SDK/pattern.py idle_state)
_IDLE_INIT = _cval(_c.DwfDigitalOutIdleInit)
_IDLE_LOW = _cval(_c.DwfDigitalOutIdleLow)
_IDLE_HIGH = _cval(_c.DwfDigitalOutIdleHigh)
_IDLE_ZET = _cval(_c.DwfDigitalOutIdleZet)

# Trigger conditions  (ref: WF_SDK/scope.py)
_TRIGCOND_RISING = _cval(_c.trigcondRisingPositive)
_TRIGCOND_FALLING = _cval(_c.trigcondFallingNegative)

# Trigger type  (ref: WF_SDK/scope.py)
_TRIGTYPE_EDGE = _cval(_c.trigtypeEdge)

# Trigger slope  (ref: WF_SDK/pattern.py)
_TRIGSLOPE_RISE = _cval(_c.DwfTriggerSlopeRise)
_TRIGSLOPE_FALL = _cval(_c.DwfTriggerSlopeFall)
_TRIGSLOPE_EITHER = _cval(_c.DwfTriggerSlopeEither)

# Scope filter  (ref: WF_SDK/scope.py)
_FILTER_DECIMATE = _cval(_c.filterDecimate)

# Analog output node  (ref: WF_SDK/wavegen.py)
_ANALOGOUT_NODE_CARRIER = _cval(_c.AnalogOutNodeCarrier)

# ---------------------------------------------------------------------------
# ctypes pointer aliases
# ---------------------------------------------------------------------------

_P_INT = ctypes.POINTER(ctypes.c_int)
_P_UINT = ctypes.POINTER(ctypes.c_uint)
_P_DOUBLE = ctypes.POINTER(ctypes.c_double)

# ---------------------------------------------------------------------------
# argtypes / restype declarations  (prevents silent truncation)
# ---------------------------------------------------------------------------


def _declare_signatures() -> None:
    """Declare argtypes and restype for every DWF function used."""
    d = _dwf

    # Device management  (ref: WF_SDK/device.py)
    d.FDwfEnum.argtypes = [ctypes.c_int, _P_INT]
    d.FDwfEnum.restype = ctypes.c_int

    d.FDwfEnumDeviceName.argtypes = [ctypes.c_int, ctypes.c_char_p]
    d.FDwfEnumDeviceName.restype = ctypes.c_int

    d.FDwfEnumSN.argtypes = [ctypes.c_int, ctypes.c_char_p]
    d.FDwfEnumSN.restype = ctypes.c_int

    d.FDwfDeviceOpen.argtypes = [ctypes.c_int, _P_INT]
    d.FDwfDeviceOpen.restype = ctypes.c_int

    d.FDwfDeviceClose.argtypes = [ctypes.c_int]
    d.FDwfDeviceClose.restype = ctypes.c_int

    d.FDwfGetLastError.argtypes = [_P_INT]
    d.FDwfGetLastError.restype = ctypes.c_int

    d.FDwfGetLastErrorMsg.argtypes = [ctypes.c_char_p]
    d.FDwfGetLastErrorMsg.restype = ctypes.c_int

    d.FDwfDeviceTriggerPC.argtypes = [ctypes.c_int]
    d.FDwfDeviceTriggerPC.restype = ctypes.c_int

    # Digital Out  (ref: WF_SDK/pattern.py)
    d.FDwfDigitalOutReset.argtypes = [ctypes.c_int]
    d.FDwfDigitalOutReset.restype = ctypes.c_int

    d.FDwfDigitalOutInternalClockInfo.argtypes = [ctypes.c_int, _P_DOUBLE]
    d.FDwfDigitalOutInternalClockInfo.restype = ctypes.c_int

    d.FDwfDigitalOutCounterInfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        _P_UINT,
    ]
    d.FDwfDigitalOutCounterInfo.restype = ctypes.c_int

    d.FDwfDigitalOutTriggerSourceSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfDigitalOutTriggerSourceSet.restype = ctypes.c_int

    d.FDwfDigitalOutTriggerSlopeSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfDigitalOutTriggerSlopeSet.restype = ctypes.c_int

    d.FDwfDigitalOutRunSet.argtypes = [ctypes.c_int, ctypes.c_double]
    d.FDwfDigitalOutRunSet.restype = ctypes.c_int

    d.FDwfDigitalOutRepeatSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfDigitalOutRepeatSet.restype = ctypes.c_int

    d.FDwfDigitalOutRepeatTriggerSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfDigitalOutRepeatTriggerSet.restype = ctypes.c_int

    d.FDwfDigitalOutEnableSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfDigitalOutEnableSet.restype = ctypes.c_int

    d.FDwfDigitalOutTypeSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfDigitalOutTypeSet.restype = ctypes.c_int

    d.FDwfDigitalOutIdleSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfDigitalOutIdleSet.restype = ctypes.c_int

    d.FDwfDigitalOutDividerSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    d.FDwfDigitalOutDividerSet.restype = ctypes.c_int

    d.FDwfDigitalOutCounterSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    d.FDwfDigitalOutCounterSet.restype = ctypes.c_int

    d.FDwfDigitalOutCounterInitSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    d.FDwfDigitalOutCounterInitSet.restype = ctypes.c_int

    d.FDwfDigitalOutConfigure.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfDigitalOutConfigure.restype = ctypes.c_int

    d.FDwfDigitalOutStatus.argtypes = [ctypes.c_int, _P_INT]
    d.FDwfDigitalOutStatus.restype = ctypes.c_int

    # Analog In (scope)  (ref: WF_SDK/scope.py)
    d.FDwfAnalogInReset.argtypes = [ctypes.c_int]
    d.FDwfAnalogInReset.restype = ctypes.c_int

    d.FDwfAnalogInChannelEnableSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogInChannelEnableSet.restype = ctypes.c_int

    d.FDwfAnalogInChannelRangeSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogInChannelRangeSet.restype = ctypes.c_int

    d.FDwfAnalogInChannelOffsetSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogInChannelOffsetSet.restype = ctypes.c_int

    d.FDwfAnalogInFrequencySet.argtypes = [ctypes.c_int, ctypes.c_double]
    d.FDwfAnalogInFrequencySet.restype = ctypes.c_int

    d.FDwfAnalogInBufferSizeSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogInBufferSizeSet.restype = ctypes.c_int

    d.FDwfAnalogInChannelFilterSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogInChannelFilterSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerSourceSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogInTriggerSourceSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerTypeSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogInTriggerTypeSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerChannelSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogInTriggerChannelSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerLevelSet.argtypes = [ctypes.c_int, ctypes.c_double]
    d.FDwfAnalogInTriggerLevelSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerConditionSet.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogInTriggerConditionSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerPositionSet.argtypes = [ctypes.c_int, ctypes.c_double]
    d.FDwfAnalogInTriggerPositionSet.restype = ctypes.c_int

    d.FDwfAnalogInTriggerAutoTimeoutSet.argtypes = [
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogInTriggerAutoTimeoutSet.restype = ctypes.c_int

    d.FDwfAnalogInConfigure.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogInConfigure.restype = ctypes.c_int

    d.FDwfAnalogInStatus.argtypes = [ctypes.c_int, ctypes.c_int, _P_INT]
    d.FDwfAnalogInStatus.restype = ctypes.c_int

    d.FDwfAnalogInStatusData.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
    ]
    d.FDwfAnalogInStatusData.restype = ctypes.c_int

    # Analog Out (wavegen)  (ref: WF_SDK/wavegen.py)
    d.FDwfAnalogOutReset.argtypes = [ctypes.c_int, ctypes.c_int]
    d.FDwfAnalogOutReset.restype = ctypes.c_int

    d.FDwfAnalogOutNodeEnableSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutNodeEnableSet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeFunctionSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutNodeFunctionSet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeDataSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
    ]
    d.FDwfAnalogOutNodeDataSet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeFrequencySet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutNodeFrequencySet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeAmplitudeSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutNodeAmplitudeSet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeOffsetSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutNodeOffsetSet.restype = ctypes.c_int

    d.FDwfAnalogOutNodeSymmetrySet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutNodeSymmetrySet.restype = ctypes.c_int

    d.FDwfAnalogOutRunSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutRunSet.restype = ctypes.c_int

    d.FDwfAnalogOutWaitSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_double,
    ]
    d.FDwfAnalogOutWaitSet.restype = ctypes.c_int

    d.FDwfAnalogOutRepeatSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutRepeatSet.restype = ctypes.c_int

    d.FDwfAnalogOutConfigure.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutConfigure.restype = ctypes.c_int

    d.FDwfAnalogOutStatus.argtypes = [ctypes.c_int, ctypes.c_int, _P_INT]
    d.FDwfAnalogOutStatus.restype = ctypes.c_int

    d.FDwfAnalogOutTriggerSourceSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutTriggerSourceSet.restype = ctypes.c_int

    d.FDwfAnalogOutTriggerSlopeSet.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    d.FDwfAnalogOutTriggerSlopeSet.restype = ctypes.c_int


_declare_signatures()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DigitalChannelConfig:
    """Configuration for one digital output channel (0-15)."""

    channel: int
    enabled: bool = False
    period: float = 1e-3  # seconds
    duty_cycle: float = 0.5  # fraction (0-1)
    delay: float = 0.0  # seconds, offset from trigger/start
    pulse_count: int = 0  # 0 = continuous
    idle_state: bool = False  # False = LOW, True = HIGH

    @property
    def pulse_width(self) -> float:
        """HIGH time in seconds."""
        return self.period * self.duty_cycle

    @property
    def repetition_rate(self) -> float:
        """Frequency in Hz."""
        return 1.0 / self.period if self.period > 0 else 0.0

    def __str__(self) -> str:
        if not self.enabled:
            return f"DIO{self.channel}: disabled"
        return (
            f"DIO{self.channel}("
            f"{self.duty_cycle * 100:.1f}% @ "
            f"{self.repetition_rate:.2f} Hz,"
            f"{self.delay * 1e3:.1f} ms delay, "
            f"idle={'HIGH' if self.idle_state else 'LOW'})"
        )


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

    def __str__(self):
        if not self.enabled:
            return f"CH{self.channel}: disabled"
        return (
            f"CH{self.channel}: "
            f"{self.range_volts} V, "
            f"{self.offset_volts} V offset, "
            f"{self.sample_rate} Hz sample rate, "
            f"{self.buffer_size} buffer size, "
            f"{self.coupling} coupling"
        )


@dataclass
class ScopeThresholdTrigger:
    """Rule: when scope channel crosses threshold, fire a digital channel."""

    scope_channel: int
    threshold_volts: float
    rising: bool = True
    digital_channel: int = -1
    response_config: Optional[DigitalChannelConfig] = None

    def __str__(self):
        return f"Threshold({'↑' if self.rising else '↓'} {self.threshold_volts} CH{self.scope_channel} -> {f' {self.response_config}' if self.response_config else f'DIO{self.digital_channel}'})"


@dataclass(frozen=True)
class PatternState:
    """Immutable snapshot of the pattern generator status."""

    running: bool
    channels: Tuple[DigitalChannelConfig, ...]
    elapsed_time: float
    trigger_source: str

    def __str__(self):
        status = "RUNNING" if self.running else "STOPPED"
        return (
            f"PatternState: {status}\n"
            f"Elapsed time: {self.elapsed_time:.3f} s\n"
            f"Trigger source: {self.trigger_source}\n"
            f"Channels:\n" + "\n".join(f"  {ch}" for ch in self.channels)
        )


@dataclass(frozen=True)
class ScopeAcquisition:
    """Immutable snapshot of a completed scope acquisition."""

    channel: int
    samples: np.ndarray
    sample_rate: float
    trigger_position: int
    timestamp: float
    clipped: bool


@dataclass
class WavegenChannelConfig:
    """Configuration for one analog output (wavegen) channel (0 or 1)."""

    channel: int
    enabled: bool = False
    function: int = WAVEGEN_SINE  # use WAVEGEN_* constants
    frequency: float = 1e3  # Hz
    amplitude: float = 1.0  # Volts (peak)
    offset: float = 0.0  # Volts (DC offset)
    symmetry: float = 50.0  # percentage (0–100)
    wait: float = 0.0  # seconds before start
    run_time: float = 0.0  # seconds, 0 = infinite
    repeat: int = 0  # 0 = infinite
    custom_data: Optional[List[float]] = None  # voltages for funcCustom

    def __str__(self) -> str:
        if not self.enabled:
            return f"W{self.channel}: disabled"
        fn_name = WAVEGEN_FUNCTION_NAMES.get(self.function, str(self.function))
        return (
            f"W{self.channel}({fn_name} "
            f"{self.frequency:.0f} Hz, "
            f"{self.amplitude:.3f} V, "
            f"offset {self.offset:.3f} V)"
        )


@dataclass(frozen=True)
class WavegenState:
    """Immutable snapshot of the waveform generator status."""

    running: Tuple[bool, ...]
    channels: Tuple[WavegenChannelConfig, ...]

    def __str__(self) -> str:
        lines = ["WavegenState:"]
        for ch, r in zip(self.channels, self.running):
            lines.append(f"  {'RUNNING' if r else 'stopped'} {ch}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def enumerate_devices() -> List[Dict[str, int | str]]:
    """Return list of connected Digilent devices with name, serial, index.

    Uses the same enumeration pattern as WF_SDK/device.py ``open()``.
    """
    count = ctypes.c_int()
    _dwf.FDwfEnum(ctypes.c_int(0), ctypes.byref(count))
    devices: List[Dict[str, int | str]] = []
    for i in range(count.value):
        name = ctypes.create_string_buffer(64)
        serial = ctypes.create_string_buffer(64)
        _dwf.FDwfEnumDeviceName(ctypes.c_int(i), name)
        _dwf.FDwfEnumSN(ctypes.c_int(i), serial)
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
    """Thread-safe driver for the Digilent Analog Discovery 2.

    Supports multi-channel digital pattern generation, analog scope
    acquisition, and cross-domain (scope -> digital) triggering.

    Lifecycle::

        d = Digilent()
        d.open()          # connect to hardware
        # ... configure & run ...
        d.close()         # release hardware
    """

    NUM_DIGITAL_CHANNELS = 16
    NUM_SCOPE_CHANNELS = 2
    NUM_WAVEGEN_CHANNELS = 2

    def __init__(self, device_index: int = -1) -> None:
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
        self._wavegen_configs: List[WavegenChannelConfig] = [
            WavegenChannelConfig(channel=i) for i in range(self.NUM_WAVEGEN_CHANNELS)
        ]
        self._threshold_triggers: List[ScopeThresholdTrigger] = []

        self._internal_clock_hz: float = 0.0
        self._trigger_source: int = TRIGSRC_NONE
        self._repeat_count: int = 0
        self._run_duration_seconds: float = 0.0

    # ------------------------------------------------------------------
    # Error helpers  (ref: WF_SDK/device.py check_error)
    # ------------------------------------------------------------------

    def _check_error(self) -> None:
        """Query the SDK for the last error and raise if non-zero."""
        code = ctypes.c_int()
        _dwf.FDwfGetLastError(ctypes.byref(code))
        if code.value != 0:
            msg = ctypes.create_string_buffer(512)
            _dwf.FDwfGetLastErrorMsg(msg)
            raise RuntimeError(f"DWF error {code.value}: {msg.value.decode()}")

    def _call(self, func_name: str, *args) -> None:
        """Invoke a DWF function and raise on failure.

        DWF functions return non-zero on success, 0 on failure.
        """
        fn = getattr(_dwf, func_name)
        ok = fn(*args)
        if ok != 0:
            return
        try:
            self._check_error()
        except RuntimeError as exc:
            raise RuntimeError(f"{func_name} failed: {exc}") from exc
        raise RuntimeError(f"{func_name} failed")

    def _require_connected(self) -> None:
        if not self._connected or self._hdwf.value == 0:
            raise RuntimeError("Digilent device is not connected")

    # ------------------------------------------------------------------
    # Connection management  (ref: WF_SDK/device.py open/close)
    # ------------------------------------------------------------------

    def open(self, device_index: Optional[int] = None) -> None:
        """Open connection to a Digilent device."""
        with self._lock:
            idx = device_index if device_index is not None else self._device_index
            print(f"[Digilent] open(device_index={idx})")
            self._call("FDwfDeviceOpen", ctypes.c_int(idx), ctypes.byref(self._hdwf))
            if self._hdwf.value == 0:
                msg = ctypes.create_string_buffer(512)
                _dwf.FDwfGetLastErrorMsg(msg)
                raise RuntimeError(
                    f"Failed to open Digilent device: {msg.value.decode()}"
                )
            self._connected = True
            print(f"[Digilent] device opened, hdwf={self._hdwf.value}")

            # Query internal clock  (ref: WF_SDK/pattern.py)
            freq = ctypes.c_double()
            self._call(
                "FDwfDigitalOutInternalClockInfo", self._hdwf, ctypes.byref(freq)
            )
            self._internal_clock_hz = freq.value
            print(f"[Digilent] internal clock = {self._internal_clock_hz} Hz")

    @property
    def connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        """Close device handle and release resources."""
        with self._lock:
            if self._connected:
                print(f"[Digilent] close() hdwf={self._hdwf.value}")
                self._call("FDwfDeviceClose", self._hdwf)
                self._hdwf.value = 0
                self._connected = False
                self._running = False
                print("[Digilent] device closed")

    # ------------------------------------------------------------------
    # Digital output — per-channel configuration
    # (refs: WF_SDK/pattern.py generate)
    # ------------------------------------------------------------------

    def configure_digital_channel(self, config: DigitalChannelConfig) -> None:
        """Apply settings for one digital output channel."""
        with self._lock:
            self._configure_digital_channel_locked(config)

    def _configure_digital_channel_locked(self, config: DigitalChannelConfig) -> None:
        """Internal: configure a channel while the lock is already held."""
        self._require_connected()
        if not (0 <= config.channel < self.NUM_DIGITAL_CHANNELS):
            raise ValueError(f"Invalid digital channel index: {config.channel}")

        ch = ctypes.c_int(config.channel)

        # Enable/disable  (ref: WF_SDK/pattern.py enable/disable)
        self._call(
            "FDwfDigitalOutEnableSet", self._hdwf, ch, ctypes.c_int(int(config.enabled))
        )

        if not config.enabled:
            self._digital_configs[config.channel] = config
            return

        # Pulse output type
        self._call(
            "FDwfDigitalOutTypeSet", self._hdwf, ch, ctypes.c_int(_DIGOUT_TYPE_PULSE)
        )

        # Idle level
        idle = _IDLE_HIGH if config.idle_state else _IDLE_LOW
        self._call("FDwfDigitalOutIdleSet", self._hdwf, ch, ctypes.c_int(idle))

        # Query counter limit for this channel  (ref: WF_SDK/pattern.py)
        counter_limit = ctypes.c_uint()
        self._call(
            "FDwfDigitalOutCounterInfo",
            self._hdwf,
            ch,
            ctypes.c_int(0),
            ctypes.byref(counter_limit),
        )
        climit = counter_limit.value

        # Timing: calculate divider to keep counter values within range
        # (ref: WF_SDK/pattern.py divider calculation)
        total_ticks_f = self._internal_clock_hz * config.period
        if climit > 0:
            divider = int(math.ceil(total_ticks_f / climit))
        else:
            divider = 1
        divider = max(1, divider)

        # Counter ticks in the divided clock domain
        total_steps = max(2, int(round(total_ticks_f / divider)))
        high_steps = max(1, int(total_steps * config.duty_cycle))
        low_steps = max(1, total_steps - high_steps)

        self._call("FDwfDigitalOutDividerSet", self._hdwf, ch, ctypes.c_uint(divider))
        self._call(
            "FDwfDigitalOutCounterSet",
            self._hdwf,
            ch,
            ctypes.c_uint(low_steps),
            ctypes.c_uint(high_steps),
        )

        # Delay via counter initial value
        if config.delay > 0:
            delay_ticks = int(config.delay * self._internal_clock_hz / divider)
            # Start LOW, count down delay_ticks before first pulse
            self._call(
                "FDwfDigitalOutCounterInitSet",
                self._hdwf,
                ch,
                ctypes.c_int(0),
                ctypes.c_uint(delay_ticks),
            )
        else:
            # Start HIGH immediately (first half cycle is the pulse)
            self._call(
                "FDwfDigitalOutCounterInitSet",
                self._hdwf,
                ch,
                ctypes.c_int(1),
                ctypes.c_uint(0),
            )

        self._digital_configs[config.channel] = config

    def configure_all_digital(self, configs: List[DigitalChannelConfig]) -> None:
        """Apply settings for multiple channels atomically (resets first)."""
        with self._lock:
            self._require_connected()
            self._call("FDwfDigitalOutReset", self._hdwf)
            for cfg in configs:
                self._configure_digital_channel_locked(cfg)

    # ------------------------------------------------------------------
    # Digital output — trigger & repeat
    # ------------------------------------------------------------------

    def set_trigger_source(self, source: int = TRIGSRC_PC) -> None:
        """Set the master trigger source for the digital pattern generator.

        Use the ``TRIGSRC_*`` module constants.
        """
        with self._lock:
            self._require_connected()
            self._call(
                "FDwfDigitalOutTriggerSourceSet", self._hdwf, ctypes.c_int(source)
            )
            self._trigger_source = source

    def set_repeat_count(self, count: int = 0) -> None:
        """Set number of pattern repetitions.  0 = infinite."""
        with self._lock:
            self._require_connected()
            self._call("FDwfDigitalOutRepeatSet", self._hdwf, ctypes.c_int(count))
            self._repeat_count = count

    def set_run_duration(self, seconds: float = 0.0) -> None:
        """Set total run duration.  0 = determined by repeat count."""
        with self._lock:
            self._require_connected()
            self._call("FDwfDigitalOutRunSet", self._hdwf, ctypes.c_double(seconds))
            self._run_duration_seconds = seconds

    # ------------------------------------------------------------------
    # Digital output — start / stop / status
    # (ref: WF_SDK/pattern.py generate, close)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Arm and start the digital pattern generator."""
        with self._lock:
            self._require_connected()

            # Re-apply global settings (they may be cleared by DigitalOutReset)
            self._call(
                "FDwfDigitalOutTriggerSourceSet",
                self._hdwf,
                ctypes.c_int(self._trigger_source),
            )
            self._call(
                "FDwfDigitalOutRepeatSet", self._hdwf, ctypes.c_int(self._repeat_count)
            )
            self._call(
                "FDwfDigitalOutRunSet",
                self._hdwf,
                ctypes.c_double(self._run_duration_seconds),
            )

            # Repeat-trigger: re-arm on each trigger event when using
            # an external trigger source  (ref: WF_SDK/pattern.py)
            repeat_trigger = 1 if self._trigger_source != TRIGSRC_NONE else 0
            self._call(
                "FDwfDigitalOutRepeatTriggerSet",
                self._hdwf,
                ctypes.c_int(repeat_trigger),
            )

            # Default to rising-edge trigger slope when trigger is active
            if self._trigger_source != TRIGSRC_NONE:
                self._call(
                    "FDwfDigitalOutTriggerSlopeSet",
                    self._hdwf,
                    ctypes.c_int(_TRIGSLOPE_RISE),
                )

            self._call("FDwfDigitalOutConfigure", self._hdwf, ctypes.c_int(1))
            self._running = True
            self._start_time = time.monotonic()

    def stop(self) -> None:
        """Stop the digital pattern generator."""
        with self._lock:
            if not self._connected:
                self._running = False
                return
            self._call("FDwfDigitalOutConfigure", self._hdwf, ctypes.c_int(0))
            self._running = False

    def trigger(self) -> None:
        """Send a software trigger (when trigger source is PC)."""
        with self._lock:
            self._require_connected()
            self._call("FDwfDeviceTriggerPC", self._hdwf)

    @property
    def is_running(self) -> bool:
        """Query whether the pattern generator is currently active."""
        with self._lock:
            if not self._connected:
                return False
            sts = ctypes.c_int()
            self._call("FDwfDigitalOutStatus", self._hdwf, ctypes.byref(sts))
            self._running = sts.value == _DWF_STATE_RUNNING
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
    # (ref: WF_SDK/scope.py open, trigger)
    # ------------------------------------------------------------------

    def configure_scope_channel(self, config: ScopeChannelConfig) -> None:
        """Configure one analog input (scope) channel."""
        with self._lock:
            self._require_connected()
            if not (0 <= config.channel < self.NUM_SCOPE_CHANNELS):
                raise ValueError(f"Invalid scope channel index: {config.channel}")
            ch = ctypes.c_int(config.channel)

            self._call(
                "FDwfAnalogInChannelEnableSet",
                self._hdwf,
                ch,
                ctypes.c_int(int(config.enabled)),
            )
            self._call(
                "FDwfAnalogInChannelRangeSet",
                self._hdwf,
                ch,
                ctypes.c_double(config.range_volts),
            )
            self._call(
                "FDwfAnalogInChannelOffsetSet",
                self._hdwf,
                ch,
                ctypes.c_double(config.offset_volts),
            )
            self._call(
                "FDwfAnalogInFrequencySet",
                self._hdwf,
                ctypes.c_double(config.sample_rate),
            )
            self._call(
                "FDwfAnalogInBufferSizeSet",
                self._hdwf,
                ctypes.c_int(config.buffer_size),
            )
            # Disable averaging  (ref: WF_SDK/scope.py open)
            self._call(
                "FDwfAnalogInChannelFilterSet",
                self._hdwf,
                ch,
                ctypes.c_int(_FILTER_DECIMATE),
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
        """Configure the analog-in trigger for scope acquisition.

        Uses the scope's own trigger detector as source, with edge
        triggering.  (ref: WF_SDK/scope.py trigger)
        """
        with self._lock:
            self._require_connected()

            # Source: scope's trigger detector  (ref: WF_SDK/scope.py)
            self._call(
                "FDwfAnalogInTriggerSourceSet",
                self._hdwf,
                ctypes.c_int(TRIGSRC_ANALOG_IN),
            )
            self._call(
                "FDwfAnalogInTriggerChannelSet",
                self._hdwf,
                ctypes.c_int(channel),
            )

            # Trigger type: edge  (ref: WF_SDK/scope.py)
            self._call(
                "FDwfAnalogInTriggerTypeSet",
                self._hdwf,
                ctypes.c_int(_TRIGTYPE_EDGE),
            )
            self._call(
                "FDwfAnalogInTriggerLevelSet",
                self._hdwf,
                ctypes.c_double(level_volts),
            )

            # Trigger condition: rising or falling
            cond = _TRIGCOND_RISING if rising else _TRIGCOND_FALLING
            self._call(
                "FDwfAnalogInTriggerConditionSet",
                self._hdwf,
                ctypes.c_int(cond),
            )
            self._call(
                "FDwfAnalogInTriggerPositionSet",
                self._hdwf,
                ctypes.c_double(position_seconds),
            )
            self._call(
                "FDwfAnalogInTriggerAutoTimeoutSet",
                self._hdwf,
                ctypes.c_double(auto_timeout),
            )

    # ------------------------------------------------------------------
    # Analog input — acquisition
    # (ref: WF_SDK/scope.py record, measure)
    # ------------------------------------------------------------------

    def start_scope(self) -> None:
        """Arm the scope for acquisition (waits for trigger)."""
        with self._lock:
            self._require_connected()
            self._call(
                "FDwfAnalogInConfigure",
                self._hdwf,
                ctypes.c_int(1),
                ctypes.c_int(1),
            )

    def poll_scope(self, channel: int = 0) -> Optional[ScopeAcquisition]:
        """Non-blocking check: if scope acquisition is complete, return data.

        Returns ``None`` if still acquiring.  Designed to be called from a
        polling loop (e.g. ``ThreadPoolExecutor``).
        """
        import numpy as _np

        with self._lock:
            self._require_connected()
            sts = ctypes.c_int()
            self._call(
                "FDwfAnalogInStatus",
                self._hdwf,
                ctypes.c_int(1),
                ctypes.byref(sts),
            )
            if sts.value != _DWF_STATE_DONE:
                return None

            config = self._scope_configs[channel]
            n = config.buffer_size
            buf = (ctypes.c_double * n)()
            self._call(
                "FDwfAnalogInStatusData",
                self._hdwf,
                ctypes.c_int(channel),
                buf,
                ctypes.c_int(n),
            )

            return ScopeAcquisition(
                channel=channel,
                samples=_np.ctypeslib.as_array(buf).copy(),
                sample_rate=config.sample_rate,
                trigger_position=n // 2,
                timestamp=time.monotonic(),
                clipped=False,
            )

    def stop_scope(self) -> None:
        """Stop scope acquisition."""
        with self._lock:
            if not self._connected:
                return
            self._call(
                "FDwfAnalogInConfigure",
                self._hdwf,
                ctypes.c_int(0),
                ctypes.c_int(0),
            )

    # ------------------------------------------------------------------
    # Analog output — waveform generator
    # (ref: WF_SDK/wavegen.py)
    # ------------------------------------------------------------------

    def configure_wavegen_channel(self, config: WavegenChannelConfig) -> None:
        """Configure one analog output (wavegen) channel without starting it."""
        with self._lock:
            self._configure_wavegen_channel_locked(config)

    def _configure_wavegen_channel_locked(self, config: WavegenChannelConfig) -> None:
        """Internal: configure a wavegen channel while lock is held."""
        self._require_connected()
        if not (0 <= config.channel < self.NUM_WAVEGEN_CHANNELS):
            raise ValueError(f"Invalid wavegen channel index: {config.channel}")

        ch = ctypes.c_int(config.channel)
        node = ctypes.c_int(_ANALOGOUT_NODE_CARRIER)

        # Enable / disable carrier node
        self._call(
            "FDwfAnalogOutNodeEnableSet",
            self._hdwf,
            ch,
            node,
            ctypes.c_int(int(config.enabled)),
        )

        if not config.enabled:
            self._wavegen_configs[config.channel] = config
            return

        # Waveform function  (ref: WF_SDK/wavegen.py function class)
        self._call(
            "FDwfAnalogOutNodeFunctionSet",
            self._hdwf,
            ch,
            node,
            ctypes.c_int(config.function),
        )

        # Custom waveform data
        if config.function == WAVEGEN_CUSTOM and config.custom_data:
            n = len(config.custom_data)
            buf = (ctypes.c_double * n)(*config.custom_data)
            self._call(
                "FDwfAnalogOutNodeDataSet",
                self._hdwf,
                ch,
                node,
                buf,
                ctypes.c_int(n),
            )

        # Frequency
        self._call(
            "FDwfAnalogOutNodeFrequencySet",
            self._hdwf,
            ch,
            node,
            ctypes.c_double(config.frequency),
        )

        # Amplitude (peak voltage)
        self._call(
            "FDwfAnalogOutNodeAmplitudeSet",
            self._hdwf,
            ch,
            node,
            ctypes.c_double(config.amplitude),
        )

        # DC offset
        self._call(
            "FDwfAnalogOutNodeOffsetSet",
            self._hdwf,
            ch,
            node,
            ctypes.c_double(config.offset),
        )

        # Symmetry (percentage 0–100)
        self._call(
            "FDwfAnalogOutNodeSymmetrySet",
            self._hdwf,
            ch,
            node,
            ctypes.c_double(config.symmetry),
        )

        # Run time (0 = infinite)
        self._call(
            "FDwfAnalogOutRunSet",
            self._hdwf,
            ch,
            ctypes.c_double(config.run_time),
        )

        # Wait time before start
        self._call(
            "FDwfAnalogOutWaitSet",
            self._hdwf,
            ch,
            ctypes.c_double(config.wait),
        )

        # Repeat count (0 = infinite)
        self._call(
            "FDwfAnalogOutRepeatSet",
            self._hdwf,
            ch,
            ctypes.c_int(config.repeat),
        )

        self._wavegen_configs[config.channel] = config

    def generate_wavegen(self, config: WavegenChannelConfig) -> None:
        """Configure and immediately start one analog output channel.

        Convenience combining configure + start in a single call
        (mirrors WF_SDK/wavegen.py ``generate``).
        """
        with self._lock:
            self._configure_wavegen_channel_locked(config)
            self._call(
                "FDwfAnalogOutConfigure",
                self._hdwf,
                ctypes.c_int(config.channel),
                ctypes.c_int(1),
            )

    def start_wavegen(self, channel: int) -> None:
        """Start (enable) one analog output channel."""
        with self._lock:
            self._require_connected()
            if not (0 <= channel < self.NUM_WAVEGEN_CHANNELS):
                raise ValueError(f"Invalid wavegen channel index: {channel}")
            self._call(
                "FDwfAnalogOutConfigure",
                self._hdwf,
                ctypes.c_int(channel),
                ctypes.c_int(1),
            )

    def stop_wavegen(self, channel: int) -> None:
        """Stop (disable) one analog output channel."""
        with self._lock:
            if not self._connected:
                return
            self._call(
                "FDwfAnalogOutConfigure",
                self._hdwf,
                ctypes.c_int(channel),
                ctypes.c_int(0),
            )

    def reset_wavegen(self, channel: int = -1) -> None:
        """Reset one wavegen channel, or all channels (channel=-1)."""
        with self._lock:
            if not self._connected:
                return
            self._call(
                "FDwfAnalogOutReset",
                self._hdwf,
                ctypes.c_int(channel),
            )
            if channel < 0:
                self._wavegen_configs = [
                    WavegenChannelConfig(channel=i)
                    for i in range(self.NUM_WAVEGEN_CHANNELS)
                ]
            else:
                self._wavegen_configs[channel] = WavegenChannelConfig(channel=channel)

    def set_wavegen_trigger_source(
        self, channel: int, source: int = TRIGSRC_NONE
    ) -> None:
        """Set the trigger source for one analog output channel.

        Use ``TRIGSRC_*`` module constants.
        """
        with self._lock:
            self._require_connected()
            self._call(
                "FDwfAnalogOutTriggerSourceSet",
                self._hdwf,
                ctypes.c_int(channel),
                ctypes.c_int(source),
            )

    def set_wavegen_trigger_slope(
        self, channel: int, slope: int = _TRIGSLOPE_RISE
    ) -> None:
        """Set the trigger slope for one analog output channel."""
        with self._lock:
            self._require_connected()
            self._call(
                "FDwfAnalogOutTriggerSlopeSet",
                self._hdwf,
                ctypes.c_int(channel),
                ctypes.c_int(slope),
            )

    @property
    def wavegen_running(self) -> List[bool]:
        """Query whether each wavegen channel is currently active."""
        with self._lock:
            if not self._connected:
                return [False] * self.NUM_WAVEGEN_CHANNELS
            result: List[bool] = []
            for ch in range(self.NUM_WAVEGEN_CHANNELS):
                sts = ctypes.c_int()
                self._call(
                    "FDwfAnalogOutStatus",
                    self._hdwf,
                    ctypes.c_int(ch),
                    ctypes.byref(sts),
                )
                result.append(sts.value == _DWF_STATE_RUNNING)
            return result

    def get_wavegen_state(self) -> WavegenState:
        """Return an immutable snapshot of the wavegen status."""
        with self._lock:
            if not self._connected:
                running: Tuple[bool, ...] = tuple(
                    False for _ in range(self.NUM_WAVEGEN_CHANNELS)
                )
            else:
                running_list: List[bool] = []
                for ch in range(self.NUM_WAVEGEN_CHANNELS):
                    sts = ctypes.c_int()
                    self._call(
                        "FDwfAnalogOutStatus",
                        self._hdwf,
                        ctypes.c_int(ch),
                        ctypes.byref(sts),
                    )
                    running_list.append(sts.value == _DWF_STATE_RUNNING)
                running = tuple(running_list)
            return WavegenState(
                running=running,
                channels=tuple(self._wavegen_configs),
            )

    def stop_all(self) -> None:
        """Stop all activity (digital output, scope, and wavegen)."""
        self.stop()
        self.stop_scope()
        for ch in range(self.NUM_WAVEGEN_CHANNELS):
            self.stop_wavegen(ch)

    # ------------------------------------------------------------------
    # Cross-trigger: scope -> digital
    # ------------------------------------------------------------------

    def configure_scope_to_digital_trigger(self, rule: ScopeThresholdTrigger) -> None:
        """Set up hardware cross-trigger: scope threshold -> digital output.

        1. Configures the scope trigger on the specified channel/threshold
        2. Routes the scope trigger detector to the digital-out trigger bus
        3. Configures the target digital channel with ``response_config``
        """
        self.configure_scope_trigger(
            channel=rule.scope_channel,
            level_volts=rule.threshold_volts,
            rising=rule.rising,
        )
        with self._lock:
            self._require_connected()
            # Route scope trigger detector -> digital out
            self._call(
                "FDwfDigitalOutTriggerSourceSet",
                self._hdwf,
                ctypes.c_int(TRIGSRC_ANALOG_IN),
            )
            self._trigger_source = TRIGSRC_ANALOG_IN

        if rule.response_config is not None and rule.digital_channel >= 0:
            self.configure_digital_channel(rule.response_config)

        self._threshold_triggers.append(rule)

    def clear_threshold_triggers(self) -> None:
        """Remove all scope -> digital trigger rules."""
        self._threshold_triggers.clear()

    def poll_and_cross_trigger(self) -> bool:
        """Software cross-trigger fallback: poll scope, fire digital if
        threshold crossed.

        Returns ``True`` if a trigger event was detected and acted on.
        Call from a background polling loop for software-based threshold
        triggers when the hardware trigger bus is insufficient.
        """
        import numpy as _np

        for rule in self._threshold_triggers:
            acq = self.poll_scope(rule.scope_channel)
            if acq is not None:
                diff = _np.diff(_np.sign(acq.samples - rule.threshold_volts))
                if rule.rising:
                    triggered = bool(_np.any(diff > 0))
                else:
                    triggered = bool(_np.any(diff < 0))
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
        """Convenience: continuous trigger signal + synchronized burst.

        Example: CH0 = 1 kHz continuous trigger (50 % duty),
        CH1 = 50 reps of 10 us on / 30 us off starting at trigger edge.
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
            "wavegen_channels": [
                {
                    "channel": w.channel,
                    "enabled": w.enabled,
                    "function": WAVEGEN_FUNCTION_NAMES.get(w.function, str(w.function)),
                    "frequency": w.frequency,
                    "amplitude": w.amplitude,
                    "offset": w.offset,
                    "symmetry": w.symmetry,
                    "wait": w.wait,
                    "run_time": w.run_time,
                    "repeat": w.repeat,
                }
                for w in self._wavegen_configs
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
        for wg_data in data.get("wavegen_channels", []):
            wg_data = dict(wg_data)  # copy to avoid mutating input
            fn = wg_data.get("function")
            if isinstance(fn, str):
                wg_data["function"] = _WAVEGEN_FUNCTION_BY_NAME.get(fn, WAVEGEN_SINE)
            wg_data.pop("custom_data", None)  # not serialized in export
            cfg = WavegenChannelConfig(**wg_data)
            self.configure_wavegen_channel(cfg)


if __name__ == "__main__":

    print("Connected devices:", enumerate_devices())

    digilent = Digilent()
    digilent.open()
    print("Current pattern state:", digilent.get_pattern_state())
    print("\nConfigure output channel:")
    channel = input("Channel number (0–15) [0]: ").strip()
    try:
        channel = int(channel) if channel else 0
    except ValueError:
        print("Invalid channel number. Defaulting to 0.")
        channel = 0
    print("Type 'q' at any prompt to exit.\n")

    def str_to_float(s: str) -> float:
        """parse string of form 11.1111k -> 11111.1"""
        prefixes = {"u": -6, "m": -3, "k": 3, "M": 6, "G": 9}
        s = s.strip()
        if s and s[-1] in prefixes:
            try:
                return float(s[:-1]) * (10 ** prefixes[s[-1]])
            except ValueError:
                pass
        return float(s)

    def _prompt_float(prompt: str, default: float) -> Optional[float]:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw.lower() in {"q", "quit", "exit"}:
            return None
        if raw == "":
            return default
        return str_to_float(raw)

    def _prompt_square_wave() -> Optional[Tuple[float, float]]:
        while True:
            try:
                freq_hz = _prompt_float("D0 frequency (Hz)", 1000.0)
                if freq_hz is None:
                    return None
                duty_pct = _prompt_float("D0 duty cycle (%)", 50.0)
                if duty_pct is None:
                    return None
                break
            except ValueError:
                print("Invalid numeric input. Try again.\n")
                continue
        return freq_hz, duty_pct

    try:
        # code
        while True:
            square_wave = _prompt_square_wave()
            if square_wave is None:
                break
            freq_hz, duty_pct = square_wave
            cfg = DigitalChannelConfig(
                channel=channel,
                enabled=True,
                period=1.0 / freq_hz,
                duty_cycle=duty_pct / 100.0,
            )
            digilent.configure_digital_channel(cfg)
            digilent.start()
            print(
                f"Running D{channel} at {freq_hz} Hz, {duty_pct}% duty. Press Ctrl+C to stop.\n"
            )
            print("Current pattern state:", digilent.get_pattern_state())
            q = input("Press Enter to reconfigure or 'q' to quit.\n")
            if q in ["q", "quit", "exit"]:
                break
            digilent.stop()
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        digilent.stop_all()
        digilent.close()
