import os
import time
import argparse
import threading
import subprocess
import traceback
import cv2
import numpy as np
from typing import Optional, Dict, Any, List

from google import genai
from google.genai import types
from google.genai.types import Content, Part

# --- Configuration ---
DEFAULT_MODEL = "gemini-3-flash-preview"

# System prompt for Android control
SYSTEM_PROMPT = """You are an AI agent operating an Android device.
Target Device Screen: {width}x{height} (Pixel coordinates)

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
        self.use_adb_fallback = use_adb_fallback
        
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

    def get_config(self) -> types.GenerateContentConfig:
        """Build configuration with generic tools for Android."""
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(width=self.width, height=self.height),
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
        """Capture screenshot directly via ADB (Slower but reliable)"""
        try:
            cmd = ["adb", "exec-out", "screencap", "-p"]
            result = subprocess.run(cmd, capture_output=True, check=True)
            image_data = np.frombuffer(result.stdout, np.uint8)
            frame = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
            return frame
        except Exception as e:
            print(f"ADB Screenshot failed: {e}")
            return None

    def _get_screenshot_bytes(self) -> bytes:
        """Capture current screen and return as PNG bytes."""
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
            result = subprocess.run(["adb", "shell", "wm", "size"], capture_output=True, text=True, check=True)
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
        subprocess.run(["adb", "shell"] + cmd_args)

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
            result = subprocess.run(
                ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
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
        
        # Handle predefined Computer Use actions
        if name == "open_web_browser":
            return self._execute_open_browser()
        elif name == "click_at":
            return self._execute_click_at(args.get("x", 0), args.get("y", 0))
        elif name == "type_text_at":
            # First click, then type
            if "x" in args and "y" in args:
                self._execute_click_at(args["x"], args["y"])
                time.sleep(0.3)
            return self._execute_type_text(args.get("text", ""), args.get("press_enter", False))
        elif name == "type":
            return self._execute_type_text(args.get("text", ""), args.get("press_enter", False))
        elif name == "scroll" or name == "scroll_at" or name == "scroll_document":
            return self._execute_scroll(args.get("x", 500), args.get("y", 500), args.get("direction", "down"))
        elif name == "navigate":
            return self._execute_navigate(args.get("url", "https://www.google.com"))
        elif name == "search":
            return self._execute_open_browser()
        elif name == "wait":
            delay = args.get("seconds", 1)
            print(f"ACTION: Wait {delay}s")
            time.sleep(delay)
            return {"status": "waited", "seconds": delay, "url": "android://device"}
        elif name.startswith("wait_") and name.endswith("_seconds"):
            # Handle model-invented functions like wait_5_seconds
            try:
                delay = int(name.split("_")[1])
            except (IndexError, ValueError):
                delay = 3
            print(f"ACTION: Wait {delay}s (from {name})")
            time.sleep(delay)
            return {"status": "waited", "seconds": delay, "url": "android://device"}
        # Handle custom functions
        elif name == "long_press_at":
            return self._execute_long_press(args.get("x", 0), args.get("y", 0))
        elif name == "go_home":
            return self._execute_go_home()
        elif name == "go_back":
            return self._execute_go_back()
        elif name == "open_app":
            return self._execute_open_app(args.get("app_name", ""))
        elif name == "launch_package":
            return self._execute_launch_package(args.get("package_name", ""))
        else:
            print(f"Unknown function: {name}")
            return {"status": "error", "message": f"Unknown function: {name}", "url": "android://device"}

    def get_screenshot_part(self) -> Part:
        """Capture current screen and return as Part."""
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
        png_bytes = buffer.tobytes()
        
        return Part.from_bytes(data=png_bytes, mime_type='image/png')

    def process_step_streaming(self, instruction: str) -> str:
        """Process a single instruction step with STREAMING for real-time thinking display."""
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
                print(f"\n--- Turn {turn + 1} ---")
                print("💭 Thinking (streaming)...\n", end="", flush=True)
                
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
                THINKING_TIMEOUT = 20  # seconds
                
                for chunk in stream:
                    # Check for thinking timeout (20 seconds)
                    elapsed = time.time() - thinking_start_time
                    if elapsed > THINKING_TIMEOUT:
                        print(f"\n⏱️  Thinking timeout ({THINKING_TIMEOUT}s), moving to next turn...")
                        streaming_interrupted = True
                        user_hint = ""
                        break
                    
                    # Check for skip signal during streaming (allows interruption of slow API)
                    should_skip, user_hint = self.check_and_reset_skip()
                    if should_skip:
                        print("\n⏭️  Interrupting streaming, will re-evaluate...")
                        streaming_interrupted = True
                        break
                    
                    if chunk.candidates and len(chunk.candidates) > 0:
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
                        return "Task Completed."
                    if "ERROR_STUCK" in text_response:
                        return f"Task Failed: {text_response}"
                    
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


    def process_step(self, instruction: str) -> str:
        """Process a single instruction step with the agent loop."""
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
                        return "Task Completed."
                    if "ERROR_STUCK" in text_response:
                        return f"Task Failed: {text_response}"
                    
                    # If model just talks without tool calls, we print it but might want to continue depending on logic?
                    # For now, if no tool calls and no special keywords, return response (legacy behavior)
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
            # Check if there's input available (non-blocking on Unix)
            if sys.platform != 'win32':
                # Use select for non-blocking input on Unix/Mac
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline().strip()
                    if line.lower() == 'q':
                        break
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
                        break
                time.sleep(0.5)
        except Exception as e:
            # Ignore errors in listener thread
            pass


agent = None


def main():
    global agent
    parser = argparse.ArgumentParser(description="Gemini Scrcpy Agent")
    parser.add_argument("--api_key", help="Google AI Studio API Key", default=os.environ.get("GOOGLE_API_KEY"))
    parser.add_argument("--model", help="Gemini Model Name", default=DEFAULT_MODEL)
    parser.add_argument("--max_width", type=int, default=800, help="Max width for scrcpy stream")
    parser.add_argument("--instruction", help="Initial instruction to the agent")
    parser.add_argument("--use_adb", action="store_true", help="Use pure ADB mode (slower but reliable)")
    parser.add_argument("--streaming", action="store_true", help="Enable streaming mode for real-time thinking display")

    
    args = parser.parse_args()
    
    if not args.api_key:
        print("Error: API Key is required.")
        return

    agent = GeminiAgent(api_key=args.api_key, model_name=args.model, use_adb_fallback=args.use_adb)

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