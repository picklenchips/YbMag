"""
ELLMotor: Object-oriented wrapper for Thorlabs Elliptec ELLO motors.
Provides a clean, Pythonic interface to the Thorlabs.Elliptec.ELLO_DLL.
"""

import os
import time
from typing import Optional, List
from dataclasses import dataclass

# need pythonnet to interface with the .NET DLL provided by Thorlabs for their Elliptec motors
import clr

ELLO_DLL_PATH = r"C:\Program Files\Thorlabs\Elliptec\Thorlabs.Elliptec.ELLO_DLL.dll"
if not __import__("os").path.exists(ELLO_DLL_PATH):
    raise FileNotFoundError(f"ELLO DLL not found at: {ELLO_DLL_PATH}")

clr.AddReference(ELLO_DLL_PATH)

from System import Decimal as NetDecimal  # type: ignore
from System.IO.Ports import SerialPort  # For COM port detection  # type: ignore
from Thorlabs.Elliptec.ELLO_DLL import ELLDevices, ELLDevicePort, ELLBaseDevice, ELLDevice  # type: ignore


def is_valid_hex_char(c):
    try:
        int(c, 16)
        return True
    except ValueError:
        return False


def _extract_from_description(
    description_list: List[str], field_name: str, default: str = "Unknown"
) -> str:
    """Extract a field value from device description list.

    Args:
        description_list: List of description strings from DeviceInfo.Description()
        field_name: Field name to search for (e.g., "Serial Number", "Firmware")
        default: Default value if field not found

    Returns:
        Field value as string
    """
    for line in description_list:
        if field_name in line and ":" in line:
            return line.split(":", 1)[1].strip()
    return default


def _determine_unit_type(device_type: str, description_list: List[str]) -> str:
    """Determine the unit type from device type and description.

    Args:
        device_type: Device type string (e.g., "OpticsRotator", "LinearStage")
        description_list: Device description list from DeviceInfo.Description()

    Returns:
        Unit type: "degrees", "mm", or "inches"
    """
    # Check if device is a rotator type
    rotator_types = ["Rotator", "OpticsRotator", "RotaryStage", "Paddle"]
    if any(rt in device_type for rt in rotator_types):
        return "degrees"

    # For linear stages, check the description for unit indication
    for line in description_list:
        if "Travel:" in line:
            if " in" in line:
                return "inches"
            elif " mm" in line or " deg" in line:
                return "mm" if " mm" in line else "degrees"

    return "mm"  # Default to mm


def _get_motor_info_details(motor_info_obj) -> tuple[Optional[float], Optional[str]]:
    """Extract frequency and description from motor info object.

    Motor info object has private fields, so try multiple approaches.

    Args:
        motor_info_obj: Motor info object from device[motor_id]

    Returns:
        Tuple of (frequency, description) or (None, str_representation)
    """
    frequency = None
    description = None

    # Try to get frequency
    try:
        if hasattr(motor_info_obj, "Frequency"):
            frequency = float(str(motor_info_obj.Frequency))
    except Exception:
        pass

    # Try to get description - first try Description property
    try:
        if hasattr(motor_info_obj, "Description"):
            description = str(motor_info_obj.Description)
    except Exception:
        pass

    # If no description yet, try ToString()
    if not description:
        try:
            str_repr = str(motor_info_obj.ToString())
            if str_repr and str_repr != "":
                description = str_repr
        except Exception:
            pass

    # If still no description, use string conversion
    if not description:
        try:
            description = str(motor_info_obj)
        except Exception:
            description = None

    return frequency, description


@dataclass
class MotorInfo:
    """Motor information structure."""

    motor_id: str
    is_valid: bool = False
    loop_state: Optional[str] = None
    motor_state: Optional[str] = None
    current_amps: Optional[float] = None
    ramp_up: Optional[int] = None
    ramp_down: Optional[int] = None
    fwd_freq_khz: Optional[float] = None
    rev_freq_khz: Optional[float] = None
    description_lines: Optional[List[str]] = None


class ELLMotor:
    """
    Pythonic wrapper for Thorlabs Elliptec rotary/linear motors.
    Encapsulates all device information, motion control, and configuration.
    """

    # Device direction constants
    class Direction:
        """Direction constants for homing."""

        LINEAR = ELLBaseDevice.DeviceDirection.Linear
        CLOCKWISE = ELLBaseDevice.DeviceDirection.Clockwise
        ANTICLOCKWISE = ELLBaseDevice.DeviceDirection.AntiClockwise

    def __init__(self, port: Optional[int] = None, verbose: bool = True):
        """
        Initialize ELLMotor wrapper.

        Args:
            addressed_device: ELLDevice instance from ELLDevices.AddressedDevice()
            ell_devices: ELLDevices instance
            port: COM port used for connection (e.g., 'COM3')
            verbose: Print connection status messages
        """
        self.verbose = verbose
        device, devices, port = self.connect(explicit_port=int(port) if port else None)
        self._device = device
        self._devices = devices
        self._port: Optional[int] = port
        self._motor_info: dict[int, MotorInfo] = {}
        self._cached_position = 0.0
        self._cached_home_offset = 0.0
        self._cached_jog_step = 0.0

    # ==================== Connection Management ====================

    @staticmethod
    def get_available_ports() -> list:
        """Get list of available COM ports."""
        return list(SerialPort.GetPortNames())

    def connect(
        self, explicit_port: Optional[int] = None, address_range=("0", "F")
    ) -> tuple[ELLDevice, ELLDevices, Optional[int]]:
        """
        Scan available COM ports and connect to first Elliptec motor found.

        Args:
            explicit_port: Optional specific port to use (e.g., 3 for 'COM3')
            address_range: Tuple of (min_address, max_address) to scan for devices within each COM port
        Returns:
            Tuple of (ELLMotor instance, ELLDevices instance, port used)

        Raises:
            RuntimeError: If no motors found or no COM ports available
        """
        if explicit_port:
            ports_to_try = [f"COM{explicit_port}"]
            if self.verbose:
                print(f"Using explicit port: {ports_to_try[0]}")
        else:
            ports_to_try = self.get_available_ports()
            if self.verbose:
                print(f"Detected COM ports: {ports_to_try}")

        if not ports_to_try:
            raise RuntimeError("No COM ports available.")

        if self.verbose:
            print("Scanning for Elliptec motors...\n")

        for port in ports_to_try:
            try:
                if self.verbose:
                    print(f"Scanning {port} for devices...")
                ELLDevicePort.Connect(port)
                ell_devices = ELLDevices()
                devices = ell_devices.ScanAddresses(address_range[0], address_range[1])
                if self.verbose:
                    print(
                        f"  Found {len(devices)} device(s): {', '.join(devices) if devices else 'none'}\n"
                    )

                if devices:
                    # Found devices on this port, configure first one
                    for device_addr in devices:
                        if ell_devices.Configure(device_addr):
                            addressed_device = ell_devices.AddressedDevice(
                                device_addr[0]
                            )
                            if self.verbose:
                                print(
                                    f"Successfully connected to address {device_addr[0]} at {port}"
                                )
                            return (
                                addressed_device,
                                ell_devices,
                                int(port.replace("COM", "")),
                            )
            except Exception as exc:
                if self.verbose:
                    print(f"  Error scanning {port}: {exc}\n")
            # no finally! we dont want to disconnect if we are successful, only if we fail to find devices on this port
            ELLDevicePort.Disconnect()
        raise RuntimeError(
            f"No Elliptec motors found on available COM ports: {ports_to_try}"
        )

    def disconnect(self) -> bool:
        """
        Disconnect from the motor.

        Returns:
            True if successful
        """
        try:
            ELLDevicePort.Disconnect()
            self._port = None
            return True
        except Exception:
            return False

    @property
    def is_connected(self) -> bool:
        """Check if motor is currently connected."""
        return self._port is not None

    @property
    def port(self) -> str | None:
        """Get the COM port this motor is connected on."""
        return f"COM{self._port}" if self._port is not None else None

    # ==================== Device Information Properties ====================

    @property
    def address(self) -> str:
        """Get device bus address ('0'-'F')."""
        return str(self._device.Address)

    @address.setter
    def address(self, new_address: str) -> bool:
        """Change device address."""
        if not is_valid_hex_char(new_address):
            raise ValueError("Address must be single hex digit 0-F")
        return self._device.SetAddress(new_address)

    @property
    def serial_number(self) -> str:
        """Get device serial number."""
        desc = self.device_info_description
        return _extract_from_description(desc, "Serial Number", "Unknown")

    @property
    def device_type(self) -> str:
        """Get device type (Rotator, Actuator, Shutter, etc.)."""
        return (
            str(self._device.DeviceInfo.DeviceType)
            if hasattr(self._device.DeviceInfo, "DeviceType")
            else "Unknown"
        )

    @property
    def motor_count(self) -> int:
        """Get number of motors."""
        return (
            self._device.DeviceInfo.MotorCount
            if hasattr(self._device.DeviceInfo, "MotorCount")
            else 1
        )

    @property
    def firmware_version(self) -> str:
        """Get firmware version."""
        desc = self.device_info_description
        fw_str = _extract_from_description(desc, "Firmware", "0.0")
        try:
            return fw_str
        except Exception:
            return "0.0"

    @property
    def hardware_version(self) -> str:
        """Get hardware version."""
        desc = self.device_info_description
        hw_str = _extract_from_description(desc, "Hardware", "0")
        return hw_str

    @property
    def year(self) -> str:
        """Get year of manufacture."""
        desc = self.device_info_description
        return _extract_from_description(desc, "Year", "Unknown")

    @property
    def variant(self) -> str:
        """Get device variant (Metric/Imperial)."""
        return "Imperial" if self._device.DeviceInfo.Imperial else "Metric"

    @property
    def travel(self) -> float:
        """Get travel distance in appropriate units (mm, inches, or degrees)."""
        if not hasattr(self._device.DeviceInfo, "Travel"):
            return 0.0

        travel_raw = float(str(self._device.DeviceInfo.Travel))
        unit_type = _determine_unit_type(self.device_type, self.device_info_description)

        # Convert based on unit type
        if unit_type == "inches":
            # Convert from mm to inches
            return travel_raw / 25.4
        else:
            # Return as-is for mm and degrees
            return travel_raw

    @property
    def pulses_per(self) -> float:
        """Get pulses per unit (pulses/mm, pulses/inch, or pulses/degree)."""
        if not hasattr(self._device.DeviceInfo, "PulsePerPosition"):
            return 0.0

        pulses_raw = float(str(self._device.DeviceInfo.PulsePerPosition))
        unit_type = _determine_unit_type(self.device_type, self.device_info_description)

        # Convert based on unit type
        if unit_type == "inches":
            # Convert pulses/mm to pulses/inch (multiply by mm/inch)
            return pulses_raw * 25.4
        elif unit_type == "degrees":
            # Convert pulses/position to pulses/degree (divide by 360)
            return pulses_raw / 360.0
        else:
            # Return as-is for mm
            return pulses_raw

    @property
    def device_info_description(self) -> List[str]:
        """Get formatted device information."""
        return list(self._device.DeviceInfo.Description())

    def print_device_info(self) -> None:
        """Print all device information."""
        unit_type = _determine_unit_type(self.device_type, self.device_info_description)

        # Determine unit label for travel and pulses
        if unit_type == "inches":
            travel_unit = "in"
            pulses_unit = "pulses/in"
        elif unit_type == "degrees":
            travel_unit = "deg"
            pulses_unit = "pulses/deg"
        else:
            travel_unit = "mm"
            pulses_unit = "pulses/mm"

        print("=" * 60)
        print(f"Device Address:        {self.address}")
        print(f"Serial Number:         {self.serial_number}")
        print(f"Device Type:           {self.device_type}")
        print(f"Motor Count:           {self.motor_count}")
        print(f"Firmware Version:      {self.firmware_version}")
        print(f"Hardware Version:      {self.hardware_version}")
        print(f"Year of Manufacture:   {self.year}")
        print(f"Variant:               {self.variant}")
        print(f"Travel:                {self.travel:.2f} {travel_unit}")
        print(f"Pulses Per Unit:       {self.pulses_per:.2f} {pulses_unit}")
        print("=" * 60)

    # ==================== Motion Commands ====================

    def home(self, direction=None) -> bool:
        """
        Home the device.

        Args:
            direction: Direction.CLOCKWISE (default) or Direction.ANTICLOCKWISE

        Returns:
            True if successful, False otherwise
        """
        if direction is None:
            direction = self.Direction.CLOCKWISE
        return self._device.Home(direction)

    def jog_forward(self) -> bool:
        """Jog one step forward."""
        return self._device.JogForward()

    def jog_backward(self) -> bool:
        """Jog one step backward."""
        return self._device.JogBackward()

    def jog_forward_start(self) -> bool:
        """Start continuous forward jog."""
        return self._device.JogForwardStart()

    def jog_backward_start(self) -> bool:
        """Start continuous backward jog."""
        return self._device.JogBackwardStart()

    def jog_stop(self) -> bool:
        """Stop jogging."""
        return self._device.JogStop()

    def move_absolute(self, position: float) -> bool:
        """
        Move to absolute position.

        Args:
            position: Target position (mm or degrees depending on device)

        Returns:
            True if successful, False otherwise
        """
        return self._device.MoveAbsolute(NetDecimal.Parse(str(position)))

    def move_relative(self, step: float) -> bool:
        """
        Move by relative distance.

        Args:
            step: Relative step distance (mm or degrees)

        Returns:
            True if successful, False otherwise
        """
        return self._device.MoveRelative(NetDecimal.Parse(str(step)))

    def move_to_position(self, position: int) -> bool:
        """
        Move to shutter position (for shutter devices only).

        Args:
            position: Shutter position (0-n)

        Returns:
            True if successful, False otherwise
        """
        if self.device_type not in ["Shutter", "Shutter4", "Shutter6"]:
            raise ValueError(f"move_to_position() not supported for {self.device_type}")
        return self._device.MoveToPosition(str(position))

    def fstop_move(self, f_stop: float, focal_length: float) -> bool:
        """
        Move based on F-stop and focal length (for optics devices).

        Args:
            f_stop: F-stop value
            focal_length: Focal length (mm)

        Returns:
            True if successful, False otherwise
        """
        if "Iris" not in self.device_type and "Rotator" not in self.device_type:
            raise ValueError(f"fstop_move() not supported for {self.device_type}")
        return self._device.FStopMove(
            NetDecimal.Parse(str(f_stop)), NetDecimal.Parse(str(focal_length))
        )

    # ==================== Position/Offset/Jog Size ====================

    @property
    def position(self) -> float:
        """Get current position (mm or degrees)."""
        self.get_position()
        return self._cached_position

    def get_position(self) -> bool:
        """
        Query current position from device.

        Returns:
            True if successful, False otherwise
        """
        result = self._device.GetPosition()
        if result:
            self._cached_position = float(str(self._device.Position))
        return result

    @property
    def home_offset(self) -> float:
        """Get home offset."""
        self.get_home_offset()
        return self._cached_home_offset

    @home_offset.setter
    def home_offset(self, offset: float) -> bool:
        """Set home offset."""
        result = self._device.SetHomeOffset(NetDecimal.Parse(str(offset)))
        if result:
            self._cached_home_offset = offset
        return result

    def get_home_offset(self) -> bool:
        """
        Query home offset from device.

        Returns:
            True if successful, False otherwise
        """
        result = self._device.GetHomeOffset()
        if result:
            self._cached_home_offset = float(str(self._device.HomeOffset))
        return result

    @property
    def jog_step_size(self) -> float:
        """Get jog step size."""
        self.get_jog_step_size()
        return self._cached_jog_step

    @jog_step_size.setter
    def jog_step_size(self, size: float) -> bool:
        """Set jog step size."""
        result = self._device.SetJogstepSize(NetDecimal.Parse(str(size)))
        if result:
            self._cached_jog_step = size
        return result

    def get_jog_step_size(self) -> bool:
        """
        Query jog step size from device.

        Returns:
            True if successful, False otherwise
        """
        result = self._device.GetJogstepSize()
        if result:
            self._cached_jog_step = float(str(self._device.JogstepSize))
        return result

    # ==================== Configuration Commands ====================

    def save_configuration(self) -> bool:
        """Save user configuration to device."""
        return self._device.SaveUserData()

    def set_address(self, new_address: str) -> bool:
        """
        Change device address.

        Args:
            new_address: New hex address ('0'-'F')

        Returns:
            True if successful, False otherwise
        """
        if len(new_address) != 1 or new_address not in "0123456789ABCDEF":
            raise ValueError("Address must be single hex digit 0-F")
        return self._device.SetAddress(new_address)

    def set_group_address(self, addresses: List[str]) -> bool:
        """
        Set group address for multiple devices.

        Args:
            addresses: List of device addresses to group

        Returns:
            True if successful, False otherwise
        """
        char_addresses = [c for c in addresses]
        return self._device.SetToGroupAddress(char_addresses)

    # ==================== Motor Setup Commands ====================

    def get_motor_info(self, motor_id: int) -> bool:
        """
        Get motor information.

        Args:
            motor_id: Motor identifier (1 or 2)

        Returns:
            True if successful, False otherwise
        """
        if motor_id not in ["1", "2"]:
            raise ValueError("motor_id must be '1' or '2'")
        result = self._device.GetMotorInfo(motor_id)
        if result:
            motor_info_obj = self._device[motor_id]

            # Get description lines
            description_lines = []
            try:
                for line in motor_info_obj.Description():
                    description_lines.append(str(line))
            except Exception:
                pass

            # Extract values from motor_info_obj properties
            try:
                is_valid = motor_info_obj.IsValid
            except Exception:
                is_valid = False

            try:
                loop_state = str(motor_info_obj.LoopState)
            except Exception:
                loop_state = None

            try:
                motor_state = str(motor_info_obj.MotorState)
            except Exception:
                motor_state = None

            try:
                current_amps = float(str(motor_info_obj.Current))
            except Exception:
                current_amps = None

            try:
                ramp_up = int(motor_info_obj.RampUp)
            except Exception:
                ramp_up = None

            try:
                ramp_down = int(motor_info_obj.RampDown)
            except Exception:
                ramp_down = None

            try:
                fwd_freq_khz = float(str(motor_info_obj.FwdFreq))
            except Exception:
                fwd_freq_khz = None

            try:
                rev_freq_khz = float(str(motor_info_obj.RevFreq))
            except Exception:
                rev_freq_khz = None

            self._motor_info[int(motor_id)] = MotorInfo(
                motor_id=motor_id,
                is_valid=is_valid,
                loop_state=loop_state,
                motor_state=motor_state,
                current_amps=current_amps,
                ramp_up=ramp_up,
                ramp_down=ramp_down,
                fwd_freq_khz=fwd_freq_khz,
                rev_freq_khz=rev_freq_khz,
                description_lines=description_lines if description_lines else None,
            )
        return result

    def print_motor_info(self, motor_id: int) -> None:
        """
        Print motor information in a formatted way.

        Args:
            motor_id: Motor identifier ('1' or '2')
        """
        if motor_id not in self._motor_info:
            if not self.get_motor_info(motor_id):
                print(f"Failed to retrieve motor {motor_id} info")
                return

        info = self._motor_info[int(motor_id)]

        if not info.is_valid:
            print(f"Motor {motor_id} info is not valid")
            return

        print(f"--- Motor {motor_id} Information ---")
        if info.description_lines:
            for line in info.description_lines:
                print(f"  {line}")
        else:
            # Fallback: print individual properties
            print(f"  Motor ID: {info.motor_id}")
            print(f"  Loop State: {info.loop_state}")
            print(f"  Motor State: {info.motor_state}")
            print(
                f"  Current: {info.current_amps:.2f} A"
                if info.current_amps
                else "  Current: N/A"
            )
            print(
                f"  Fwd Frequency: {info.fwd_freq_khz:.1f} kHz"
                if info.fwd_freq_khz
                else "  Fwd Frequency: N/A"
            )
            print(
                f"  Rev Frequency: {info.rev_freq_khz:.1f} kHz"
                if info.rev_freq_khz
                else "  Rev Frequency: N/A"
            )
            print(f"  Ramp Up: {info.ramp_up}" if info.ramp_up else "  Ramp Up: N/A")
            print(
                f"  Ramp Down: {info.ramp_down}"
                if info.ramp_down
                else "  Ramp Down: N/A"
            )
        print()

    def set_period(
        self,
        motor_id: str,
        forward: bool,
        frequency: float,
        permanent: bool = False,
        hard_save: bool = False,
    ) -> bool:
        """
        Set motor drive frequency.

        Args:
            motor_id: Motor identifier ('1' or '2')
            forward: True for forward, False for backward
            frequency: Drive frequency (kHz)
            permanent: Save to device
            hard_save: Hard save flag

        Returns:
            True if successful, False otherwise
        """
        if motor_id not in (1, 2):
            raise ValueError("motor_id must be '1' or '2'")
        return self._device.SetPeriod(
            motor_id, forward, NetDecimal.Parse(str(frequency)), permanent, hard_save
        )

    def search_period(self, motor_id: str, permanent: bool = False) -> bool:
        """
        Auto-search optimal motor frequency.

        Args:
            motor_id: Motor identifier ('1' or '2')
            permanent: Save to device

        Returns:
            True if successful, False otherwise
        """
        if motor_id not in (1, 2):
            raise ValueError("motor_id must be '1' or '2'")
        return self._device.SearchPeriod(motor_id, permanent)

    def reset_period(self) -> bool:
        """Reset all motor frequencies to default."""
        return self._device.ResetPeriod()

    def skip_frequency_search(self) -> bool:
        """Skip frequency search on startup."""
        return self._device.SkipFrequencySearch()

    # ==================== Maintenance Commands ====================

    def clean(self) -> bool:
        """Run cleaning cycle. WARNING: This is a BLOCKING call that waits until cleaning completes."""
        return self._device.SendCleanMachine()

    def clean_and_optimize(self) -> bool:
        """Run cleaning and optimization cycle. Takes ~20-30s to load and start, then runs for 10-15 min. :WARNING: This is a BLOCKING call that waits until complete."""
        return self._device.SendCleanAndOptimize()

    def optimize(self) -> bool:
        """Run optimization cycle. :WARNING: This is a BLOCKING call that waits until complete."""
        return self._device.SendOptimize()

    def stop_cleaning(self) -> bool:
        """Stop ongoing cleaning/optimization."""
        return self._device.SendStopCleaning()

    # ==================== Utility Methods ====================

    def is_busy(self) -> bool:
        """Check if device is busy (cleaning or thermal lockout)."""
        return self._device.IsDeviceBusy()

    def wait_for_ready(self, timeout: float = 30.0, dt: float = 0.1) -> bool:
        """
        Wait for device to be ready.

        Args:
            timeout: Maximum wait time in seconds
            dt: Time interval between checks in seconds

        Returns:
            True if device becomes ready, False if timeout
        """
        dt = max(dt, 0.1)  # Ensure minimum dt of 0.1s to avoid excessive CPU usage
        start = time.time()
        while time.time() - start < timeout:
            if not self.is_busy():
                return True
            time.sleep(dt)
        return False

    def __del__(self) -> None:
        """Destructor - automatically disconnect when instance is deleted."""
        try:
            if hasattr(self, "_port") and self._port is not None:
                self.disconnect()
        except Exception:
            # Silently ignore any errors during cleanup
            pass

    def __repr__(self) -> str:
        """String representation of device."""
        return f"ELLMotor(address={self.address}, type={self.device_type}, serial={self.serial_number})"


if __name__ == "__main__":
    # Example usage
    print("=" * 70)
    print("ELLMotor - Thorlabs Elliptec Motor Control")
    print("=" * 70)
    print()

    # Auto-detect and connect to motor
    port = os.environ.get("ELL_PORT")
    port = 3
    motor = ELLMotor(port)
    print(f"Connected to device on port {motor.port}: {motor}\n")

    # Display device information
    motor.print_device_info()
    print()
    print(", ".join(motor.device_info_description))
    print()
    for m in [1, 2]:
        motor.print_motor_info(m)
        print()
    # clean and optimize
    print("Starting cleaning and optimization cycle... takes ~20-30s to load and run")
    print(
        "This will BLOCK until the cycle completes (can take up to 15 min) so use threading or multiprocessing if you want to run this without blocking your main program"
    )
    print()
    import threading

    thread = threading.Thread(target=motor.clean_and_optimize)
    thread.start()
    cancel_input = input("Press Enter to cancel cleaning...\n")
    if cancel_input == "":
        print(
            "Cancelled cleaning. Device will continue cleaning in background. You can check status later."
        )
        motor.stop_cleaning()
    # look at potentially different values after cleaning/optimization
    thread.join()  # Wait for cleaning to finish before querying info again
    for m in [1, 2]:
        motor.print_motor_info(m)
        print()
    # Clean up
    motor.disconnect()
    print("Disconnected successfully.")
