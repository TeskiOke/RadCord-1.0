"""
voice_bar.py — Bottom-left panel containing the active voice status and user profile.
"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ui.chat_view import AvatarLabel

logger = logging.getLogger("voice_bar")

STYLE = """
QWidget {
    background: #000000;
}
QWidget#active-call {
    background: #000000;
    border-bottom: 1px solid #1e1f22;
}
QLabel#vc-status {
    color: #43b581; font-size: 13px; font-weight: 600; font-family: 'Segoe UI';
}
QLabel#vc-channel {
    color: #949ba4; font-size: 11px; font-family: 'Segoe UI';
}
QPushButton.call-action {
    background: #2b2d31; color: #b5bac1; border-radius: 4px; border: none;
    font-size: 14px; font-weight: 700;
}
QPushButton.call-action:hover {
    background: #313338; color: #dbdee1;
}
QPushButton.call-action:checked {
    background: #43b581; color: white;
}
QPushButton#btn-disconnect {
    background: transparent; color: #b5bac1; border: none; border-radius: 4px;
    font-size: 18px;
}
QPushButton#btn-disconnect:hover {
    background: #313338; color: #f23f43;
}

QLabel#user-name {
    color: #f2f3f5; font-size: 13px; font-weight: 700; font-family: 'Segoe UI';
}
QLabel#user-status {
    color: #b5bac1; font-size: 11px; font-family: 'Segoe UI';
}
QPushButton.user-btn {
    background: transparent; color: #b5bac1; border: none; border-radius: 4px;
    font-size: 15px; padding: 6px;
}
QPushButton.user-btn:hover {
    background: #313338; color: #dbdee1;
}
"""

class VoiceBar(QWidget):
    mute_toggled = Signal(bool)
    deafen_toggled = Signal(bool)
    
    # New signals for the active call panel
    disconnect_requested = Signal()
    screen_share_requested = Signal()
    disconnect_clicked = Signal()
    settings_requested = Signal()

    def __init__(self, profile_config: dict, accent_color: str = "#7289da", parent=None):
        super().__init__(parent)
        self._profile = profile_config
        self._accent = accent_color
        self.setObjectName("voice-bar")
        self.setMinimumHeight(55)
        self.setStyleSheet(STYLE)

        self._muted = False
        self._was_manually_muted = False
        self._deafened = False
        self._speaking = False
        self._sharing = False
        
        self.setFixedWidth(240)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Active Call Module (Hidden by default) ──
        self._call_panel = QWidget(objectName="active-call")
        call_lay = QVBoxLayout(self._call_panel)
        call_lay.setContentsMargins(8, 8, 8, 8)
        call_lay.setSpacing(8)

        # Top row: info + disconnect
        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self._vc_status_lbl = QLabel("Голос подключен", objectName="vc-status")
        self._vc_lbl = QLabel("Канал", objectName="vc-channel")
        text_col.addWidget(self._vc_status_lbl)
        text_col.addWidget(self._vc_lbl)
        info_row.addLayout(text_col, 1)

        self._btn_disconnect = QPushButton("📞", objectName="btn-disconnect")
        self._btn_disconnect.setFixedSize(32, 32)
        self._btn_disconnect.setToolTip("Отключиться")
        self._btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        info_row.addWidget(self._btn_disconnect)
        
        call_lay.addLayout(info_row)


        # Bottom row: Action buttons
        act_row = QHBoxLayout()
        act_row.setSpacing(6)
        
        self._btn_screen = QPushButton("🖥")
        self._btn_screen.setProperty("class", "call-action")
        self._btn_screen.setFixedHeight(32)
        self._btn_screen.setCheckable(True)
        self._btn_screen.setToolTip("Поделиться экраном")
        self._btn_screen.clicked.connect(self.screen_share_requested.emit)
        
        act_row.addWidget(self._btn_screen)
        call_lay.addLayout(act_row)
        
        self._call_panel.hide()
        root.addWidget(self._call_panel)

        # ── User Profile Panel ──
        self._user_panel = QWidget()
        self._user_panel.setFixedHeight(52)
        user_lay = QHBoxLayout(self._user_panel)
        user_lay.setContentsMargins(8, 0, 8, 0)
        user_lay.setSpacing(6)

        # Avatar container (for border when speaking)
        self._av_container = QWidget()
        self._av_container.setFixedSize(36, 36)
        av_lay = QVBoxLayout(self._av_container)
        av_lay.setContentsMargins(0, 0, 0, 0)
        self._avatar = AvatarLabel(self._profile["nickname"][:1], self._profile["avatar_color"])
        av_lay.addWidget(self._avatar, 0, Qt.AlignCenter)
        user_lay.addWidget(self._av_container)

        u_col = QVBoxLayout()
        u_col.setSpacing(0)
        u_col.setAlignment(Qt.AlignVCenter)
        self._name_lbl = QLabel(self._profile["nickname"], objectName="user-name")
        self._status_lbl = QLabel("В сети", objectName="user-status")
        u_col.addWidget(self._name_lbl)
        u_col.addWidget(self._status_lbl)
        user_lay.addLayout(u_col, 1)

        # Mic/Deafen/Settings
        self._btn_mute = QPushButton("🎙")
        self._btn_mute.setProperty("class", "user-btn")
        self._btn_mute.setFixedSize(32, 32)
        self._btn_mute.setToolTip("Микрофон")
        self._btn_mute.clicked.connect(self._toggle_mute)

        self._btn_deaf = QPushButton("🎧")
        self._btn_deaf.setProperty("class", "user-btn")
        self._btn_deaf.setFixedSize(32, 32)
        self._btn_deaf.setToolTip("Наушники")
        self._btn_deaf.clicked.connect(self._toggle_deafen)

        self._btn_set = QPushButton("⚙")
        self._btn_set.setProperty("class", "user-btn")
        self._btn_set.setFixedSize(32, 32)
        self._btn_set.setToolTip("Настройки")
        self._btn_set.clicked.connect(self.settings_requested.emit)

        user_lay.addWidget(self._btn_mute)
        user_lay.addWidget(self._btn_deaf)
        user_lay.addWidget(self._btn_set)

        root.addWidget(self._user_panel)

    def update_profile(self, nickname: str, avatar_color: str):
        self._profile["nickname"] = nickname
        self._profile["avatar_color"] = avatar_color
        self._name_lbl.setText(nickname)
        # Re-create or update avatar
        from ui.chat_view import AvatarLabel
        self._avatar.deleteLater()
        self._avatar = AvatarLabel(nickname[:1], avatar_color)
        self._av_container.layout().addWidget(self._avatar)

    def set_in_voice(self, in_voice: bool, channel_name: str = ""):
        self._in_voice = in_voice
        self._call_panel.setVisible(in_voice)
        if in_voice:
            self._vc_lbl.setText(f"🔊 {channel_name}")
        else:
            self.set_speaking(False)
            self._btn_screen.setChecked(False)

    def set_speaking(self, speaking: bool):
        self._speaking = speaking
        if speaking and not self._muted:
            self._av_container.setStyleSheet(f"background: {self._accent}; border-radius: 18px;")
        else:
            self._av_container.setStyleSheet("background: transparent; border-radius: 18px;")

    def set_screen_sharing(self, sharing: bool):
        self._sharing = sharing
        self._btn_screen.setChecked(sharing)
        self._btn_screen.setText("❌" if sharing else "🖥")
        self._btn_screen.setToolTip("Прекратить стрим" if sharing else "Поделиться экраном")




    def set_peer_count(self, count: int):
        self._status_lbl.setText(f"В сети (пиров: {count})")

    def _toggle_mute(self):
        if self._deafened:
            # If deafened, toggling mute unmutes speakers too
            self._toggle_deafen()
            return

        self._was_manually_muted = not self._muted
        self._set_muted_state(self._was_manually_muted)

    def _toggle_deafen(self):
        self._deafened = not self._deafened
        if self._deafened:
            # Deafening forces mic to mute
            self._btn_deaf.setText("🎧❌")
            self._btn_deaf.setStyleSheet("color: #f04747;")
            self._set_muted_state(True)
        else:
            # Undeafening
            self._btn_deaf.setText("🎧")
            self._btn_deaf.setStyleSheet("")
            # Restore previous mute state
            self._set_muted_state(self._was_manually_muted)

        self.deafen_toggled.emit(self._deafened)

    def _set_muted_state(self, muted: bool):
        if self._muted == muted:
            return
        self._muted = muted
        if self._muted:
            self._btn_mute.setText("🔇")
            self._btn_mute.setStyleSheet("color: #f04747;")
            self.set_speaking(False)
        else:
            self._btn_mute.setText("🎙")
            self._btn_mute.setStyleSheet("")
        self.mute_toggled.emit(self._muted)
