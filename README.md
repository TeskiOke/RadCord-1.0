# RadCord

P2P communication tool (Text, Voice, Screenshare) designed for use over Radmin VPN or local networks.

## Features
- **P2P Mesh Network**: No central server, direct connections between peers.
- **Voice Chat**: Real-time voice communication with VAD (Voice Activity Detection).
- **Screenshare**: Share your screen or specific windows with peers.
- **Global Hotkeys**: Bind Mute/Deafen to any key or mouse button (Mouse 4/5 supported).
- **Advanced Audio Mixer**: 0-200% volume control for each participant.
- **Cursor Capture**: Visualizes the cursor during screenshare.
- **Security**: Designed for private, trusted networks (Radmin VPN / LAN).

## Current Status
Check [PROJECT_STATUS.md](PROJECT_STATUS.md) for detailed implementation progress and known limitations.

## How to run
1. Install requirements: `pip install -r radmin_discord/requirements.txt`
2. Run `python radmin_discord/main.py`
