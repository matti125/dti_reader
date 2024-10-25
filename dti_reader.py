#!/usr/bin/env python3

import argparse
import signal
import sys
import time
import json
from pymodbus.client import ModbusSerialClient
import asyncio
from bleak import BleakClient

# Global variables for verbose and json printing
VERBOSE_MODE = False
JSON_MODE = False
CHARACTERISTIC_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"

# 100 years in seconds
INFINITE_RUN_TIME = 100 * 365.25 * 24 * 60 * 60  # = 3,155,760,000 seconds


def verbose_print(message):
    """Print verbose messages if verbose mode is enabled."""
    if VERBOSE_MODE:
        print(message)


def output_displacement(displacement_value):
    """Output displacement value in either JSON or regular format."""
    formatted_value = f"{displacement_value:.3f}"  # Ensures 3 decimal places

    if JSON_MODE:
        # Output in JSON format
        output = {
            "displacement": float(formatted_value),
            "unit": "mm"
        }
        print(json.dumps(output))
    else:
        # Regular format output
        print(f"{formatted_value} mm")


# RS232 (Modbus) Functions
def read_displacement_rs232(client, slave_id):
    """Function to read displacement from the RS232 device."""
    address = 0x0000  # Starting address
    count = 2         # Reading 2 registers (2 registers = 4 bytes)

    # Send the read holding registers command
    response = client.read_holding_registers(address=address, count=count, slave=slave_id)

    if not response.isError():
        verbose_print(f"Raw register data: {response.registers}")

        # Ensure we have received 2 registers (4 bytes)
        if len(response.registers) == 2:
            # Extract the sign bit from the high byte (first byte of the high register)
            sign_bit = (response.registers[0] & 0xFF00) >> 8
            # Combine the two 16-bit registers into a 32-bit value
            value = response.registers[1]

            # If the sign bit is 1, the value is negative
            if sign_bit == 1:
                value = -value

            displacement_value = value / 1000.0  # Convert microns to mm
            output_displacement(displacement_value)
        else:
            verbose_print("Unexpected number of registers returned.")
    else:
        verbose_print("Failed to read displacement sensor data.")


# Bluetooth (BLE) Functions
def handle_notification(sender: int, data: bytearray):
    """Callback function to process incoming BLE notifications."""
    if len(data) >= 4:
        value_bytes = data[-4:-1]  # Get the 3 value bytes (big-endian)
        sign_byte = data[-1]       # The last byte (sign byte)

        # Convert the 3 value bytes (big-endian) to a decimal number
        decimal_value = int.from_bytes(value_bytes, byteorder="big")

        # Apply the sign based on the last byte
        if sign_byte == 0x01:
            decimal_value = -decimal_value

        # Convert to mm and print
        displacement_value = decimal_value / 1000.0
        output_displacement(displacement_value)


async def read_displacement_bt(device_address, period=None):
    """Function to read displacement from the Bluetooth device."""
    async with BleakClient(device_address) as client:
        verbose_print(f"Connected: {client.is_connected}")
        await client.start_notify(CHARACTERISTIC_UUID, handle_notification)
        verbose_print("Subscribed to notifications. Waiting for updates...")

        # Keep connection open indefinitely or for the specified period
        try:
            if period:
                await asyncio.sleep(period)  # Sleep for the defined period
            else:
                await asyncio.sleep(INFINITE_RUN_TIME)  # Simulate infinite run (100 years)
        except asyncio.CancelledError:
            verbose_print("Notification listening was cancelled.")
        finally:
            await client.stop_notify(CHARACTERISTIC_UUID)


def signal_handler(sig, frame):
    """Handle termination signals (e.g., Ctrl+C) gracefully."""
    print("\nTerminating script.")
    sys.exit(0)


def main():
    global VERBOSE_MODE, JSON_MODE

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Displacement Sensor Reader (RS232/BT)")
    parser.add_argument('--bt', action='store_true', help="Use Bluetooth connection")
    parser.add_argument('--rs232', action='store_true', help="Use RS232/Modbus connection")
    parser.add_argument('--device', type=str, required=True, help="The device file for RS232 or the MAC address for Bluetooth")
    parser.add_argument('--interval', type=float, help="Time interval between RS232 queries in seconds (e.g., 0.5 for 500 ms)")
    parser.add_argument('--period', type=float, help="Run the script for a specified time period in seconds (e.g., 60 for 1 minute)")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output")
    parser.add_argument('--json', action='store_true', help="Output the displacement data in JSON format")

    args = parser.parse_args()

    # Set verbose and json modes
    VERBOSE_MODE = args.verbose
    JSON_MODE = args.json

    # Handle signals (e.g., Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)

    # Choose Bluetooth or RS232 communication
    if args.bt:
        # Bluetooth mode
        verbose_print(f"Starting Bluetooth mode using device {args.device}...")
        asyncio.run(read_displacement_bt(args.device, args.period))
    elif args.rs232:
        if not args.interval:
            print("For RS232, --interval is required.")
            sys.exit(1)

        # RS232 mode
        verbose_print(f"Starting RS232 mode on device {args.device} with interval {args.interval} seconds.")
        client = ModbusSerialClient(
            port=args.device,
            baudrate=38400,
            stopbits=2,
            bytesize=8,
            parity='N',
            timeout=1
        )

        # Connect to the RS232 sensor
        if not client.connect():
            print("Failed to connect to the RS232 sensor.")
            sys.exit(1)
        else:
            verbose_print("Connected to the RS232 sensor.")

        slave_id = 0x01  # Default Modbus address for the sensor

        # Infinite loop to query RS232 at specified interval
        start_time = time.time()
        try:
            while True:
                read_displacement_rs232(client, slave_id)
                time.sleep(args.interval)

                # If period is defined, stop after the period
                if args.period and time.time() - start_time >= args.period:
                    break
        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            client.close()
    else:
        print("Please specify either --bt or --rs232.")
        sys.exit(1)


if __name__ == "__main__":
    main()