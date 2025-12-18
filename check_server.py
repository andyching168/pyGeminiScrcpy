import os
import zipfile

path = "scrcpy-server"
print(f"Checking {path}...")
if not os.path.exists(path):
    print("File not found.")
else:
    size = os.path.getsize(path)
    print(f"Size: {size} bytes")
    
    # Check header
    with open(path, "rb") as f:
        header = f.read(4)
        print(f"Header: {header}")
        
    # Check if valid zip
    try:
        with zipfile.ZipFile(path, 'r') as z:
            print("Valid ZIP/JAR. Contents:")
            for name in z.namelist()[:5]:
                print(f" - {name}")
    except zipfile.BadZipFile:
        print("Invalid ZIP/JAR file.")
    except Exception as e:
        print(f"Error checking zip: {e}")

print("\n--- debug_output.txt content ---")
if os.path.exists("debug_output.txt"):
    with open("debug_output.txt", "r") as f:
        print(f.read())
else:
    print("debug_output.txt not found.")
