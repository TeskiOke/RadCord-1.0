"""
sidebar.py — Left sidebar: channel list + right panel: online users list.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QScrollArea, QFrame, QSizePolicy, QInputDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QFont

SIDEBAR_STYLE = """
QWidget#sidebar { background: #000000; }
QLabel#server-name {
    color: #ffffff; font-size: 15px; font-weight: 800; font-family: 'Segoe UI';
    padding: 10px 16px; border-bottom: 1px solid #111111;
}
QLabel.section-header {
    color: #80848e; font-size: 11px; font-weight: 800; font-family: 'Segoe UI';
    letter-spacing: 0.5px; padding: 10px 8px 2px 16px;
}
QPushButton.channel-btn {
    background: transparent; border: none; border-radius: 4px;
    color: #80848e; font-size: 14px; font-family: 'Segoe UI';
    text-align: left; padding: 4px 10px; margin: 0px 8px;
}
QPushButton.channel-btn:hover { background: #1a1a1a; color: #dbdee1; }
QPushButton.channel-btn[active="true"] { background: #2a2d31; color: #ffffff; }

QPushButton.voice-btn {
    background: transparent; border: none; border-radius: 4px;
    color: #80848e; font-size: 14px; font-family: 'Segoe UI';
    text-align: left; padding: 4px 10px; margin: 0px 8px;
}
QPushButton.voice-btn:hover { background: #1a1a1a; color: #dbdee1; }
QPushButton.voice-btn[active="true"] { color: {accent}; font-weight: 600; }
"""




USERS_STYLE = """
QWidget#users-panel {
    background: #000000;
    border-left: 1px solid #111111;
}
QLabel.section-header {
    color: #80848e;
    font-size: 11px;
    font-weight: 800;
    font-family: 'Segoe UI';
    letter-spacing: 0.5px;
    padding: 18px 12px 4px 12px;
}
QPushButton#btn-screen {
    background: #1a1a1a;
    color: #dbdee1;
    border: none;
    border-radius: 3px;
    font-size: 12px;
    font-family: 'Segoe UI';
    padding: 8px 12px;
    margin: 4px 12px;
    text-align: left;
}
QPushButton#btn-screen:hover { background: #2a2d31; }
QPushButton#btn-screen[sharing="true"]:hover { background: #d84040; }
"""



class AvatarDot(QWidget):
    """Small avatar circle with status indicator."""
    def __init__(self, letter: str, color: str, online: bool = True, size: int = 32):
        super().__init__()
        self._letter  = letter.upper()[:1]
        self._color   = QColor(color)
        self._online  = online
        self._size    = size
        self.setFixedSize(size + 6, size + 6)

    def set_online(self, v: bool):
        self._online = v
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Avatar
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, self._size, self._size)
        # Letter
        p.setPen(QColor("white"))
        f = QFont("Segoe UI", max(1, int(self._size * 0.38)))
        f.setBold(True)
        p.setFont(f)
        p.drawText(0, 0, self._size, self._size, Qt.AlignCenter, self._letter)
        # Status dot
        dot_r = 8
        dot_x = self._size - dot_r + 2
        dot_y = self._size - dot_r + 2
        p.setBrush(QColor("#1e2124"))
        p.drawEllipse(dot_x - 2, dot_y - 2, dot_r + 4, dot_r + 4)
        p.setBrush(QColor("#43b581") if self._online else QColor("#747f8d"))
        p.drawEllipse(dot_x, dot_y, dot_r, dot_r)
        
    def set_speaking(self, speaking: bool):
        self._speaking = speaking
        self.update()


class UserRow(QWidget):
    def __init__(self, device_id: str, nickname: str, color: str,
                 is_self: bool = False, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._is_self = is_self

        self.setFixedHeight(40)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self._avatar = AvatarDot(nickname[:1], color)
        lay.addWidget(self._avatar)

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        suffix = " (ты)" if is_self else ""
        self._name_lbl = QLabel(nickname + suffix)
        self._name_lbl.setStyleSheet(
            "color: #dcddde; font-size: 13px; font-family: 'Segoe UI';"
        )
        name_col.addWidget(self._name_lbl)
        self._status_lbl = QLabel("в сети")
        self._status_lbl.setStyleSheet(
            "color: #72767d; font-size: 10px; font-family: 'Segoe UI';"
        )
        name_col.addWidget(self._status_lbl)
        lay.addLayout(name_col, 1)

        self._ping_lbl = QLabel("")
        self._ping_lbl.setStyleSheet(
            "color: #72767d; font-size: 10px; font-family: 'Segoe UI';"
        )
        lay.addWidget(self._ping_lbl)
        lay.addStretch()

    def set_ping(self, ms: int):
        if ms > 0:
            self._ping_lbl.setText(f"{ms}ms")
            # Color indicator: Green < 100, Yellow < 250, Red > 250
            color = "#43b581" if ms < 100 else "#faa61a" if ms < 250 else "#f04747"
            self._ping_lbl.setStyleSheet(f"color: {color}; font-size: 10px; font-family: 'Segoe UI';")
        else:
            self._ping_lbl.setText("")



class VoiceChannelButton(QPushButton):
    delete_requested = Signal(str)

    def __init__(self, name: str, parent=None):
        super().__init__(f"  🔊  {name}", parent)
        self._name = name

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu
        if self._name == "Голосовой":
            return
        menu = QMenu(self)
        
        act = menu.addAction("🗑 Удалить канал")
        # In a real app we'd check if it's empty, but let's blindly let the user delete it
        action = menu.exec_(event.globalPos())
        if action == act:
            self.delete_requested.emit(self._name)


class VoiceUserRow(QWidget):
    """Small row for a user inside a voice channel."""
    volume_changed = Signal(str, float)

    def __init__(self, device_id: str, nickname: str, color: str, accent_color: str = "#7289da",
                 is_self: bool = False, muted: bool = False, deafened: bool = False, speaking: bool = False, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.is_self = is_self
        self._accent = accent_color
        self._muted = muted
        self.setFixedHeight(24)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(32, 0, 12, 0)
        lay.setSpacing(6)

        # Avatar container for speaking ring
        self._av_container = QWidget()
        self._av_container.setFixedSize(22, 22)
        av_lay = QVBoxLayout(self._av_container)
        av_lay.setContentsMargins(2, 2, 2, 2)
        
        self._av = AvatarDot(nickname[:1], color, size=18)
        av_lay.addWidget(self._av)
        lay.addWidget(self._av_container)
        
        # Name
        self._name_lbl = QLabel(nickname)
        self._name_lbl.setStyleSheet("color: #8e9297; font-size: 13px; font-family: 'Segoe UI';")
        lay.addWidget(self._name_lbl)

        lay.addStretch()

        # Mute/Deafen icons (using crossed out emojis for better visual cue)
        self._mic_ico = QLabel("🎙️\u200D❌")
        self._mic_ico.setVisible(muted)
        self._mic_ico.setStyleSheet("font-size: 10px; color: #ed4245;")
        lay.addWidget(self._mic_ico)

        self._spk_ico = QLabel("🎧\u200D❌")
        self._spk_ico.setVisible(deafened)
        self._spk_ico.setStyleSheet("font-size: 10px; color: #ed4245;")
        lay.addWidget(self._spk_ico)
        
        self._speaking = False
        self.set_speaking(speaking, muted)

    def set_speaking(self, speaking: bool, muted: bool):
        self._speaking = speaking
        if speaking and not muted:
            self._av_container.setStyleSheet(f"background: {self._accent}; border: 1px solid {self._accent}; border-radius: 11px;")
            self._name_lbl.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 600; font-family: 'Segoe UI';")
        else:
            self._av_container.setStyleSheet("background: transparent; border: 1px solid transparent; border-radius: 11px;")
            self._name_lbl.setStyleSheet("color: #8e9297; font-size: 13px; font-family: 'Segoe UI';")
        self._av.set_speaking(speaking and not muted)

    def contextMenuEvent(self, event):
        if self.is_self:
            return
        
        from PySide6.QtWidgets import QMenu, QWidgetAction, QSlider, QWidget, QHBoxLayout
        from PySide6.QtCore import Qt as _Qt
        
        menu = QMenu(self)
        menu.setStyleSheet("QLabel { font-size: 12px; font-weight: 600; background: transparent; }")
        
        title = QLabel("Громкость пользователя")
        act_title = QWidgetAction(menu)
        act_title.setDefaultWidget(title)
        menu.addAction(act_title)
        
        from ui.app import MainWindow
        from PySide6.QtWidgets import QApplication
        main_win = next((w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)), None)

        # Volume row: slider + % label
        vol_widget = QWidget()
        vol_widget.setFixedWidth(240)
        vol_lay = QHBoxLayout(vol_widget)
        vol_lay.setContentsMargins(8, 4, 8, 4)
        vol_lay.setSpacing(8)

        slider = QSlider(_Qt.Horizontal)
        slider.setRange(0, 200)
        current_vol = 100
        if main_win:
            current_vol = int(main_win._audio.get_peer_volume(self.device_id) * 100)
        slider.setValue(current_vol)
        slider.setFixedWidth(160)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { background: #4f545c; height: 4px; border-radius: 2px; }"
            f"QSlider::handle:horizontal {{ background: {self._accent}; width: 14px; height: 14px; border-radius: 7px; margin: -5px 0; }}"
            f"QSlider::sub-page:horizontal {{ background: {self._accent}; border-radius: 2px; }}"
        )

        pct_lbl = QLabel(f"{current_vol}%")
        pct_lbl.setStyleSheet(
            f"color: {self._accent}; font-size: 12px; font-weight: 700;"
            " font-family: 'Segoe UI'; min-width: 42px;"
        )

        slider.valueChanged.connect(lambda v: (
            pct_lbl.setText(f"{v}%"),
            self.volume_changed.emit(self.device_id, v / 100.0)
        ))

        vol_lay.addWidget(slider)
        vol_lay.addWidget(pct_lbl)

        act_slider = QWidgetAction(menu)
        act_slider.setDefaultWidget(vol_widget)
        menu.addAction(act_slider)

        menu.addSeparator()

        if main_win:
            muted_local = main_win._audio.is_peer_locally_muted(self.device_id)
            act_mute = menu.addAction("🔇 Замутить для себя")
            act_mute.setCheckable(True)
            act_mute.setChecked(muted_local)
            act_mute.triggered.connect(lambda v: main_win._audio.set_peer_local_mute(self.device_id, v))
        
        menu.exec_(event.globalPos())



class Sidebar(QWidget):
    channel_selected = Signal(str)   # channel name
    voice_join_requested = Signal(str) # Pass channel name
    voice_leave_requested = Signal(str)
    voice_channel_create_requested = Signal(str)
    voice_channel_delete_requested = Signal(str)
    watch_screen_requested = Signal(str)  # device_id
    user_volume_changed = Signal(str, float)


    def __init__(self, config: dict, accent_color: str = "#7289da", parent=None):
        super().__init__(parent)
        self._config = config
        self._accent = accent_color
        self.setObjectName("sidebar")
        self._apply_style()


        self._active_channel = "general"
        self._active_voice = None # which voice channel we are in
        self._channel_btns: dict[str, QPushButton] = {}
        self._voice_btns: dict[str, QPushButton] = {}
        self._voice_user_lists: dict[str, QVBoxLayout] = {} # channel -> layout
        self._voice_user_widgets: dict[str, list[QWidget]] = {} # channel -> list
        self._in_voice = False

        self._build_ui()
        
        from ui.signals import signals
        signals.voice_state_changed.connect(self.sync_voice_users)
        signals.peer_joined.connect(self.sync_voice_users)
        signals.peer_left.connect(self.sync_voice_users)




    def _apply_style(self):
        style = SIDEBAR_STYLE.replace("{accent}", self._accent)
        self.setStyleSheet(style)

    def set_accent(self, color: str):
        self._accent = color
        self._apply_style()
        self.sync_voice_users()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        net_name = self._config.get("network_name", "RadCord")
        name_lbl = QLabel(f"📡  {net_name}", objectName="server-name")
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        # Text channels
        txt_hdr = QLabel("ТЕКСТОВЫЕ КАНАЛЫ")
        txt_hdr.setProperty("class", "section-header")
        txt_hdr.setStyleSheet("color:#96989d;font-size:11px;font-weight:700;"
                               "font-family:'Segoe UI';letter-spacing:1px;"
                               "padding:16px 8px 6px 16px;")
        lay.addWidget(txt_hdr)

        for ch in ("general", "off-topic"):
            btn = QPushButton(f"  #  {ch}")
            btn.setProperty("class", "channel-btn")
            btn.setStyleSheet(SIDEBAR_STYLE)
            btn.setProperty("active", ch == self._active_channel)
            btn.clicked.connect(lambda _, c=ch: self._select_channel(c))
            self._channel_btns[ch] = btn
            lay.addWidget(btn)

        # Voice channels
        vc_hdr = QWidget()
        vc_lay = QHBoxLayout(vc_hdr)
        vc_lay.setContentsMargins(16, 16, 8, 6)
        lbl = QLabel("ГОЛОСОВЫЕ КАНАЛЫ")
        lbl.setStyleSheet("color:#96989d;font-size:11px;font-weight:700;"
                          "font-family:'Segoe UI';letter-spacing:1px;")
        
        btn_add_vc = QPushButton("+")
        btn_add_vc.setStyleSheet("QPushButton { background: transparent; color: #b9bbbe; font-size: 16px; font-weight: bold; border: none; } QPushButton:hover { color: #dcddde; }")
        btn_add_vc.setFixedSize(24, 24)
        btn_add_vc.clicked.connect(self._prompt_new_voice_channel)
        
        vc_lay.addWidget(lbl)
        vc_lay.addStretch()
        vc_lay.addWidget(btn_add_vc)
        lay.addWidget(vc_hdr)

        self._vc_list_w = QWidget()
        self._vc_list_lay = QVBoxLayout(self._vc_list_w)
        self._vc_list_lay.setContentsMargins(0, 0, 0, 0)
        self._vc_list_lay.setSpacing(0)
        lay.addWidget(self._vc_list_w)
        
        # Add default channel
        self.add_voice_channel("Голосовой")

        lay.addStretch()

    def _select_channel(self, ch: str):
        for name, btn in self._channel_btns.items():
            btn.setProperty("active", str(name == ch).lower())
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._active_channel = ch
        self.channel_selected.emit(ch)

    def _prompt_new_voice_channel(self):
        text, ok = QInputDialog.getText(self, "Новый канал", "Название:")
        if ok and text:
            from core.identity import add_voice_channel_to_config
            from ui.app import MainWindow
            from PySide6.QtWidgets import QApplication
            
            # Find current_net_id from MainWindow
            main_win = next((w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)), None)
            if main_win and main_win._current_net_id:
                add_voice_channel_to_config(main_win._config, main_win._current_net_id, text)
            
            self.voice_channel_create_requested.emit(text)
            self.add_voice_channel(text)


    def add_voice_channel(self, name: str):
        if name in self._voice_btns:
            return
        btn = VoiceChannelButton(name)
        btn.setProperty("class", "voice-btn")
        btn.setStyleSheet(SIDEBAR_STYLE)
        btn.setProperty("active", "false")
        btn.clicked.connect(lambda _, n=name: self._toggle_voice(n))
        btn.delete_requested.connect(self._request_remove_channel)
        self._voice_btns[name] = btn
        self._vc_list_lay.addWidget(btn)

        # Container for users
        user_list_w = QWidget()
        user_lay = QVBoxLayout(user_list_w)
        user_lay.setContentsMargins(0, 0, 0, 0)
        user_lay.setSpacing(0)
        self._vc_list_lay.addWidget(user_list_w)
        self._voice_user_lists[name] = user_lay
        self._voice_user_widgets[name] = []



    def remove_voice_channel(self, name: str):
        if name == "Голосовой": return # Protect default
        btn = self._voice_btns.pop(name, None)
        if btn:
            self._vc_list_lay.removeWidget(btn)
            btn.deleteLater()
            if self._active_voice == name:
                self._toggle_voice(name) # Force leave

    def _request_remove_channel(self, name: str):
        from core.identity import remove_voice_channel_from_config
        from ui.app import MainWindow
        from PySide6.QtWidgets import QApplication
        
        main_win = next((w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)), None)
        if main_win and main_win._current_net_id:
            remove_voice_channel_from_config(main_win._config, main_win._current_net_id, name)
            
        self.voice_channel_delete_requested.emit(name)
        self.remove_voice_channel(name)


    def reset_voice_channels(self):
        """Clear all voice channels except the default one."""
        names = list(self._voice_btns.keys())
        for n in names:
            if n != "Голосовой":
                self.remove_voice_channel(n)
        self._active_voice = None
        self._in_voice = False


    def _toggle_voice(self, name: str):
        if self._active_voice == name:
            # Already in this voice channel, just switch the Main UI view back to voice grid
            self.channel_selected.emit("voice")
            return
        self.join_voice(name)

    def join_voice(self, name: str):
        # Leave old if any (logic cleanup, UI side)
        if self._active_voice and self._active_voice in self._voice_btns:
            self.leave_voice(self._active_voice)
        
        # Join new
        self._in_voice = True
        self._active_voice = name
        btn = self._voice_btns[name]
        btn.setProperty("active", True)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.voice_join_requested.emit(name)

    def leave_voice(self, name: str):
        if name not in self._voice_btns:
            return
        btn = self._voice_btns[name]
        btn.setProperty("active", False)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        
        if self._active_voice == name:
            self._active_voice = None
            self._in_voice = False
            self.voice_leave_requested.emit(name)




    def sync_voice_users(self, *args):
        """Update the sidebar to show who is in which voice channel."""
        from ui.app import MainWindow
        from PySide6.QtWidgets import QApplication
        
        main_win = next((w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)), None)
        if not main_win or not main_win._mesh:
            return

        # 1. Clear existing rows from ALL voice channel layouts
        for name in self._voice_user_lists:
            lay = self._voice_user_lists[name]
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if name in self._voice_user_widgets:
                self._voice_user_widgets[name].clear()

        # 2. Add Local User (Self)
        if main_win._audio.in_voice and main_win._voice_ch_name:
            ch_name = main_win._voice_ch_name
            if ch_name in self._voice_user_lists:
                 # Local user speaking state from _audio
                 speaking = getattr(main_win._audio, 'is_speaking', False)
                 vbar = main_win._voice_bar
                 w = VoiceUserRow(self._config["device_id"], self._config["nickname"], self._config["avatar_color"], 
                                  accent_color=self._accent, is_self=True, muted=vbar._muted, deafened=vbar._deafened, speaking=speaking)
                 self._voice_user_lists[ch_name].addWidget(w)

                 self._voice_user_widgets[ch_name].append(w)

        # 3. Add Remote Peers
        for p in main_win._mesh.peers.values():
            if not p.in_voice:
                continue
            # Accept peer if: they share current network, OR their network_ids is empty
            # (can happen during a timing race — peer connected before network IDs were synced)
            peer_nets = p.network_ids
            if peer_nets and main_win._current_net_id not in peer_nets:
                continue
            ch_name = getattr(p, "voice_channel", "Голосовой")
            if not ch_name:
                ch_name = "Голосовой"
            if ch_name in self._voice_user_lists:
                speaking = getattr(p, "is_speaking", False)
                w = VoiceUserRow(p.device_id, p.nickname, p.avatar_color, accent_color=self._accent,
                                 is_self=False, muted=p.muted, deafened=p.deafened, speaking=speaking)
                w.volume_changed.connect(self.user_volume_changed.emit)
                self._voice_user_lists[ch_name].addWidget(w)
                self._voice_user_widgets[ch_name].append(w)




    def update_voice_speaking(self, device_id: str, speaking: bool):
        for w_list in self._voice_user_widgets.values():
            for w in w_list:
                if w.device_id == device_id:
                    # In VoiceUserRow, set_speaking evaluates (speaking, muted)
                    w.set_speaking(speaking, getattr(w, '_muted', False))
                    return

    @property
    def active_channel(self) -> str:
        return self._active_channel

    @property
    def in_voice(self) -> bool:
        return self._in_voice


class UsersPanel(QWidget):
    watch_screen_requested = Signal(str)  # device_id

    def __init__(self, config: dict, accent_color: str = "#7289da", parent=None):
        super().__init__(parent)
        self._config = config
        self._accent = accent_color
        self.setObjectName("users-panel")
        self.setFixedWidth(200)
        self.setStyleSheet(USERS_STYLE)

        self._rows: dict[str, UserRow] = {}
        self._build_ui()
        # Add self
        self._add_self_row()
        
        from ui.signals import signals
        signals.ping_updated.connect(self.update_ping)


    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        hdr = QLabel("УЧАСТНИКИ")
        hdr.setProperty("class", "section-header")
        hdr.setStyleSheet("color:#96989d;font-size:11px;font-weight:700;"
                          "font-family:'Segoe UI';letter-spacing:1px;"
                          "padding:16px 12px 6px 12px;")
        lay.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}"
                             "QScrollBar:vertical{background:#2f3136;width:6px;}"
                             "QScrollBar::handle:vertical{background:#202225;}")

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 4, 0, 8)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        lay.addWidget(scroll, 1)

        # Watch screen button placeholder — hidden by default
        self._watch_btn = QPushButton("👁  Смотреть экран")
        self._watch_btn.setObjectName("btn-screen")
        self._watch_btn.setStyleSheet(USERS_STYLE)
        self._watch_btn.hide()
        self._watch_btn.clicked.connect(self._on_watch)
        lay.addWidget(self._watch_btn)
        self._watch_target: str | None = None

    def _add_self_row(self):
        row = UserRow(
            self._config["device_id"],
            self._config["nickname"],
            self._config["avatar_color"],
            is_self=True,
        )
        self._rows[self._config["device_id"]] = row
        count = self._list_layout.count()
        self._list_layout.insertWidget(count - 1, row)

    def update_self_profile(self, nickname: str, avatar_color: str):
        did = self._config["device_id"]
        if did in self._rows:
            old_row = self._rows[did]
            new_row = UserRow(did, nickname, avatar_color, is_self=True)
            self._list_layout.replaceWidget(old_row, new_row)
            self._rows[did] = new_row
            old_row.deleteLater()


    def add_peer(self, info: dict):
        did = info["device_id"]
        if did in self._rows:
            return
        row = UserRow(did, info["nickname"], info.get("avatar_color", "#7289da"))
        self._rows[did] = row
        count = self._list_layout.count()
        self._list_layout.insertWidget(count - 1, row)

    def remove_peer(self, device_id: str):
        row = self._rows.pop(device_id, None)
        if row:
            self._list_layout.removeWidget(row)
            row.deleteLater()
        if self._watch_target == device_id:
            self._watch_target = None
            self._watch_btn.hide()

    def clear_peers(self):
        """Clear all peers except self."""
        dids = list(self._rows.keys())
        for did in dids:
            if did != self._config["device_id"]:
                self.remove_peer(did)

    def update_ping(self, device_id: str, ms: int):
        if device_id in self._rows:
            self._rows[device_id].set_ping(ms)



    def update_screen(self, device_id: str, sharing: bool):
        # Show/hide watch button
        if sharing:
            nick = self._rows[device_id]._name_lbl.text() if device_id in self._rows else "?"
            self._watch_target = device_id
            self._watch_btn.setText(f"👁  Смотреть: {self._rows[device_id]._name_lbl.text()}")
            self._watch_btn.show()
        else:
            if self._watch_target == device_id:
                self._watch_target = None
                self._watch_btn.hide()

    def _on_watch(self):
        if self._watch_target:
            self.watch_screen_requested.emit(self._watch_target)
