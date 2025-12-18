#!/usr/bin/env python3
"""
Test to capture server output and see what's happening.
"""

import socket
import subprocess
import time
import sys
import threading

def run_adb(*args):
    """Run ADB command."""
    cmd = ["adb"] + list(args)
    return subprocess.run(cmd, capture_output=True)

def read_server_output(proc):
    """Read server stdout in background."""
    print("\n=== Server stdout ===")
    for line in iter(proc.stdout.readline, b''):
        if line:
            print(f"[SERVER] {line.decode(errors='replace').rstrip()}")

def read_server_errors(proc):
    """Read server stderr in background."""
    print("\n=== Server stderr ===")
    for line in iter(proc.stderr.readline, b''):
        if line:
            print(f"[ERROR] {line.decode(errors='replace').rstrip()}")

def main():
    local_port = 27183
    server_process = None
    
    try:
        # Deploy server
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
        print("Starting scrcpy server with debug logging...")
        server_cmd = [
            "adb", "shell",
            "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process", "/", "com.genymobile.scrcpy.Server",
            "3.3.3",
            "log_level=debug",
            "video_bit_rate=8000000",  # FIXED
            "max_size=800",            
            "max_fps=0",
            # REMOVED lock_video_orientation - not valid
            "tunnel_forward=true",
            "send_device_meta=true",
            "send_codec_meta=true",
            "send_dummy_byte=true",
            "send_frame_meta=true",
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
        
        print(f"Command: {' '.join(server_cmd)}")
        
        server_process = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        
        # Start threads to read server output
        stdout_thread = threading.Thread(target=read_server_output, args=(server_process,), daemon=True)
        stderr_thread = threading.Thread(target=read_server_errors, args=(server_process,), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        
        print("\nWaiting for server to initialize...")
        time.sleep(3)
        
        # Check if server is still running
        if server_process.poll() is not None:
            print(f"Server exited early with code {server_process.poll()}")
            return 1
        
        print("\n=== Connecting to server ===")
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        video_socket.settimeout(10.0)
        video_socket.connect(("127.0.0.1", local_port))
        print("✓ Video socket connected")
        
        # Try to receive data
        print("\nReading first 100 bytes...")
        data = video_socket.recv(100)
        print(f"Received {len(data)} bytes:")
        print(f"  Hex: {data.hex()}")
        print(f"  ASCII: {data.decode('utf-8', errors='replace')}")
        
        # Let server output accumulate
        print("\nWaiting 5 seconds for server output...")
        time.sleep(5)
        
        video_socket.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if server_process:
            print("\nTerminating server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=2)
            except:
                server_process.kill()
        run_adb("forward", "--remove-all")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
