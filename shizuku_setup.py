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
TERMUX_HOME = "/data/data/com.termux/files/home"

# All possible locations for rish files
RISH_LOCATIONS = [
    # Termux accessible paths (via termux-setup-storage)
    os.path.expanduser("~/storage/shared/Download/rish"),
    os.path.expanduser("~/storage/shared/rish"),
    os.path.expanduser("~/storage/downloads/rish"),
    # Android shared storage
    f"{SHARED_STORAGE}/Download/rish",
    f"{SHARED_STORAGE}/Downloads/rish",
    f"{SHARED_STORAGE}/rish",
    f"{SHARED_STORAGE}/Shizuku/rish",
    f"{SHARED_STORAGE}/Documents/rish",
    # Already installed
    f"{TERMUX_BIN}/rish",
    f"{TERMUX_HOME}/rish",
]


def find_rish_files():
    """Search for rish and rish_shizuku.dex files."""
    print("🔍 Searching for rish files...\n")
    
    found_rish = []
    found_dex = []
    
    # Check all known locations
    for path in RISH_LOCATIONS:
        if os.path.exists(path):
            found_rish.append(path)
            print(f"   ✓ Found rish: {path}")
        
        dex_path = path.replace("rish", "rish_shizuku.dex")
        if os.path.exists(dex_path):
            found_dex.append(dex_path)
            print(f"   ✓ Found dex: {dex_path}")
    
    # Also try to find using find command
    try:
        result = subprocess.run(
            ["find", SHARED_STORAGE, "-name", "rish", "-type", "f", "2>/dev/null"],
            capture_output=True, text=True, timeout=30, shell=False
        )
        for line in result.stdout.strip().split('\n'):
            if line and line not in found_rish:
                found_rish.append(line)
                print(f"   ✓ Found rish: {line}")
    except:
        pass
    
    if not found_rish:
        print("   ❌ No rish files found!")
        print("\n📋 To export files from Shizuku:")
        print("   1. Open Shizuku app")
        print("   2. Scroll down to '使用 Shizuku 的終端應用' / 'Use Shizuku in terminal apps'")
        print("   3. Tap '導出文件' / 'Export files'")
        print("   4. Save to 'Download' folder")
        print("\n📁 Expected file locations after export:")
        print(f"   • {SHARED_STORAGE}/Download/rish")
        print(f"   • {SHARED_STORAGE}/Download/rish_shizuku.dex")
        print("\n💡 Make sure Termux has storage access:")
        print("   termux-setup-storage")
    else:
        print(f"\n✅ Found {len(found_rish)} rish file(s)")
        if found_dex:
            print(f"✅ Found {len(found_dex)} dex file(s)")
    
    return found_rish, found_dex


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
    
    def screenshot(self, output_path: str = None) -> Optional[str]:
        """Capture screenshot using Shizuku shell."""
        # Use Termux home directory if no path specified
        if output_path is None:
            output_path = os.path.join(TERMUX_HOME, "screen.png")
        
        try:
            # Method 1: Direct stdout capture (preferred)
            result = self.run_raw("screencap -p", timeout=15)
            if result.returncode == 0 and result.stdout and len(result.stdout) > 100:
                with open(output_path, 'wb') as f:
                    f.write(result.stdout)
                return output_path
            
            # Method 2: Save to shared storage then copy
            temp_path = "/data/local/tmp/shizuku_screen.png"
            code, stdout, stderr = self.run(f"screencap -p {temp_path}", timeout=15)
            if code == 0:
                # Read the file back
                result = self.run_raw(f"cat {temp_path}", timeout=10)
                if result.returncode == 0 and result.stdout:
                    with open(output_path, 'wb') as f:
                        f.write(result.stdout)
                    # Clean up
                    self.run(f"rm {temp_path}")
                    return output_path
            
            # If we get here, something went wrong
            if result.stderr:
                print(f"Screenshot error: {result.stderr.decode() if isinstance(result.stderr, bytes) else result.stderr}")
            return None
            
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None
    
    def screenshot_bytes(self) -> Optional[bytes]:
        """Capture screenshot and return as bytes (for direct use)."""
        temp_path = "/data/local/tmp/shizuku_screen.png"
        
        try:
            # Method 1: File-based (more reliable for binary data)
            code, stdout, stderr = self.run(f"screencap -p {temp_path}", timeout=15)
            if code == 0:
                # Read the file using cat
                result = self.run_raw(f"cat {temp_path}", timeout=10)
                # Clean up
                self.run(f"rm {temp_path}")
                
                if result.returncode == 0 and result.stdout and len(result.stdout) > 1000:
                    # Validate PNG
                    if result.stdout[:8] == b'\x89PNG\r\n\x1a\n':
                        return result.stdout
                    else:
                        print(f"[Shizuku] File method got invalid PNG header")
            
            # Method 2: Direct stdout (fallback, may have binary issues)
            result = self.run_raw("screencap -p", timeout=15)
            if result.returncode == 0 and result.stdout and len(result.stdout) > 1000:
                if result.stdout[:8] == b'\x89PNG\r\n\x1a\n':
                    return result.stdout
                else:
                    print(f"[Shizuku] Direct stdout got invalid PNG header: {result.stdout[:8]}")
            
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
    print("📦 Installing rish to Termux...\n")
    
    # First, find the files
    found_rish, found_dex = find_rish_files()
    
    if not found_rish:
        return False
    
    # Use the first found rish
    rish_source = found_rish[0]
    dex_source = found_dex[0] if found_dex else None
    
    print(f"\n📁 Using: {rish_source}")
    
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
            print("   ✓ Updated package ID to com.termux")
    except Exception as e:
        print(f"   ⚠️ Could not update package ID: {e}")
    
    print("\n✅ rish installed successfully!")
    print("   Now you can use: rish -c 'your command'")
    print("\n🧪 Test with: python shizuku_setup.py check")
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
        print("   Run: python shizuku_setup.py install")
        return
    
    print(f"📍 rish path: {shell.rish_path}")
    
    # Test 1: Basic echo (multiple attempts)
    print("\n1️⃣ Testing basic echo command...")
    success_count = 0
    for i in range(3):
        code, stdout, stderr = shell.run("echo 'test'")
        # rish sometimes outputs to stderr instead of stdout
        output = stdout + stderr
        if code == 0 and "test" in output:
            success_count += 1
        else:
            print(f"   Attempt {i+1} failed: code={code}, output={output[:50]}")
    
    if success_count >= 2:
        print(f"   ✓ Echo test: {success_count}/3 passed")
    else:
        print(f"   ⚠️ Echo test: {success_count}/3 passed (unstable)")
    
    # Test 2: Get ID
    print("\n2️⃣ Testing shell identity...")
    code, stdout, stderr = shell.run("id")
    if code == 0:
        print(f"   ✓ ID: {stdout.strip()[:60]}...")
    else:
        print(f"   ❌ Failed: {stderr}")
    
    # Test 3: Screen size
    print("\n3️⃣ Testing screen size...")
    size = shell.get_screen_size()
    if size:
        print(f"   ✓ Screen: {size[0]}x{size[1]}")
    else:
        print("   ❌ Failed to get screen size")
    
    # Test 4: Screenshot (direct bytes)
    print("\n4️⃣ Testing screenshot (direct)...")
    png_bytes = shell.screenshot_bytes()
    if png_bytes and len(png_bytes) > 1000:
        print(f"   ✓ Got {len(png_bytes)} bytes")
        # Save to Termux home
        output_path = os.path.expanduser("~/shizuku_test.png")
        with open(output_path, 'wb') as f:
            f.write(png_bytes)
        print(f"   ✓ Saved to: {output_path}")
    else:
        print("   ❌ Direct screenshot failed, trying file method...")
        
        # Try file-based method
        temp_path = "/data/local/tmp/test_screen.png"
        code, stdout, stderr = shell.run(f"screencap -p {temp_path}")
        print(f"   File save result: code={code}, stderr={stderr}")
        
        if code == 0:
            # Try to read it back
            result = shell.run_raw(f"cat {temp_path}")
            if result.returncode == 0 and result.stdout:
                print(f"   ✓ Got {len(result.stdout)} bytes via file")
                output_path = os.path.expanduser("~/shizuku_test.png")
                with open(output_path, 'wb') as f:
                    f.write(result.stdout)
                print(f"   ✓ Saved to: {output_path}")
            else:
                print(f"   ❌ Can't read temp file")
        else:
            print("   ❌ Screenshot permission denied")
            print("\n💡 This might be a Shizuku permission issue.")
            print("   Try restarting Shizuku service in the app.")
    
    print("\n" + "=" * 50)
    if success_count >= 2:
        print("✅ Shizuku is working! Use: python agent.py --shizuku --streaming")
    else:
        print("⚠️ Shizuku has issues. Check the errors above.")


def main():
    import sys
    
    print("=" * 50)
    print("🔰 Shizuku Setup for pyGeminiScrcpy")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python shizuku_setup.py find      - Search for rish files")
        print("  python shizuku_setup.py install   - Install rish to Termux")
        print("  python shizuku_setup.py check     - Check Shizuku status")
        print("  python shizuku_setup.py test      - Run test command")
        print("\n📁 Where to put rish files:")
        print(f"   Export from Shizuku app to: {SHARED_STORAGE}/Download/")
        print("   Files needed:")
        print("   • rish")
        print("   • rish_shizuku.dex")
        print("\n💡 First time setup:")
        print("   1. termux-setup-storage    # Grant storage access")
        print("   2. Export files from Shizuku app")
        print("   3. python shizuku_setup.py install")
        print("   4. python shizuku_setup.py check")
        return
    
    command = sys.argv[1].lower()
    
    if command == "find":
        find_rish_files()
    elif command == "install":
        install_rish()
    elif command == "check":
        check_status()
    elif command == "test":
        run_test()
    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
