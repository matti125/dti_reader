#!/usr/bin/env python3

import argparse
import signal
import sys
import json
import asyncio
from datetime import datetime
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
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{current_time}] {message}", file=sys.stderr)


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
        self.interrupt_event = asyncio.Event()  # Event to manage interruptions
        self.deadman_timer = None
        self.triggered_by_deadman = False

    async def handle_notification(self, sender: int, data: bytearray):
        """Callback function to process incoming BLE notifications."""
        self.triggered_by_deadman = False  # Reset the flag because we received data
        self.reset_timer()  # Reset the deadman timer
        verbose_print(f"Raw data (Bluetooth): {':'.join(f'{byte:02X}' for byte in data)}")
        if len(data) >= 8:
            sign_bit = data[-1]  # Extract the sign bit from the last byte
            value_bytes = data[-4:-1]  # Extract the previous 3 bytes as the value
            process_displacement_data(value_bytes, sign_bit)

    def reset_timer(self):
        """Reset the deadman timer by canceling the existing one and starting a new one."""
        if self.deadman_timer:
            self.deadman_timer.cancel()  # Cancel the existing timer
        self.deadman_timer = asyncio.create_task(self.start_timer())  # Start a new timer

    async def start_timer(self):
        """Start the deadman timer and set the interrupt event when it expires."""
        try:
            await asyncio.sleep(self.deadman_timeout)  # Wait for the deadman timeout
            self.triggered_by_deadman = True
            verbose_print("Deadman timeout reached. Attempting to reconnect...")
            # Instead of shutting down, handle reconnection or resubscription
            self.interrupt_event.set()  # Trigger the event to handle reconnection
        except asyncio.CancelledError:
            # Timer was reset
            pass

    def trigger_interrupt(self):
        """Method to trigger an interrupt on Ctrl+C."""
        self.interrupt_event.set()
        self.triggered_by_deadman = False

    async def read_displacement(self):
        """Function to read displacement from the Bluetooth device."""
        client = None
        try:
            while True:
                try:
                    client = BleakClient(self.device_address)
                    verbose_print(f"Connecting to {client.address}")
                    await client.connect()
                    verbose_print(f"Connected: {client.is_connected}")
                    self.interrupt_event.clear()  # Clear the interrupt event
                    await client.start_notify(
                        CHARACTERISTIC_UUID,
                        self.handle_notification
                    )
                    verbose_print("Subscribed to notifications. Waiting for updates...")

                    # Determine the wait duration
                    wait_duration = self.period if self.period else INFINITE_RUN_TIME
                    await asyncio.wait_for(self.interrupt_event.wait(), timeout=wait_duration)

                    if self.triggered_by_deadman:
                        verbose_print("Got a deadman alert. Will try again")
                        await client.stop_notify(CHARACTERISTIC_UUID)
                        continue  # Reconnect by restarting the loop
                    else:
                        verbose_print("Shutting down due to external signal (e.g., Ctrl+C).")
                        await client.stop_notify(CHARACTERISTIC_UUID)
                        await client.disconnect()
                        verbose_print("Stopped notifications and disconnected.")
                        break
                except asyncio.TimeoutError:
                    verbose_print("Period timeout reached. Exiting...")
                    break
                except BleakDeviceNotFoundError:
                    error_message(f"Device with address {self.device_address} was not found. Retrying.")
                    await asyncio.sleep(1)  # Wait before retrying

                except BleakError as e:
                    error_message(f"Bluetooth error: {e}. Retrying...")
                    await asyncio.sleep(1)  # Wait before retrying
 
        except Exception as e:
            error_message(f"Unexpected error: {e}")
            sys.exit(1)


def signal_handler(reader):
    """Handle termination signals (e.g., Ctrl+C) gracefully."""
    verbose_print("\nTerminating script...")
    reader.trigger_interrupt()


def main():
    global VERBOSE_MODE, JSON_MODE

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Displacement Sensor Reader (RS232/BT)")
    parser.add_argument('--connection', choices=['bt', 'rs232'], required=True, help="Connection type: 'bt' for Bluetooth or 'rs232' for serial communication")
    parser.add_argument('--device', type=str, required=True, help="The device file for RS232 or the MAC address for Bluetooth")
    parser.add_argument('--interval', type=float, help="Time interval between RS232 queries in seconds (e.g., 0.5 for 500 ms)")
    parser.add_argument('--period', type=float, help="Run the script for a specified time period in seconds (e.g., 60 for 1 minute)")
    parser.add_argument('--deadman', type=float, help="Maximum time to wait for an update before attempting to reconnect")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output")
    parser.add_argument('--json', action='store_true', help="Output the displacement data in JSON format")
    args = parser.parse_args()

    # Set verbose and json modes
    VERBOSE_MODE = args.verbose
    JSON_MODE = args.json

    if args.connection == 'bt':
        verbose_print(f"Starting Bluetooth mode using device {args.device}...")
        reader = BluetoothDisplacementReader(args.device, args.period, args.deadman)

        # Set up signal handling
        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(reader))

        # Run the async event loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(reader.read_displacement())
    elif args.connection == 'rs232':
        # RS232 handling code remains the same
        pass

if __name__ == "__main__":
    main()