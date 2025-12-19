"""
Shizuku Support Module for pyGeminiScrcpy

Shizuku allows running ADB commands without WiFi debugging or PC connection.
This module provides utilities to detect and use Shizuku's `rish` shell.

Setup:
1. Install Shizuku app from Play Store or GitHub
2. Start Shizuku (via wireless ADB once, or root, or PC)
3. In Shizuku app: "Use Shizuku in terminal apps" -> "Export files"
4. Export to shared storage accessible by Termux
5. Run this script to set up rish in Termux

Usage:
    python shizuku_setup.py install    # Install rish to Termux
    python shizuku_setup.py check      # Check if Shizuku is working
    python shizuku_setup.py test       # Run a test command
"""

import os
import subprocess
import shutil
from typing import Optional, Tuple

# Paths
TERMUX_BIN = "/data/data/com.termux/files/usr/bin"
SHARED_STORAGE = "/storage/emulated/0"
RISH_LOCATIONS = [
    f"{SHARED_STORAGE}/Download/rish",
    f"{SHARED_STORAGE}/rish",
    f"{SHARED_STORAGE}/Shizuku/rish",
    os.path.expanduser("~/storage/shared/Download/rish"),
    os.path.expanduser("~/storage/shared/rish"),
]


class ShizukuShell:
    """Execute commands using Shizuku's rish shell."""
    
    def __init__(self):
        self.rish_path = self._find_rish()
        self.available = self.rish_path is not None
        
    def _find_rish(self) -> Optional[str]:
        """Find the rish executable."""
        # Check if already in PATH
        try:
            result = subprocess.run(
                ["which", "rish"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        
        # Check Termux bin
        termux_rish = os.path.join(TERMUX_BIN, "rish")
        if os.path.exists(termux_rish):
            return termux_rish
        
        # Check common locations
        for path in RISH_LOCATIONS:
            if os.path.exists(path) and os.path.isfile(path):
                return path
        
        return None
    
    def check_shizuku_running(self) -> bool:
        """Check if Shizuku service is running."""
        if not self.available:
            return False
        
        try:
            result = subprocess.run(
                [self.rish_path, "-c", "echo test"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0 and "test" in result.stdout
        except Exception as e:
            print(f"Shizuku check failed: {e}")
            return False
    
    def run(self, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """
        Run a command via rish.
        
        Returns:
            (returncode, stdout, stderr)
        """
        if not self.available:
            raise RuntimeError("rish not available")
        
        try:
            result = subprocess.run(
                [self.rish_path, "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)
    
    def run_raw(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """
        Run a command via rish and return raw result.
        
        Returns:
            subprocess.CompletedProcess with stdout as bytes
        """
        if not self.available:
            raise RuntimeError("rish not available")
        
        return subprocess.run(
            [self.rish_path, "-c", command],
            capture_output=True,
            timeout=timeout
        )
    
    def screenshot(self, output_path: str = "/tmp/screen.png") -> Optional[str]:
        """Capture screenshot using Shizuku shell."""
        try:
            result = self.run_raw("screencap -p", timeout=10)
            if result.returncode == 0 and result.stdout:
                with open(output_path, 'wb') as f:
                    f.write(result.stdout)
                return output_path
            return None
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None
    
    def tap(self, x: int, y: int):
        """Tap at coordinates."""
        self.run(f"input tap {x} {y}")
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        """Swipe gesture."""
        self.run(f"input swipe {x1} {y1} {x2} {y2} {duration}")
    
    def text(self, text: str):
        """Input text."""
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        self.run(f"input text '{escaped}'")
    
    def keyevent(self, keycode: int):
        """Send keycode."""
        self.run(f"input keyevent {keycode}")
    
    def get_screen_size(self) -> Optional[Tuple[int, int]]:
        """Get screen resolution."""
        code, stdout, _ = self.run("wm size")
        if code == 0:
            import re
            match = re.search(r'(\d+)x(\d+)', stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None


def install_rish():
    """Install rish to Termux bin directory."""
    print("📦 Installing rish to Termux...")
    
    # Find rish file
    rish_source = None
    dex_source = None
    
    for base_path in RISH_LOCATIONS:
        if os.path.exists(base_path):
            rish_source = base_path
            dex_path = base_path.replace("rish", "rish_shizuku.dex")
            if os.path.exists(dex_path):
                dex_source = dex_path
            break
    
    if not rish_source:
        print("❌ rish file not found!")
        print("\nTo install:")
        print("1. Open Shizuku app")
        print("2. Go to 'Use Shizuku in terminal apps'")
        print("3. Tap 'Export files'")
        print("4. Save to Download folder")
        print("5. Run this script again")
        return False
    
    print(f"   Found: {rish_source}")
    
    # Copy to Termux bin
    dest_rish = os.path.join(TERMUX_BIN, "rish")
    try:
        shutil.copy2(rish_source, dest_rish)
        os.chmod(dest_rish, 0o755)
        print(f"   ✓ Copied to {dest_rish}")
    except Exception as e:
        print(f"   ❌ Failed to copy: {e}")
        return False
    
    if dex_source:
        dest_dex = os.path.join(TERMUX_BIN, "rish_shizuku.dex")
        try:
            shutil.copy2(dex_source, dest_dex)
            print(f"   ✓ Copied dex to {dest_dex}")
        except Exception as e:
            print(f"   ⚠️ Failed to copy dex: {e}")
    
    # Update package ID in rish script
    try:
        with open(dest_rish, 'r') as f:
            content = f.read()
        
        if 'RISH_APPLICATION_ID="PKG"' in content:
            content = content.replace(
                'RISH_APPLICATION_ID="PKG"',
                'RISH_APPLICATION_ID="com.termux"'
            )
            with open(dest_rish, 'w') as f:
                f.write(content)
            print("   ✓ Updated package ID")
    except Exception as e:
        print(f"   ⚠️ Could not update package ID: {e}")
    
    print("\n✅ rish installed successfully!")
    print("   Now you can use: rish -c 'your command'")
    return True


def check_status():
    """Check Shizuku status."""
    print("🔍 Checking Shizuku status...\n")
    
    shell = ShizukuShell()
    
    if not shell.available:
        print("❌ rish not found")
        print("\nTo install rish:")
        print("   python shizuku_setup.py install")
        return
    
    print(f"✓ rish found at: {shell.rish_path}")
    
    if shell.check_shizuku_running():
        print("✓ Shizuku service is running!")
        
        # Get some info
        size = shell.get_screen_size()
        if size:
            print(f"✓ Screen size: {size[0]}x{size[1]}")
    else:
        print("❌ Shizuku service not running")
        print("\nTo start Shizuku:")
        print("1. Open Shizuku app")
        print("2. Start via one of:")
        print("   - Wireless ADB (one-time setup)")
        print("   - Root")
        print("   - PC connection")


def run_test():
    """Run a test command."""
    print("🧪 Testing Shizuku...\n")
    
    shell = ShizukuShell()
    
    if not shell.available:
        print("❌ rish not available")
        return
    
    print("Running: echo 'Hello from Shizuku!'")
    code, stdout, stderr = shell.run("echo 'Hello from Shizuku!'")
    
    if code == 0:
        print(f"✓ Output: {stdout.strip()}")
        
        # Test screenshot
        print("\nTesting screenshot...")
        path = shell.screenshot("/tmp/shizuku_test.png")
        if path:
            print(f"✓ Screenshot saved to: {path}")
        else:
            print("❌ Screenshot failed")
    else:
        print(f"❌ Failed: {stderr}")


def main():
    import sys
    
    print("=" * 50)
    print("🔰 Shizuku Setup for pyGeminiScrcpy")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python shizuku_setup.py install   - Install rish to Termux")
        print("  python shizuku_setup.py check     - Check Shizuku status")
        print("  python shizuku_setup.py test      - Run test command")
        print("\nWhat is Shizuku?")
        print("  Shizuku lets you run ADB commands without:")
        print("  - WiFi debugging")
        print("  - PC connection (after initial setup)")
        print("  - Root (optional)")
        return
    
    command = sys.argv[1].lower()
    
    if command == "install":
        install_rish()
    elif command == "check":
        check_status()
    elif command == "test":
        run_test()
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
