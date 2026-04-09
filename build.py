import os
import subprocess
import sys
import shutil

def main():
    print("Preparing to build RadCord...")

    # Ensure dependencies are available
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Path to main.py
    main_script = os.path.join(os.path.dirname(__file__), "radmin_discord", "main.py")

    if not os.path.exists(main_script):
        print(f"Error: {main_script} not found.")
        sys.exit(1)

    # PyInstaller arguments
    # --noconsole removes the command prompt window in the background
    # --name changes the output executable name
    # --onefile creates a single .exe
    args = [
        "pyinstaller",
        "--noconsole",
        "--clean",
        "--name", "RadCord",
        "--onefile",
        "--windowed",
        "--add-data", f"radmin_discord/ui;ui",
        "--add-data", f"radmin_discord/core;core",
        "--add-data", f"radmin_discord/shared;shared",
        main_script,
    ]

    print("Running PyInstaller...")
    print(" ".join(args))
    
    # Run PyInstaller
    subprocess.check_call(args)

    print("Build complete! Check the 'dist' directory for RadCord.exe")

if __name__ == "__main__":
    main()
