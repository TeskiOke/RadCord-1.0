"""
signals.py — Qt signal bus used to safely cross the asyncio ↔ Qt boundary.

All network callbacks emit signals here; UI widgets connect to them.
"""
from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    # Peer lifecycle
    peer_joined  = Signal(dict)   # {"device_id", "nickname", "avatar_color", "ip"}
    peer_left    = Signal(str)    # device_id

    # Chat
    text_received = Signal(dict)  # full message dict

    # Voice state (from a peer)
    voice_state_changed = Signal(str, bool, bool)
    # args: device_id, in_voice, is_speaking

    # Screen share state
    screen_state_changed = Signal(str, bool)
    # args: device_id, is_sharing

    # Incoming screen frame (JPEG bytes) from a specific sharer
    screen_frame_received = Signal(str, bytes)
    # args: device_id, jpeg_bytes

    # Self speaking indicator (from VAD)
    self_speaking_changed = Signal(bool)

    # Connection count changed
    peer_count_changed = Signal(int)

    # Dynamic Voice channels
    voice_channel_added = Signal(str)
    voice_channel_removed = Signal(str)

    # Ping/RTT updates
    ping_updated = Signal(str, int)  # device_id, rtt_ms



# Singleton – import and use everywhere
signals = AppSignals()
