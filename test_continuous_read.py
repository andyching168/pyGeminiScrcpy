#!/usr/bin/env python3
"""
Continuously read from video socket to see when data arrives.
"""

import socket
import subprocess
import time
import sys

def run_adb(*args):
    cmd = ["adb"] + list(args)
    return subprocess.run(cmd, capture_output=True)

def main():
    local_port = 27183
    server_process = None
    
    try:
        # Deploy server
        print("Deploying server...")
        run_adb("push", "/home/ac/pyGeminiScrcpy/scrcpy-server", "/data/local/tmp/scrcpy-server.jar")
        run_adb("forward", "--remove-all")
        run_adb("forward", f"tcp:{local_port}", "localabstract:scrcpy")
        
        # Start server
        print("Starting server...")
        server_cmd = [
            "adb", "shell",
            "CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process", "/", "com.genymobile.scrcpy.Server",
            "3.3.3",
            "log_level=debug",
            "video_bit_rate=8000000",
            "max_size=800",
            "max_fps=0",
            "tunnel_forward=true",
            "send_device_meta=true",
            "send_codec_meta=true",
            "send_dummy_byte=true",
            "send_frame_meta=true",
            "control=true",
            "display_id=0",
        ]
        
        server_process = subprocess.Popen(server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        
        print("Connecting video socket...")
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        video_socket.settimeout(1.0)
        video_socket.connect(("127.0.0.1", local_port))
        print("✓ Connected\n")
        
        # Read data in chunks
        total_bytes = 0
        chunk_num = 0
        
        print("Reading data continuously...")
        for i in range(20):  # Try for 20 seconds
            try:
                data = video_socket.recv(4096)
                if data:
                    chunk_num += 1
                    total_bytes += len(data)
                    print(f"\n[Chunk {chunk_num}] Received {len(data)} bytes (total: {total_bytes})")
                    print(f"  Hex (first 64): {data[:64].hex()}")
                    
                    # Try to decode as text
                    try:
                        text = data[:64].decode('utf-8', errors='ignore').rstrip('\x00')
                        if text.isprintable():
                            print(f"  ASCII: '{text}'")
                    except:
                        pass
                        
            except socket.timeout:
                print(f"[{i}s] No data (timeout)...")
                time.sleep(1)
            except Exception as e:
                print(f"Error: {e}")
                break
        
        print(f"\n✓ Total bytes received: {total_bytes}")
        
        # Now try connecting control socket
        print("\nNow connecting control socket...")
        control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_socket.settimeout(2.0)
        control_socket.connect(("127.0.0.1", local_port))
        print("✓ Control socket connected")
        
        # Check if more data comes on video socket now
        print("\nChecking video socket after control connection...")
        video_socket.settimeout(2.0)
        for i in range(5):
            try:
                data = video_socket.recv(4096)
                if data:
                    chunk_num += 1
                    total_bytes += len(data)
                    print(f"\n[Chunk {chunk_num}] Received {len(data)} bytes (total: {total_bytes})")
                    print(f"  Hex (first 100): {data[:100].hex()}")
            except socket.timeout:
                print(f"  [{i}] Still no data...")
        
        control_socket.close()
        video_socket.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if server_process:
            server_process.terminate()
            try:
                server_process.wait(timeout=2)
            except:
                server_process.kill()
        run_adb("forward", "--remove-all")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
