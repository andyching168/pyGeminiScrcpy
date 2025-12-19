#!/usr/bin/env python3
"""
Termux Mode Launcher

A simplified launcher for running pyGeminiScrcpy on Termux (Android).
This mode uses ADB screenshots instead of scrcpy video stream to avoid
complex dependencies (PyAV, OpenCV GUI, etc.).

Features:
- Wireless ADB pairing and connection
- ADB-based screenshot capture
- Works without display/GUI
- Minimal dependencies

Usage:
    python termux_mode.py          # Interactive setup
    python termux_mode.py --pair   # Pair with device
    python termux_mode.py --run    # Run agent in headless mode
"""

import os
import sys
import time
import subprocess
import argparse
from typing import Optional, Tuple

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from wireless_adb import WirelessADB
except ImportError:
    print("Error: wireless_adb.py not found")
    sys.exit(1)


class TermuxScrcpyClient:
    """
    Simplified scrcpy client for Termux.
    Uses ADB commands instead of video streaming.
    """
    
    def __init__(self, serial: Optional[str] = None):
        self.serial = serial
        self.resolution: Optional[Tuple[int, int]] = None
        self.alive = False
        self._get_resolution()
    
    def _adb_cmd(self, *args) -> list:
        """Build ADB command."""
        cmd = ["adb"]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd
    
    def _run_adb(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Run ADB command."""
        return subprocess.run(
            self._adb_cmd(*args),
            capture_output=True,
            **kwargs
        )
    
    def _get_resolution(self):
        """Get device screen resolution."""
        result = self._run_adb("shell", "wm", "size")
        if result.returncode == 0:
            # Parse "Physical size: 1080x2400"
            import re
            match = re.search(r'(\d+)x(\d+)', result.stdout.decode())
            if match:
                self.resolution = (int(match.group(1)), int(match.group(2)))
                print(f"📱 Screen resolution: {self.resolution[0]}x{self.resolution[1]}")
    
    def screenshot(self, output_path: str = "/tmp/screen.png") -> Optional[str]:
        """
        Capture screenshot via ADB.
        
        Returns:
            Path to screenshot file, or None on failure
        """
        try:
            # Capture to device, then pull
            result = self._run_adb(
                "exec-out", "screencap", "-p",
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                with open(output_path, 'wb') as f:
                    f.write(result.stdout)
                return output_path
            else:
                print(f"Screenshot failed: {result.stderr.decode()}")
                return None
                
        except Exception as e:
            print(f"Screenshot error: {e}")
            return None
    
    def tap(self, x: int, y: int):
        """Tap at coordinates."""
        self._run_adb("shell", "input", "tap", str(x), str(y))
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        """Swipe gesture."""
        self._run_adb("shell", "input", "swipe", 
                      str(x1), str(y1), str(x2), str(y2), str(duration))
    
    def text(self, text: str):
        """Input text (ASCII only)."""
        # Escape special characters
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        self._run_adb("shell", "input", "text", escaped)
    
    def keyevent(self, keycode: int):
        """Send keycode."""
        self._run_adb("shell", "input", "keyevent", str(keycode))
    
    def home(self):
        """Press home button."""
        self.keyevent(3)
    
    def back(self):
        """Press back button."""
        self.keyevent(4)
    
    def start(self, threaded: bool = False):
        """Start the client (compatibility with ScrcpyClient)."""
        self.alive = True
        print("✅ Termux client ready (ADB mode)")
    
    def stop(self):
        """Stop the client."""
        self.alive = False


class TermuxAgent:
    """
    Simplified agent for Termux.
    Uses ADB screenshots instead of real-time video.
    """
    
    def __init__(self, api_key: str, device_serial: Optional[str] = None):
        self.api_key = api_key
        self.client = TermuxScrcpyClient(device_serial)
        self.screenshot_dir = "/tmp"
        
        # Try to import Gemini
        try:
            from google import genai
            self.genai = genai
            self.gemini_client = genai.Client(api_key=api_key)
            print("✅ Gemini API initialized")
        except ImportError:
            print("⚠️ google-generativeai not installed")
            print("   Install with: pip install google-generativeai")
            self.gemini_client = None
    
    def capture_screen(self) -> Optional[str]:
        """Capture current screen."""
        timestamp = int(time.time() * 1000)
        path = os.path.join(self.screenshot_dir, f"screen_{timestamp}.png")
        return self.client.screenshot(path)
    
    def send_to_gemini(self, prompt: str, image_path: str) -> Optional[str]:
        """Send image and prompt to Gemini."""
        if not self.gemini_client:
            return None
        
        try:
            # Read image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            # Create image part
            image_part = self.genai.types.Part.from_bytes(
                data=image_data,
                mime_type="image/png"
            )
            
            # Send to Gemini
            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[prompt, image_part]
            )
            
            return response.text
            
        except Exception as e:
            print(f"Gemini error: {e}")
            return None
    
    def run_interactive(self):
        """Run interactive mode."""
        print("\n" + "=" * 50)
        print("📱 Termux Agent - Interactive Mode")
        print("=" * 50)
        print("\nCommands:")
        print("  screenshot / ss  - Capture screen")
        print("  tap X Y          - Tap at coordinates")
        print("  swipe X1 Y1 X2 Y2 - Swipe gesture")
        print("  home             - Go home")
        print("  back             - Go back")
        print("  ask <prompt>     - Ask Gemini about current screen")
        print("  quit / exit      - Exit")
        print()
        
        self.client.start()
        
        while True:
            try:
                cmd = input(">>> ").strip()
                
                if not cmd:
                    continue
                
                parts = cmd.split()
                action = parts[0].lower()
                
                if action in ['quit', 'exit', 'q']:
                    break
                
                elif action in ['screenshot', 'ss']:
                    path = self.capture_screen()
                    if path:
                        print(f"✅ Screenshot saved: {path}")
                    else:
                        print("❌ Screenshot failed")
                
                elif action == 'tap' and len(parts) >= 3:
                    x, y = int(parts[1]), int(parts[2])
                    self.client.tap(x, y)
                    print(f"✅ Tapped at ({x}, {y})")
                
                elif action == 'swipe' and len(parts) >= 5:
                    x1, y1, x2, y2 = map(int, parts[1:5])
                    self.client.swipe(x1, y1, x2, y2)
                    print(f"✅ Swiped from ({x1},{y1}) to ({x2},{y2})")
                
                elif action == 'home':
                    self.client.home()
                    print("✅ Home pressed")
                
                elif action == 'back':
                    self.client.back()
                    print("✅ Back pressed")
                
                elif action == 'ask':
                    prompt = ' '.join(parts[1:]) if len(parts) > 1 else "What do you see on this screen?"
                    print("📸 Capturing screen...")
                    path = self.capture_screen()
                    if path:
                        print("🤖 Asking Gemini...")
                        response = self.send_to_gemini(prompt, path)
                        if response:
                            print(f"\n{response}\n")
                        else:
                            print("❌ No response from Gemini")
                    else:
                        print("❌ Screenshot failed")
                
                elif action == 'text' and len(parts) >= 2:
                    text = ' '.join(parts[1:])
                    self.client.text(text)
                    print(f"✅ Typed: {text}")
                
                else:
                    print(f"Unknown command: {action}")
                    
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
        
        self.client.stop()


def check_adb_connection() -> Tuple[bool, Optional[str]]:
    """Check ADB connection and return device serial if connected."""
    wadb = WirelessADB()
    
    if not wadb.check_adb_available():
        print("❌ ADB not found!")
        print("   Install with: pkg install android-tools")
        return False, None
    
    devices = wadb.get_connected_devices()
    
    if not devices:
        print("❌ No devices connected")
        return False, None
    
    for d in devices:
        if d['status'] == 'device':
            wireless = "📶" if d['is_wireless'] else "🔌"
            print(f"✅ Connected: {wireless} {d['serial']}")
            return True, d['serial']
    
    return False, None


def main():
    parser = argparse.ArgumentParser(description="Termux Mode for pyGeminiScrcpy")
    parser.add_argument("--pair", action="store_true", help="Pair with device")
    parser.add_argument("--connect", type=str, help="Connect to device (IP:port)")
    parser.add_argument("--run", action="store_true", help="Run agent")
    parser.add_argument("--api-key", type=str, help="Gemini API key")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("📱 pyGeminiScrcpy - Termux Mode")
    print("=" * 50)
    
    wadb = WirelessADB()
    
    # Handle pairing
    if args.pair:
        from wireless_adb import interactive_setup
        interactive_setup()
        return
    
    # Handle connection
    if args.connect:
        if ':' in args.connect:
            host, port = args.connect.rsplit(':', 1)
        else:
            host, port = args.connect, "5555"
        success, msg = wadb.connect(host, int(port))
        print(msg)
        if not success:
            return
    
    # Check connection
    connected, serial = check_adb_connection()
    
    if not connected:
        print("\n💡 To connect:")
        print("   1. Enable Developer Options on your device")
        print("   2. Enable Wireless debugging")
        print("   3. Run: python termux_mode.py --pair")
        print("   4. Or run: python wireless_adb.py")
        return
    
    # Get API key
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("\n⚠️ No Gemini API key found")
        print("   Set with: export GEMINI_API_KEY='your-key'")
        print("   Or use: --api-key YOUR_KEY")
        print("\n   Running without Gemini AI...\n")
        api_key = ""
    
    # Run agent
    agent = TermuxAgent(api_key, serial)
    agent.run_interactive()


if __name__ == "__main__":
    main()
