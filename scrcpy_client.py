"""
Custom Scrcpy Client Implementation

This module provides a pure-Python implementation for connecting to scrcpy-server
on Android devices. It uses ADB subprocess commands and direct socket communication.
"""

import os
import socket
import struct
import subprocess
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

import cv2
import numpy as np

# Try to import av for H.264 decoding
try:
    from av.codec import CodecContext
    HAS_AV = True
except ImportError:
    HAS_AV = False
    print("Warning: PyAV not available, video stream decoding disabled")

# --- Constants ---
EVENT_FRAME = "frame"
EVENT_INIT = "init"

# Touch action types
ACTION_DOWN = 0
ACTION_UP = 1
ACTION_MOVE = 2

# Pointer IDs
POINTER_ID_MOUSE = 0xFFFFFFFFFFFFFFFF
POINTER_ID_VIRTUAL_FINGER = -2  # 0xFFFFFFFFFFFFFFFE as signed

# Control message types
TYPE_INJECT_KEYCODE = 0
TYPE_INJECT_TEXT = 1
TYPE_INJECT_TOUCH_EVENT = 2
TYPE_INJECT_SCROLL_EVENT = 3
TYPE_BACK_OR_SCREEN_ON = 4
TYPE_EXPAND_NOTIFICATION_PANEL = 5
TYPE_EXPAND_SETTINGS_PANEL = 6
TYPE_COLLAPSE_PANELS = 7
TYPE_GET_CLIPBOARD = 8
TYPE_SET_CLIPBOARD = 9
TYPE_SET_SCREEN_POWER_MODE = 10
TYPE_ROTATE_DEVICE = 11

# Key event actions
KEYEVENT_ACTION_DOWN = 0
KEYEVENT_ACTION_UP = 1

# Keycodes (Android)
KEYCODE_HOME = 3
KEYCODE_BACK = 4
KEYCODE_ENTER = 66
KEYCODE_DPAD_UP = 19
KEYCODE_DPAD_DOWN = 20
KEYCODE_DPAD_LEFT = 21
KEYCODE_DPAD_RIGHT = 22
KEYCODE_VOLUME_UP = 24
KEYCODE_VOLUME_DOWN = 25
KEYCODE_POWER = 26
KEYCODE_APP_SWITCH = 187

# Screen orientation
LOCK_SCREEN_ORIENTATION_UNLOCKED = -1

# Scrcpy server version (you may need to update this)
SCRCPY_SERVER_VERSION = "3.3.3"
SCRCPY_SERVER_FILENAME = f"scrcpy-server-v{SCRCPY_SERVER_VERSION}"


class ControlSender:
    """Sends control messages to scrcpy server."""
    
    def __init__(self, client: "ScrcpyClient"):
        self.client = client
    
    def _send(self, data: bytes) -> None:
        """Send data to control socket."""
        if self.client.control_socket is None:
            return
        try:
            with self.client.control_socket_lock:
                self.client.control_socket.sendall(data)
        except Exception as e:
            print(f"Control send error: {e}")
    
    def touch(self, x: int, y: int, action: int = ACTION_DOWN, pointer_id: int = POINTER_ID_VIRTUAL_FINGER) -> None:
        """
        Send touch event.
        
        Args:
            x: X coordinate (pixels)
            y: Y coordinate (pixels)
            action: ACTION_DOWN, ACTION_UP, or ACTION_MOVE
            pointer_id: Pointer ID for multi-touch
        """
        if self.client.resolution is None:
            print("Touch failed: resolution unknown")
            return
        
        width, height = self.client.resolution
        
        # Clamp coordinates
        x = max(0, min(x, width))
        y = max(0, min(y, height))
        
        # Build touch event message
        # Format: type(1) + action(1) + pointerId(8) + x(4) + y(4) + width(2) + height(2) + pressure(2) + actionButton(4) + buttons(4)
        # actionButton: 1 = primary button for DOWN, 0 for UP
        # buttons: bitmask of currently pressed buttons
        action_button = 1 if action == ACTION_DOWN else 0
        buttons = 1 if action == ACTION_DOWN else 0
        
        msg = struct.pack(
            ">BBqiiHHHII",
            TYPE_INJECT_TOUCH_EVENT,
            action,
            pointer_id,
            x,
            y,
            width,
            height,
            0xFFFF if action != ACTION_UP else 0,  # pressure
            action_button,  # actionButton
            buttons  # buttons
        )
        self._send(msg)
    
    def keycode(self, keycode: int, action: int = KEYEVENT_ACTION_DOWN, repeat: int = 0, metastate: int = 0) -> None:
        """
        Send keycode event.
        
        Args:
            keycode: Android keycode
            action: KEYEVENT_ACTION_DOWN or KEYEVENT_ACTION_UP
            repeat: Repeat count
            metastate: Meta state flags
        """
        # Format: type(1) + action(1) + keycode(4) + repeat(4) + metastate(4)
        msg = struct.pack(
            ">BBIII",
            TYPE_INJECT_KEYCODE,
            action,
            keycode,
            repeat,
            metastate
        )
        self._send(msg)
    
    def text(self, text: str) -> None:
        """
        Inject text input.
        
        Args:
            text: Text to inject
        """
        text_bytes = text.encode("utf-8")
        # Format: type(1) + length(4) + text(variable)
        msg = struct.pack(">BI", TYPE_INJECT_TEXT, len(text_bytes)) + text_bytes
        self._send(msg)
    
    def set_clipboard(self, text: str, paste: bool = True) -> None:
        """
        Set device clipboard and optionally paste.
        This works for unicode/Chinese text unlike inject_text.
        
        Args:
            text: Text to set in clipboard
            paste: If True, also simulate paste action
        """
        text_bytes = text.encode("utf-8")
        # Format: type(1) + copy_key(8) + paste(1) + length(4) + text(variable)
        # copy_key is sequence number, we use 0
        # paste: 1 to paste after setting, 0 to just set clipboard
        msg = struct.pack(">BqBI", TYPE_SET_CLIPBOARD, 0, 1 if paste else 0, len(text_bytes)) + text_bytes
        self._send(msg)
    
    def scroll(self, x: int, y: int, h: int, v: int) -> None:
        """
        Send scroll event.
        
        Args:
            x: X coordinate
            y: Y coordinate
            h: Horizontal scroll (-1, 0, 1)
            v: Vertical scroll (-1, 0, 1)
        """
        if self.client.resolution is None:
            return
        
        width, height = self.client.resolution
        
        # Format: type(1) + x(4) + y(4) + width(2) + height(2) + h(4) + v(4) + buttons(4)
        msg = struct.pack(
            ">BiiHHiiI",
            TYPE_INJECT_SCROLL_EVENT,
            max(0, min(x, width)),
            max(0, min(y, height)),
            width,
            height,
            h,
            v,
            0  # buttons
        )
        self._send(msg)
    
    def back_or_screen_on(self, action: int = KEYEVENT_ACTION_DOWN) -> None:
        """Send back or screen on event."""
        msg = struct.pack(">BB", TYPE_BACK_OR_SCREEN_ON, action)
        self._send(msg)


class ScrcpyClient:
    """
    Custom scrcpy client implementation.
    
    Connects to scrcpy-server on Android device via ADB and provides
    video stream and control functionality.
    """
    
    def __init__(
        self,
        serial: Optional[str] = None,
        max_width: int = 0,
        bitrate: int = 8000000,
        max_fps: int = 0,
        flip: bool = False,
        block_frame: bool = False,
        stay_awake: bool = False,
        lock_screen_orientation: int = LOCK_SCREEN_ORIENTATION_UNLOCKED,
        connection_timeout: int = 5000,
    ):
        """
        Create a scrcpy client.
        
        Args:
            serial: Device serial (None for first device)
            max_width: Max frame width (0 = unlimited)
            bitrate: Video bitrate
            max_fps: Max FPS (0 = unlimited)
            flip: Flip video horizontally
            block_frame: Only return non-empty frames
            stay_awake: Keep device awake
            lock_screen_orientation: Lock orientation
            connection_timeout: Connection timeout in ms
        """
        self.serial = serial
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.flip = flip
        self.block_frame = block_frame
        self.stay_awake = stay_awake
        self.lock_screen_orientation = lock_screen_orientation
        self.connection_timeout = connection_timeout
        
        # State
        self.alive = False
        self.last_frame: Optional[np.ndarray] = None
        self.resolution: Optional[Tuple[int, int]] = None
        self.device_name: Optional[str] = None
        
        # Sockets
        self.video_socket: Optional[socket.socket] = None
        self.control_socket: Optional[socket.socket] = None
        self.control_socket_lock = threading.Lock()
        
        # Server process
        self.server_process: Optional[subprocess.Popen] = None
        
        # Event listeners
        self.listeners = {EVENT_FRAME: [], EVENT_INIT: []}
        
        # Control sender
        self.control = ControlSender(self)
        
        # Port for forwarding
        self.local_port = 27183
    
    def _adb_cmd(self, *args) -> List[str]:
        """Build ADB command with optional serial."""
        cmd = ["adb"]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd
    
    def _run_adb(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Run ADB command."""
        cmd = self._adb_cmd(*args)
        return subprocess.run(cmd, capture_output=True, **kwargs)

    def _recv_exact(self, sock: socket.socket, length: int, desc: str) -> bytes:
        """Receive exactly `length` bytes or raise a ConnectionError."""
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError(f"Connection closed while receiving {desc}")
            data.extend(chunk)
        return bytes(data)
    
    def _get_server_path(self) -> str:
        """Get path to scrcpy-server file."""
        # Check local directory first
        local_path = os.path.join(os.path.dirname(__file__), "scrcpy-server")
        if os.path.exists(local_path):
            return local_path
        
        # Check for versioned file
        local_versioned = os.path.join(os.path.dirname(__file__), SCRCPY_SERVER_FILENAME)
        if os.path.exists(local_versioned):
            return local_versioned
        
        # Try system locations
        system_paths = [
            "/usr/share/scrcpy/scrcpy-server",
            "/usr/local/share/scrcpy/scrcpy-server",
            os.path.expanduser("~/.local/share/scrcpy/scrcpy-server"),
        ]
        for path in system_paths:
            if os.path.exists(path):
                return path
        
        raise FileNotFoundError(
            f"scrcpy-server not found. Please download from "
            f"https://github.com/Genymobile/scrcpy/releases and place in {os.path.dirname(__file__)}"
        )
    
    def _deploy_server(self) -> None:
        """Deploy scrcpy-server to device."""
        server_path = self._get_server_path()
        remote_path = "/data/local/tmp/scrcpy-server.jar"
        
        # Generate a random SCID (8 hex digits) to avoid socket name collisions
        import random
        scid = f"{random.randint(0, 0x7FFFFFFF):08x}"
        
        print(f"Deploying server from {server_path}...")
        
        # Push server to device
        result = self._run_adb("push", server_path, remote_path)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to push server: {result.stderr.decode()}")
        
        # Set up port forwarding
        self._run_adb("forward", "--remove-all")
        result = self._run_adb("forward", f"tcp:{self.local_port}", f"localabstract:scrcpy_{scid}")
        if result.returncode != 0:
            raise RuntimeError(f"Failed to forward port: {result.stderr.decode()}")
        
        # Start server
        # IMPORTANT: scrcpy v2.x+ protocol:
        # - Sockets connect in order: video -> audio -> control
        # - Server waits for all enabled sockets to connect before sending metadata
        # - We disable audio to simplify the connection (only video + control)
        server_cmd = self._adb_cmd(
            "shell",
            f"CLASSPATH=/data/local/tmp/scrcpy-server.jar",
            "app_process", "/", "com.genymobile.scrcpy.Server",
            SCRCPY_SERVER_VERSION,
            f"scid={scid}",           # Use custom SCID
            f"log_level=debug",  # Changed to debug for better diagnostics
            f"video_bit_rate={self.bitrate}",
            f"max_size={self.max_width}",
            f"max_fps={self.max_fps}",
            "tunnel_forward=true",
            "video=true",             # Enable video
            "audio=false",            # CRITICAL: disable audio to avoid needing audio socket
            "control=true",           # Enable control
            "send_device_meta=true",  # Send device metadata (64 bytes device name)
            "send_codec_meta=true",   # Send codec metadata (codec_id + width + height)
            "send_dummy_byte=true",   # Send dummy byte for connection detection
            "send_frame_meta=true",   # Send frame metadata (PTS + size for each packet)
            "display_id=0",
            "show_touches=false",
            f"stay_awake={'true' if self.stay_awake else 'false'}",
            "power_off_on_close=false",
            "clipboard_autosync=false",
            "downsize_on_error=true",
            "cleanup=true",
            "power_on=true",
        )
        
        print(f"Starting server...")
        self.server_process = subprocess.Popen(
            server_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # Wait for server to start and check if it's running
        print("Waiting for server to initialize...")
        for i in range(30):  # Wait up to 3 seconds
            time.sleep(0.1)
            poll_result = self.server_process.poll()
            if poll_result is not None:
                # Server exited
                stdout, stderr = self.server_process.communicate()
                error_msg = f"Server exited with code {poll_result}\n"
                if stdout:
                    error_msg += f"Stdout: {stdout.decode(errors='replace')}\n"
                if stderr:
                    error_msg += f"Stderr: {stderr.decode(errors='replace')}"
                raise RuntimeError(error_msg)
            
            # After 2 seconds, assume it's probably running
            if i >= 20:
                print("Server appears to be running...")
                break
    
    def _connect(self) -> None:
        """Connect to scrcpy server sockets."""
        print(f"Connecting to server on port {self.local_port}...")
        
        # Connect video socket
        connected = False
        for attempt in range(self.connection_timeout // 100):
            try:
                self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.video_socket.connect(("127.0.0.1", self.local_port))
                connected = True
                print(f"✓ Video socket connected on attempt {attempt + 1}")
                break
            except ConnectionRefusedError:
                if self.video_socket:
                    self.video_socket.close()
                self.video_socket = None
                time.sleep(0.1)
            except Exception as e:
                if self.video_socket:
                    self.video_socket.close()
                self.video_socket = None
                print(f"Connection attempt {attempt + 1} failed: {e}")
                time.sleep(0.1)
        
        if not connected:
            error_msg = "Failed to connect to scrcpy server (video)\n"
            error_msg += "Possible causes:\n"
            error_msg += "  - Device is offline (check 'adb devices')\n"
            error_msg += "  - Port forwarding failed\n"
            error_msg += "  - Server crashed on startup\n"
            if self.server_process and self.server_process.poll() is not None:
                try:
                    stdout, stderr = self.server_process.communicate(timeout=0.5)
                    if stdout:
                        error_msg += f"\nServer stdout: {stdout.decode(errors='replace')}"
                    if stderr:
                        error_msg += f"\nServer stderr: {stderr.decode(errors='replace')}"
                except:
                    pass
            raise ConnectionError(error_msg)
        
        # Set timeout for receiving initial handshake data
        self.video_socket.settimeout(10.0)
        
        # scrcpy v2.x+ protocol for tunnel_forward=true with video=true, audio=false, control=true:
        # 1. Server creates LocalServerSocket
        # 2. Server accepts video socket (first connection)
        # 3. Server sends dummy byte on video socket (if send_dummy_byte=true)
        # 4. Server accepts control socket (second connection, since audio=false)
        # 5. Server sends device metadata on first socket (video) if send_device_meta=true
        # 6. Server sends codec metadata on video socket if send_codec_meta=true
        # 7. Video streaming begins
        
        # Receive dummy byte FIRST (scrcpy v2.x+ protocol)
        # The dummy byte is sent immediately after video socket is accepted
        print("Waiting for dummy byte...")
        try:
            dummy = self._recv_exact(self.video_socket, 1, "dummy byte")
            if dummy != b"\x00":
                raise ConnectionError(f"Expected dummy byte 0x00, got 0x{dummy.hex()}")
            print(f"✓ Received dummy byte: 0x{dummy.hex()}")
        except socket.timeout:
            raise ConnectionError("Timeout waiting for dummy byte from server")
        
        # NOW connect control socket (server is waiting for this before sending metadata)
        # With audio=false, control socket is the second socket
        print("Connecting control socket...")
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_socket.settimeout(10.0)
        self.control_socket.connect(("127.0.0.1", self.local_port))
        print("✓ Control socket connected")
        
        # Receive device metadata: 64 bytes device name (scrcpy v2.x+)
        # Note: The old protocol sent device name + width + height (68 bytes)
        # The new protocol only sends 64 bytes device name; resolution comes in codec metadata
        print("Receiving device metadata...")
        try:
            # scrcpy v2.x+ sends only 64 bytes device name (not the old 68 byte format)
            device_meta = self._recv_exact(self.video_socket, 64, "device metadata")
            self.device_name = device_meta.decode("utf-8", errors='replace').rstrip("\x00")
            print(f"✓ Connected to device: {self.device_name}")
        except socket.timeout:
            raise ConnectionError("Timeout waiting for device metadata")
        
        # Receive codec metadata from video socket (scrcpy v2.1+ protocol)
        # 12 bytes: codec_id (u32) + width (u32) + height (u32)
        print("Receiving video codec metadata...")
        try:
            codec_meta = self._recv_exact(self.video_socket, 12, "codec metadata")
            codec_id, width, height = struct.unpack(">III", codec_meta)
            self.resolution = (width, height)
            
            # Codec IDs: see scrcpy source code
            # v2.0 used enum (0=h264), v2.1+ uses FourCC (e.g. 0x68323634 for h264)
            codec_name = "Unknown"
            if codec_id < 100:
                codec_names = {0: "H264", 1: "H265", 2: "AV1"}
                codec_name = codec_names.get(codec_id, f"UnknownEnum({codec_id})")
            else:
                # Try to decode FourCC
                try:
                    bytes_id = codec_id.to_bytes(4, byteorder='big')
                    codec_name = bytes_id.decode('ascii', errors='replace')
                except:
                    codec_name = f"UnknownFourCC({codec_id})"
            
            print(f"✓ Video codec: {codec_name}")
            print(f"✓ Resolution: {width}x{height}")
        except socket.timeout:
            raise ConnectionError("Timeout waiting for codec metadata")
        
        # Set video socket to non-blocking for streaming
        self.video_socket.setblocking(False)
        print("✓ Connection established successfully!")
    
    def _stream_loop(self) -> None:
        """Main loop for receiving and decoding video stream."""
        if not HAS_AV:
            print("PyAV not available, stream loop disabled")
            return
        
        codec = CodecContext.create("h264", "r")
        
        while self.alive:
            try:
                raw_h264 = self.video_socket.recv(0x10000)
                if not raw_h264:
                    continue
                
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        np_frame = frame.to_ndarray(format="bgr24")
                        if self.flip:
                            np_frame = cv2.flip(np_frame, 1)
                        self.last_frame = np_frame
                        self.resolution = (np_frame.shape[1], np_frame.shape[0])
                        self._send_to_listeners(EVENT_FRAME, np_frame)
                        
            except BlockingIOError:
                time.sleep(0.01)
                if not self.block_frame:
                    self._send_to_listeners(EVENT_FRAME, None)
            except OSError as e:
                if self.alive:
                    print(f"Stream error: {e}")
                break
    
    def add_listener(self, event: str, listener: Callable[..., Any]) -> None:
        """Add event listener."""
        if event in self.listeners:
            self.listeners[event].append(listener)
    
    def remove_listener(self, event: str, listener: Callable[..., Any]) -> None:
        """Remove event listener."""
        if event in self.listeners and listener in self.listeners[event]:
            self.listeners[event].remove(listener)
    
    def _send_to_listeners(self, event: str, *args, **kwargs) -> None:
        """Send event to all listeners."""
        for listener in self.listeners.get(event, []):
            try:
                listener(*args, **kwargs)
            except Exception as e:
                print(f"Listener error: {e}")
    
    def start(self, threaded: bool = False) -> None:
        """
        Start the scrcpy client.
        
        Args:
            threaded: Run stream loop in separate thread
        """
        if self.alive:
            return
        
        self._deploy_server()
        self._connect()
        self.alive = True
        self._send_to_listeners(EVENT_INIT)
        
        if threaded:
            threading.Thread(target=self._stream_loop, daemon=True).start()
        else:
            self._stream_loop()
    
    def stop(self) -> None:
        """Stop the scrcpy client."""
        self.alive = False
        
        if self.video_socket:
            try:
                self.video_socket.close()
            except:
                pass
            self.video_socket = None
        
        if self.control_socket:
            try:
                self.control_socket.close()
            except:
                pass
            self.control_socket = None
        
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=3)
            except:
                self.server_process.kill()
            self.server_process = None
        
        # Clean up port forwarding
        try:
            self._run_adb("forward", "--remove-all")
        except:
            pass
        
        print("Scrcpy client stopped")


# Convenience aliases for compatibility
Client = ScrcpyClient
