#!/usr/bin/env python3
"""Diagnostic script to check scrcpy server connection issues"""
import socket
import subprocess
import time
import sys

# Check ADB device
print("1. Checking ADB device...")
result = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True)
print(result.stdout)

# Check port forwarding
print("\n2. Checking port forwarding...")
result = subprocess.run(["adb", "forward", "--list"], capture_output=True, text=True)
print(result.stdout if result.stdout else "No port forwards")

# Check if scrcpy server is running
print("\n3. Checking for running scrcpy server...")
result = subprocess.run(["adb", "shell", "ps | grep scrcpy"], capture_output=True, text=True)
print(result.stdout if result.stdout else "No scrcpy server process found")

# Try to connect to port 27183
print("\n4. Trying to connect to port 27183...")
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect(("127.0.0.1", 27183))
    print("✓ Connection successful!")
    
    # Try to receive data with timeout
    print("\n5. Waiting for data (3 second timeout)...")
    sock.settimeout(3)
    try:
        data = sock.recv(1)
        print(f"✓ Received {len(data)} bytes: {data.hex()}")
    except socket.timeout:
        print("✗ Timeout waiting for data")
    
    sock.close()
except socket.timeout:
    print("✗ Connection timeout")
except ConnectionRefusedError:
    print("✗ Connection refused - port not listening")
except Exception as e:
    print(f"✗ Error: {e}")

# Check ADB server logs
print("\n6. Checking ADB logcat for scrcpy...")
result = subprocess.run(
    ["adb", "logcat", "-d", "-s", "scrcpy:*"], 
    capture_output=True, 
    text=True,
    timeout=5
)
if result.stdout:
    print(result.stdout[-1000:])  # Last 1000 chars
else:
    print("No logcat output")
