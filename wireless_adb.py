"""
Wireless ADB Pairing and Connection Module

This module provides utilities for:
1. Pairing with Android devices via wireless ADB (Android 11+)
2. Connecting to devices via wireless ADB
3. Auto-discovery of devices on local network
4. Self-connection for Termux usage

Usage:
    python wireless_adb.py pair <ip:port> <pairing_code>
    python wireless_adb.py connect <ip:port>
    python wireless_adb.py scan
    python wireless_adb.py self-connect
"""

import subprocess
import socket
import re
import os
import time
from typing import Optional, List, Tuple, Dict


class WirelessADB:
    """Handles wireless ADB pairing and connection."""
    
    def __init__(self):
        self.adb_path = self._find_adb()
        
    def _find_adb(self) -> str:
        """Find ADB executable path."""
        # Check if adb is in PATH
        try:
            result = subprocess.run(
                ["which", "adb"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        
        # Common locations
        common_paths = [
            "/data/data/com.termux/files/usr/bin/adb",  # Termux
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return "adb"  # Hope it's in PATH
    
    def _run_adb(self, *args, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run ADB command."""
        cmd = [self.adb_path] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
    
    def check_adb_available(self) -> bool:
        """Check if ADB is available and working."""
        try:
            result = self._run_adb("version")
            return result.returncode == 0
        except Exception as e:
            print(f"ADB check failed: {e}")
            return False
    
    def get_connected_devices(self) -> List[Dict[str, str]]:
        """Get list of connected devices."""
        result = self._run_adb("devices", "-l")
        devices = []
        
        for line in result.stdout.strip().split('\n')[1:]:
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                status = parts[1]
                
                # Extract additional info
                info = {}
                for part in parts[2:]:
                    if ':' in part:
                        key, value = part.split(':', 1)
                        info[key] = value
                
                devices.append({
                    'serial': serial,
                    'status': status,
                    'info': info,
                    'is_wireless': ':' in serial  # IP:port format
                })
        
        return devices
    
    def pair(self, host: str, port: int, pairing_code: str) -> Tuple[bool, str]:
        """
        Pair with a device using wireless debugging (Android 11+).
        
        Args:
            host: Device IP address
            port: Pairing port (shown in wireless debugging settings)
            pairing_code: 6-digit pairing code
            
        Returns:
            (success, message)
        """
        address = f"{host}:{port}"
        print(f"🔗 Pairing with {address}...")
        
        try:
            # ADB pair command
            result = subprocess.run(
                [self.adb_path, "pair", address],
                input=f"{pairing_code}\n",
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout + result.stderr
            
            if "Successfully paired" in output:
                return True, f"✅ Successfully paired with {address}"
            elif "Failed" in output:
                return False, f"❌ Pairing failed: {output}"
            else:
                return False, f"❌ Unknown result: {output}"
                
        except subprocess.TimeoutExpired:
            return False, "❌ Pairing timeout - check if device is reachable"
        except Exception as e:
            return False, f"❌ Pairing error: {e}"
    
    def connect(self, host: str, port: int = 5555) -> Tuple[bool, str]:
        """
        Connect to a device via wireless ADB.
        
        Args:
            host: Device IP address
            port: ADB port (default 5555, or the port shown in wireless debugging)
            
        Returns:
            (success, message)
        """
        address = f"{host}:{port}"
        print(f"🔌 Connecting to {address}...")
        
        try:
            result = self._run_adb("connect", address)
            output = result.stdout + result.stderr
            
            if "connected" in output.lower():
                return True, f"✅ Connected to {address}"
            elif "already connected" in output.lower():
                return True, f"✅ Already connected to {address}"
            elif "refused" in output.lower():
                return False, f"❌ Connection refused - is wireless debugging enabled?"
            else:
                return False, f"❌ Connection failed: {output}"
                
        except subprocess.TimeoutExpired:
            return False, "❌ Connection timeout"
        except Exception as e:
            return False, f"❌ Connection error: {e}"
    
    def disconnect(self, host: str = None, port: int = 5555) -> Tuple[bool, str]:
        """
        Disconnect from a device or all devices.
        
        Args:
            host: Device IP (None to disconnect all)
            port: ADB port
            
        Returns:
            (success, message)
        """
        if host:
            address = f"{host}:{port}"
            result = self._run_adb("disconnect", address)
        else:
            result = self._run_adb("disconnect")
        
        return True, result.stdout + result.stderr
    
    def get_device_ip(self, serial: str = None) -> Optional[str]:
        """
        Get the IP address of a connected device.
        
        Args:
            serial: Device serial (None for first device)
            
        Returns:
            IP address or None
        """
        cmd = ["shell", "ip", "route"]
        if serial:
            cmd = ["-s", serial] + cmd
        
        result = self._run_adb(*cmd)
        
        # Parse IP from route output
        # Example: "192.168.1.0/24 dev wlan0 proto kernel scope link src 192.168.1.100"
        match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
        
        # Alternative: get from wlan0
        result = self._run_adb("shell", "ip", "addr", "show", "wlan0")
        match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
        if match:
            return match.group(1)
        
        return None
    
    def enable_tcpip(self, port: int = 5555, serial: str = None) -> Tuple[bool, str]:
        """
        Enable TCP/IP mode on a USB-connected device.
        
        Args:
            port: Port to listen on (default 5555)
            serial: Device serial (None for first device)
            
        Returns:
            (success, message)
        """
        cmd = ["tcpip", str(port)]
        if serial:
            cmd = ["-s", serial] + cmd
        
        result = self._run_adb(*cmd)
        output = result.stdout + result.stderr
        
        if "restarting" in output.lower() or result.returncode == 0:
            return True, f"✅ TCP/IP mode enabled on port {port}"
        else:
            return False, f"❌ Failed to enable TCP/IP: {output}"
    
    def self_connect_termux(self) -> Tuple[bool, str]:
        """
        Special mode for Termux: connect to the same device.
        Requires wireless debugging to be enabled.
        
        Returns:
            (success, message)
        """
        print("📱 Attempting self-connection (Termux mode)...")
        
        # Check if already connected to localhost
        devices = self.get_connected_devices()
        for device in devices:
            if '127.0.0.1' in device['serial'] or 'localhost' in device['serial']:
                return True, f"✅ Already connected to self: {device['serial']}"
        
        # Try localhost connection
        success, msg = self.connect("127.0.0.1", 5555)
        if success:
            return success, msg
        
        # Try with different ports
        for port in [5555, 5554, 5037]:
            success, msg = self.connect("localhost", port)
            if success:
                return success, msg
        
        return False, """❌ Self-connection failed. 

To connect to yourself in Termux:
1. Go to Settings → Developer Options → Wireless debugging
2. Enable "Wireless debugging"  
3. Tap "Pair device with pairing code"
4. Note the IP:Port and 6-digit code
5. Run: python wireless_adb.py pair <ip:port> <code>
6. Then: python wireless_adb.py connect <ip:port>

Or use USB first to enable tcpip:
1. Connect via USB
2. Run: adb tcpip 5555
3. Then: python wireless_adb.py connect 127.0.0.1:5555
"""
    
    def scan_network(self, subnet: str = None, ports: List[int] = None) -> List[Dict]:
        """
        Scan local network for devices with ADB port open.
        
        Args:
            subnet: Subnet to scan (e.g., "192.168.1"). Auto-detected if None.
            ports: Ports to check (default: [5555, 5554])
            
        Returns:
            List of found devices with {ip, port, reachable}
        """
        if ports is None:
            ports = [5555, 5554]
        
        # Auto-detect subnet
        if subnet is None:
            try:
                # Get local IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                subnet = '.'.join(local_ip.split('.')[:3])
            except:
                subnet = "192.168.1"
        
        print(f"🔍 Scanning {subnet}.0/24 for ADB devices...")
        found = []
        
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            for port in ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.1)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        print(f"  Found: {ip}:{port}")
                        found.append({
                            'ip': ip,
                            'port': port,
                            'address': f"{ip}:{port}"
                        })
                except:
                    pass
        
        return found


def interactive_setup():
    """Interactive setup wizard."""
    wadb = WirelessADB()
    
    print("=" * 50)
    print("🔌 Wireless ADB Setup Wizard")
    print("=" * 50)
    
    if not wadb.check_adb_available():
        print("❌ ADB not found! Install with: pkg install android-tools")
        return
    
    print("\nOptions:")
    print("1. Pair with new device (Android 11+)")
    print("2. Connect to paired device")
    print("3. Self-connect (Termux on same device)")
    print("4. Scan network for devices")
    print("5. Show connected devices")
    print("6. Enable TCP/IP on USB device")
    print("0. Exit")
    
    choice = input("\nSelect option: ").strip()
    
    if choice == "1":
        print("\n📱 On your Android device:")
        print("1. Go to Settings → Developer Options → Wireless debugging")
        print("2. Tap 'Pair device with pairing code'")
        print("3. Note the IP:Port and 6-digit code shown\n")
        
        address = input("Enter pairing address (IP:Port): ").strip()
        code = input("Enter 6-digit pairing code: ").strip()
        
        if ':' in address:
            host, port = address.rsplit(':', 1)
            success, msg = wadb.pair(host, int(port), code)
            print(msg)
            
            if success:
                print("\n💡 Now connect using option 2")
        else:
            print("❌ Invalid address format. Use IP:Port")
    
    elif choice == "2":
        address = input("Enter device address (IP:Port, e.g., 192.168.1.100:5555): ").strip()
        
        if ':' in address:
            host, port = address.rsplit(':', 1)
        else:
            host = address
            port = "5555"
        
        success, msg = wadb.connect(host, int(port))
        print(msg)
        
        if success:
            print("\n✅ Ready to use! Device serial:", f"{host}:{port}")
    
    elif choice == "3":
        success, msg = wadb.self_connect_termux()
        print(msg)
    
    elif choice == "4":
        devices = wadb.scan_network()
        if devices:
            print(f"\n✅ Found {len(devices)} device(s):")
            for d in devices:
                print(f"   {d['address']}")
        else:
            print("\n❌ No devices found on network")
    
    elif choice == "5":
        devices = wadb.get_connected_devices()
        if devices:
            print(f"\n📱 Connected devices ({len(devices)}):")
            for d in devices:
                wireless = "📶" if d['is_wireless'] else "🔌"
                print(f"   {wireless} {d['serial']} ({d['status']})")
        else:
            print("\n❌ No devices connected")
    
    elif choice == "6":
        success, msg = wadb.enable_tcpip()
        print(msg)
        if success:
            ip = wadb.get_device_ip()
            if ip:
                print(f"📶 Device IP: {ip}")
                print(f"💡 Connect with: adb connect {ip}:5555")
    
    elif choice == "0":
        print("Bye!")
    else:
        print("Invalid option")


def main():
    """Main entry point with CLI support."""
    import sys
    
    wadb = WirelessADB()
    
    if len(sys.argv) < 2:
        interactive_setup()
        return
    
    command = sys.argv[1].lower()
    
    if command == "pair":
        if len(sys.argv) < 4:
            print("Usage: python wireless_adb.py pair <ip:port> <pairing_code>")
            print("Example: python wireless_adb.py pair 192.168.1.100:37123 123456")
            return
        
        address = sys.argv[2]
        code = sys.argv[3]
        
        if ':' not in address:
            print("❌ Address must include port (IP:Port)")
            return
        
        host, port = address.rsplit(':', 1)
        success, msg = wadb.pair(host, int(port), code)
        print(msg)
    
    elif command == "connect":
        if len(sys.argv) < 3:
            print("Usage: python wireless_adb.py connect <ip:port>")
            print("Example: python wireless_adb.py connect 192.168.1.100:5555")
            return
        
        address = sys.argv[2]
        if ':' in address:
            host, port = address.rsplit(':', 1)
        else:
            host = address
            port = "5555"
        
        success, msg = wadb.connect(host, int(port))
        print(msg)
    
    elif command == "disconnect":
        if len(sys.argv) >= 3:
            address = sys.argv[2]
            if ':' in address:
                host, port = address.rsplit(':', 1)
            else:
                host = address
                port = "5555"
            success, msg = wadb.disconnect(host, int(port))
        else:
            success, msg = wadb.disconnect()
        print(msg)
    
    elif command == "scan":
        devices = wadb.scan_network()
        if devices:
            print(f"Found {len(devices)} device(s):")
            for d in devices:
                print(f"  {d['address']}")
        else:
            print("No devices found")
    
    elif command == "devices":
        devices = wadb.get_connected_devices()
        for d in devices:
            print(f"{d['serial']}\t{d['status']}")
    
    elif command == "self-connect" or command == "self":
        success, msg = wadb.self_connect_termux()
        print(msg)
    
    elif command == "tcpip":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 5555
        success, msg = wadb.enable_tcpip(port)
        print(msg)
        if success:
            ip = wadb.get_device_ip()
            if ip:
                print(f"Connect with: adb connect {ip}:{port}")
    
    else:
        print(f"Unknown command: {command}")
        print("\nAvailable commands:")
        print("  pair <ip:port> <code>  - Pair with device")
        print("  connect <ip:port>      - Connect to device")
        print("  disconnect [ip:port]   - Disconnect from device(s)")
        print("  scan                   - Scan network for devices")
        print("  devices                - List connected devices")
        print("  self-connect           - Connect to self (Termux)")
        print("  tcpip [port]           - Enable TCP/IP mode on USB device")


if __name__ == "__main__":
    main()
