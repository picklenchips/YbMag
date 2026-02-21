"""
ELL6 Rotary Motor Example using ELLMotor wrapper
Demonstrates the object-oriented interface for Thorlabs Elliptec motors.
"""

import os

from ell_motor import ELLMotor


def main() -> None:
    """Demonstrate ELLMotor class usage."""
    print("=" * 70)
    print("Elliptec Motor Control Example using ELLMotor")
    print("=" * 70)
    print()

    # Connect to motor - now using integrated ELLMotor.scan_and_connect()
    port_override = os.environ.get("ELL_PORT")
    port_override = "3"
    motor = ELLMotor(port=port_override)
    print(f"Connection: {motor}\n")

    # Display device information
    motor.print_device_info()
    print()

    # Query current state
    print("Querying device state...")
    motor.get_position()
    motor.get_home_offset()
    motor.get_jog_step_size()
    print(f"Position:        {motor.position:.2f}")
    print(f"Home Offset:     {motor.home_offset:.2f}")
    print(f"Jog Step Size:   {motor.jog_step_size:.2f}\n")

    # Set jog step if needed
    if motor.jog_step_size == 0:
        print("Setting jog step size to 1.0...")
        motor.jog_step_size = 1.0
        print()

    # Demonstrate motion commands
    print("Demonstrating motion commands...")
    print()

    print("1. Homing...")
    if motor.home(motor.Direction.CLOCKWISE):
        print("   ✓ Homing completed\n")
    else:
        print("   ✗ Homing failed\n")

    while 1:
        t = (
            input(
                "Enter 'j' to jog forward, 'k' to jog backward, 'm' to move absolute, 'r' to move relative, 'i' for motor info, 's' to set step size, 'q' to quit: "
            )
            .strip()
            .lower()
        )
        if t == "j":
            print("Jogging forward...")
            if motor.jog_forward():
                motor.get_position()
                print(f"   ✓ New position: {motor.position:.2f}\n")
            else:
                print("   ✗ Jog failed\n")
        elif t == "k":
            print("Jogging backward...")
            if motor.jog_backward():
                motor.get_position()
                print(f"   ✓ New position: {motor.position:.2f}\n")
            else:
                print("   ✗ Jog failed\n")
        elif t == "m":
            try:
                pos = float(input("Enter absolute position to move to: "))
                print(f"Moving to absolute position {pos}...")
                if motor.move_absolute(pos):
                    motor.get_position()
                    print(f"   ✓ Moved to position: {motor.position:.2f}\n")
                else:
                    print("   ✗ Move failed\n")
            except ValueError:
                print("Invalid input. Please enter a numeric value.\n")
        elif t == "r":
            try:
                delta = float(
                    input("Enter relative distance to move (positive or negative): ")
                )
                print(f"Moving relative by {delta}...")
                if motor.move_relative(delta):
                    motor.get_position()
                    print(f"   ✓ New position: {motor.position:.2f}\n")
                else:
                    print("   ✗ Move failed\n")
            except ValueError:
                print("Invalid input. Please enter a numeric value.\n")
        elif t == "i":
            if motor.motor_count > 1:
                for motor_id in ["1", "2"]:
                    motor.print_motor_info(int(motor_id))
            else:
                print("Single-motor device, no additional motor info available.\n")
        elif t == "s":
            try:
                step = float(input("Enter new jog step size: "))
                motor.jog_step_size = step
                print(f"Jog step size set to {motor.jog_step_size:.2f}\n")
            except ValueError:
                print("Invalid input. Please enter a numeric value.\n")
        elif t == "q":
            print("Exiting demonstration...\n")
            motor.disconnect()
            break
        else:
            print(
                "Invalid command. Please enter 'j', 'k', 'm', 'r', 'i', 's', or 'q'.\n"
            )

    # Move to absolute position (if supported)
    if motor.device_type in ["Linear Stage", "Rotary Stage", "Actuator"]:
        print("4. Moving to absolute position 5.0...")
        if motor.move_absolute(5.0):
            motor.get_position()
            print(f"   ✓ Moved to position: {motor.position:.2f}\n")
        else:
            print("   ✗ Move failed\n")

    # Relative move
    print("5. Moving relative (+2.0)...")
    if motor.move_relative(2.0):
        motor.get_position()
        print(f"   ✓ New position: {motor.position:.2f}\n")
    else:
        print("   ✗ Move failed\n")

    # Get motor info if multi-motor device
    if motor.motor_count > 1:
        print("6. Motor information...")
        for motor_id in ["1", "2"]:
            if motor.get_motor_info(motor_id):
                print(f"   ✓ Motor {motor_id} info retrieved")
        print()

    # Demonstrate reconnection
    print("7. Testing reconnection...")
    port = motor.port
    if motor.disconnect():
        print("   ✓ Disconnected successfully")
        if motor.connect(port=port):
            print("   ✓ Reconnected successfully\n")
        else:
            print("   ✗ Reconnection failed\n")

    # Clean up
    motor.disconnect()

    print("=" * 70)
    print("Demonstration completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
