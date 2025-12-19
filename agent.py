import os
import time
import argparse
import threading
import subprocess
import traceback
from typing import Optional, Dict, Any, List

# Termux detection - set before importing OpenCV
IS_TERMUX = os.path.exists("/data/data/com.termux")

# Shizuku shell (optional - for running without WiFi ADB)
SHIZUKU_SHELL = None
try:
    from shizuku_setup import ShizukuShell
    _shizuku = ShizukuShell()
    if _shizuku.available and _shizuku.check_shizuku_running():
        SHIZUKU_SHELL = _shizuku
        print("🔰 Shizuku mode available!")
except ImportError:
    pass
except Exception as e:
    print(f"⚠️ Shizuku check failed: {e}")

# Try to import OpenCV (optional for Termux)
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    # Provide fallback numpy
    try:
        import numpy as np
    except ImportError:
        np = None

from google import genai
from google.genai import types
from google.genai.types import Content, Part

# Fix for OpenCV/Qt interaction on some Linux systems (prevents QObject::moveToThread errors)
if not IS_TERMUX:
    os.environ["QT_QPA_PLATFORM"] = "xcb"

# --- Configuration ---
DEFAULT_MODEL = "gemini-3-flash-preview"

# System prompt for Android control
SYSTEM_PROMPT = """You are an AI agent operating an Android device.
Target Device Screen: {width}x{height} (Pixel coordinates)
Installed Apps (3rd party):
{app_list}

Your goal is to complete the user's request by interacting with the screen.

available tools:
- click_at(x, y): Click at normalized coordinates (0-1000). (0,0) is top-left, (1000,1000) is bottom-right.
- type(text, press_enter): Type text. Use this for all text input. Set press_enter=True to submit.
- scroll(x, y, direction): Scroll in a direction ('up', 'down', 'left', 'right') starting from (x,y).
- wait(seconds): Wait for a specific amount of time.
- long_press_at(x, y): Long press at normalized coordinates.
- go_home(): Press the Home button.
- go_back(): Press the Back button.
- open_app(app_name): Open an app by name.
- launch_package(package_name): Launch an app directly by its package name (e.g., 'com.google.android.apps.maps' for Google Maps). More reliable than open_app.

CRITICAL RULES TO PREVENT HALLUCINATIONS:
1. Coordinates are NORMALIZED (0-1000). You MUST map your desired screen location to this range.
2. ALWAYS describe what you SEE in the current screenshot BEFORE taking any action.
3. NEVER assume UI elements exist if you cannot see them in the screenshot.
4. NEVER click on coordinates where you cannot verify a button/element exists.
5. If you don't see what you expect, STOP and SCROLL to find it, or report that you cannot proceed.
6. If text is cut off, assume there is more content and scroll to reveal it.
7. DO NOT make up app names, button locations, or UI elements that are not visible.
8. If the user asks to "open X", try `open_app("X")` first. If that fails or if you need to navigate within an app, use clicks ONLY on visible elements.
9. To search, find the search bar IN THE SCREENSHOT and click it, then type. Do not assume where it is.
10. When the task is successfully completed, output ONLY "TASK_FINISHED".
11. If you are stuck and cannot proceed, output "ERROR_STUCK" with a brief explanation.

WORKFLOW FOR EVERY ACTION:
Step 1: Describe what you see in the current screenshot
Step 2: Plan your next action based ONLY on what is visible
Step 3: Execute the action using available tools
Step 4: Verify the result in the next screenshot
"""

def get_tool_definitions():
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="click_at",
                    description="Click at specific coordinates on the screen.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "x": types.Schema(type=types.Type.INTEGER, description="X coordinate (0-1000)"),
                            "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate (0-1000)"),
                        },
                        required=["x", "y"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="type",
                    description="Type text into the focused field.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "text": types.Schema(type=types.Type.STRING, description="The text to type"),
                            "press_enter": types.Schema(type=types.Type.BOOLEAN, description="Whether to press enter after typing"),
                        },
                        required=["text"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="scroll",
                    description="Scroll the screen in a specific direction.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "x": types.Schema(type=types.Type.INTEGER, description="X coordinate to start scroll (0-1000)"),
                            "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate to start scroll (0-1000)"),
                            "direction": types.Schema(type=types.Type.STRING, description="Direction to scroll (up, down, left, right)"),
                        },
                        required=["direction"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="wait",
                    description="Wait for a specified number of seconds.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "seconds": types.Schema(type=types.Type.INTEGER, description="Number of seconds to wait"),
                        },
                        required=["seconds"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="long_press_at",
                    description="Long press at specific coordinates.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "x": types.Schema(type=types.Type.INTEGER, description="X coordinate (0-1000)"),
                            "y": types.Schema(type=types.Type.INTEGER, description="Y coordinate (0-1000)"),
                        },
                        required=["x", "y"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="go_home",
                    description="Press the Android Home button.",
                ),
                types.FunctionDeclaration(
                    name="go_back",
                    description="Press the Android Back button.",
                ),
                types.FunctionDeclaration(
                    name="open_app",
                    description="Open an app by its name.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "app_name": types.Schema(type=types.Type.STRING, description="Name of the app to open"),
                        },
                        required=["app_name"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="launch_package",
                    description="Launch an app directly using its package name. More reliable than open_app. Examples: com.google.android.apps.maps for Google Maps, com.android.chrome for Chrome.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "package_name": types.Schema(type=types.Type.STRING, description="Android package name (e.g., com.google.android.apps.maps)"),
                        },
                        required=["package_name"],
                    ),
                ),
            ]
        )
    ]

class GeminiAgent:
    def __init__(self, api_key, model_name=DEFAULT_MODEL, use_adb_fallback=False):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.use_adb_fallback = use_adb_fallback
        self.debug_mode = False  # Changed via setter or directly if needed
        
        self.scrcpy_client = None
        self.last_frame = None
        self.frame_lock = threading.Lock()
        self.width = 1080  # Default, will update
        self.height = 2400 # Default, will update
        
        # Cache real device screen size (for ADB input coordinates)
        self.real_width = None
        self.real_height = None
        
        # Conversation history for multi-turn
        self.contents: List[Content] = []
        
        # Manual intervention: skip to next turn with optional hint
        self.skip_to_next_turn = False
        self.user_hint = ""  # Optional user message when skipping
        self.skip_lock = threading.Lock()

        # Debug Threading
        self.debug_thread = None
        self.debug_running = False
        self.overlay_data = None
        self.overlay_expire_time = 0
        self.debug_status_text = ""
        self.debug_status_expire_time = 0
        
        # Cache installed packages
        self.app_list = self._get_installed_packages()
        
        # State to coordinate input between main loop and listener thread
        self.is_processing = False
        
        # Termux notification support
        self.notifications_enabled = False
        self.notification_id = "gemini_agent"
        self.current_turn = 0
        self._check_termux_notification()
        
        # Shizuku shell support (for running without WiFi ADB)
        self.shizuku_shell = SHIZUKU_SHELL
        self.use_shizuku = SHIZUKU_SHELL is not None
    
    def _check_termux_notification(self):
        """Check if termux-notification is available."""
        if not IS_TERMUX:
            return
        
        # Try multiple methods to find termux-notification
        termux_bin_paths = [
            "/data/data/com.termux/files/usr/bin/termux-notification",
            os.path.expanduser("~/../usr/bin/termux-notification"),
        ]
        
        # Method 1: Check known paths
        for path in termux_bin_paths:
            if os.path.exists(path):
                self.notifications_enabled = True
                print(f"🔔 Termux notifications enabled (found at {path})")
                # Test notification
                self._test_notification()
                return
        
        # Method 2: Try which command
        try:
            result = subprocess.run(
                ["which", "termux-notification"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                self.notifications_enabled = True
                print(f"🔔 Termux notifications enabled (via which: {result.stdout.strip()})")
                self._test_notification()
                return
        except Exception as e:
            print(f"⚠️ which command failed: {e}")
        
        # Method 3: Try running it directly
        try:
            result = subprocess.run(
                ["termux-notification", "--help"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                self.notifications_enabled = True
                print("🔔 Termux notifications enabled (direct test)")
                self._test_notification()
                return
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ Direct test failed: {e}")
        
        print("💡 Notifications not available. Install with:")
        print("   pkg install termux-api")
        print("   Also install Termux:API app from F-Droid")
    
    def _test_notification(self):
        """Send a test notification to verify it works."""
        try:
            cmd = [
                "termux-notification",
                "--id", "gemini_test",
                "--title", "🤖 Gemini Agent",
                "--content", "Notifications working!",
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0:
                print("   ✓ Test notification sent!")
                # Remove test notification after 2 seconds
                time.sleep(1)
                subprocess.run(["termux-notification-remove", "gemini_test"], capture_output=True, timeout=5)
            else:
                print(f"   ⚠️ Test notification failed: {result.stderr.decode() if result.stderr else 'unknown error'}")
                self.notifications_enabled = False
        except Exception as e:
            print(f"   ⚠️ Test notification error: {e}")
            self.notifications_enabled = False
    
    def send_notification(self, title: str, content: str, action_type: str = "info"):
        """Send a Termux notification."""
        if not self.notifications_enabled:
            return
        
        try:
            # Icon based on action type
            icons = {
                "click": "👆",
                "type": "⌨️",
                "scroll": "📜",
                "home": "🏠",
                "back": "◀️",
                "launch": "🚀",
                "thinking": "💭",
                "done": "✅",
                "error": "❌",
                "info": "ℹ️",
            }
            icon = icons.get(action_type, "🤖")
            
            # Send toast (brief popup) - always try
            toast_msg = f"{icon} {content}"
            self.send_toast(toast_msg)
            
            # Send persistent notification
            if not self.notifications_enabled:
                return
                
            cmd = [
                "termux-notification",
                "--id", self.notification_id,
                "--title", f"{icon} {title}",
                "--content", content,
                "--ongoing",  # Keep notification visible
                "--alert-once",  # Don't make sound every update
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode != 0:
                # Log error once, then disable notifications
                print(f"⚠️ Notification failed, disabling: {result.stderr.decode() if result.stderr else ''}")
                self.notifications_enabled = False
        except Exception as e:
            print(f"⚠️ Notification error: {e}")
            self.notifications_enabled = False
    
    def clear_notification(self):
        """Clear the ongoing notification."""
        if not self.notifications_enabled:
            return
        try:
            subprocess.run(
                ["termux-notification-remove", self.notification_id],
                capture_output=True,
                timeout=5
            )
        except:
            pass
    
    def send_toast(self, message: str, short: bool = True):
        """Send a toast message (brief popup)."""
        if not IS_TERMUX:
            return
        
        try:
            cmd = [
                "termux-toast",
                "-g", "top",  # Position at top
                "-b", "black",  # Background color
                "-c", "white",  # Text color
            ]
            if short:
                cmd.extend(["-s"])  # Short duration
            cmd.append(message)
            
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass  # termux-toast not available
        except:
            pass

    def _get_installed_packages(self) -> List[str]:
        """Get list of installed 3rd party packages via ADB."""
        try:
            # Build ADB command with optional device serial
            cmd = ["adb"]
            if hasattr(self, 'device_serial') and self.device_serial:
                cmd.extend(["-s", self.device_serial])
            cmd.extend(["shell", "pm", "list", "packages", "-3"])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
                # Don't check=True here to avoid crashing if adb fails (e.g. device not connected yet)
            )
            if result.returncode != 0:
                print(f"Warning: Failed to get app list (code {result.returncode})")
                return []
                
            packages = []
            for line in result.stdout.strip().split('\n'):
                if line.startswith('package:'):
                    pkg = line.replace('package:', '').strip()
                    packages.append(pkg)
            packages.sort()
            return packages
        except Exception as e:
            print(f"Failed to get package list: {e}")
            return []


    def get_config(self) -> types.GenerateContentConfig:
        """Build configuration with generic tools for Android."""
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(
                width=self.width, 
                height=self.height,
                app_list=", ".join(self.app_list) if self.app_list else "Unknown (ADB failed)"
            ),
            tools=get_tool_definitions(),
            # 思考配置：medium 模式平衡思考深度與速度
            # thinking_budget: 0=關閉, -1=動態, 1-24576=固定預算
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=8192,  # medium: 適合需要座標精確的任務
            ),
            # 降低溫度以減少幻覺，提高準確性
            temperature=0.0,  # 0.0 = 最確定性，1.0+ = 更有創意但可能幻覺
            top_p=0.95,       # Nucleus sampling: 只考慮累積機率95%的 tokens
            top_k=40,         # 只從前40個最可能的 tokens 中選擇
        )

    def set_scrcpy_client(self, client):
        self.scrcpy_client = client

    def update_frame(self, frame):
        with self.frame_lock:
            self.last_frame = frame
            if self.width == 0:
                self.height, self.width, _ = frame.shape
    
    def check_and_reset_skip(self) -> tuple:
        """Check if user wants to skip to next turn, and reset the flag.
        Returns (should_skip, user_hint)"""
        with self.skip_lock:
            if self.skip_to_next_turn:
                self.skip_to_next_turn = False
                hint = self.user_hint
                self.user_hint = ""
                return True, hint
            return False, ""
    
    def request_skip_with_hint(self, hint: str = ""):
        """Request to skip current turn with an optional hint message."""
        with self.skip_lock:
            self.skip_to_next_turn = True
            self.user_hint = hint
            if hint:
                print(f"\n💬 User hint received: {hint}")
            print("⏭️  Skip signal - moving to next turn...\n")


    def get_adb_screenshot(self):
        """Capture screenshot directly via ADB or Shizuku (Slower but reliable)"""
        # Try Shizuku first if available
        if self.use_shizuku and self.shizuku_shell:
            try:
                result = self.shizuku_shell.run_raw("screencap -p", timeout=10)
                if result.returncode == 0 and result.stdout:
                    if HAS_CV2:
                        image_data = np.frombuffer(result.stdout, np.uint8)
                        frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                        return frame
                    else:
                        return result.stdout
            except Exception as e:
                print(f"Shizuku screenshot (direct) failed: {e}")
            
            # Try screenshot_bytes method as fallback
            try:
                png_bytes = self.shizuku_shell.screenshot_bytes()
                if png_bytes and len(png_bytes) > 100:
                    if HAS_CV2:
                        image_data = np.frombuffer(png_bytes, np.uint8)
                        frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                        return frame
                    else:
                        return png_bytes
            except Exception as e:
                print(f"Shizuku screenshot (bytes) failed: {e}, trying ADB...")
        
        # Fall back to ADB
        try:
            cmd = ["adb"]
            if hasattr(self, 'device_serial') and self.device_serial:
                cmd.extend(["-s", self.device_serial])
            cmd.extend(["exec-out", "screencap", "-p"])
            
            result = subprocess.run(cmd, capture_output=True, check=True, timeout=10)
            
            if HAS_CV2:
                image_data = np.frombuffer(result.stdout, np.uint8)
                frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                return frame
            else:
                # Termux mode without OpenCV - return raw PNG bytes
                return result.stdout
        except subprocess.TimeoutExpired:
            print("ADB Screenshot timeout")
            return None
        except Exception as e:
            print(f"ADB Screenshot failed: {e}")
            return None

    def get_adb_screenshot_bytes(self) -> bytes:
        """Capture screenshot via ADB/Shizuku and return as PNG bytes (for Termux mode)."""
        # Try Shizuku first if available
        if self.use_shizuku and self.shizuku_shell:
            # Try screenshot_bytes method (has better fallback)
            try:
                png_bytes = self.shizuku_shell.screenshot_bytes()
                if png_bytes and len(png_bytes) > 1000:
                    return png_bytes
            except Exception as e:
                print(f"Shizuku screenshot_bytes failed: {e}")
            
            # Try direct screencap as fallback
            try:
                result = self.shizuku_shell.run_raw("screencap -p", timeout=15)
                if result.returncode == 0 and result.stdout and len(result.stdout) > 1000:
                    return result.stdout
            except Exception as e:
                print(f"Shizuku screencap failed: {e}, trying ADB...")
        
        # Fall back to ADB
        try:
            cmd = ["adb"]
            if hasattr(self, 'device_serial') and self.device_serial:
                cmd.extend(["-s", self.device_serial])
            cmd.extend(["exec-out", "screencap", "-p"])
            
            result = subprocess.run(cmd, capture_output=True, check=True, timeout=10)
            return result.stdout
        except Exception as e:
            print(f"ADB Screenshot failed: {e}")
            return None
    
    def _validate_png(self, data: bytes) -> bool:
        """Check if data is a valid PNG."""
        if not data or len(data) < 100:
            return False
        # PNG signature: 89 50 4E 47 0D 0A 1A 0A
        png_sig = b'\x89PNG\r\n\x1a\n'
        return data[:8] == png_sig

    def _get_screenshot_bytes(self) -> bytes:
        """Capture current screen and return as PNG bytes."""
        # Termux mode without OpenCV - get raw PNG bytes
        if self.use_adb_fallback and not HAS_CV2:
            # Try up to 3 times
            for attempt in range(3):
                png_bytes = self.get_adb_screenshot_bytes()
                
                if png_bytes and self._validate_png(png_bytes) and len(png_bytes) > 1000:
                    # Try to get dimensions from PNG header (width/height at bytes 16-24)
                    if len(png_bytes) > 24:
                        import struct
                        # PNG IHDR chunk contains width (4 bytes) and height (4 bytes) at offset 16
                        try:
                            self.width = struct.unpack('>I', png_bytes[16:20])[0]
                            self.height = struct.unpack('>I', png_bytes[20:24])[0]
                        except:
                            pass  # Keep default dimensions
                    
                    return png_bytes
                
                # Screenshot failed or corrupted, retry
                if attempt < 2:
                    print(f"Screenshot attempt {attempt + 1} failed, retrying...")
                    time.sleep(0.5)
            
            raise RuntimeError("No screen frame available after 3 attempts")
        
        # Normal mode with OpenCV
        frame = None
        
        if self.use_adb_fallback:
            frame = self.get_adb_screenshot()
        else:
            with self.frame_lock:
                if self.last_frame is not None:
                    frame = self.last_frame.copy()
        
        if frame is None:
            raise RuntimeError("No screen frame available")
        
        # Update dimensions
        self.height, self.width = frame.shape[:2]
        
        # Convert to PNG bytes
        _, buffer = cv2.imencode('.png', frame)
        return buffer.tobytes()

    def _get_real_screen_size(self):
        """Get real device screen size via ADB (cached)."""
        if self.real_width and self.real_height:
            return self.real_width, self.real_height
        try:
            cmd = ["adb"]
            if hasattr(self, 'device_serial') and self.device_serial:
                cmd.extend(["-s", self.device_serial])
            cmd.extend(["shell", "wm", "size"])
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            # Parse "Physical size: 1220x2712"
            for line in result.stdout.strip().split('\n'):
                if 'Physical size' in line:
                    size_str = line.split(':')[1].strip()
                    w, h = map(int, size_str.split('x'))
                    self.real_width, self.real_height = w, h
                    print(f"Detected real device screen size: {w}x{h}")
                    return w, h
        except Exception as e:
            print(f"Failed to get screen size: {e}")
        return None, None

    def denormalize_x_for_adb(self, x: float) -> int:
        """Convert normalized x (0-999) to real device pixel coordinate (for ADB)."""
        real_w, _ = self._get_real_screen_size()
        if real_w:
            return int((x / 1000.0) * real_w)
        return int((x / 1000.0) * self.width)

    def denormalize_y_for_adb(self, y: float) -> int:
        """Convert normalized y (0-999) to real device pixel coordinate (for ADB)."""
        _, real_h = self._get_real_screen_size()
        if real_h:
            return int((y / 1000.0) * real_h)
        return int((y / 1000.0) * self.height)

    def denormalize_x_for_scrcpy(self, x: float) -> int:
        """Convert normalized x (0-999) to scrcpy stream coordinate."""
        # scrcpy handles coordinate mapping internally, use stream resolution
        return int((x / 1000.0) * self.width)

    def denormalize_y_for_scrcpy(self, y: float) -> int:
        """Convert normalized y (0-999) to scrcpy stream coordinate."""
        return int((y / 1000.0) * self.height)

    # --- ADB Action Executors ---
    def _adb_shell(self, cmd_args):
        """Run shell command via Shizuku or ADB."""
        # Try Shizuku first if available
        if self.use_shizuku and self.shizuku_shell:
            try:
                command = " ".join(cmd_args)
                code, stdout, stderr = self.shizuku_shell.run(command, timeout=10)
                if code != 0 and stderr:
                    print(f"Shizuku command warning: {stderr}")
                return
            except Exception as e:
                print(f"Shizuku failed: {e}, trying ADB...")
        
        # Fall back to ADB
        cmd = ["adb"]
        if hasattr(self, 'device_serial') and self.device_serial:
            cmd.extend(["-s", self.device_serial])
        cmd.extend(["shell"] + cmd_args)
        subprocess.run(cmd)

    def _execute_click_at(self, x: int, y: int):
        """Execute click at given coordinates."""
        real_w, real_h = self._get_real_screen_size()
        
        if self.use_adb_fallback:
            # ADB mode: use real device coordinates
            actual_x = self.denormalize_x_for_adb(x)
            actual_y = self.denormalize_y_for_adb(y)
            print(f"ACTION: Click at ({actual_x}, {actual_y}) [normalized: {x}, {y}] [ADB mode, real: {real_w}x{real_h}]")
            self._adb_shell(["input", "tap", str(actual_x), str(actual_y)])
        elif self.scrcpy_client:
            # Scrcpy mode: use scrcpy stream coordinates (works better for Unity games)
            actual_x = self.denormalize_x_for_scrcpy(x)
            actual_y = self.denormalize_y_for_scrcpy(y)
            print(f"ACTION: Click at ({actual_x}, {actual_y}) [normalized: {x}, {y}] [scrcpy mode, stream: {self.width}x{self.height}]")
            from scrcpy_client import ACTION_DOWN, ACTION_UP
            self.scrcpy_client.control.touch(actual_x, actual_y, ACTION_DOWN)
            time.sleep(0.01)  # Very brief delay between DOWN and UP
            self.scrcpy_client.control.touch(actual_x, actual_y, ACTION_UP)
        else:
            # Fallback to ADB
            actual_x = self.denormalize_x_for_adb(x)
            actual_y = self.denormalize_y_for_adb(y)
            print(f"ACTION: Click at ({actual_x}, {actual_y}) [normalized: {x}, {y}] [fallback ADB]")
            self._adb_shell(["input", "tap", str(actual_x), str(actual_y)])
        
        if self.debug_mode:
            self._visualize_action(actual_x, actual_y, action="click")

        return {"status": "clicked", "x": actual_x, "y": actual_y, "url": "android://device"}

    def _execute_type_text(self, text: str, press_enter: bool = False):
        """Execute typing text."""
        print(f"ACTION: Type '{text}' (enter={press_enter})")
        
        # Check if text contains non-ASCII (e.g., Chinese)
        is_unicode = any(ord(c) > 127 for c in text)
        
        if self.scrcpy_client:
            try:
                if is_unicode:
                    # Use clipboard method for unicode text (Chinese, etc.)
                    print(f"  Using clipboard method for unicode text")
                    self.scrcpy_client.control.set_clipboard(text, paste=True)
                else:
                    # Use direct inject for ASCII
                    self.scrcpy_client.control.text(text)
                time.sleep(0.3)
            except Exception as e:
                print(f"Scrcpy text failed: {e}, trying ADB")
                escaped_text = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
                self._adb_shell(["input", "text", escaped_text])
        else:
            # ADB fallback (only works for ASCII)
            escaped_text = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
            self._adb_shell(["input", "text", escaped_text])
        
        if press_enter:
            time.sleep(0.1)
            if self.scrcpy_client:
                from scrcpy_client import KEYCODE_ENTER, KEYEVENT_ACTION_DOWN, KEYEVENT_ACTION_UP
                self.scrcpy_client.control.keycode(KEYCODE_ENTER, KEYEVENT_ACTION_DOWN)
                time.sleep(0.05)
                self.scrcpy_client.control.keycode(KEYCODE_ENTER, KEYEVENT_ACTION_UP)
            else:
                self._adb_shell(["input", "keyevent", "KEYCODE_ENTER"])
        
        if self.debug_mode:
             # For text, we might just show an overlay at center or top
             self._visualize_action(self.width//2, self.height//2, action="type", text=text)

        return {"status": "typed", "text": text, "url": "android://device"}

    def _execute_scroll(self, x: int, y: int, direction: str):
        """Execute scroll action."""
        if self.use_adb_fallback or not self.scrcpy_client:
            actual_x = self.denormalize_x_for_adb(x)
            actual_y = self.denormalize_y_for_adb(y)
            print(f"ACTION: Scroll {direction} at ({actual_x}, {actual_y}) [ADB mode]")
            
            distance = 500  # pixels to scroll
            if direction == "down":
                end_y = actual_y + distance
            elif direction == "up":
                end_y = actual_y - distance
            elif direction == "left":
                self._adb_shell(["input", "swipe", str(actual_x), str(actual_y), str(actual_x + distance), str(actual_y), "300"])
                return {"status": "scrolled", "direction": direction, "url": "android://device"}
            else:  # right
                self._adb_shell(["input", "swipe", str(actual_x), str(actual_y), str(actual_x - distance), str(actual_y), "300"])
                return {"status": "scrolled", "direction": direction, "url": "android://device"}
            self._adb_shell(["input", "swipe", str(actual_x), str(actual_y), str(actual_x), str(end_y), "300"])
        else:
            # scrcpy mode - use stream coordinates
            actual_x = self.denormalize_x_for_scrcpy(x)
            actual_y = self.denormalize_y_for_scrcpy(y)
            print(f"ACTION: Scroll {direction} at ({actual_x}, {actual_y}) [scrcpy mode]")
            
            distance = int(self.height * 0.4) # Scroll 40% of screen height
            if distance == 0: distance = 300

            start_x, start_y = actual_x, actual_y
            end_x, end_y = actual_x, actual_y

            if direction == "down":
                end_y = actual_y + distance
            elif direction == "up":
                end_y = actual_y - distance
            elif direction == "left":
                end_x = actual_x - distance
            else:  # right
                end_x = actual_x + distance
            
            # Helper for swipe
            self._scrcpy_swipe_gesture(start_x, start_y, end_x, end_y)
        
        if self.debug_mode:
            # Visualize scroll as an arrow
             self._visualize_action(actual_x, actual_y, action="scroll", end_x=end_x, end_y=end_y)

        return {"status": "scrolled", "direction": direction, "url": "android://device"}

    def _scrcpy_swipe_gesture(self, start_x, start_y, end_x, end_y, steps=10, duration=0.3):
        """Perform a smooth swipe gesture using scrcpy touch events."""
        from scrcpy_client import ACTION_DOWN, ACTION_UP, ACTION_MOVE
        
        if not self.scrcpy_client:
            return

        # Send DOWN
        self.scrcpy_client.control.touch(start_x, start_y, ACTION_DOWN)
        time.sleep(0.01)

        # Send MOVE steps
        for i in range(steps):
            t = (i + 1) / steps
            x = int(start_x + (end_x - start_x) * t)
            y = int(start_y + (end_y - start_y) * t)
            self.scrcpy_client.control.touch(x, y, ACTION_MOVE)
            time.sleep(duration / steps)
        
        # Send UP
        self.scrcpy_client.control.touch(end_x, end_y, ACTION_UP)

    def _execute_long_press(self, x: int, y: int):
        """Execute long press at coordinates."""
        if self.use_adb_fallback or not self.scrcpy_client:
            actual_x = self.denormalize_x_for_adb(x)
            actual_y = self.denormalize_y_for_adb(y)
            print(f"ACTION: Long press at ({actual_x}, {actual_y}) [ADB mode]")
            self._adb_shell(["input", "swipe", str(actual_x), str(actual_y), str(actual_x), str(actual_y), "1000"])
        else:
            actual_x = self.denormalize_x_for_scrcpy(x)
            actual_y = self.denormalize_y_for_scrcpy(y)
            print(f"ACTION: Long press at ({actual_x}, {actual_y}) [scrcpy mode]")
            from scrcpy_client import ACTION_DOWN, ACTION_UP
            self.scrcpy_client.control.touch(actual_x, actual_y, ACTION_DOWN)
            time.sleep(1.0)
            self.scrcpy_client.control.touch(actual_x, actual_y, ACTION_UP)
        
        if self.debug_mode:
             self._visualize_action(actual_x, actual_y, action="long_press")

        return {"status": "long_pressed", "x": actual_x, "y": actual_y, "url": "android://device"}

    def _execute_go_home(self):
        """Press home button."""
        print("ACTION: Home")
        if self.use_adb_fallback:
            self._adb_shell(["input", "keyevent", "KEYCODE_HOME"])
        elif self.scrcpy_client:
            from scrcpy_client import KEYCODE_HOME, KEYEVENT_ACTION_DOWN, KEYEVENT_ACTION_UP
            self.scrcpy_client.control.keycode(KEYCODE_HOME, KEYEVENT_ACTION_DOWN)
            self.scrcpy_client.control.keycode(KEYCODE_HOME, KEYEVENT_ACTION_UP)
        return {"status": "home_pressed", "url": "android://device"}

    def _execute_go_back(self):
        """Press back button."""
        print("ACTION: Back")
        if self.use_adb_fallback:
            self._adb_shell(["input", "keyevent", "KEYCODE_BACK"])
        elif self.scrcpy_client:
            from scrcpy_client import KEYCODE_BACK, KEYEVENT_ACTION_DOWN, KEYEVENT_ACTION_UP
            self.scrcpy_client.control.keycode(KEYCODE_BACK, KEYEVENT_ACTION_DOWN)
            self.scrcpy_client.control.keycode(KEYCODE_BACK, KEYEVENT_ACTION_UP)
        return {"status": "back_pressed", "url": "android://device"}

    def _execute_open_app(self, app_name: str, intent: Optional[str] = None):
        """Open an app by name using am start."""
        print(f"ACTION: Open app '{app_name}'")
        # Try to open via monkey (best effort for app name)
        self._adb_shell(["monkey", "-p", app_name, "-c", "android.intent.category.LAUNCHER", "1"])
        return {"status": "app_opened", "app_name": app_name, "url": "android://device"}

    def _execute_launch_package(self, package_name: str):
        """Launch an app directly by package name using am start."""
        print(f"ACTION: Launch package '{package_name}'")
        
        # Method 1: Use monkey (most reliable for launcher apps)
        try:
            cmd = ["adb"]
            if hasattr(self, 'device_serial') and self.device_serial:
                cmd.extend(["-s", self.device_serial])
            cmd.extend(["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and "Events injected: 1" in result.stdout:
                print(f"  ✓ Successfully launched via monkey")
                return {"status": "package_launched", "package_name": package_name, "url": "android://device"}
        except Exception as e:
            print(f"  Monkey method failed: {e}")
        
        # Method 2: Use am start with MAIN/LAUNCHER intent (doesn't require activity name)
        try:
            self._adb_shell([
                "am", "start",
                "-a", "android.intent.action.MAIN",
                "-c", "android.intent.category.LAUNCHER",
                "-n", package_name
            ])
            print(f"  ✓ Launched via am start MAIN/LAUNCHER")
        except Exception as e:
            print(f"  am start method failed: {e}")
        
        return {"status": "package_launched", "package_name": package_name, "url": "android://device"}

    def _execute_open_browser(self):
        """Open Google App search screen (like tapping search bar on home screen)."""
        print("ACTION: Open Google App search")
        # Launch Google App's search activity directly
        self._adb_shell([
            "am", "start", "-a", "android.intent.action.WEB_SEARCH"
        ])
        time.sleep(1)
        return {"status": "browser_opened", "url": "google://search"}

    def _execute_navigate(self, url: str):
        """Navigate to a URL in browser."""
        print(f"ACTION: Navigate to {url}")
        self._adb_shell([
            "am", "start", "-a", "android.intent.action.VIEW",
            "-d", url
        ])
        time.sleep(1)
        return {"status": "navigated", "url": url}

    def execute_function_call(self, function_call) -> Dict[str, Any]:
        """Execute a single function call and return the result."""
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        
        print(f"Function call: {name}({args})")
        
        # Send notification for this action
        action_type = "info"
        notification_content = ""
        
        # Handle predefined Computer Use actions
        if name == "open_web_browser":
            action_type = "launch"
            notification_content = "Opening web browser"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_open_browser()
        elif name == "click_at":
            x, y = args.get("x", 0), args.get("y", 0)
            action_type = "click"
            notification_content = f"Clicking at ({x}, {y})"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_click_at(x, y)
        elif name == "type_text_at":
            # First click, then type
            if "x" in args and "y" in args:
                self._execute_click_at(args["x"], args["y"])
                time.sleep(0.3)
            action_type = "type"
            text = args.get("text", "")
            notification_content = f"Typing: {text[:30]}..." if len(text) > 30 else f"Typing: {text}"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_type_text(text, args.get("press_enter", False))
        elif name == "type":
            action_type = "type"
            text = args.get("text", "")
            notification_content = f"Typing: {text[:30]}..." if len(text) > 30 else f"Typing: {text}"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_type_text(text, args.get("press_enter", False))
        elif name == "scroll" or name == "scroll_at" or name == "scroll_document":
            direction = args.get("direction", "down")
            action_type = "scroll"
            notification_content = f"Scrolling {direction}"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_scroll(args.get("x", 500), args.get("y", 500), direction)
        elif name == "navigate":
            action_type = "launch"
            url = args.get("url", "https://www.google.com")
            notification_content = f"Navigating to {url[:30]}..."
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_navigate(url)
        elif name == "search":
            action_type = "launch"
            notification_content = "Opening search"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_open_browser()
        elif name == "wait":
            delay = args.get("seconds", 1)
            print(f"ACTION: Wait {delay}s")
            notification_content = f"Waiting {delay} seconds..."
            self.send_notification(f"Turn {self.current_turn}", notification_content, "info")
            time.sleep(delay)
            return {"status": "waited", "seconds": delay, "url": "android://device"}
        elif name.startswith("wait_") and name.endswith("_seconds"):
            # Handle model-invented functions like wait_5_seconds
            try:
                delay = int(name.split("_")[1])
            except (IndexError, ValueError):
                delay = 3
            print(f"ACTION: Wait {delay}s (from {name})")
            notification_content = f"Waiting {delay} seconds..."
            self.send_notification(f"Turn {self.current_turn}", notification_content, "info")
            time.sleep(delay)
            return {"status": "waited", "seconds": delay, "url": "android://device"}
        # Handle custom functions
        elif name == "long_press_at":
            x, y = args.get("x", 0), args.get("y", 0)
            action_type = "click"
            notification_content = f"Long press at ({x}, {y})"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_long_press(x, y)
        elif name == "go_home":
            action_type = "home"
            notification_content = "Pressing Home"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_go_home()
        elif name == "go_back":
            action_type = "back"
            notification_content = "Pressing Back"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_go_back()
        elif name == "open_app":
            app_name = args.get("app_name", "")
            action_type = "launch"
            notification_content = f"Opening app: {app_name}"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_open_app(app_name)
        elif name == "launch_package":
            package_name = args.get("package_name", "")
            action_type = "launch"
            notification_content = f"Launching: {package_name}"
            self.send_notification(f"Turn {self.current_turn}", notification_content, action_type)
            return self._execute_launch_package(package_name)
        else:
            print(f"Unknown function: {name}")
            self.send_notification(f"Turn {self.current_turn}", f"Unknown: {name}", "error")
            return {"status": "error", "message": f"Unknown function: {name}", "url": "android://device"}

    def get_screenshot_part(self) -> Part:
        """Capture current screen and return as Part."""
        # Use shared method that handles both Termux and normal mode
        png_bytes = self._get_screenshot_bytes()
        
        if self.debug_mode and HAS_CV2:
            # Update status for debug loop
            self.debug_status_text = "Sending to Gemini..."
            self.debug_status_expire_time = time.time() + 2.0

        return Part.from_bytes(data=png_bytes, mime_type='image/png')

    def _iter_stream_with_timeout(self, stream, timeout_per_chunk: float = 5.0):
        """Iterate over stream with timeout for each chunk.
        
        Uses a background thread to fetch chunks, allowing the main thread
        to check for timeouts and skip signals even when API is blocking.
        
        Yields: (chunk, timed_out) tuples
        - chunk: the stream chunk, or None if timed out
        - timed_out: True if this iteration timed out waiting for a chunk
        """
        import queue
        
        chunk_queue = queue.Queue()
        stream_done = threading.Event()
        
        def fetch_chunks():
            """Background thread to fetch chunks from stream."""
            try:
                for chunk in stream:
                    chunk_queue.put(('chunk', chunk))
                chunk_queue.put(('done', None))
            except Exception as e:
                chunk_queue.put(('error', e))
            finally:
                stream_done.set()
        
        fetch_thread = threading.Thread(target=fetch_chunks, daemon=True)
        fetch_thread.start()
        
        while not stream_done.is_set() or not chunk_queue.empty():
            try:
                item_type, item = chunk_queue.get(timeout=timeout_per_chunk)
                if item_type == 'chunk':
                    yield item, False
                elif item_type == 'error':
                    raise item
                elif item_type == 'done':
                    break
            except queue.Empty:
                # Timed out waiting for chunk
                yield None, True

    def process_step_streaming(self, instruction: str) -> str:
        """Process a single instruction step with STREAMING for real-time thinking display."""
        self.is_processing = True
        # Reset manual intervention flags for new task
        with self.skip_lock:
            self.skip_to_next_turn = False
            self.user_hint = ""
        
        # Termux mode: countdown to let user switch to target app
        countdown = getattr(self, 'startup_delay', 5)
        if IS_TERMUX and self.use_adb_fallback and countdown > 0:
            print(f"\n⏳ Starting in {countdown} seconds - switch to target app now!")
            self.send_notification("Get Ready!", f"Starting in {countdown}s - switch to target app", "info")
            
            for i in range(countdown, 0, -1):
                print(f"   {i}...", flush=True)
                self.send_notification("Get Ready!", f"Starting in {i}s...", "info")
                time.sleep(1)
            
            print("   🚀 Starting!\n")
            self.send_notification("Starting!", instruction[:30] + "..." if len(instruction) > 30 else instruction, "launch")
            time.sleep(0.5)  # Brief pause after countdown
        
        # Send initial notification (non-Termux mode or no delay)
        else:
            self.send_notification("Starting Task", instruction[:50] + "..." if len(instruction) > 50 else instruction, "info")
            
        try:
            # Clear conversation history for new instruction
            self.contents = []
            
            # Get initial screenshot
            screenshot_part = self.get_screenshot_part()
            
            # Add user message with instruction and screenshot
            self.contents.append(Content(
                role="user",
                parts=[
                    Part(text=instruction),
                    screenshot_part,
                ]
            ))
            
            config = self.get_config()
            
            # Agent loop with streaming
            max_turns = 30
            for turn in range(max_turns):
                self.current_turn = turn + 1
                print(f"\n--- Turn {turn + 1} ---")
                print("💭 Thinking (streaming)...\n", end="", flush=True)
                
                # Send thinking notification
                self.send_notification(f"Turn {turn + 1}", "Thinking...", "thinking")
                
                # Use streaming API
                stream = self.client.models.generate_content_stream(
                    model=self.model_name,
                    contents=self.contents,
                    config=config,
                )
                
                # Collect parts from stream - we need to track the best parts seen
                # because the last chunk might not contain function_calls
                displayed_text_length = 0
                best_parts = []  # Parts with most content (esp. function_calls)
                streaming_interrupted = False
                thinking_start_time = time.time()
                THINKING_TIMEOUT = 20  # seconds - total timeout for thinking
                CHUNK_TIMEOUT = 3  # seconds - timeout per chunk (allows checking skip/timeout)
                user_hint = ""
                
                # Use timeout-enabled iterator to prevent blocking
                for chunk, timed_out in self._iter_stream_with_timeout(stream, timeout_per_chunk=CHUNK_TIMEOUT):
                    # Check for thinking timeout (20 seconds total)
                    elapsed = time.time() - thinking_start_time
                    if elapsed > THINKING_TIMEOUT:
                        print(f"\n⏱️  Thinking timeout ({THINKING_TIMEOUT}s), moving to next turn...")
                        streaming_interrupted = True
                        break
                    
                    # Check for skip signal during streaming (allows interruption of slow API)
                    should_skip, user_hint = self.check_and_reset_skip()
                    if should_skip:
                        print("\n⏭️  Interrupting streaming, will re-evaluate...")
                        streaming_interrupted = True
                        break
                    
                    # If timed out waiting for chunk, just continue to check timeout/skip again
                    if timed_out:
                        print(".", end="", flush=True)  # Visual indicator that we're waiting
                        continue
                    
                    if chunk and chunk.candidates and len(chunk.candidates) > 0:
                        candidate = chunk.candidates[0]
                        if candidate.content and candidate.content.parts:
                            current_parts = list(candidate.content.parts)
                            
                            # Check if this chunk has function_calls
                            has_function_call = any(
                                hasattr(p, 'function_call') and p.function_call 
                                for p in current_parts
                            )
                            
                            # Keep parts that have function_calls, or update if current has more content
                            if has_function_call or len(current_parts) > len(best_parts):
                                best_parts = current_parts
                            
                            # Display thought text in real-time
                            for part in current_parts:
                                if hasattr(part, 'text') and part.text:
                                    if hasattr(part, 'thought') and part.thought:
                                        if len(part.text) > displayed_text_length:
                                            new_text = part.text[displayed_text_length:]
                                            print(new_text, end="", flush=True)
                                            displayed_text_length = len(part.text)
                
                print()  # New line after streaming
                
                # If streaming was interrupted, skip to next turn with fresh screenshot
                if streaming_interrupted:
                    time.sleep(0.3)
                    screenshot_bytes = self._get_screenshot_bytes()
                    
                    # Build interrupt message with optional user hint
                    if user_hint:
                        interrupt_msg = f"[USER INTERRUPTION] User says: {user_hint}\nPlease re-observe the screen and adjust your approach accordingly."
                    else:
                        interrupt_msg = "[USER INTERRUPTED DURING THINKING] Please re-observe the screen and reconsider."
                    
                    self.contents.append(Content(
                        role="user",
                        parts=[
                            Part(text=interrupt_msg),
                            Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                        ]
                    ))
                    continue
                
                # Use the best_parts we collected (which should have function_calls if any)
                final_parts = best_parts
                
                # Build complete content from final parts
                complete_content = Content(role="model", parts=final_parts)
                self.contents.append(complete_content)
                
                # Check for function calls (use final_parts)
                function_calls = [part.function_call for part in final_parts if hasattr(part, 'function_call') and part.function_call]
                
                if not function_calls:
                    # No function calls - agent might be done or thinking
                    text_response = " ".join([part.text for part in final_parts if hasattr(part, 'text') and part.text])
                    if "TASK_FINISHED" in text_response:
                        self.send_notification("Task Completed", "✅ Successfully finished!", "done")
                        self.clear_notification()
                        return "Task Completed."
                    if "ERROR_STUCK" in text_response:
                        self.send_notification("Task Failed", text_response[:50], "error")
                        self.clear_notification()
                        return f"Task Failed: {text_response}"
                    
                    self.clear_notification()
                    return text_response if text_response else "Task completed (no response text)"
                
                # Check if user requested to skip to next turn
                should_skip, user_hint = self.check_and_reset_skip()
                if should_skip:
                    print("\n" + "="*60)
                    print("⏭️  USER INTERRUPTION - Skipping planned actions")
                    if user_hint:
                        print(f"💬 User: {user_hint}")
                    print("🔄 Forcing AI to re-evaluate the situation...")
                    print("="*60 + "\n")
                    
                    # Capture current state without executing actions
                    time.sleep(0.5)
                    screenshot_bytes = self._get_screenshot_bytes()
                    
                    # Build interrupt message with optional user hint
                    if user_hint:
                        interrupt_msg = f"[USER INTERRUPTION] User says: {user_hint}\nPlease re-observe the screen and adjust your approach accordingly."
                    else:
                        interrupt_msg = ("[IMPORTANT] User has interrupted the planned actions. "
                                        "The situation may have changed or your plan may not be optimal. "
                                        "Please carefully observe the current screen state and reconsider your approach. "
                                        "What do you see now? What should be the next best action?")
                    
                    self.contents.append(Content(
                        role="user",
                        parts=[
                            Part(text=interrupt_msg),
                            Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                        ]
                    ))
                    continue
                
                # Execute function calls
                print(f"\n🎯 Executing {len(function_calls)} action(s)...")
                results = []
                
                for fc in function_calls:
                    result = self.execute_function_call(fc)
                    time.sleep(0.5)
                    results.append((fc.name, result))
                
                # Capture new state (wait 1s for UI to update)
                print("📸 Capturing state...")
                time.sleep(1.0)  # 延遲 1 秒讓畫面更新
                screenshot_bytes = self._get_screenshot_bytes()
                
                # Build function responses
                response_parts = []
                for name, result in results:
                    if "url" not in result:
                        result["url"] = "android://device"
                    
                    response_parts.append(
                        Part(function_response=types.FunctionResponse(
                            name=name,
                            response=result,
                        ))
                    )
                
                response_parts.append(Part.from_bytes(data=screenshot_bytes, mime_type='image/png'))
                self.contents.append(Content(role="user", parts=response_parts))
            
            return "Max turns reached - task may be incomplete"
            
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            return f"Error: {e}"
        finally:
            self.is_processing = False


    def process_step(self, instruction: str) -> str:
        """Process a single instruction step with the agent loop."""
        self.is_processing = True
        # Reset manual intervention flags for new task
        with self.skip_lock:
            self.skip_to_next_turn = False
            self.user_hint = ""

        try:
            # Clear conversation history for new instruction
            self.contents = []
            
            # Get initial screenshot
            screenshot_part = self.get_screenshot_part()
            
            # Add user message with instruction and screenshot
            self.contents.append(Content(
                role="user",
                parts=[
                    Part(text=instruction),
                    screenshot_part,
                ]
            ))
            
            config = self.get_config()
            
            # Agent loop
            max_turns = 30
            for turn in range(max_turns):
                print(f"\n--- Turn {turn + 1} ---")
                print("Thinking...")
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=self.contents,
                    config=config,
                )
                
                candidate = response.candidates[0]
                self.contents.append(candidate.content)
                
                # Display thinking process if available
                for part in candidate.content.parts:
                    if hasattr(part, 'thought') and part.thought:
                        print(f"\n💭 [Thinking Process]:\n{part.text}")
                    elif hasattr(part, 'text') and part.text and not part.function_call:
                        # Show regular text output (observations, reasoning)
                        if part.text.strip() and "TASK_FINISHED" not in part.text and "ERROR_STUCK" not in part.text:
                            print(f"\n🤔 [Agent]: {part.text}")
                
                # Check for function calls
                function_calls = [part.function_call for part in candidate.content.parts if part.function_call]
                
                if not function_calls:
                    # No function calls - agent might be done or thinking
                    text_response = " ".join([part.text for part in candidate.content.parts if part.text])
                    if "TASK_FINISHED" in text_response:
                        self.is_processing = False
                        return "Task Completed."
                    if "ERROR_STUCK" in text_response:
                        self.is_processing = False
                        return f"Task Failed: {text_response}"
                    
                    # If model just talks without tool calls, we print it but might want to continue depending on logic?
                    # For now, if no tool calls and no special keywords, return response (legacy behavior)
                    self.is_processing = False
                    return text_response if text_response else "Task completed (no response text)"
                
                # Check if user requested to skip to next turn
                should_skip, user_hint = self.check_and_reset_skip()
                if should_skip:
                    print("\n" + "="*60)
                    print("⏭️  USER INTERRUPTION - Skipping planned actions")
                    if user_hint:
                        print(f"💬 User: {user_hint}")
                    print("🔄 Forcing AI to re-evaluate the situation...")
                    print("="*60 + "\n")
                    
                    # Capture current state without executing actions
                    time.sleep(0.5)
                    screenshot_bytes = self._get_screenshot_bytes()
                    
                    # Build interrupt message with optional user hint
                    if user_hint:
                        interrupt_msg = f"[USER INTERRUPTION] User says: {user_hint}\nPlease re-observe the screen and adjust your approach accordingly."
                    else:
                        interrupt_msg = ("[IMPORTANT] User has interrupted the planned actions. "
                                        "The situation may have changed or your plan may not be optimal. "
                                        "Please carefully observe the current screen state and reconsider your approach. "
                                        "What do you see now? What should be the next best action?")
                    
                    self.contents.append(Content(
                        role="user",
                        parts=[
                            Part(text=interrupt_msg),
                            Part.from_bytes(data=screenshot_bytes, mime_type='image/png')
                        ]
                    ))
                    continue
                
                # Execute function calls
                print(f"Executing {len(function_calls)} action(s)...")
                results = []
                
                for fc in function_calls:
                    result = self.execute_function_call(fc)
                    time.sleep(0.5)  # Small delay between actions
                    results.append((fc.name, result))
                
                # Capture new state (wait 1s for UI to update)
                print("Capturing state...")
                time.sleep(1.0)  # 延遲 1 秒讓畫面更新
                screenshot_bytes = self._get_screenshot_bytes()
                
                # Build function responses with screenshot in each response
                # According to docs: FunctionResponse should contain url and screenshot
                response_parts = []
                for name, result in results:
                    # Ensure result has url field
                    if "url" not in result:
                        result["url"] = "android://device"
                    
                    response_parts.append(
                        Part(function_response=types.FunctionResponse(
                            name=name,
                            response=result,
                        ))
                    )
                
                # Add screenshot as separate part after all function responses
                response_parts.append(Part.from_bytes(data=screenshot_bytes, mime_type='image/png'))
                
                self.contents.append(Content(role="user", parts=response_parts))
            
            return "Max turns reached - task may be incomplete"
            
        except Exception as e:
            print(f"Error: {e}")
            traceback.print_exc()
            return f"Error: {e}"
        finally:
            self.is_processing = False


    print("Starting Main Loop...")

    def start_debug_loop(self):
        """Start the debug render thread."""
        if self.debug_mode and not self.debug_running:
            self.debug_running = True
            self.debug_thread = threading.Thread(target=self._render_loop, daemon=True)
            self.debug_thread.start()

    def _render_loop(self):
        """Continuous render loop for debug window."""
        print("Debug render loop started")
        while self.debug_running:
            try:
                with self.frame_lock:
                    if self.last_frame is None:
                        frame_to_show = None
                    else:
                        frame_to_show = self.last_frame.copy()
                
                if frame_to_show is None:
                    time.sleep(0.1)
                    continue

                # Resize for display FIRST (to ensure consistent coordinate mapping if we wanted to map clicks, 
                # but valid overlay text is better done on original resolution or we accept scaling artifacts)
                # Actually, better to draw on original frame then resize.

                # Draw Status
                if time.time() < self.debug_status_expire_time:
                    # Draw a black bar at the top
                    h, w = frame_to_show.shape[:2]
                    cv2.rectangle(frame_to_show, (0, 0), (w, 40), (0, 0, 0), -1)
                    cv2.putText(frame_to_show, self.debug_status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                # Draw Overlay Actions
                if self.overlay_data and time.time() < self.overlay_expire_time:
                    self._draw_overlay(frame_to_show, self.overlay_data)
                
                # Resize if too big for screen
                display_h, display_w = frame_to_show.shape[:2]
                max_h = 900
                if display_h > max_h:
                    scale = max_h / display_h
                    display_w = int(display_w * scale)
                    display_h = max_h
                    frame_to_show = cv2.resize(frame_to_show, (display_w, display_h))

                cv2.imshow("Gemini Debug", frame_to_show)
                cv2.waitKey(1)
                
                time.sleep(0.03) # ~30 FPS
            except Exception as e:
                # print(f"Render loop error: {e}")
                time.sleep(1)
        
        try:
            cv2.destroyAllWindows()
        except:
            pass

    def _draw_overlay(self, frame, data):
        """Draw action overlay on the frame."""
        try:
            x, y = data.get("x", 0), data.get("y", 0)
            action = data.get("action", "")
            end_x, end_y = data.get("end_x", 0), data.get("end_y", 0)
            text = data.get("text", "")

            color = (0, 0, 255) # Red for actions
            thickness = 3
            
            label = action
            
            if action == "click":
                cv2.circle(frame, (x, y), 20, color, thickness)
                cv2.drawMarker(frame, (x, y), color, markerType=cv2.MARKER_CROSS, markerSize=30, thickness=thickness)
                label = f"Click ({x}, {y})"
            elif action == "long_press":
                cv2.circle(frame, (x, y), 30, (0, 255, 255), thickness) # Yellow
                label = f"Long Press ({x}, {y})"
            elif action == "scroll":
                cv2.arrowedLine(frame, (x, y), (end_x, end_y), (255, 0, 0), 5) # Blue arrow
                label = f"Scroll"
            elif action == "type":
                label = f"Type: {text}"

            # Add label with background
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)
            cv2.rectangle(frame, (50, 50 - h - 10), (50 + w, 50 + 10), (0, 0, 0), -1)
            cv2.putText(frame, label, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
            
        except Exception as e:
            print(f"Draw error: {e}")

    def _visualize_action(self, x, y, action="click", end_x=0, end_y=0, text=None):
        """Queue action for visualization on debug window."""
        self.overlay_data = {
            "x": x, 
            "y": y, 
            "action": action, 
            "end_x": end_x, 
            "end_y": end_y, 
            "text": text
        }
        self.overlay_expire_time = time.time() + 1.5 # Show for 1.5s

def on_frame(frame):
    if frame is not None and agent is not None:
        agent.update_frame(frame)


def keyboard_listener_thread(agent_instance):
    """Background thread to listen for keyboard input to trigger skip with optional hint."""
    import sys
    import select
    
    print("\n💡 Tips:")
    print("   - Press Enter alone: Skip to next turn")
    print("   - Type a message + Enter: Send hint to AI and skip")
    print("   - Type 'q' + Enter: Quit when in instruction prompt\n")
    
    while True:
        try:
            # Only listen if agent is actively processing a task
            if not agent_instance.is_processing:
                time.sleep(0.5)
                continue

            # Check if there's input available (non-blocking on Unix)
            if sys.platform != 'win32':
                # Use select for non-blocking input on Unix/Mac
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline().strip()
                else:
                    line = None
                    
                if line is not None:
                    if line.lower() == 'q':
                        # In processing mode, q acts as skip/cancel or we could ignore
                        # But typically q is for main loop quit. 
                        # Let's treat it as a skip hint "quit/stop"
                        agent_instance.request_skip_with_hint("User requested stop/quit")
                    elif line == '' or line.lower() == 's':
                        # Empty line or 's' = simple skip
                        agent_instance.request_skip_with_hint("")
                    else:
                        # Any other input = skip with hint message
                        agent_instance.request_skip_with_hint(line)
            else:
                # Windows: simplified handling
                import msvcrt
                if msvcrt.kbhit():
                    char = msvcrt.getch().decode('utf-8')
                    if char == '\r':  # Enter
                        agent_instance.request_skip_with_hint("")
                    elif char.lower() == 'q':
                         agent_instance.request_skip_with_hint("User requested stop/quit")
                time.sleep(0.5)
        except Exception as e:
            # Ignore errors in listener thread
            pass


agent = None


def main():
    global agent
    parser = argparse.ArgumentParser(description="Gemini Scrcpy Agent")
    parser.add_argument("--api_key", help="Google AI Studio API Key", default=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    parser.add_argument("--model", help="Gemini Model Name", default=DEFAULT_MODEL)
    parser.add_argument("--max_width", type=int, default=800, help="Max width for scrcpy stream")
    parser.add_argument("--instruction", help="Initial instruction to the agent")
    parser.add_argument("--use_adb", action="store_true", help="Use pure ADB mode (slower but reliable)")
    parser.add_argument("--streaming", action="store_true", help="Enable streaming mode for real-time thinking display")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode to show OpenCV window with actions")
    
    # Termux mode options
    parser.add_argument("--termux", action="store_true", help="Termux mode: use ADB, no GUI, wireless ADB support")
    parser.add_argument("--shizuku", action="store_true", help="Use Shizuku instead of ADB (no WiFi needed)")
    parser.add_argument("--device", "-s", help="Device serial (IP:port for wireless ADB)")
    parser.add_argument("--pair", action="store_true", help="Pair with wireless ADB device first")
    parser.add_argument("--connect", type=str, help="Connect to wireless ADB device (IP:port)")
    parser.add_argument("--delay", type=int, default=5, help="Countdown seconds before starting in Termux mode (default: 5, use 0 to disable)")
    
    args = parser.parse_args()
    
    # Handle Shizuku mode
    if args.shizuku:
        # Re-check Shizuku (don't rely on module-level check which may be stale)
        try:
            from shizuku_setup import ShizukuShell
            shizuku = ShizukuShell()
            if not shizuku.available:
                print("❌ Shizuku rish not found!")
                print("\nRun: python shizuku_setup.py install")
                return
            
            if not shizuku.check_shizuku_running():
                print("❌ Shizuku service not running!")
                print("\nTo start Shizuku:")
                print("1. Open Shizuku app")
                print("2. Start the service")
                print("3. Try again")
                return
            
            # Update global for use in agent
            global SHIZUKU_SHELL
            SHIZUKU_SHELL = shizuku
            print("🔰 Shizuku mode active!")
            
        except ImportError:
            print("❌ shizuku_setup.py not found!")
            return
        except Exception as e:
            print(f"❌ Shizuku error: {e}")
            return
        
        args.termux = True
        args.use_adb = True
    
    # Auto-detect Termux environment
    if IS_TERMUX and not args.use_adb and not args.shizuku:
        print("📱 Termux detected, enabling ADB mode automatically")
        args.termux = True
    
    # Handle Termux/wireless ADB setup (skip if using Shizuku)
    if (args.termux or args.pair or args.connect) and not args.shizuku:
        try:
            from wireless_adb import WirelessADB, interactive_setup
            wadb = WirelessADB()
            
            if args.pair:
                print("\n🔗 Wireless ADB Pairing Mode")
                interactive_setup()
                return
            
            if args.connect:
                if ':' in args.connect:
                    host, port = args.connect.rsplit(':', 1)
                else:
                    host, port = args.connect, "5555"
                success, msg = wadb.connect(host, int(port))
                print(msg)
                if not success:
                    return
                # Set device serial for ADB commands
                args.device = f"{host}:{port}"
            
            # Check connected devices
            devices = wadb.get_connected_devices()
            active_devices = [d for d in devices if d['status'] == 'device']
            
            if not active_devices:
                print("❌ No devices connected!")
                print("   Use --pair to pair a device, or --connect IP:port to connect")
                return
            
            # Handle multiple devices
            if len(active_devices) > 1 and not args.device:
                print(f"\n📱 Multiple devices detected ({len(active_devices)}):")
                for i, d in enumerate(active_devices):
                    wireless = "📶" if d['is_wireless'] else "🔌"
                    print(f"   [{i+1}] {wireless} {d['serial']}")
                
                print("\n💡 Please select a device:")
                try:
                    choice = input("   Enter number (or device serial): ").strip()
                    if choice.isdigit():
                        idx = int(choice) - 1
                        if 0 <= idx < len(active_devices):
                            args.device = active_devices[idx]['serial']
                        else:
                            print("❌ Invalid selection")
                            return
                    else:
                        # Treat as serial
                        args.device = choice
                except (KeyboardInterrupt, EOFError):
                    print("\nCancelled")
                    return
                
                print(f"✅ Selected: {args.device}")
            
            # Auto-select device if only one available
            elif not args.device and len(active_devices) == 1:
                args.device = active_devices[0]['serial']
                print(f"✅ Using device: {args.device}")
                
        except ImportError:
            print("⚠️ wireless_adb.py not found, continuing with default ADB")
        except Exception as e:
            print(f"⚠️ Wireless ADB setup failed: {e}")
    
    # Force ADB mode for Termux
    if args.termux:
        args.use_adb = True
        args.debug = False  # No GUI in Termux
        if not HAS_CV2:
            print("📱 Running without OpenCV (Termux lightweight mode)")
    
    if not args.api_key:
        print("Error: API Key is required.")
        print("   Set with: export GEMINI_API_KEY='your-key'")
        print("   Or use: --api_key YOUR_KEY")
        return

    agent = GeminiAgent(api_key=args.api_key, model_name=args.model, use_adb_fallback=args.use_adb)
    agent.debug_mode = args.debug
    
    # Set device serial for ADB commands
    if args.device:
        agent.device_serial = args.device
    
    # Set Shizuku shell if using --shizuku mode
    if args.shizuku and SHIZUKU_SHELL:
        agent.shizuku_shell = SHIZUKU_SHELL
        agent.use_shizuku = True
        print("   Shizuku shell attached to agent")
    
    # Set startup delay for Termux mode
    agent.startup_delay = args.delay
    
    if args.debug and HAS_CV2:
        agent.start_debug_loop()

    if not args.use_adb:
        try:
            from scrcpy_client import ScrcpyClient, EVENT_FRAME
            client = ScrcpyClient(max_width=args.max_width)
            client.add_listener(EVENT_FRAME, on_frame)
            agent.set_scrcpy_client(client)
            
            print("Starting Scrcpy (Video Stream)...")
            client.start(threaded=True)
            
            # Wait a bit for connection
            print("Waiting for video stream...")
            for _ in range(20):
                if agent.last_frame is not None:
                    break
                time.sleep(0.5)
                print(".", end="", flush=True)
            print()
            
            if agent.last_frame is None:
                print("Warning: Scrcpy video stream timed out or failed.")
                print("Falling back to ADB screenshot mode automatically.")
                agent.use_adb_fallback = True
        except ImportError as e:
            print(f"Custom scrcpy client import failed: {e}. Using ADB mode.")
            agent.use_adb_fallback = True
        except FileNotFoundError as e:
            print(f"Scrcpy server not found: {e}. Using ADB mode.")
            agent.use_adb_fallback = True
        except Exception as e:
            print(f"Scrcpy init failed: {e}. Using ADB mode.")
            agent.use_adb_fallback = True

    if agent.use_adb_fallback:
        print("Running in ADB Mode (1-2s per frame latency).")
    
    if args.streaming:
        print("✨ Streaming mode enabled - you will see real-time thinking process")
    
    # Start keyboard listener thread for manual intervention
    listener_thread = threading.Thread(target=keyboard_listener_thread, args=(agent,), daemon=True)
    listener_thread.start()

    if args.instruction:
        print(f"Executing: {args.instruction}")
        if args.streaming:
            result = agent.process_step_streaming(args.instruction)
        else:
            result = agent.process_step(args.instruction)
        print(f"Result: {result}")
    
    # Interactive Loop
    try:
        while True:
            user_input = input("\nEnter instruction (or 'q' to quit): ")
            if user_input.lower() == 'q':
                break
            
            print("Processing...")
            if args.streaming:
                result = agent.process_step_streaming(user_input)
            else:
                result = agent.process_step(user_input)
            print("Gemini says:", result)

            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        if agent.scrcpy_client:
            agent.scrcpy_client.stop()


if __name__ == "__main__":
    main()