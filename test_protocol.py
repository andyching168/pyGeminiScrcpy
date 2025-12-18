#!/usr/bin/env python3
"""
Test script to debug scrcpy protocol handshake.
This will help us understand what data is being sent by the server.
"""

import socket
import struct
import subprocess
import time
import sys

def run_adb(*args):
    """Run ADB command."""
    cmd = ["adb"] + list(args)
    return subprocess.run(cmd, capture_output=True)

def main():
    local_port = 27183
    server_process = None
    video_socket = None
    control_socket = None
    
    try:
        # First, deploy and start the server
        print("Deploying server...")
        server_path = "/home/ac/pyGeminiScrcpy/scrcpy-server"
        remote_path = "/data/local/tmp/scrcpy-server.jar"
        
        result = run_adb("push", server_path, remote_path)
        if result.returncode != 0:
            print(f"Failed to push server: {result.stderr.decode()}")
            return 1
        
        print("Cleaning up previous port forwards...")
        run_adb("forward", "--remove-all")
        
        print("Setting up port forward...")
        result = run_adb("forward", f"tcp:{local_port}", "localabstract:scrcpy")
        if result.returncode != 0:
            print(f"Failed to forward port: {result.stderr.decode()}")
            return 1
        
        # Start the server
        print("Starting scrcpy server...")
        server_cmd = [
            "adb", "shell",
            "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process", "/", "com.genymobile.scrcpy.Server",
            "3.3.3",
            "log_level=debug",
            "bit_rate=8000000",
            "max_size=800",
            "max_fps=0",
            "lock_video_orientation=-1",
            "tunnel_forward=true",
            "control=true",
            "display_id=0",
            "show_touches=false",
            "stay_awake=false",
            "power_off_on_close=false",
            "clipboard_autosync=false",
            "downsize_on_error=true",
            "cleanup=true",
            "power_on=true",
        ]
        
        server_process = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        print("Waiting for server to initialize...")
        time.sleep(2)
        
        # Check if server is still running
        if server_process.poll() is not None:
            stdout, stderr = server_process.communicate()
            print(f"Server exited early!")
            print(f"Stdout: {stdout.decode(errors='replace')}")
            print(f"Stderr: {stderr.decode(errors='replace')}")
            return 1
        
        print("Connecting video socket...")
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        video_socket.settimeout(10.0)
        video_socket.connect(("127.0.0.1", local_port))
        print("✓ Video socket connected")
        
        # Try to receive dummy byte
        print("\nWaiting for dummy byte...")
        dummy = video_socket.recv(1)
        print(f"Received {len(dummy)} bytes: {dummy.hex()}")
        if dummy == b'\x00':
            print("✓ Dummy byte is correct (0x00)")
        else:
            print(f"⚠ Expected 0x00, got 0x{dummy.hex()}")
        
        # Connect control socket
        print("\nConnecting control socket...")
        control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_socket.settimeout(10.0)
        control_socket.connect(("127.0.0.1", local_port))
        print("✓ Control socket connected")
        
        # Try to receive device name (64 bytes)
        print("\nWaiting for device name (64 bytes)...")
        try:
            device_name_bytes = video_socket.recv(64)
            print(f"Received {len(device_name_bytes)} bytes")
            print(f"Hex dump: {device_name_bytes.hex()}")
            print(f"Raw bytes: {device_name_bytes}")
            device_name = device_name_bytes.decode("utf-8", errors='replace').rstrip("\x00")
            print(f"Device name: '{device_name}'")
        except socket.timeout:
            print("✗ Timeout receiving device name")
            print("\nLet's try reading byte-by-byte to see what we get...")
            video_socket.settimeout(2.0)
            bytes_received = []
            for i in range(100):  # Try to read up to 100 bytes
                try:
                    b = video_socket.recv(1)
                    if not b:
                        break
                    bytes_received.append(b)
                    print(f"Byte {i}: 0x{b.hex()} '{chr(b[0]) if 32 <= b[0] < 127 else '?'}'")
                except socket.timeout:
                    print(f"Timeout after {i} bytes")
                    break
                except Exception as e:
                    print(f"Error after {i} bytes: {e}")
                    break
            
            if bytes_received:
                all_bytes = b''.join(bytes_received)
                print(f"\nTotal received: {len(all_bytes)} bytes")
                print(f"Hex: {all_bytes.hex()}")
                print(f"ASCII: {all_bytes.decode('utf-8', errors='replace')}")
            else:
                print("\nNo data received at all!")
            
            return 1
        
        # Try to receive resolution (4 bytes)
        print("\nWaiting for resolution (4 bytes)...")
        res_data = video_socket.recv(4)
        print(f"Received {len(res_data)} bytes: {res_data.hex()}")
        if len(res_data) == 4:
            width, height = struct.unpack(">HH", res_data)
            print(f"Resolution: {width}x{height}")
        
        print("\n✓ Handshake complete!")
        
    except Exception as e:
        print(f"Error during protocol test: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        # Clean up sockets
        if video_socket:
            video_socket.close()
        if control_socket:
            control_socket.close()
            
        # Clean up server process
        if server_process:
            try:
                server_process.terminate()
                server_process.wait(timeout=3)
            except:
                server_process.kill()
        run_adb("forward", "--remove-all")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
