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
# Computer Use 必須使用這個專用模型
DEFAULT_MODEL = "gemini-2.5-computer-use-preview-10-2025"

# System prompt for Android control
SYSTEM_PROMPT = """You are operating an Android phone. 
* To provide an answer to the user, *do not use any tools* and output your answer on a separate line.
* Make sure you scroll down to see everything before deciding something isn't available.
* You can open an app from anywhere. The icon doesn't have to currently be on screen.
* Unless explicitly told otherwise, make sure to save any changes you make.
* If text is cut off or incomplete, scroll or click into the element to get the full text before providing an answer.
* IMPORTANT: Complete the given task EXACTLY as stated. DO NOT make any assumptions that completing a similar task is correct. If you can't find what you're looking for, SCROLL to find it.
* If you want to edit some text, ONLY USE THE `type` tool. Do not use the onscreen keyboard.
* Quick settings shouldn't be used to change settings. Use the Settings app instead.
* The given task may already be completed. If so, there is no need to do anything.

Available actions:
- click_at(x, y): Click at coordinates (0-999 normalized)
- type(text, press_enter): Type text, optionally press enter
- scroll(x, y, direction): Scroll up/down/left/right at position
- wait(seconds): Wait for specified seconds
- go_back(): Press Android back button
- go_home(): Press Android home button
"""

# Exclude browser-specific predefined functions for Android
EXCLUDED_PREDEFINED_FUNCTIONS = [
    "open_web_browser",
    "search",
    "navigate",
    "hover_at",
    "scroll_document",
    "go_forward",
    "key_combination",
    "drag_and_drop",
]


class GeminiAgent:
    def __init__(self, api_key, model_name=DEFAULT_MODEL, use_adb_fallback=False):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.use_adb_fallback = use_adb_fallback
        
        self.scrcpy_client = None
        self.last_frame = None
        self.frame_lock = threading.Lock()
        self.width = 0
        self.height = 0
        
        # Cache real device screen size (for ADB input coordinates)
        self.real_width = None
        self.real_height = None
        
        # Conversation history for multi-turn
        self.contents: List[Content] = []

    def get_config(self) -> types.GenerateContentConfig:
        """Build configuration with Computer Use tool for Android."""
        return types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    ),
                ),
            ],
        )

    def set_scrcpy_client(self, client):
        self.scrcpy_client = client

    def update_frame(self, frame):
        with self.frame_lock:
            self.last_frame = frame
            if self.width == 0:
                self.height, self.width, _ = frame.shape

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
                end_y = actual_y - distance
            elif direction == "up":
                end_y = actual_y + distance
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
                end_y = actual_y - distance
            elif direction == "up":
                end_y = actual_y + distance
            elif direction == "left":
                end_x = actual_x - distance # Scroll right to see left? No, swipe left moves content left, seeing right.
                # Wait, "scroll left" usually means "I want to see content to the left".
                # So I swipe RIGHT (drag content right).
                # ADB implementation above: left -> swipe to x+distance? 
                # ADB code: if direction == "left": swipe x to x+distance. (Drag Right).
                end_x = actual_x + distance
            else:  # right
                # "Scroll right" -> see content to the right. Swipe LEFT.
                end_x = actual_x - distance
            
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
                
                # Check for function calls
                function_calls = [part.function_call for part in candidate.content.parts if part.function_call]
                
                if not function_calls:
                    # No function calls - agent is done
                    text_response = " ".join([part.text for part in candidate.content.parts if part.text])
                    return text_response if text_response else "Task completed (no response text)"
                
                # Execute function calls
                print(f"Executing {len(function_calls)} action(s)...")
                results = []
                
                for fc in function_calls:
                    result = self.execute_function_call(fc)
                    time.sleep(0.5)  # Small delay between actions
                    results.append((fc.name, result))
                
                # Capture new state
                print("Capturing state...")
                time.sleep(0.5)  # Wait for UI to update
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


agent = None


def main():
    global agent
    parser = argparse.ArgumentParser(description="Gemini Scrcpy Agent")
    parser.add_argument("--api_key", help="Google AI Studio API Key", default=os.environ.get("GOOGLE_API_KEY"))
    parser.add_argument("--model", help="Gemini Model Name", default=DEFAULT_MODEL)
    parser.add_argument("--max_width", type=int, default=800, help="Max width for scrcpy stream")
    parser.add_argument("--instruction", help="Initial instruction to the agent")
    parser.add_argument("--use_adb", action="store_true", help="Use pure ADB mode (slower but reliable)")
    
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

    if args.instruction:
        print(f"Executing: {args.instruction}")
        result = agent.process_step(args.instruction)
        print(f"Result: {result}")
    
    # Interactive Loop
    try:
        while True:
            user_input = input("\nEnter instruction (or 'q' to quit): ")
            if user_input.lower() == 'q':
                break
            
            print("Processing...")
            result = agent.process_step(user_input)
            print("Gemini says:", result)
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        if agent.scrcpy_client:
            agent.scrcpy_client.stop()


if __name__ == "__main__":
    main()