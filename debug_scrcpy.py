from scrcpy_client import ScrcpyClient
import time
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def main():
    print("Starting debug run...")
    client = ScrcpyClient(
        max_width=800,
        bitrate=8000000
    )
    
    try:
        print("Starting client...")
        client.start(threaded=True)
        print("Client started. Waiting for connection...")
        
        # Give it a few seconds
        for i in range(5):
            print(f"Tick {i}...")
            if client.video_socket:
                print("Video socket connected!")
            if client.resolution:
                print(f"Got resolution: {client.resolution}")
                break
            time.sleep(1)
            
    except Exception as e:
        print(f"Caught exception: {e}")
    finally:
        print("Stopping client...")
        client.stop()

if __name__ == "__main__":
    main()
