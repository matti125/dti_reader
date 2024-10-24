#!/usr/bin/env python3

import argparse
import signal
import sys
import time
import json
from pymodbus.client import ModbusSerialClient


# Global variable to control verbose and json printing
VERBOSE_MODE = False
JSON_MODE = False


def verbose_print(message):
    """Print verbose messages if verbose mode is enabled."""
    if VERBOSE_MODE:
        print(message)


def output_displacement(displacement_value):
    """Output displacement value in either JSON or regular format."""
    if JSON_MODE:
        # Output in JSON format
        output = {
            "displacement": displacement_value,
            "unit": "mm"
        }
        print(json.dumps(output))
    else:
        # Regular format output
        print(f"Displacement: {displacement_value} mm")


def read_displacement(client, slave_id):
    """Function to read displacement from the device."""
    address = 0x0000  # Starting address
    count = 2         # Reading 2 registers (2 registers = 4 bytes)

    # Send the read holding registers command
    response = client.read_holding_registers(address=address, count=count, slave=slave_id)

    if not response.isError():
        # Print raw data in verbose mode
        verbose_print(f"Raw register data: {response.registers}")

        # Ensure you have received 2 registers (4 bytes)
        if len(response.registers) == 2:
            # Combine the two 16-bit registers into a 32-bit value
            high_register = response.registers[0]
            low_register = response.registers[1]

            # Manually combine the two 16-bit registers into a single 32-bit integer
            combined_value = (high_register << 16) | low_register

            # Extract the sign bit from the high byte (first byte of the high register)
            sign_bit = (high_register & 0xFF00) >> 8

            # If the sign bit is 1, the value is negative
            if sign_bit == 1:
                combined_value = -combined_value

            # Convert value to a readable format (example based on protocol conversion to millimeters)
            displacement_value = combined_value / 10000.0  # Assuming high precision (4 decimal places)
            
            # Output the displacement in either JSON or regular format
            output_displacement(displacement_value)
        else:
            verbose_print("Unexpected number of registers returned.")
    else:
        verbose_print("Failed to read displacement sensor data.")


def signal_handler(sig, frame):
    """Handle termination signals (e.g., Ctrl+C) gracefully."""
    print("\nTerminating script.")
    sys.exit(0)


def main():
    global VERBOSE_MODE, JSON_MODE

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Modbus RTU Client for Grating Displacement Sensor")
    parser.add_argument('--device', type=str, required=True, help="The device file for the USB to Serial cable (e.g., /dev/ttyUSB0)")
    parser.add_argument('--interval', type=float, required=True, help="Time interval between queries in seconds (e.g., 0.5 for 500 ms)")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output")
    parser.add_argument('--json', action='store_true', help="Output the displacement data in JSON format")

    args = parser.parse_args()

    # Set verbose and json modes
    VERBOSE_MODE = args.verbose
    JSON_MODE = args.json

    # Initialize the Modbus RTU client
    client = ModbusSerialClient(
        port=args.device,
        baudrate=38400,
        stopbits=2,
        bytesize=8,
        parity='N',
        timeout=1
    )

    # Connect to the sensor
    if not client.connect():
        print("Failed to connect to the sensor.")
        sys.exit(1)
    else:
        verbose_print("Connected to the sensor.")

    # Handle signals (e.g., Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)

    # Slave ID for the device
    slave_id = 0x01  # Default address

    # Infinite loop to query the device at the specified interval
    try:
        while True:
            read_displacement(client, slave_id)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        client.close()


if __name__ == "__main__":
    main()