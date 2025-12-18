#!/usr/bin/env python3
"""
Test script to debug scrcpy protocol handshake - trying control socket for device info.
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
        # Deploy and start the server
        print("Deploying server...")
        server_path = "/home/ac/pyGeminiScrcpy/scrcpy-server"
        remote_path = "/data/local/tmp/scrcpy-server.jar"
        
        result = run_adb("push", server_path, remote_path)
        if result.returncode != 0:
            print(f"Failed to push server: {result.stderr.decode()}")
            return 1
        
        run_adb("forward", "--remove-all")
        
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
        
        print("\n=== Connecting video socket ===")
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        video_socket.settimeout(10.0)
        video_socket.connect(("127.0.0.1", local_port))
        print("✓ Video socket connected")
        
        # Receive dummy byte
        print("\n=== Waiting for dummy byte ===")
        dummy = video_socket.recv(1)
        print(f"✓ Received dummy byte: 0x{dummy.hex()}")
        
        # Connect control socket
        print("\n=== Connecting control socket ===")
        control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_socket.settimeout(10.0)
        control_socket.connect(("127.0.0.1", local_port))
        print("✓ Control socket connected")
        
        # Try reading from BOTH sockets to see which one has the device info
        print("\n=== Trying to read from VIDEO socket (64 bytes for device name) ===")
        video_socket.settimeout(2.0)
        try:
            device_name_bytes = video_socket.recv(64)
            if device_name_bytes:
                print(f"✓ VIDEO socket received {len(device_name_bytes)} bytes")
                print(f"  Hex: {device_name_bytes.hex()}")
                print(f"  ASCII: {device_name_bytes.decode('utf-8', errors='replace').rstrip(chr(0))}")
        except socket.timeout:
            print("✗ VIDEO socket timeout (no data)")
        
        print("\n=== Trying to read from CONTROL socket (64 bytes for device name) ===")
        control_socket.settimeout(2.0)
        try:
            device_name_bytes = control_socket.recv(64)
            if device_name_bytes:
                print(f"✓ CONTROL socket received {len(device_name_bytes)} bytes")
                print(f"  Hex: {device_name_bytes.hex()}")
                print(f"  ASCII: {device_name_bytes.decode('utf-8', errors='replace').rstrip(chr(0))}")
        except socket.timeout:
            print("✗ CONTROL socket timeout (no data)")
        
        print("\n=== Let's try reading any available data from both sockets ===")
        video_socket.setblocking(False)
        control_socket.setblocking(False)
        
        for i in range(10):
            time.sleep(0.5)
            
            # Try video socket
            try:
                data = video_socket.recv(4096)
                if data:
                    print(f"[{i}] VIDEO socket: {len(data)} bytes")
                    print(f"    Hex: {data[:100].hex()}")
                    print(f"    ASCII: {data[:100].decode('utf-8', errors='replace')}")
            except BlockingIOError:
                pass
            
            # Try control socket
            try:
                data = control_socket.recv(4096)
                if data:
                    print(f"[{i}] CONTROL socket: {len(data)} bytes")
                    print(f"    Hex: {data[:100].hex()}")
                    print(f"    ASCII: {data[:100].decode('utf-8', errors='replace')}")
            except BlockingIOError:
                pass
        
        print("\n=== Done ===")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if video_socket:
            video_socket.close()
        if control_socket:
            control_socket.close()
            
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
