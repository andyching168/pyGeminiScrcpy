import time
import sys
from scrcpy_client import (
    ScrcpyClient, 
    ACTION_DOWN, ACTION_UP, ACTION_MOVE, 
    KEYCODE_HOME, KEYCODE_BACK, 
    KEYEVENT_ACTION_DOWN, KEYEVENT_ACTION_UP
)

def on_frame(frame):
    pass # We just need the connection to keep alive, not processing frames here

def swipe(client, start_x, start_y, end_x, end_y, steps=10, duration=0.3):
    """
    Simulate a swipe gesture.
    """
    print(f"Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y})")
    
    # Send DOWN
    client.control.touch(start_x, start_y, ACTION_DOWN)
    time.sleep(0.01)
    
    # Send MOVE steps
    for i in range(steps):
        t = (i + 1) / steps
        x = int(start_x + (end_x - start_x) * t)
        y = int(start_y + (end_y - start_y) * t)
        client.control.touch(x, y, ACTION_MOVE)
        time.sleep(duration / steps)
        
    # Send UP
    client.control.touch(end_x, end_y, ACTION_UP)

def main():
    print("Initializing Scrcpy Client...")
    # Use standard settings
    client = ScrcpyClient(max_width=800, bitrate=8000000)
    # Add dummy listener to prevent warning if any
    client.add_listener("frame", on_frame)
    
    print("Connecting to device...")
    try:
        client.start(threaded=True)
    except Exception as e:
        print(f"Failed to start client: {e}")
        return

    # Wait for resolution to ensure connection is fully established
    print("Waiting for device info...")
    for i in range(20):
        if client.resolution:
            break
        time.sleep(0.5)
        if i % 2 == 0:
            print(".", end="", flush=True)
    print()
    
    if not client.resolution:
        print("Could not get device resolution. Is the device connected?")
        print("Stopping client...")
        client.stop()
        return

    width, height = client.resolution
    print(f"Connected! Resolution: {width}x{height}")
    print(f"Device Name: {client.device_name}")

    running = True
    while running:
        print("\n" + "="*40)
        print("      INTERACTIVE CONTROL TEST")
        print("="*40)
        print(" 1. Tap Center")
        print(" 2. Scroll Down (Swipe Up)")
        print(" 3. Scroll Up (Swipe Down)")
        print(" 4. Swipe Left")
        print(" 5. Swipe Right")
        print(" 6. Home Button")
        print(" 7. Back Button")
        print(" 8. Type Text ('Hello Scrcpy')")
        print(" 9. Paste Text (Set Clipboard)")
        print("10. Long Press Center")
        print(" 0. Exit")
        print("-" * 40)
        
        try:
            choice = input("Enter choice (0-10): ").strip()
        except EOFError:
            break

        if choice == '0':
            print("Exiting...")
            running = False
            continue

        if not choice:
            continue

        center_x, center_y = width // 2, height // 2
        
        try:
            if choice == '1':
                print("ACTION: Tap at Center")
                client.control.touch(center_x, center_y, ACTION_DOWN)
                time.sleep(0.05)
                client.control.touch(center_x, center_y, ACTION_UP)
                
            elif choice == '2':
                print("ACTION: Scroll Down (Content moves UP, Finger moves UP)")
                distance = int(height * 0.4)
                # Swipe from bottom-ish to top-ish
                swipe(client, center_x, center_y + distance//2, center_x, center_y - distance//2)
                
            elif choice == '3':
                print("ACTION: Scroll Up (Content moves DOWN, Finger moves DOWN)")
                distance = int(height * 0.4)
                # Swipe from top-ish to bottom-ish
                swipe(client, center_x, center_y - distance//2, center_x, center_y + distance//2)

            elif choice == '4':
                print("ACTION: Swipe Left (Finger moves LEFT)")
                distance = int(width * 0.6)
                swipe(client, center_x + distance//2, center_y, center_x - distance//2, center_y)

            elif choice == '5':
                print("ACTION: Swipe Right (Finger moves RIGHT)")
                distance = int(width * 0.6)
                swipe(client, center_x - distance//2, center_y, center_x + distance//2, center_y)
                
            elif choice == '6':
                print("ACTION: Home Button")
                client.control.keycode(KEYCODE_HOME, KEYEVENT_ACTION_DOWN)
                time.sleep(0.05)
                client.control.keycode(KEYCODE_HOME, KEYEVENT_ACTION_UP)

            elif choice == '7':
                print("ACTION: Back Button")
                client.control.keycode(KEYCODE_BACK, KEYEVENT_ACTION_DOWN)
                time.sleep(0.05)
                client.control.keycode(KEYCODE_BACK, KEYEVENT_ACTION_UP)

            elif choice == '8':
                text = "Hello Scrcpy"
                print(f"ACTION: Type '{text}'")
                client.control.text(text)

            elif choice == '9':
                text = "Clipboard Text"
                print(f"ACTION: Set Clipboard '{text}' & Paste")
                client.control.set_clipboard(text, paste=True)
                
            elif choice == '10':
                print("ACTION: Long Press Center (1s)")
                client.control.touch(center_x, center_y, ACTION_DOWN)
                time.sleep(1.0)
                client.control.touch(center_x, center_y, ACTION_UP)

            else:
                print("Invalid choice. Please enter a number from 0-10.")
        
        except Exception as e:
            print(f"Error executing command: {e}")
            # Try to reconnect or just stop?
            pass
            
        time.sleep(0.2)

    print("Stopping client...")
    client.stop()
    print("Done.")

if __name__ == "__main__":
    main()
