# Message types (JSON)
MSG_TEXT = "text"
MSG_VOICE_JOIN = "voice_join"
MSG_VOICE_LEAVE = "voice_leave"
MSG_VOICE_SPEAKING = "voice_speaking"
MSG_SCREEN_START = "screen_start"
MSG_SCREEN_STOP = "screen_stop"
MSG_IDENTIFY = "identify"
MSG_VOICE_STATE = "voice_state"   # broadcasts muted/deafened flags
MSG_PING = "ping"
MSG_PONG = "pong"

# Binary frame types
BIN_AUDIO = 0x01
BIN_SCREEN = 0x02

# Network constants
WS_PORT = 8765
UDP_DISCOVERY_PORT = 8766
UDP_BROADCAST_ADDRS = ["26.255.255.255", "255.255.255.255"]
UDP_INTERVAL = 5.0

APP_VERSION = "1.0"

# Audio constants
AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "int16"
AUDIO_CHUNK_FRAMES = 960   # 20ms at 48kHz
AUDIO_RMS_THRESHOLD = 400  # VAD threshold

# Screen share constants (defaults; overridden by user settings)
SCREEN_FPS = 15
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
SCREEN_JPEG_QUALITY = 60

# Quality presets  (label, width, height, jpeg_quality)
QUALITY_PRESETS = [
    ("🔴 360p  — Низкое",   640,  360, 35),
    ("🟡 480p  — Среднее",  854,  480, 50),
    ("🟢 720p  — Высокое",  1280, 720, 65),
    ("🔵 1080p — Отличное", 1920, 1080, 82),
]
FPS_OPTIONS = [15, 20, 24, 30, 45, 60]

# Colors
AVATAR_COLORS = [
    "#7289da", "#43b581", "#faa61a", "#f04747",
    "#593695", "#1abc9c", "#e91e63", "#ff9800",
]
# UI Contexts
CHANNEL_DESCS = {
    "general":   "Главный чат — общайся с командой",
    "off-topic": "Офтоп, мемы и всё остальное",
}
