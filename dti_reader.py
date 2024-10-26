#!/usr/bin/env python3

import argparse
import signal
import sys
import time
import json
import asyncio
from pymodbus.client import ModbusSerialClient
from bleak import BleakClient, BleakError
from bleak.exc import BleakDeviceNotFoundError

# Global variables for verbose and json printing
VERBOSE_MODE = False
JSON_MODE = False
CHARACTERISTIC_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
INFINITE_RUN_TIME = 100 * 365.25 * 24 * 60 * 60  # 100 years in seconds
DISCONNECTED = False  # Track the connection status


def verbose_print(message):
    """Print verbose messages if verbose mode is enabled."""
    if VERBOSE_MODE:
        print(f"{message}", file=sys.stderr)

def output_displacement(displacement_value):
    """Output displacement value in either JSON or regular format."""
    formatted_value = f"{displacement_value:.3f}"  # Ensures 3 decimal places

    try:
        if JSON_MODE:
            # Output in JSON format
            output = {
                "displacement": float(formatted_value),
                "unit": "mm"
            }
            print(json.dumps(output), flush=True)
        else:
            # Regular format output
            print(f"{formatted_value} mm", flush=True)
    except BrokenPipeError:
        verbose_print("Broken pipe detected. Exiting gracefully...")
        sys.exit(0)  # Exit without error


def process_displacement_data(data_bytes, sign_bit):
    """
    Common function to process displacement data from Bluetooth and RS232.

    :param data_bytes: 3 bytes representing the displacement value
    :param sign_bit: The sign byte (1 means negative, 0 means positive)
    """
    # Combine the 3 bytes (big-endian) to create the full 24-bit value
    value = int.from_bytes(data_bytes, byteorder="big")

    # Apply sign if needed
    if sign_bit == 0x01:
        value = -value

    # Convert to millimeters (assuming the value is in microns)
    displacement_value = value / 1000.0
    output_displacement(displacement_value)


# RS232 (Modbus) Functions
def read_displacement_rs232(client, slave_id):
    """Function to read displacement from the RS232 device."""
    address = 0x0000  # Starting address
    count = 2         # Reading 2 registers (4 bytes total)

    # Send the read holding registers command
    response = client.read_holding_registers(address=address, count=count, slave=slave_id)

    if not response.isError():
        verbose_print(f"Raw register data (RS232): {response.registers}")
        # Ensure we have received 2 registers (4 bytes)
        if len(response.registers) == 2:
            # Extract the sign bit from the high byte (first byte of the high register)
            sign_bit = (response.registers[0] & 0xFF00) >> 8
            # Extract the 3 value bytes: last byte of the first register and two bytes of the second register
            value_bytes = [
                response.registers[0] & 0x00FF,  # Low byte from the first register
                (response.registers[1] & 0xFF00) >> 8,  # High byte from the second register
                response.registers[1] & 0x00FF  # Low byte from the second register
            ]
            process_displacement_data(value_bytes, sign_bit)
        else:
            verbose_print("Unexpected number of registers returned.")
    else:
        verbose_print("Failed to read displacement sensor data.")


# Bluetooth (BLE) Functions
def handle_notification(sender: int, data: bytearray):
    """Callback function to process incoming BLE notifications."""
    # Print raw data for debugging in verbose mode
    verbose_print(f"Raw data (Bluetooth): {':'.join(f'{byte:02X}' for byte in data)}")

    if len(data) >= 8:
        # Extract the sign bit from the last byte
        sign_bit = data[-1]
        # Extract the previous 3 bytes as the value
        value_bytes = data[-4:-1]
        process_displacement_data(value_bytes, sign_bit)


async def read_displacement_bt(device_address, period=None):
    """Function to read displacement from the Bluetooth device."""
    global DISCONNECTED
    max_retries = 5  # Set a limit to how many times to retry
    retry_count = 0

    while retry_count < max_retries and not DISCONNECTED:
        try:
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
                    if not DISCONNECTED:
                        await client.stop_notify(CHARACTERISTIC_UUID)
                break  # Successfully ran, break out of retry loop
        except BleakDeviceNotFoundError:
            print(f"Device with address {device_address} was not found. Exiting.")
            sys.exit(1)
        except BleakError as e:
            retry_count += 1
            verbose_print(f"Bluetooth connection lost: {e}. Retrying ({retry_count}/{max_retries})...")
            DISCONNECTED = True  # Mark the device as disconnected
            await asyncio.sleep(5)  # Wait 5 seconds before retrying

    if retry_count >= max_retries:
        print("Max retries reached. Exiting.")
        sys.exit(1)


def signal_handler(sig, frame):
    """Handle termination signals (e.g., Ctrl+C) gracefully."""
    global DISCONNECTED
    verbose_print("\nTerminating script.")
    DISCONNECTED = True  # Set disconnected to prevent further operations
    sys.exit(0)



def main():
    global VERBOSE_MODE, JSON_MODE

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Displacement Sensor Reader (RS232/BT)")
    parser.add_argument('--connection', choices=['bt', 'rs232'], required=True, help="Connection type: 'bt' for Bluetooth or 'rs232' for serial communication")
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

    # Choose Bluetooth or RS232 communication based on the --connection argument
    if args.connection == 'bt':
        # Bluetooth mode
        verbose_print(f"Starting Bluetooth mode using device {args.device}...")
        asyncio.run(read_displacement_bt(args.device, args.period))
    elif args.connection == 'rs232':
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
        print("Invalid connection type. Use --connection bt or rs232.")
        sys.exit(1)


if __name__ == "__main__":
    main()