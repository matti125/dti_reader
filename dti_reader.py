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


def verbose_print(message):
    """Print verbose messages if verbose mode is enabled."""
    if VERBOSE_MODE:
        print(f"{message}", file=sys.stderr)


def error_message(message):
    """Print error messages to stderr."""
    print(f"Error: {message}", file=sys.stderr)


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
    """Common function to process displacement data from Bluetooth and RS232."""
    # Combine the 3 bytes (big-endian) to create the full 24-bit value
    value = int.from_bytes(data_bytes, byteorder="big")

    # Apply sign if needed
    if sign_bit == 0x01:
        value = -value

    # Convert to millimeters (assuming the value is in microns)
    displacement_value = value / 1000.0
    output_displacement(displacement_value)


class BluetoothDisplacementReader:
    def __init__(self, device_address, period=None, deadman=None):
        self.device_address = device_address
        self.period = period
        self.deadman_timeout = deadman
        self.disconnected = False
        self.deadman = asyncio.Event()  # Event to manage the deadman timer
        self.timer_task = None  # Task for the resettable timer

    async def handle_notification(self, sender: int, data: bytearray):
        """Callback function to process incoming BLE notifications."""
        self.reset_timer()  # Reset the timer whenever a notification is received
        verbose_print(f"Raw data (Bluetooth): {':'.join(f'{byte:02X}' for byte in data)}")
        if len(data) >= 8:
            sign_bit = data[-1]  # Extract the sign bit from the last byte
            value_bytes = data[-4:-1]  # Extract the previous 3 bytes as the value
            process_displacement_data(value_bytes, sign_bit)

    def reset_timer(self):
        """Reset the timer by canceling the existing one and starting a new one."""
        if self.timer_task:
            self.timer_task.cancel()  # Cancel the existing timer task
        self.deadman.clear()  # Clear the event
        self.timer_task = asyncio.create_task(self.start_timer())  # Start a new timer

    async def start_timer(self):
        """Start the timer and set the event when the deadman timeout expires."""
        try:
            await asyncio.sleep(self.deadman_timeout)  # Wait for the deadman timeout
            verbose_print("Deadman timeout reached, reconnecting...")
            self.deadman.set()  # Set the event to signal timeout
        except asyncio.CancelledError:
            pass  # Timer was reset

    async def read_displacement(self):
        """Function to read displacement from the Bluetooth device."""
        max_retries = 5  # Set a limit to how many times to retry
        retry_count = 0

        while retry_count < max_retries:
            try:
                async with BleakClient(self.device_address) as client:
                    verbose_print(f"Connected: {client.is_connected}")
                    self.disconnected = False
                    self.deadman.clear()  # Clear the event at the start of the connection

                    await client.start_notify(
                        CHARACTERISTIC_UUID,
                        self.handle_notification
                    )
                    verbose_print("Subscribed to notifications. Waiting for updates...")

                    # Loop to wait for either a deadman timeout or the period to elapse
                    try:
                        # Wait for the deadman event to be set or for the period to elapse
                        wait_duration = self.period if self.period else INFINITE_RUN_TIME
                        await asyncio.wait_for(self.deadman.wait(), timeout=wait_duration)
                        if self.deadman.is_set():
                            verbose_print("Deadman timeout reached. Reconnecting...")
#                            break  # Break the loop to trigger a reconnection
                    except asyncio.TimeoutError:
                        # Period elapsed, exit the loop
                        verbose_print("Period elapsed. Exiting...")
                        await client.stop_notify(CHARACTERISTIC_UUID)
                        return

            except BleakDeviceNotFoundError:
                error_message(f"Device with address {self.device_address} was not found. Exiting.")
                sys.exit(1)
            except BleakError as e:
                retry_count += 1
                verbose_print(f"Bluetooth connection lost: {e}. Retrying ({retry_count}/{max_retries})...")
                await asyncio.sleep(5)  # Wait before retrying

        if retry_count >= max_retries:
            error_message("Max retries reached. Exiting.")
            sys.exit(1)


def signal_handler(sig, frame):
    """Handle termination signals (e.g., Ctrl+C) gracefully."""
    verbose_print("\nTerminating script.")
    sys.exit(0)


def main():
    global VERBOSE_MODE, JSON_MODE

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Displacement Sensor Reader (RS232/BT)")
    parser.add_argument('--connection', choices=['bt', 'rs232'], required=True, help="Connection type: 'bt' for Bluetooth or 'rs232' for serial communication")
    parser.add_argument('--device', type=str, required=True, help="The device file for RS232 or the MAC address for Bluetooth")
    parser.add_argument('--interval', type=float, help="Time interval between RS232 queries in seconds (e.g., 0.5 for 500 ms)")
    parser.add_argument('--period', type=float, help="Run the script for a specified time period in seconds (e.g., 60 for 1 minute)")
    parser.add_argument('--deadman', type=float, help="Maximum time to wait for an update before reconnecting")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output")
    parser.add_argument('--json', action='store_true', help="Output the displacement data in JSON format")
    args = parser.parse_args()

    # Set verbose and json modes
    VERBOSE_MODE = args.verbose
    JSON_MODE = args.json

    # Handle signals (e.g., Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)

    loop = asyncio.get_event_loop()  # Get the current event loop

    if args.connection == 'bt':
        # Bluetooth mode
        verbose_print(f"Starting Bluetooth mode using device {args.device}...")
        reader = BluetoothDisplacementReader(args.device, args.period, args.deadman)
        loop.run_until_complete(reader.read_displacement())  # Use the event loop to run the async function
    elif args.connection == 'rs232':
        if not args.interval:
            print("For RS232, --interval is required.")
            sys.exit(1)

        verbose_print(f"Starting RS232 mode on device {args.device} with interval {args.interval} seconds.")
        client = ModbusSerialClient(
            port=args.device,
            baudrate=38400,
            stopbits=2,
            bytesize=8,
            parity='N',
            timeout=1
        )

        if not client.connect():
            print("Failed to connect to the RS232 sensor.")
            sys.exit(1)
        else:
            verbose_print("Connected to the RS232 sensor.")

        slave_id = 0x01  # Default Modbus address for the sensor

        start_time = time.time()
        try:
            while True:
                read_displacement_rs232(client, slave_id)
                time.sleep(args.interval)

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