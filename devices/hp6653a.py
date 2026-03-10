"""
Pure-Python driver for the HP/Agilent 6653A single-channel DC power supply
(0-35 V, 0-15 A) connected via a Prologix GPIB-USB adapter.

No Qt dependency — safe to use from scripts, notebooks, and tests.
Thread-safe: every SCPI transaction is guarded by a per-instrument lock.

Reference: HP 6653A Programming Guide (SCPI command set).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
import time
from typing import List, Optional, Tuple

from pyvisa import ResourceManager
from pyvisa.resources import MessageBasedResource
from pyvisa.errors import VisaIOError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ChannelInfo:
    """Snapshot of the single channel's state (cached by poll_all).

    Uses number=1 for consistency with DP832A ChannelInfo interface.
    """

    number: int = 1
    max_voltage: float = 35.0
    max_current: float = 15.0
    set_voltage: float = 0.0
    set_current: float = 0.0
    meas_voltage: float = 0.0
    meas_current: float = 0.0
    meas_power: float = 0.0
    output_enabled: bool = False

    def __str__(self) -> str:
        return f"CH{self.number}:{'ON' if self.output_enabled else 'OFF'}: set {self.set_voltage} V / {self.set_current} A, meas {self.meas_voltage} V / {self.meas_current} A / {self.meas_power} W"


# ---------------------------------------------------------------------------
# Single-supply driver
# ---------------------------------------------------------------------------


class HP6653A:
    """Thread-safe pyvisa wrapper for one HP 6653A supply via Prologix GPIB-USB.

    The Prologix adapter appears as an ASRL (serial) VISA resource.
    Prologix-specific ``++`` commands configure controller mode and GPIB
    address before any SCPI traffic is sent.
    """

    NUM_CHANNELS = 1

    # HP 6653A absolute limits
    _MAX_VOLTAGE = 35.0
    _MAX_CURRENT = 15.0

    # Minimum seconds between consecutive SCPI commands (Prologix GPIB-USB pacing)
    _CMD_INTERVAL_S = 0.200

    def __init__(
        self,
        resource_name: str,
        gpib_address: int = 5,
        resource_manager: Optional[ResourceManager] = None,
    ):
        self._resource_name = resource_name
        self._gpib_address = gpib_address
        self._rm = resource_manager or ResourceManager()
        self._inst: Optional[MessageBasedResource] = None
        self._lock = threading.Lock()
        self._identity: str = ""
        self._serial: str = ""
        self._connected = False
        self._channels: List[ChannelInfo] = [ChannelInfo(number=1)]
        self._last_cmd_time: float = 0.0

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        """Open the VISA resource, configure Prologix, and query identity."""
        with self._lock:
            if self._connected:
                return
            # Ensure any stale resource handle is released first
            self._close_resource()
            try:
                resource = self._rm.open_resource(self._resource_name)
                assert isinstance(resource, MessageBasedResource)
                self._inst = resource
                self._inst.timeout = 3000
                self._inst.read_termination = "\n"
                self._inst.write_termination = "\n"

                # Prologix initialization — full reset sequence
                self._write("++mode 1")  # controller mode
                self._write("++auto 1")  # auto read-after-write
                self._write(f"++addr {self._gpib_address}")
                self._write("++read_tmo_ms 1500")  # read timeout

                # Clear any stale GPIB state
                self._write("*CLS")

                # Identity
                self._identity = self._query("*IDN?")
                parts = self._identity.split(",")
                self._serial = parts[2].strip() if len(parts) > 2 else ""

                # Query programmed levels
                ch = self._channels[0]
                ch.set_voltage = float(self._query("VOLT?"))
                ch.set_current = float(self._query("CURR?"))
                out_state = self._query("OUTP?")
                ch.output_enabled = out_state.upper() in ("ON", "1")

                self._connected = True
            except Exception:
                self._connected = False
                self._close_resource()
                raise

    def disconnect(self) -> None:
        """Close the VISA resource."""
        with self._lock:
            self._connected = False
            self._close_resource()

    def _close_resource(self) -> None:
        """Release the VISA handle (caller holds lock)."""
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
        return parts[1].strip() if len(parts) > 1 else "6653A"

    @property
    def channels(self) -> List[ChannelInfo]:
        return list(self._channels)

    # -- per-channel commands -----------------------------------------------
    # HP 6653A is single-channel; ch argument kept for interface consistency.

    def _pace(self) -> None:
        """Wait until at least _CMD_INTERVAL_S has elapsed since the last command.

        Prevents overrunning the Prologix GPIB-USB adapter.  Caller must hold _lock.
        """
        now = time.monotonic()
        elapsed = now - self._last_cmd_time
        if elapsed < self._CMD_INTERVAL_S:
            time.sleep(self._CMD_INTERVAL_S - elapsed)
        self._last_cmd_time = time.monotonic()

    def _query(self, cmd: str) -> str:
        """Send a SCPI query (lock must be held by caller)."""
        assert self._inst is not None
        self._pace()
        return self._inst.query(cmd).strip()

    def _write(self, cmd: str) -> None:
        """Send a SCPI write (lock must be held by caller)."""
        assert self._inst is not None
        self._pace()
        self._inst.write(cmd)

    def set_voltage(self, ch: int, volts: float) -> None:
        """Set the target voltage (ch is ignored — single channel)."""
        self._validate_channel(ch)
        info = self._channels[0]
        volts = max(0.0, min(volts, info.max_voltage))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"VOLT {volts:.4f}")
            info.set_voltage = volts

    def set_current(self, ch: int, amps: float) -> None:
        """Set the current limit (ch is ignored — single channel)."""
        self._validate_channel(ch)
        info = self._channels[0]
        amps = max(0.0, min(amps, info.max_current))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"CURR {amps:.4f}")
            info.set_current = amps

    def set_output(self, ch: int, on: bool) -> None:
        """Enable or disable the output (ch is ignored — single channel)."""
        self._validate_channel(ch)
        state = "ON" if on else "OFF"
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"OUTP {state}")
            self._channels[0].output_enabled = on

    def measure(self, ch: int = 1) -> Tuple[float, float, float]:
        """Read measured voltage, current, power.

        Returns (voltage, current, power).
        """
        self._validate_channel(ch)
        with self._lock:
            if not self._safe_guard():
                return (0.0, 0.0, 0.0)
            v = float(self._query("MEAS:VOLT?"))
            i = float(self._query("MEAS:CURR?"))
            p = v * i  # HP 6653A has no MEAS:POWE? command
            info = self._channels[0]
            info.meas_voltage = v
            info.meas_current = i
            info.meas_power = p
            return (v, i, p)

    def poll_all(self) -> None:
        """Refresh cached measurement + output-state.

        Designed to be called from a background thread on a timer.
        """
        with self._lock:
            if not self._safe_guard():
                return
            ch = self._channels[0]
            try:
                ch.meas_voltage = float(self._query("MEAS:VOLT?"))
                ch.meas_current = float(self._query("MEAS:CURR?"))
                ch.meas_power = ch.meas_voltage * ch.meas_current
                ch.set_voltage = float(self._query("VOLT?"))
                ch.set_current = float(self._query("CURR?"))
                out = self._query("OUTP?")
                ch.output_enabled = out.upper() in ("ON", "1")
            except (VisaIOError, ValueError, AssertionError):
                self._connected = False
                self._close_resource()
                return

    # -- overvoltage / overcurrent protection --------------------------------

    def set_overvoltage_protection(self, volts: float) -> None:
        """Set the overvoltage protection level."""
        volts = max(0.0, min(volts, self._MAX_VOLTAGE))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"VOLT:PROT {volts:.4f}")

    def set_overcurrent_protection(self, on: bool) -> None:
        """Enable or disable overcurrent protection."""
        state = "ON" if on else "OFF"
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"CURR:PROT:STAT {state}")

    # -- trigger support -----------------------------------------------------

    def set_trigger_voltage(self, volts: float) -> None:
        """Set pending trigger voltage (armed with INIT)."""
        volts = max(0.0, min(volts, self._MAX_VOLTAGE))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"VOLT:TRIG {volts:.4f}")

    def set_trigger_current(self, amps: float) -> None:
        """Set pending trigger current (armed with INIT)."""
        amps = max(0.0, min(amps, self._MAX_CURRENT))
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"CURR:TRIG {amps:.4f}")

    def init_trigger(self, continuous: bool = False) -> None:
        """Arm the trigger system."""
        with self._lock:
            if not self._safe_guard():
                return
            if continuous:
                self._write("INIT:CONT ON")
            else:
                self._write("INIT")

    def send_trigger(self) -> None:
        """Send a software trigger (*TRG)."""
        with self._lock:
            if not self._safe_guard():
                return
            self._write("*TRG")

    # -- save / recall -------------------------------------------------------

    def save_state(self, location: int = 0) -> None:
        """Save operating state to device memory."""
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"*SAV {location}")

    def recall_state(self, location: int = 0) -> None:
        """Recall operating state from device memory."""
        with self._lock:
            if not self._safe_guard():
                return
            self._write(f"*RCL {location}")

    # -- helpers ------------------------------------------------------------

    def _validate_channel(self, ch: int) -> None:
        if ch != 1:
            raise ValueError(f"HP 6653A has only 1 channel, got ch={ch}")

    def _safe_guard(self) -> bool:
        """Return True if instrument is usable (caller holds lock)."""
        if not self._connected or self._inst is None:
            return False
        return True

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<HP6653A {self._serial or self._resource_name} ({status})>"


# ---------------------------------------------------------------------------
# Prologix discovery
# ---------------------------------------------------------------------------


class HP6653AManager:
    """Discover and manage HP 6653A supplies via Prologix GPIB-USB adapters.

    If an explicit resource name is provided (e.g. from settings.json),
    it is tried first.  Otherwise all ASRL ports are scanned for Prologix
    adapters and each is probed for an HP 6653A at the given GPIB address.
    """

    _MATCH_MANUFACTURER = "HEWLETT-PACKARD"
    _MATCH_MODEL_FRAGMENT = "6653"

    def __init__(
        self,
        explicit_port: Optional[str] = None,
        gpib_address: int = 5,
    ) -> None:
        self._rm = ResourceManager()
        self._explicit_port = explicit_port
        self._gpib_address = gpib_address
        self._supplies: List[HP6653A] = []

    @property
    def supplies(self) -> List[HP6653A]:
        return list(self._supplies)

    def scan(self) -> List[HP6653A]:
        """Scan for HP 6653A supplies via Prologix adapters.

        Already-connected supplies are kept as-is.  Disconnected supplies
        are retried.  New supplies are probed and connected.
        """
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

        # Build candidate port list
        if self._explicit_port:
            candidates = [self._explicit_port]
        else:
            # Fall back to scanning all ASRL ports for Prologix adapters
            prologix = find_prologix_ports(self._rm)
            candidates = [res for res, _ver in prologix]

        for res in candidates:
            if res in existing_names:
                seen.add(res)
                continue

            # Probe: open via Prologix, query *IDN?, check if HP 6653A
            try:
                with self._rm.open_resource(res) as inst:
                    assert isinstance(inst, MessageBasedResource)
                    inst.timeout = 2000
                    inst.read_termination = "\n"
                    inst.write_termination = "\n"
                    inst.write("++mode 1")
                    inst.write("++auto 1")
                    inst.write(f"++addr {self._gpib_address}")
                    idn = inst.query("*IDN?").strip()
            except Exception:
                continue

            parts = idn.split(",")
            if len(parts) < 2:
                continue
            manufacturer = parts[0].strip().upper()
            model = parts[1].strip().upper()

            if (
                self._MATCH_MANUFACTURER in manufacturer
                and self._MATCH_MODEL_FRAGMENT in model
            ):
                supply = HP6653A(res, self._gpib_address, self._rm)
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


# ---------------------------------------------------------------------------
# Prologix discovery
# ---------------------------------------------------------------------------


def find_prologix_ports(
    resource_manager: Optional[ResourceManager] = None,
) -> List[Tuple[str, str]]:
    """Scan ASRL ports for Prologix GPIB-USB adapters.

    Returns a list of (resource_name, version_string) tuples.
    """
    rm = resource_manager or ResourceManager()
    results: List[Tuple[str, str]] = []

    try:
        resources = rm.list_resources()
    except Exception:
        return results

    for res in resources:
        if not res.upper().startswith("ASRL"):
            continue
        try:
            with rm.open_resource(res) as inst:
                assert isinstance(inst, MessageBasedResource)
                inst.timeout = 500
                inst.read_termination = "\n"
                inst.write_termination = "\n"
                inst.write("++ver")
                version = inst.read().strip()
                if "Prologix" in version:
                    results.append((res, version))
        except Exception:
            pass

    return results


if __name__ == "__main__":
    # Quick test: scan for supplies and print their status
    manager = HP6653AManager()
    supplies = manager.scan()
    for s in supplies:
        print(s)
        for ch in s.channels:
            # turn on
            s.set_output(ch.number, True)
            time.sleep(0.5)
            s.measure(ch.number)
            print(ch)
            time.sleep(0.5)
            s.measure(ch.number)
            print(ch)
            time.sleep(0.5)
            # turn off
            s.set_output(ch.number, False)
            time.sleep(0.5)
            s.measure(ch.number)
            print(ch)
