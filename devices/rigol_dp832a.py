"""
Pure-Python driver for one or more Rigol DP832A DC power supplies.

No Qt dependency — safe to use from scripts, notebooks, and tests.
Thread-safe: every SCPI transaction is guarded by a per-instrument lock.

Reference: [Rigol DP800 Programming Guide](https://www.batronix.com/pdf/Rigol/ProgrammingGuide/DP800_ProgrammingGuide_EN.pdf)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from pyvisa import ResourceManager
from pyvisa.resources import MessageBasedResource
from pyvisa.errors import VisaIOError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ChannelInfo:
    """Snapshot of one channel's state (cached by poll_all)."""

    number: int  # 1, 2, or 3
    max_voltage: float = 0.0
    max_current: float = 0.0
    set_voltage: float = 0.0
    set_current: float = 0.0
    meas_voltage: float = 0.0
    meas_current: float = 0.0
    meas_power: float = 0.0
    output_enabled: bool = False


# ---------------------------------------------------------------------------
# Single-supply driver
# ---------------------------------------------------------------------------


class RigolDP832A:
    """Thread-safe pyvisa wrapper for one Rigol DP832A supply."""

    # DP832A has 3 channels: CH1 (32 V/3.2 A), CH2 (32 V/3.2 A), CH3 (5.3 V/3.2 A)
    NUM_CHANNELS = 3

    def __init__(
        self,
        resource_name: str,
        resource_manager: Optional[ResourceManager] = None,
    ):
        self._resource_name = resource_name
        self._rm = resource_manager or ResourceManager()
        self._inst: Optional[MessageBasedResource] = None
        self._lock = threading.Lock()
        self._identity: str = ""
        self._serial: str = ""
        self._connected = False
        self._channels: List[ChannelInfo] = [
            ChannelInfo(number=i) for i in range(1, self.NUM_CHANNELS + 1)
        ]

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        """Open the VISA resource and query identity + channel limits."""
        with self._lock:
            if self._connected:
                return
            try:
                # type checker saying MessagedBasedResource
                resource = self._rm.open_resource(self._resource_name)
                assert isinstance(resource, MessageBasedResource)
                self._inst = resource
                assert self._inst is not None
                self._inst.timeout = 3000  # ms
                self._inst.read_termination = "\n"
                self._inst.write_termination = "\n"

                # Identity
                self._identity = self._inst.query("*IDN?").strip()
                parts = self._identity.split(",")
                self._serial = parts[2].strip() if len(parts) > 2 else ""

                # Query per-channel limits and current set-points
                for ch in self._channels:
                    ch.max_voltage = float(
                        self._inst.query(f":SOUR{ch.number}:VOLT? MAX").strip()
                    )
                    ch.max_current = float(
                        self._inst.query(f":SOUR{ch.number}:CURR? MAX").strip()
                    )
                    ch.set_voltage = float(
                        self._inst.query(f":SOUR{ch.number}:VOLT?").strip()
                    )
                    ch.set_current = float(
                        self._inst.query(f":SOUR{ch.number}:CURR?").strip()
                    )
                    out_state = self._inst.query(f":OUTP? CH{ch.number}").strip()
                    ch.output_enabled = out_state.upper() in ("ON", "1")

                self._connected = True
            except Exception:
                self._connected = False
                if self._inst is not None:
                    try:
                        self._inst.close()
                    except Exception:
                        pass
                    self._inst = None
                raise

    def disconnect(self) -> None:
        """Close the VISA resource."""
        with self._lock:
            self._connected = False
            if self._inst is not None:
                try:
                    self._inst.close()
                except Exception:
                    pass
                self._inst = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def resource_name(self) -> str:
        return self._resource_name

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def model(self) -> str:
        """Extract model name from *IDN? response."""
        parts = self._identity.split(",")
        return parts[1].strip() if len(parts) > 1 else "DP832A"

    @property
    def channels(self) -> List[ChannelInfo]:
        return list(self._channels)

    # -- per-channel commands -----------------------------------------------

    def _query(self, cmd: str) -> str:
        """Send a SCPI query (lock must be held by caller)."""
        assert self._inst is not None
        return self._inst.query(cmd).strip()

    def _write(self, cmd: str) -> None:
        """Send a SCPI write (lock must be held by caller)."""
        assert self._inst is not None
        self._inst.write(cmd)

    def set_voltage(self, ch: int, volts: float) -> None:
        """Set the target voltage for *ch* (1-3)."""
        self._validate_channel(ch)
        info = self._channels[ch - 1]
        volts = max(0.0, min(volts, info.max_voltage))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f":SOUR{ch}:VOLT {volts:.4f}")
            info.set_voltage = volts

    def set_current(self, ch: int, amps: float) -> None:
        """Set the current limit for *ch* (1-3)."""
        self._validate_channel(ch)
        info = self._channels[ch - 1]
        amps = max(0.0, min(amps, info.max_current))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f":SOUR{ch}:CURR {amps:.4f}")
            info.set_current = amps

    def set_output(self, ch: int, on: bool) -> None:
        """Enable or disable the output of *ch* (1-3)."""
        self._validate_channel(ch)
        state = "ON" if on else "OFF"
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f":OUTP CH{ch},{state}")
            self._channels[ch - 1].output_enabled = on

    def measure(self, ch: int) -> Tuple[float, float, float]:
        """Read measured voltage, current, power for *ch*.

        Returns (voltage, current, power).
        """
        self._validate_channel(ch)
        with self._lock:
            if not self._safe_guard():
                return (0.0, 0.0, 0.0)
            v = float(self._query(f":MEAS:VOLT? CH{ch}"))
            i = float(self._query(f":MEAS:CURR? CH{ch}"))
            p = float(self._query(f":MEAS:POWE? CH{ch}"))
            info = self._channels[ch - 1]
            info.meas_voltage = v
            info.meas_current = i
            info.meas_power = p
            return (v, i, p)

    def poll_all(self) -> None:
        """Refresh cached measurement + output-state for all channels.

        Designed to be called from a background thread on a timer.
        """
        with self._lock:
            if not self._safe_guard():
                return
            for ch in self._channels:
                try:
                    ch.meas_voltage = float(self._query(f":MEAS:VOLT? CH{ch.number}"))
                    ch.meas_current = float(self._query(f":MEAS:CURR? CH{ch.number}"))
                    ch.meas_power = float(self._query(f":MEAS:POWE? CH{ch.number}"))
                    ch.set_voltage = float(self._query(f":SOUR{ch.number}:VOLT?"))
                    ch.set_current = float(self._query(f":SOUR{ch.number}:CURR?"))
                    out = self._query(f":OUTP? CH{ch.number}")
                    ch.output_enabled = out.upper() in ("ON", "1")
                except (VisaIOError, ValueError, AssertionError):
                    # Communication failure — mark disconnected
                    self._connected = False
                    return

    # -- helpers ------------------------------------------------------------

    def _validate_channel(self, ch: int) -> None:
        if ch < 1 or ch > self.NUM_CHANNELS:
            raise ValueError(f"Channel must be 1-{self.NUM_CHANNELS}, got {ch}")

    def _safe_guard(self) -> bool:
        """Return True if instrument is usable (caller holds lock)."""
        if not self._connected or self._inst is None:
            return False
        return True

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<RigolDP832A {self._serial or self._resource_name} ({status})>"


# ---------------------------------------------------------------------------
# Manager — auto-detect & manage multiple supplies
# ---------------------------------------------------------------------------


class RigolManager:
    """Discover and manage all connected Rigol DP832A supplies."""

    # USB resource names for DP832A typically contain "DP8" in the IDN
    _MATCH_MANUFACTURER = "RIGOL"
    _MATCH_MODEL_PREFIX = "DP8"

    def __init__(self) -> None:
        self._rm = ResourceManager()
        self._supplies: List[RigolDP832A] = []

    @property
    def supplies(self) -> List[RigolDP832A]:
        return list(self._supplies)

    def scan(self) -> List[RigolDP832A]:
        """Scan USB for DP832A supplies.

        Already-connected supplies are kept as-is.  Disconnected supplies
        are retried.  New supplies are probed and connected.
        """
        try:
            resources = self._rm.list_resources()
        except Exception:
            resources = ()

        # Build a set of currently-seen resource names
        seen: set[str] = set()

        # Try to reconnect previously-known but disconnected supplies
        for s in self._supplies:
            if not s.is_connected:
                try:
                    s.connect()
                except Exception:
                    pass
            if s.is_connected:
                seen.add(s.resource_name)

        existing_names = {s.resource_name for s in self._supplies}
        for res in resources:
            # Only probe USB resources (DP832A connects via USB-TMC)
            if "USB" not in res.upper():
                continue

            if res in existing_names:
                # Already tracked
                seen.add(res)
                continue

            # Probe: open, query *IDN?, check if it's a DP8xx
            try:
                inst = self._rm.open_resource(res)
                assert isinstance(inst, MessageBasedResource)  # for type checking
                inst.timeout = 2000
                inst.read_termination = "\n"
                inst.write_termination = "\n"
                idn = inst.query("*IDN?").strip()
                inst.close()
            except Exception:
                continue

            parts = idn.split(",")
            if len(parts) < 2:
                continue
            manufacturer = parts[0].strip().upper()
            model = parts[1].strip().upper()

            if self._MATCH_MANUFACTURER in manufacturer and model.startswith(
                self._MATCH_MODEL_PREFIX
            ):
                supply = RigolDP832A(res, self._rm)
                try:
                    supply.connect()
                    self._supplies.append(supply)
                    seen.add(res)
                except Exception:
                    pass

        # Mark supplies whose resource disappeared as disconnected
        for s in self._supplies:
            if s.resource_name not in seen and s.is_connected:
                s.disconnect()

        return list(self._supplies)

    def close_all(self) -> None:
        """Disconnect every supply and clear the list."""
        for s in self._supplies:
            try:
                s.disconnect()
            except Exception:
                pass
        self._supplies.clear()


# Backward-compatible alias
PowerSupplyManager = RigolManager
