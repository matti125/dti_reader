#!/usr/bin/env python3

import asyncio
import fnmatch
import argparse
from bleak import BleakScanner

# Dictionary to keep track of devices we've already printed
discovered_devices = {}

def detection_callback(device, advertisement_data, name_pattern):
    """Callback function that is called when a BLE device is detected."""
    device_address = device.address
    device_name = device.name or advertisement_data.local_name or "Unknown"

    # Check if the name matches the provided glob-style pattern
    if name_pattern and not fnmatch.fnmatch(device_name, name_pattern):
        return  # Skip if the name doesn't match the pattern

    # Check if we've seen this device before
    if device_address in discovered_devices:
        if discovered_devices[device_address] != device_name:
            print(f"Updated device: Name: {device_name}, Address: {device_address}, RSSI: {advertisement_data.rssi} dBm")
            discovered_devices[device_address] = device_name  # Update with the new name
    else:
        # New device detected, print its details and add to the list
        print(f"Detected device: Name: {device_name}, Address: {device_address}, RSSI: {advertisement_data.rssi} dBm")
        discovered_devices[device_address] = device_name

async def scan_ble_devices_continuously(name_pattern):
    """Scan for BLE devices continuously and print their information as they appear."""
    print("Starting continuous BLE device scanning...")

    # Create the BLE scanner and pass the detection callback directly in the constructor
    scanner = BleakScanner(detection_callback=lambda device, advertisement_data: detection_callback(device, advertisement_data, name_pattern))

    # Start the scanner
    await scanner.start()

    try:
        # Run the scanner indefinitely
        while True:
            await asyncio.sleep(1)  # Keep the script running
    except asyncio.CancelledError:
        # Stop the scanner if the task is cancelled
        await scanner.stop()

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Scan BLE devices and filter by name using glob-style patterns.")
    parser.add_argument('--name', type=str, help='Glob pattern to filter device names (e.g., "B-*")')
    args = parser.parse_args()

    # Run the async BLE scanning with optional name pattern filter
    try:
        asyncio.run(scan_ble_devices_continuously(args.name))
    except KeyboardInterrupt:
        print("\nScan stopped by user.")

if __name__ == "__main__":
    main()