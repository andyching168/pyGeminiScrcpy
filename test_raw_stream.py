#!/usr/bin/env python3
"""
Test raw video stream to see what data format is being sent.
"""

import socket
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
        
        if server_process.poll() is not None:
            stdout, stderr = server_process.communicate()
            print(f"Server exited early!")
            print(f"Stdout: {stdout.decode(errors='replace')}")
            print(f"Stderr: {stderr.decode(errors='replace')}")
            return 1
        
        print("Connecting sockets...")
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        video_socket.settimeout(10.0)
        video_socket.connect(("127.0.0.1", local_port))
        
        dummy = video_socket.recv(1)
        print(f"✓ Dummy byte: 0x{dummy.hex()}")
        
        control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_socket.settimeout(10.0)
        control_socket.connect(("127.0.0.1", local_port))
        print("✓ Control socket connected")
        
        # Now let's just read whatever comes next on the video socket
        print("\n=== Reading raw data from video socket ===")
        video_socket.settimeout(5.0)
        
        total_bytes = 0
        for attempt in range(5):
            try:
                data = video_socket.recv(4096)
                if data:
                    total_bytes += len(data)
                    print(f"\nChunk {attempt + 1}: {len(data)} bytes (total: {total_bytes})")
                    
                    # Show first 200 bytes in detail
                    show_bytes = min(200, len(data))
                    print(f"First {show_bytes} bytes (hex): {data[:show_bytes].hex()}")
                    
                    # Try to identify patterns
                    # H.264 NAL units start with 0x00000001 or 0x000001
                    if b'\x00\x00\x00\x01' in data[:100]:
                        print("  → Found H.264 NAL unit marker (0x00000001)")
                    if b'\x00\x00\x01' in data[:100]:
                        print("  → Found H.264 NAL unit marker (0x000001)")
                    
                    # Check for ASCII text (might be device name)
                    ascii_chars = sum(1 for b in data[:100] if 32 <= b < 127 or b == 0)
                    if ascii_chars > len(data[:100]) * 0.5:
                        print(f"  → Looks like ASCII text: {data[:100].decode('utf-8', errors='replace')}")
                    
                    # Show byte structure
                    if len(data) >= 4:
                        import struct
                        # Try as big-endian uint32
                        val32 = struct.unpack('>I', data[:4])[0]
                        print(f"  → First 4 bytes as uint32 (BE): {val32} (0x{val32:08x})")
                        
                        # Try as width/height
                        if len(data) >= 4:
                            w, h = struct.unpack('>HH', data[:4])
                            print(f"  → First 4 bytes as width×height: {w}×{h}")
                    
                else:
                    print(f"Chunk {attempt + 1}: No data")
                    
            except socket.timeout:
                print(f"Timeout on attempt {attempt + 1}")
                break
        
        print(f"\n✓ Total bytes received: {total_bytes}")
        
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
