"""
app.py — Main application window.

Wires together: MeshNetwork, PeerDiscovery, AudioManager, ScreenCapture, all UI widgets.
asyncio runs in a background thread; all cross-thread comms use AppSignals.
"""
import asyncio
import logging
import time
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QLabel, QFrame, QSizePolicy, QStackedWidget,
    QMenu, QWidgetAction
)
from PySide6.QtCore import Qt, QTimer, QEvent, QUrl, Signal
import winsound
from PySide6.QtGui import QFont, QColor



from shared.protocol import (
    WS_PORT, BIN_AUDIO, BIN_SCREEN, BIN_STREAM_AUDIO, CHANNEL_DESCS,
    AVATAR_COLORS
)
from core.mesh import MeshNetwork, Peer
from core.discovery import PeerDiscovery
from core.audio import AudioManager
from core.screenshare import ScreenCapture
from core import message_cache
from core.identity import load_config, save_config, add_network, remove_network

from ui.signals import signals
from ui.sidebar import Sidebar, UsersPanel
from ui.chat_view import ChatView
from ui.voice_bar import VoiceBar
from ui.voice_grid import VoiceGridWidget
from ui.screen_view import ScreenViewWindow
from ui.settings_dialog import SettingsDialog
from ui.screen_picker import ScreenPickerDialog
from ui.server_bar import ServerBar
from ui.network_dialog import NetworkDialog


logger = logging.getLogger("app")

MAIN_STYLE_TEMPLATE = """
QMainWindow, QWidget#central {{ background: {bg_main}; }}
QWidget#top-bar {{
    background: {bg_main}; border-bottom: 2px solid {border};
}}
QLabel#channel-title {{
    color: {text_main}; font-size: 15px; font-weight: 700;
    font-family: 'Segoe UI'; padding: 0 8px;
}}
QLabel#channel-desc {{
    color: {text_muted}; font-size: 13px;
    font-family: 'Segoe UI'; padding: 0 8px;
}}
QFrame#input-frame {{
    background: {bg_main};
    border-top: 2px solid {border};
}}
QLineEdit#msg-input {{
    background: {bg_input}; border: 1px solid {border}; border-radius: 8px;
    color: {text_main}; font-size: 14px; font-family: 'Segoe UI'; padding: 11px 16px;
    selection-background-color: {accent};
}}
QLineEdit#msg-input:focus {{ background: {bg_input_focus}; border-color: {accent}; }}
QPushButton#send-btn {{
    background: {accent}; border: none; border-radius: 8px;
    color: white; font-size: 14px; font-weight: 600;
    font-family: 'Segoe UI'; padding: 11px 20px;
}}
QPushButton#send-btn:hover  {{ opacity: 0.8; }}
QPushButton.wm-btn {{
    background: transparent; border: none; color: {text_muted};
    font-size: 14px; font-weight: 600; padding: 2px 10px; font-family: 'Segoe UI';
}}
QPushButton.wm-btn:hover {{ background: {bg_hover}; color: {text_main}; }}
QPushButton#close-btn:hover  {{ background: #f04747; color: white; }}
QPushButton#settings-btn {{
    background: transparent; border: none; color: {text_muted};
    font-size: 18px; padding: 2px 10px;
}}
QPushButton#settings-btn:hover {{ background: {bg_hover}; color: {text_main}; }}

/* Left and Right panels */
QWidget#left-panel {{ border-right: 2px solid {border}; }}
QWidget#users-panel {{ border-left: 2px solid {border}; }}

/* Global QMenu (context menus) */
QMenu {{
    background: {bg_input};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px;
    color: {text_main};
    font-family: 'Segoe UI';
}}
QMenu::item {{
    background: transparent;
    padding: 6px 20px 6px 12px;
    border-radius: 2px;
    margin: 2px 4px;
}}
QMenu::item:selected {{
    background: {accent};
    color: white;
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 0;
}}
"""

THEMES = {
    "dark": {
        "bg_main": "#000000",
        "border": "#2e2e30",   # Soft visible grey
        "text_main": "#ffffff",
        "text_muted": "#96989d", 
        "bg_input": "#000000", 
        "bg_input_focus": "#050505",
        "bg_hover": "#1a1a1a"
    }
}






class MainWindow(QMainWindow):
    _hotkey_mute_signal = Signal()
    _hotkey_deafen_signal = Signal()

    def __init__(self, config: dict, async_loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._config     = config # Combined config: profile + networks
        self._loop       = async_loop
        self._active_ch  = "general"
        self._current_net_id = None

        self._mesh: Optional[MeshNetwork] = None
        self._discovery: Optional[PeerDiscovery] = None
        self._audio: AudioManager = AudioManager(self._loop)
        self._screen: ScreenCapture = ScreenCapture(self._loop)

        self._screen_wins: Dict[str, ScreenViewWindow] = {}
        self._sharing = False
        self._voice_net_id = None
        self._voice_ch_name = None

        self._build_ui()
        self._connect_signals()
        
        # Audio callbacks (global)
        self._audio.on_audio_frame      = self._send_audio
        self._audio.on_speaking_change  = self._on_speaking_change
        # Open audio I/O streams immediately on launch
        # Apply initial volume levels and device selection from config
        prof = self._config["profile"]
        self._audio.set_master_volume(prof.get("master_volume", 100) / 100.0)
        self._audio.set_peers_volume(prof.get("peers_volume", 100) / 100.0)
        self._audio.set_ui_volume(prof.get("ui_volume", 100) / 100.0)
        self._audio.vad_threshold = prof.get("vad_threshold", 400)
        self._audio.device_in  = prof.get("audio_input_device", None)
        self._audio.device_out = prof.get("audio_output_device", None)
        self._audio.start_streams()
        # Screen capture (global)
        self._screen.on_frame = self._send_screen_frame

        # Start core networking once for ALL networks
        mesh_profile = dict(self._config["profile"])
        mesh_profile["_network_ids"] = [n["id"] for n in self._config.get("networks", [])]
        self._mesh = MeshNetwork(mesh_profile, self._loop)
        self._discovery = PeerDiscovery(self._config, on_peer_found=self._mesh.peer_discovered)
        
        # Mesh → Qt signals
        self._mesh.on_peer_join           = lambda p: signals.peer_joined.emit(self._peer_to_dict(p))
        self._mesh.on_peer_leave          = lambda p: signals.peer_left.emit(p.device_id)
        self._mesh.on_text_message        = lambda p, m: signals.text_received.emit(m)
        self._mesh.on_voice_state         = lambda p: signals.voice_state_changed.emit(
            p.device_id, p.in_voice, p.is_speaking)
        self._mesh.on_screen_state_change = lambda p: signals.screen_state_changed.emit(
            p.device_id, p.is_sharing)
        self._mesh.on_voice_frame         = self._on_voice_frame
        self._mesh.on_screen_frame        = lambda p, b: signals.screen_frame_received.emit(
            p.device_id, b)
        self._mesh.on_stream_audio_frame  = lambda p, b: self._audio.receive_peer_stream_audio(
            p.device_id, b)

        self._audio.on_stream_audio_ready = self._send_stream_audio


        asyncio.run_coroutine_threadsafe(self._mesh.start_server(), self._loop)
        asyncio.run_coroutine_threadsafe(self._discovery.start(), self._loop)
        self.setWindowTitle("RadCord")
        self.setMinimumSize(800, 600)
        self.resize(1200, 750)
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowSystemMenuHint)
        
        # Native Windows Frameless resize hack
        import sys
        if sys.platform == 'win32':
            import ctypes
            hwnd = self.winId().__int__()
            user32 = ctypes.windll.user32
            try:
                style = user32.GetWindowLongPtrW(hwnd, -16)
                user32.SetWindowLongPtrW(hwnd, -16, style | 0x00040000 | 0x00C00000 | 0x00020000 | 0x00010000)
            except AttributeError:
                style = user32.GetWindowLongW(hwnd, -16)
                user32.SetWindowLongW(hwnd, -16, style | 0x00040000 | 0x00C00000 | 0x00020000 | 0x00010000)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020|0x0002|0x0001|0x0004|0x0200)
        
        # Audio feedback storage
        import os
        self._ui_sounds = {}
        for snd in ("mute", "unmute", "deafen", "undeafen"):
            path = os.path.abspath(os.path.join(os.getcwd(), "assets", "sounds", f"{snd}.wav"))
            if os.path.exists(path):
                self._ui_sounds[snd] = path
        
        self._apply_theme()

        # Build initial server bar
        self._server_bar.set_networks(self._config.get("networks", []))

        # Check saved voice state - DISABLED auto-join as requested
        # saved_voice = self._config["profile"].get("last_voice")
        # if saved_voice:
        #     QTimer.singleShot(100, lambda: self._auto_join_voice(saved_voice["net_id"], saved_voice["ch_name"]))

    def _auto_join_voice(self, net_id: str, channel_name: str):
        net_info = next((n for n in self._config.get("networks", []) if n["id"] == net_id), None)
        if not net_info: return # Network was deleted
        
        self._voice_net_id = net_id
        self._voice_ch_name = channel_name
        self._audio.in_voice = True
        self._voice_bar.set_in_voice(True, channel_name)
        self._voice_grid.add_peer(self._config["profile"], is_self=True) 
        if self._mesh:
            asyncio.run_coroutine_threadsafe(self._mesh.join_voice(channel_name, net_id), self._loop)
        self._loop.call_soon_threadsafe(self._audio.start_capture_task)
        
        if self._current_net_id == net_id:
            self._sidebar._active_voice = channel_name
            self._sidebar.sync_voice_users()

    def _start_network(self, network_info: dict):
        """No longer used for starting, only for initializing UI state."""
        # This is now handled globally in __init__
        pass


    def _build_ui(self):
        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_title_bar())

        content = QHBoxLayout()
        content.setSpacing(0)
        root.addLayout(content)

        # 1. Server Bar (Far Left)
        self._server_bar = ServerBar()
        self._server_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._server_bar.setObjectName("server-bar")
        self._server_bar.network_selected.connect(self._select_network)
        self._server_bar.add_requested.connect(self._prompt_add_network)
        self._server_bar.remove_requested.connect(self._remove_network)
        self._server_bar.rename_requested.connect(self._rename_network)
        content.addWidget(self._server_bar)

        server_line = QFrame()
        server_line.setFrameShape(QFrame.VLine)
        server_line.setFrameShadow(QFrame.Plain)
        server_line.setFixedWidth(2)
        server_line.setStyleSheet("background-color: #2e2e30; border: none;")
        content.addWidget(server_line)

        # 2. Main content stack
        self._main_stack = QStackedWidget()
        content.addWidget(self._main_stack, 1)

        # 2a. Empty Page (Welcome screen)
        empty_page = QWidget()
        empty_lay = QVBoxLayout(empty_page)
        empty_lay.setAlignment(Qt.AlignCenter)
        well_lbl = QLabel("👋 Привет! Выберите или создайте группу слева.")
        well_lbl.setStyleSheet("color: #72767d; font-size: 18px; font-weight: 600; font-family: 'Segoe UI';")
        empty_lay.addWidget(well_lbl)
        self._main_stack.addWidget(empty_page)

        # 2b. Active Network Page
        active_w = QWidget()
        active_lay = QHBoxLayout(active_w)
        active_lay.setContentsMargins(0, 0, 0, 0)
        active_lay.setSpacing(0)
        self._main_stack.addWidget(active_w)
        
        accent = self._config["profile"].get("app_color", "#7289da")
        self._sidebar = Sidebar(self._config["profile"], accent_color=accent)
        self._voice_bar = VoiceBar(self._config["profile"], accent_color=accent)
        
        self._sidebar.channel_selected.connect(self._on_channel_selected)
        self._sidebar.voice_join_requested.connect(self._join_voice)
        self._sidebar.voice_leave_requested.connect(self._leave_voice)
        self._sidebar.user_volume_changed.connect(lambda d, v: self._audio.set_peer_volume(d, v))
        
        # Thread-safe hotkey connections
        self._hotkey_mute_signal.connect(self._voice_bar._toggle_mute)
        self._hotkey_deafen_signal.connect(self._voice_bar._toggle_deafen)
        
        # Apply hotkeys now that voice_bar exists
        self._apply_hotkeys()


        
        left_panel = QWidget(objectName="left-panel")
        left_panel.setAttribute(Qt.WA_StyledBackground, True)
        left_panel.setFixedWidth(240) # Standard Discord sidebar width
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        left_lay.addWidget(self._sidebar, 1)
        left_lay.addWidget(self._voice_bar)
        active_lay.addWidget(left_panel)

        v_line = QFrame()
        v_line.setFrameShape(QFrame.VLine)
        v_line.setFrameShadow(QFrame.Plain)
        v_line.setFixedWidth(2)
        v_line.setStyleSheet("background-color: #2e2e30; border: none;")
        active_lay.addWidget(v_line)

        # Center area
        center_w = QWidget()
        center_lay = QVBoxLayout(center_w)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)
        active_lay.addWidget(center_w, 1)

        # Top bar (channel info)
        self._top_info_bar = QWidget(objectName="top-bar")
        self._top_info_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._top_info_bar.setFixedHeight(48)
        tb_lay = QHBoxLayout(self._top_info_bar)
        tb_lay.setContentsMargins(16, 0, 16, 0)
        self._ch_title_lbl = QLabel("# general", objectName="channel-title")
        self._ch_desc_lbl  = QLabel(CHANNEL_DESCS["general"], objectName="channel-desc")
        tb_lay.addWidget(self._ch_title_lbl)
        tb_lay.addWidget(self._ch_desc_lbl)
        tb_lay.addStretch()
        center_lay.addWidget(self._top_info_bar)

        # View stack (Chat / Voice Grid)
        self._view_stack = QStackedWidget()
        center_lay.addWidget(self._view_stack, 1)

        self._chat_view = ChatView()
        self._view_stack.addWidget(self._chat_view)

        self._voice_grid = VoiceGridWidget(accent_color=accent)
        self._voice_grid.volume_changed.connect(lambda d, v: self._audio.set_peer_volume(d, v))
        self._voice_grid.watch_screen_requested.connect(self._open_watch_window)
        self._view_stack.addWidget(self._voice_grid)

        # Input bar
        self._input_frame = QFrame(objectName="input-frame")
        self._input_frame.setFixedHeight(72)
        if_lay = QHBoxLayout(self._input_frame)
        if_lay.setContentsMargins(16, 12, 16, 12) 
        self._msg_input = QLineEdit(objectName="msg-input")
        self._msg_input.installEventFilter(self)


        self._msg_input.setPlaceholderText("Написать в #general...")
        self._msg_input.returnPressed.connect(self._send_text)
        if_lay.addWidget(self._msg_input)
        center_lay.addWidget(self._input_frame)

        # Users panel
        self._users_panel = UsersPanel(self._config["profile"], accent_color=accent)
        self._users_panel.watch_screen_requested.connect(self._open_watch_window)
        active_lay.addWidget(self._users_panel)

        self._main_stack.setCurrentIndex(0)


    def _on_channel_selected(self, ch: str):
        if ch == self._active_ch:
            if ch == "voice" and self._view_stack.currentIndex() != 1:
                self._view_stack.setCurrentIndex(1)
            return

        self._active_ch = ch
        
        if ch == "voice":
            self._view_stack.setCurrentWidget(self._voice_grid)
            self._input_frame.hide()
            self._ch_title_lbl.setText("🔊 Голосовой")
            self._ch_desc_lbl.setText("Голосовой канал — участники")
        else:
            self._view_stack.setCurrentWidget(self._chat_view)
            self._input_frame.show()
            self._ch_title_lbl.setText(f"# {ch}")
            self._ch_desc_lbl.setText(CHANNEL_DESCS.get(ch, ""))
            self._msg_input.setPlaceholderText(f"Написать в #{ch}…")
            self._load_cached_messages()



    def _select_network(self, net_id: str):
        if self._current_net_id == net_id:
            return
        
        self._current_net_id = net_id
        
        # Find network config
        net_info = next((n for n in self._config["networks"] if n["id"] == net_id), None)
        if not net_info:
            return

        # 1. Update UI
        self._server_bar.set_active(net_id)
        self._main_stack.setCurrentIndex(1) # Show active UI
        self._view_stack.setCurrentIndex(0) # Show chat
        self._chat_view.clear()
        # Clear ALL cards from voice grid (not just self)
        for did in list(self._voice_grid._cards.keys()):
            self._voice_grid.remove_peer(did)
        self._users_panel.clear_peers()
        self._msg_input.setPlaceholderText(f"Написать в #{self._active_ch}...")
        
        # Reset sidebar/voice channels
        self._sidebar.reset_voice_channels()

        # 2. Start Network (Logic now happens in background, just update UI)
        self._on_channel_selected("general")
        self._sidebar.reset_voice_channels()
        
        # Load persistent dynamic channels
        if "voice_channels" in net_info:
            for vc in net_info["voice_channels"]:
                self._sidebar.add_voice_channel(vc)

        # Update users panel for the new network
        self._users_panel.clear_peers()

        for p in self._mesh.peers.values():
            if net_id in p.network_ids:
                self._users_panel.add_peer(self._peer_to_dict(p))
                # If peer is already in voice — restore their card in voice grid
                if p.in_voice:
                    self._voice_grid.add_peer(self._peer_to_dict(p))


    def _prompt_add_network(self):
        menu = QMenu(self)
        act_create = menu.addAction("➕ Создать сеть")
        act_join = menu.addAction("🔍 Найти сеть")
        action = menu.exec_(self._server_bar.add_btn.mapToGlobal(self._server_bar.add_btn.rect().bottomLeft()))
        
        if action == act_create:
            dlg = NetworkDialog(mode="create", async_loop=self._loop, parent=self)
            if dlg.exec_():
                name, pw = dlg.result_data
                self._config = add_network(self._config, name, pw)
                if self._mesh:
                    self._mesh.config["_network_ids"] = [n["id"] for n in self._config.get("networks", [])]
                self._server_bar.set_networks(self._config["networks"], active_id=self._current_net_id)
        elif action == act_join:
            dlg = NetworkDialog(mode="join", async_loop=self._loop, parent=self)

            if dlg.exec_():
                name, pw = dlg.result_data
                self._config = add_network(self._config, name, pw)
                if self._mesh:
                    self._mesh.config["_network_ids"] = [n["id"] for n in self._config.get("networks", [])]
                self._server_bar.set_networks(self._config["networks"], active_id=self._current_net_id)

    def _remove_network(self, net_id: str):
        from core.message_cache import clear_network_cache
        
        if self._current_net_id == net_id:
             # Stop current if active
             if self._mesh:
                self._loop.call_soon_threadsafe(self._mesh.stop)
             self._current_net_id = None
             self._main_stack.setCurrentIndex(0)


        self._config = remove_network(self._config, net_id)
        clear_network_cache(net_id)
        self._server_bar.set_networks(self._config["networks"], active_id=self._current_net_id)

    def _rename_network(self, net_id: str, old_name: str):
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "Переименовать сеть", "Новое название:", text=old_name)
        if ok and new_name and new_name != old_name:
            for net in self._config.get("networks", []):
                if net["id"] == net_id:
                    net["name"] = new_name
                    from core.identity import save_config
                    save_config(self._config)
                    self._server_bar.set_networks(self._config["networks"], active_id=self._current_net_id)
                    break

    def _make_title_bar(self) -> QWidget:
        bar = QWidget(objectName="top-bar")
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 4, 0)
        lay.setSpacing(0)

        icon = QLabel("📡  RadCord")
        icon.setStyleSheet("color:#7289da;font-size:14px;font-weight:700;font-family:'Segoe UI';")
        lay.addWidget(icon)
        lay.addStretch()

        # Settings button
        btn_sets = QPushButton("⚙")
        btn_sets.setObjectName("settings-btn")
        btn_sets.setFixedSize(36, 36)
        btn_sets.setToolTip("Настройки")
        btn_sets.clicked.connect(self._open_settings)
        lay.addWidget(btn_sets)

        for text, slot in [("─", self.showMinimized), ("□", self._toggle_max)]:
            b = QPushButton(text)
            b.setProperty("class", "wm-btn")
            b.setFixedSize(36, 36)
            b.clicked.connect(slot)
            lay.addWidget(b)

        close = QPushButton("✕")
        close.setProperty("class", "wm-btn")
        close.setObjectName("close-btn")
        close.setFixedSize(36, 36)
        close.clicked.connect(self.close)
        lay.addWidget(close)
        return bar

    def _connect_signals(self):
        from PySide6.QtCore import Qt
        
        signals.peer_joined.connect(self._on_peer_joined, type=Qt.QueuedConnection)
        signals.peer_left.connect(self._on_peer_left, type=Qt.QueuedConnection)
        signals.text_received.connect(self._on_text_received, type=Qt.QueuedConnection)
        signals.voice_state_changed.connect(self._on_voice_state, type=Qt.QueuedConnection)
        signals.screen_state_changed.connect(self._on_screen_state, type=Qt.QueuedConnection)
        signals.screen_frame_received.connect(self._on_screen_frame_qt, type=Qt.QueuedConnection)
        
        signals.self_speaking_changed.connect(self._voice_bar.set_speaking, type=Qt.QueuedConnection)
        signals.self_speaking_changed.connect(
            lambda s: self._voice_grid.update_voice(self._config["profile"]["device_id"], s) if self._audio.in_voice else None,
            type=Qt.QueuedConnection
        )
        signals.self_speaking_changed.connect(
            lambda s: self._sidebar.update_voice_speaking(self._config["profile"]["device_id"], s) if self._audio.in_voice else None,
            type=Qt.QueuedConnection
        )
        
        signals.peer_count_changed.connect(self._voice_bar.set_peer_count, type=Qt.QueuedConnection)

        self._voice_bar.mute_toggled.connect(self._on_mute)
        self._voice_bar.deafen_toggled.connect(self._on_deafen)
        
        signals.voice_channel_added.connect(self._sidebar.add_voice_channel)
        signals.voice_channel_removed.connect(self._sidebar.remove_voice_channel)
        
        self._sidebar.voice_channel_create_requested.connect(
            lambda name: asyncio.run_coroutine_threadsafe(self._mesh.add_voice_channel(name, self._current_net_id), self._loop) if self._mesh else None
        )
        self._sidebar.voice_channel_delete_requested.connect(
            lambda name: asyncio.run_coroutine_threadsafe(self._mesh.remove_voice_channel(name, self._current_net_id), self._loop) if self._mesh else None
        )
        
        self._voice_bar.disconnect_requested.connect(lambda: self._sidebar.leave_voice(self._sidebar._active_voice) if self._sidebar._active_voice else None)

        self._voice_bar.screen_share_requested.connect(self._toggle_screen_share)
        self._voice_bar.settings_requested.connect(self._open_settings)
        self._voice_grid.stream_volume_changed.connect(self._audio.set_peer_stream_volume)

    def _load_cached_messages(self):
        if not self._current_net_id:
            return
        self._chat_view.clear()
        for ch in ("general", "off-topic"):
            if ch != self._active_ch: continue # Only load for active
            cached = message_cache.load_messages(self._current_net_id, ch)
            if not cached: continue
            for msg in cached:
                self._chat_view.add_message(msg)



    def _on_peer_joined(self, info: dict):
        peer_nets = set(info.get("network_ids", []))
        my_nets   = set(n["id"] for n in self._config.get("networks", []))
        # Show peer if they share ANY network with us (even if no network selected yet)
        peer_visible = bool(peer_nets & my_nets) or (self._current_net_id is not None and self._current_net_id in peer_nets)

        if self._current_net_id and self._current_net_id in peer_nets:
            self._users_panel.add_peer(info)
            # Do NOT add to voice_grid here — only add when peer sends voice_join
        elif peer_visible and self._current_net_id is None:
            # No network selected yet but we still track it, will populate on _select_network
            pass

        signals.peer_count_changed.emit(len(self._mesh.peers))

        # Sync dynamic channels (global for all networks we have)
        if self._mesh:
            for net in self._config.get("networks", []):
                if "voice_channels" in net:
                    for vc_name in net["voice_channels"]:
                        asyncio.run_coroutine_threadsafe(
                            self._mesh.add_voice_channel(vc_name, net["id"]), self._loop
                        )

        if self._current_net_id and self._current_net_id in peer_nets:
            sys_msg = {
                "from": "__system__", "nickname": "Система",
                "avatar_color": "#43b581", "channel": self._active_ch,
                "content": f"✅  {info['nickname']} подключился",
                "ts": int(time.time())
            }
            self._chat_view.add_message(sys_msg)

        # If WE are already in voice — announce ourselves ONLY to the new peer
        # (not broadcast to everyone — that causes unexpected state resets)
        if self._audio.in_voice and self._voice_net_id and self._voice_ch_name:
            import uuid as _uuid
            new_peer = self._mesh.peers.get(info.get("device_id"))
            if new_peer:
                asyncio.run_coroutine_threadsafe(
                    self._mesh._send_to(new_peer, {
                        "type": "voice_join",
                        "channel": self._voice_ch_name,
                        "network_id": self._voice_net_id,
                        "msg_id": str(_uuid.uuid4()),
                    }),
                    self._loop
                )


    def _on_peer_left(self, device_id: str):
        peer_name = "Участник"
        if device_id in self._mesh.peers:
            peer_name = self._mesh.peers[device_id].nickname
        self._users_panel.remove_peer(device_id)
        self._voice_grid.remove_peer(device_id)
        self._audio.remove_peer(device_id)
        signals.peer_count_changed.emit(len(self._mesh.peers))
        sys_msg = {"from": "__system__", "nickname": "Система", "avatar_color": "#f04747", "channel": self._active_ch, "content": f"❌  {peer_name} вышел из сети", "ts": int(time.time())}
        self._chat_view.add_message(sys_msg)
        if device_id in self._screen_wins:
            self._screen_wins[device_id].close()
            del self._screen_wins[device_id]

    def _on_text_received(self, msg: dict):
        net_id = msg.get("network_id")
        ch = msg.get("channel", "general")
        
        # Save to cache regardless of visibility
        if net_id:
            message_cache.save_message(net_id, ch, msg)
        
        # Filter for current view
        if net_id == self._current_net_id and ch == self._active_ch:
            self._chat_view.add_message(msg)


    def _on_voice_state(self, device_id: str, in_voice: bool, speaking: bool):
        """Called when a peer's voice state changes (join/leave/speaking)."""
        if not self._mesh:
            return
        peer = self._mesh.peers.get(device_id)
        if peer is None:
            return

        # Consider peer as belonging to current network if:
        # - their network_ids includes current net, OR
        # - their network_ids is empty (timing race — accept them)
        peer_nets = peer.network_ids
        in_current_net = (not peer_nets) or (self._current_net_id in peer_nets)

        if in_voice and in_current_net:
            # Peer joined voice — add card to grid if not there yet
            if device_id not in self._voice_grid._cards:
                peer_dict = self._peer_to_dict(peer)
                self._voice_grid.add_peer(peer_dict)
                self._sidebar.sync_voice_users()
            # Also ensure they appear in UsersPanel
            if device_id not in self._users_panel._rows:
                self._users_panel.add_peer(self._peer_to_dict(peer))
        elif not in_voice:
            # Peer left voice — remove card from grid (no chat notification)
            self._voice_grid.remove_peer(device_id)
            self._sidebar.sync_voice_users()

        self._voice_grid.update_voice(device_id, speaking)
        self._sidebar.update_voice_speaking(device_id, speaking)

    def _on_screen_state(self, device_id: str, sharing: bool):
        self._users_panel.update_screen(device_id, sharing)
        self._voice_grid.update_screen_state(device_id, sharing)
        if not sharing and device_id in self._screen_wins:
            self._screen_wins[device_id].hide()

    def _on_screen_frame_qt(self, device_id: str, jpeg_bytes: bytes):
        if device_id in self._screen_wins and self._screen_wins[device_id].isVisible():
            self._screen_wins[device_id].update_frame(jpeg_bytes)
        self._voice_grid.update_frame(device_id, jpeg_bytes)

    def _send_text(self):
        if not self._current_net_id: return
        text = self._msg_input.text().strip()
        if not text:
            return
        self._msg_input.clear()
        import uuid
        msg_id = str(uuid.uuid4())
        
        own_msg = {
            "msg_id": msg_id,
            "from": self._config["profile"]["device_id"],
            "nickname": self._config["profile"]["nickname"],
            "avatar_color": self._config["profile"]["avatar_color"],
            "channel": self._active_ch,
            "network_id": self._current_net_id,
            "content": text,
            "ts": int(time.time()),
        }
        
        # Mark as seen locally to prevent duplicate from echo
        if self._mesh:
            self._mesh._seen_ids.add(msg_id)
            self._mesh._seen_queue.append(msg_id)

        self._chat_view.add_message(own_msg)
        message_cache.save_message(self._current_net_id, self._active_ch, own_msg)
        asyncio.run_coroutine_threadsafe(self._mesh.send_text(self._active_ch, text, self._current_net_id), self._loop)



    def _join_voice(self, channel_name: str):
        self._voice_net_id = self._current_net_id
        self._voice_ch_name = channel_name
        
        # Find the real network name for display
        net_info = next((n for n in self._config.get("networks", []) if n["id"] == self._current_net_id), None)
        net_name = net_info["name"] if net_info else "Сеть"
        
        self._audio.in_voice = True
        self._voice_bar.set_in_voice(True, f"{channel_name} / {net_name}")
        self._on_channel_selected("voice") 
        self._voice_grid.add_peer(self._config["profile"], is_self=True) 
        asyncio.run_coroutine_threadsafe(self._mesh.join_voice(channel_name, self._voice_net_id), self._loop)
        self._loop.call_soon_threadsafe(self._audio.start_capture_task)
        self._sidebar.sync_voice_users()

    def _leave_voice(self, channel_name: str):
        if self._sharing:
            self._toggle_screen_share()
        self._audio.in_voice = False
        self._voice_bar.set_in_voice(False)
        self._on_channel_selected("general")
        self._voice_grid.remove_peer(self._config["profile"]["device_id"])
        asyncio.run_coroutine_threadsafe(self._mesh.leave_voice(channel_name, self._voice_net_id), self._loop)
        self._loop.call_soon_threadsafe(self._audio.stop_capture_task)
        self._voice_net_id = None
        self._voice_ch_name = None
        self._sidebar.sync_voice_users()



    def _toggle_screen_share(self):
        if not self._sharing:
            picker = ScreenPickerDialog(self)
            if picker.exec() != ScreenPickerDialog.Accepted:
                self._voice_bar.set_screen_sharing(False)
                return
            source = picker.get_result()
            if not source:
                self._voice_bar.set_screen_sharing(False)
                return
            self._sharing = True
            self._voice_bar.set_screen_sharing(True)
            self._screen.configure(source)
            self._screen.start()
            self._on_screen_state(self._config["profile"]["device_id"], True)
            asyncio.run_coroutine_threadsafe(self._mesh.start_screen_share(self._voice_net_id), self._loop)

            # --- Start Audio Capture ---
            import os
            my_pid = os.getpid()
            if source.get("type") == "window":
                target_pid = source.get("pid", 0)
                # Mode 0 = Include only this process
                asyncio.run_coroutine_threadsafe(self._audio.start_system_audio(target_pid, 0), self._loop)
            else:
                # Mode 1 = Exclude OUR application from desktop capture
                asyncio.run_coroutine_threadsafe(self._audio.start_system_audio(my_pid, 1), self._loop)

        else:
            self._sharing = False
            self._voice_bar.set_screen_sharing(False)
            self._screen.stop()
            asyncio.run_coroutine_threadsafe(self._audio.stop_system_audio(), self._loop)
            self._on_screen_state(self._config["profile"]["device_id"], False)
            asyncio.run_coroutine_threadsafe(self._mesh.stop_screen_share(self._voice_net_id), self._loop)


    def _open_watch_window(self, device_id: str):
        peer = self._mesh.peers.get(device_id)
        nick = peer.nickname if peer else device_id
        if device_id not in self._screen_wins:
            self._screen_wins[device_id] = ScreenViewWindow(nick, parent=self)
        self._screen_wins[device_id].show()
        self._screen_wins[device_id].raise_()

    # NOTE: the real _on_voice_state(device_id, in_voice, speaking) is above (line ~508).

    def _play_ui_sound(self, name: str):
        if not hasattr(self, "_sound_paths_vol"):
            import wave, io, os, tempfile, numpy as np
            self._sound_paths_vol = {}
            volume = self._config["profile"].get("ui_volume", 100) / 100.0
            for s_name, s_path in self._ui_sounds.items():
                if not os.path.exists(s_path):
                    continue
                with wave.open(s_path, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    nch, sw, fr, nf = wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
                audio = np.frombuffer(frames, dtype=np.int16).copy()
                if volume != 1.0:
                    audio = np.clip(audio * volume, -32768, 32767).astype(np.int16)
                out_io = io.BytesIO()
                with wave.open(out_io, 'wb') as ow:
                    ow.setnchannels(nch); ow.setsampwidth(sw); ow.setframerate(fr)
                    ow.writeframes(audio.tobytes())
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=tempfile.gettempdir())
                tmp.write(out_io.getvalue()); tmp.close()
                self._sound_paths_vol[s_name] = tmp.name

        if name in getattr(self, "_sound_paths_vol", {}):
            import winsound, threading
            path = self._sound_paths_vol[name]
            threading.Thread(
                target=winsound.PlaySound,
                args=(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT),
                daemon=True
            ).start()

    def _on_mute(self, muted: bool):
        self._audio.muted = muted
        self._play_ui_sound("mute" if muted else "unmute")
        self._voice_grid.update_muted(self._config["profile"]["device_id"], muted)
        if self._mesh and self._voice_net_id:
            asyncio.run_coroutine_threadsafe(
                self._mesh.broadcast_json({
                    "type": "voice_state",
                    "from": self._config["profile"]["device_id"],
                    "muted": muted,
                    "deafened": self._audio.deafened
                }, self._voice_net_id), self._loop
            )
        # Refresh sidebar to show local mute status
        self._sidebar.sync_voice_users()



    def _on_deafen(self, deafened: bool):
        self._audio.deafened = deafened
        self._play_ui_sound("deafen" if deafened else "undeafen")

    def _open_settings(self):
        # Fix spacebar bug by clearing focus from the settings button
        self._voice_bar._btn_set.clearFocus()
        
        dlg = SettingsDialog(self._config["profile"], self._audio, self._loop, parent=self)
        dlg.saved.connect(self._on_settings_saved)
        dlg.exec()


    def _apply_theme(self):
        from PySide6.QtWidgets import QApplication
        theme_name = self._config["profile"].get("theme", "dark")
        accent = self._config["profile"].get("app_color", "#7289da")
        colors = THEMES.get(theme_name, THEMES["dark"]).copy()
        colors["accent"] = accent
        
        style = MAIN_STYLE_TEMPLATE.format(**colors)
        self.setStyleSheet(style)

        # Apply QMenu style globally so popup windows (which don't inherit
        # the main window stylesheet) also get the dark theme.
        qmenu_style = (
            "QMenu {{"
            "  background: #000000;"
            f"  border: 1px solid {colors['border']};"
            "  border-radius: 4px; padding: 4px;"
            f"  color: {colors['text_main']}; font-family: 'Segoe UI';"
            "}}"
            "QMenu::item {{ background: transparent; padding: 6px 20px 6px 12px;"
            "  border-radius: 2px; margin: 2px 4px; }}"
            f"QMenu::item:selected {{ background: {accent}; color: white; }}"
            f"QMenu::separator {{ height: 1px; background: {colors['border']}; margin: 4px 0; }}"
        )
        QApplication.instance().setStyleSheet(qmenu_style)

        # Update sub-widgets if they have internal styles
        if hasattr(self, "_server_bar"):
            self._server_bar.set_accent(accent)
        if hasattr(self, "_sidebar"):
            self._sidebar.set_accent(accent)
        if hasattr(self, "_voice_bar"):
            self._voice_bar._accent = accent
            # Force update speaking indicators if any
            self._voice_bar.set_speaking(self._voice_bar._speaking)
        if hasattr(self, "_voice_grid"):
            self._voice_grid.set_accent(accent)

    def _on_settings_saved(self, new_config: dict, changed: list):
        self._config["profile"].update(new_config)
        save_config(self._config)
        
        if "nickname" in changed or "avatar_color" in changed:
            # 1. Update local UI
            nick = self._config["profile"]["nickname"]
            color = self._config["profile"]["avatar_color"]
            self._voice_bar.update_profile(nick, color)
            self._users_panel.update_self_profile(nick, color)
            self._sidebar.sync_voice_users() # Refresh name in voice list
            
            # 2. Broadcast identity update
            if self._mesh:
                asyncio.run_coroutine_threadsafe(self._mesh.broadcast_json(self._mesh._identity_dict()), self._loop)


        if "theme" in changed or "app_color" in changed:
            self._apply_theme()
            
        if any(c in changed for c in ["audio_input", "audio_output"]):
            prof = self._config["profile"]
            self._audio.device_in  = prof.get("audio_input_device", None)
            self._audio.device_out = prof.get("audio_output_device", None)
            was_in_voice = self._audio.in_voice
            self._audio.stop_streams()
            self._audio.start_streams()
            # If user was in voice — resume audio capture automatically
            if was_in_voice:
                self._audio.in_voice = True
                QTimer.singleShot(400, lambda: self._loop.call_soon_threadsafe(self._audio.start_capture_task))

        if "vad_threshold" in changed:
            new_thresh = self._config["profile"].get("vad_threshold", 400)
            self._audio.vad_threshold = new_thresh

        if "hotkeys" in changed:
            self._apply_hotkeys()

        # Apply volume settings to audio engine
        if any(c in changed for c in ["master_volume", "peers_volume", "ui_volume"]):
            prof = self._config["profile"]
            self._audio.set_master_volume(prof.get("master_volume", 100) / 100.0)
            self._audio.set_peers_volume(prof.get("peers_volume", 100) / 100.0)
            self._audio.set_ui_volume(prof.get("ui_volume", 100) / 100.0)
            if "ui_volume" in changed and hasattr(self, "_sound_paths_vol"):
                import os
                for p in self._sound_paths_vol.values():
                    try: os.unlink(p)
                    except Exception: pass
                delattr(self, "_sound_paths_vol")



    def _apply_hotkeys(self):
        """Register global keyboard/mouse hotkeys from config."""
        try:
            import keyboard as kb
            kb.unhook_all()
        except Exception:
            pass

        try:
            import mouse as ms
            # Remove previous mouse hooks safely
            try: ms.unhook_all()
            except Exception: pass
        except Exception:
            pass

        hotkeys = self._config["profile"].get("hotkeys", {})
        hk_mute   = hotkeys.get("hotkey_mute", "").strip()
        hk_deafen = hotkeys.get("hotkey_deafen", "").strip()

        def _do_mute(*args, **kwargs):
            self._hotkey_mute_signal.emit()

        def _do_deafen(*args, **kwargs):
            self._hotkey_deafen_signal.emit()

        import logging
        logger = logging.getLogger("app")

        if hk_mute:
            if hk_mute in ("mouse4", "mouse5", "mouse3", "mouse3 (СКМ)"):
                btn_name = {"mouse4": "x", "mouse5": "x2", "mouse3": "middle", "mouse3 (СКМ)": "middle"}.get(hk_mute, "x")
                try:
                    import mouse as ms
                    ms.on_button(_do_mute, buttons=(btn_name,), types=("down",))
                    logger.info(f"Mouse mute hotkey set: {btn_name}")
                except Exception as e:
                    logger.warning(f"Mouse hotkey failed: {e}")
            else:
                try:
                    import keyboard as kb
                    kb.add_hotkey(hk_mute, _do_mute, suppress=False)
                    logger.info(f"Keyboard mute hotkey set: {hk_mute}")
                except Exception as e:
                    logger.warning(f"Keyboard hotkey failed: {e}")

        if hk_deafen:
            if hk_deafen in ("mouse4", "mouse5", "mouse3", "mouse3 (СКМ)"):
                btn_name = {"mouse4": "x", "mouse5": "x2", "mouse3": "middle", "mouse3 (СКМ)": "middle"}.get(hk_deafen, "x2")
                try:
                    import mouse as ms
                    ms.on_button(_do_deafen, buttons=(btn_name,), types=("down",))
                    logger.info(f"Mouse deafen hotkey set: {btn_name}")
                except Exception as e:
                    logger.warning(f"Mouse hotkey failed: {e}")
            else:
                try:
                    import keyboard as kb
                    kb.add_hotkey(hk_deafen, _do_deafen, suppress=False)
                    logger.info(f"Keyboard deafen hotkey set: {hk_deafen}")
                except Exception as e:
                    logger.warning(f"Keyboard hotkey failed: {e}")


    def _on_voice_frame(self, peer: Peer, payload: bytes):
        self._audio.receive_peer_audio(peer.device_id, payload)

    async def _send_audio(self, audio_bytes: bytes):
        if self._mesh:
            await self._mesh.broadcast_audio_to_voice(audio_bytes, self._voice_net_id)

    async def _on_speaking_change(self, speaking: bool):
        signals.self_speaking_changed.emit(speaking)
        if self._mesh and self._voice_net_id:
            try:
                await self._mesh.set_speaking(speaking, self._voice_net_id)
            except Exception:
                pass


    async def _send_screen_frame(self, jpeg_bytes: bytes):
        signals.screen_frame_received.emit(self._config["profile"]["device_id"], jpeg_bytes)
        if self._mesh: await self._mesh.broadcast_binary(BIN_SCREEN, jpeg_bytes)

    async def _send_stream_audio(self, audio_bytes: bytes):
        if self._sharing and self._mesh:
            await self._mesh.broadcast_stream_audio(audio_bytes, self._voice_net_id)


    def _toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def nativeEvent(self, eventType, message):
        if eventType != b"windows_generic_MSG":
            return super().nativeEvent(eventType, message)

        import sys
        if sys.platform == 'win32':
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(message.__int__())
            if msg.message == 0x0083: # WM_NCCALCSIZE
                if msg.wParam:
                    return True, 0
                    
            if msg.message == 0x0084: # WM_NCHITTEST
                pos = self.mapFromGlobal(self.cursor().pos())
                x, y = pos.x(), pos.y()
                w, h = self.width(), self.height()
                m = 8 # Resize grab margin

                if x < m and y < m: return True, 13 # HTTOPLEFT
                if x > w - m and y < m: return True, 14 # HTTOPRIGHT
                if x < m and y > h - m: return True, 16 # HTBOTTOMLEFT
                if x > w - m and y > h - m: return True, 17 # HTBOTTOMRIGHT
                if x < m: return True, 10 # HTLEFT
                if x > w - m: return True, 11 # HTRIGHT
                if y < m: return True, 12 # HTTOP
                if y > h - m: return True, 15 # HTBOTTOM

        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < 40:
            self._drag_start  = event.globalPosition().toPoint()
            self._win_start   = self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if (event.buttons() == Qt.LeftButton and hasattr(self, "_drag_start") and event.position().y() < 40):
            self.move(self._win_start + event.globalPosition().toPoint() - self._drag_start)

    def closeEvent(self, event):
        # Save voice state
        if self._audio.in_voice and self._voice_net_id and self._voice_ch_name:
            self._config["profile"]["last_voice"] = {
                "net_id": self._voice_net_id,
                "ch_name": self._voice_ch_name
            }
        else:
            if "last_voice" in self._config["profile"]:
                del self._config["profile"]["last_voice"]
        from core.identity import save_config
        save_config(self._config)

        self._audio.stop_streams()
        self._screen.stop()
        if self._discovery: self._discovery.stop()
        if self._mesh: self._loop.call_soon_threadsafe(self._mesh.stop)
        super().closeEvent(event)

    @staticmethod
    def _peer_to_dict(peer: Peer) -> dict:
        return {
            "device_id":    peer.device_id,
            "nickname":     peer.nickname,
            "avatar_color": peer.avatar_color,
            "ip":           peer.ip,
            "network_ids":  list(peer.network_ids),
            "sharing":      peer.is_sharing,
        }

