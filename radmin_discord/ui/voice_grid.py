"""
voice_grid.py — Grid of participant cards for the active voice channel.
Replaces the ChatView when looking at a voice channel.
"""
import logging
from typing import Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QGridLayout, QMenu, QWidgetAction, QSlider, QStackedWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QImage

from ui.chat_view import AvatarLabel

logger = logging.getLogger("voice_grid")


class GridContainer(QWidget):
    """Responsive grid that auto-reshuffles cards when the widget resizes."""

    CARD_MIN_W = 220
    SPACING    = 16
    MARGIN     = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(self.SPACING)
        self._grid.setContentsMargins(
            self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN
        )

    # ── public API ──────────────────────────────────────────────────────────

    def addCard(self, card: QWidget):
        card.setParent(self)
        self._items.append(card)
        self._relayout()

    def removeCard(self, card: QWidget):
        if card in self._items:
            self._items.remove(card)
            self._grid.removeWidget(card)
            card.hide()
            self._relayout()

    # ── internal ────────────────────────────────────────────────────────────

    def _relayout(self):
        # Strip all current grid positions without deleting widgets
        while self._grid.count():
            self._grid.takeAt(0)

        n = len(self._items)
        if not n:
            return

        import math
        cols = max(1, math.ceil(math.sqrt(n)))
        if n == 2: cols = 2  # Special case for 2: side by side

        # Clear existing stretches
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)

        # Re-add items
        for i, item in enumerate(self._items):
            r, c = divmod(i, cols)
            # Add with offset of +1 to allow row/col 0 for stretch spacers
            self._grid.addWidget(item, r + 1, c + 1, Qt.AlignCenter)
            item.show()

        # Add flexible margins around the grid to constantly keep cards centered
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(cols + 1, 1)
        
        total_rows = (n - 1) // cols + 1
        self._grid.setRowStretch(0, 1)
        self._grid.setRowStretch(total_rows + 1, 1)



class VoicePeerCard(QWidget):
    """Single participant tile displayed in the voice grid."""

    volume_changed = Signal(str, float)
    watch_screen_requested = Signal(str)

    def __init__(self, device_id: str, nickname: str, avatar_color: str,
                 accent_color: str = "#7289da", is_self: bool = False,
                 parent=None):
        super().__init__(parent)
        self.device_id   = device_id
        self.nickname    = nickname
        self.avatar_color = avatar_color
        self._accent     = accent_color
        self._is_self    = is_self
        self._is_sharing = False
        self._is_muted   = False
        self._is_speaking = False

        # Fixed size boundaries, but allow expansion
        self.setMinimumSize(220, 180)
        self.setMaximumSize(800, 450)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._build_ui()

    # ── build ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Card background ──
        self._bg = QWidget()
        self._bg.setObjectName("cardBg")
        self._bg.setStyleSheet("#cardBg { background: #1a1b1e; border-radius: 10px; border: 3px solid transparent; }")
        bg_lay = QVBoxLayout(self._bg)
        bg_lay.setContentsMargins(8, 12, 8, 8)
        bg_lay.setSpacing(6)

        # ── View stack: avatar OR screen share ──
        self._view_stack = QStackedWidget()

        # Page 0 — avatar (centered)
        av_page = QWidget()
        av_page_lay = QVBoxLayout(av_page)
        av_page_lay.setContentsMargins(0, 0, 0, 0)
        av_page_lay.setAlignment(Qt.AlignCenter)

        self._avatar = AvatarLabel(self.nickname[:1], self.avatar_color)
        self._avatar.setFixedSize(74, 74)
        av_page_lay.addWidget(self._avatar, 0, Qt.AlignCenter)
        
        self._view_stack.addWidget(av_page)          # index 0

        # Page 1 — screen share
        self._screen_lbl = QLabel()
        self._screen_lbl.setAlignment(Qt.AlignCenter)
        self._screen_lbl.setStyleSheet("background: #000000; border-radius: 6px;")
        self._view_stack.addWidget(self._screen_lbl) # index 1

        self._view_stack.setCurrentIndex(0)
        bg_lay.addWidget(self._view_stack, 1)

        # ── Name pill at the bottom ──
        pill = QWidget()
        pill.setAttribute(Qt.WA_StyledBackground, True)
        pill.setStyleSheet("background: rgba(0, 0, 0, 0.55); border-radius: 4px;")
        pill.setFixedHeight(24)
        p_lay = QHBoxLayout(pill)
        p_lay.setContentsMargins(8, 0, 8, 0)
        p_lay.setSpacing(4)

        name_lbl = QLabel(self.nickname)
        name_lbl.setStyleSheet(
            "color: white; font-size: 12px; font-weight: 600;"
            " font-family: 'Segoe UI'; background: transparent;"
        )
        p_lay.addWidget(name_lbl)

        self._mute_icon = QLabel("🔇")
        self._mute_icon.setStyleSheet(
            "color: #f04747; font-size: 10px; background: transparent;"
        )
        self._mute_icon.hide()
        p_lay.addWidget(self._mute_icon)
        p_lay.addStretch()

        bg_lay.addWidget(pill)
        outer.addWidget(self._bg)

    # ── public state ─────────────────────────────────────────────────────────

    def set_speaking(self, speaking: bool):
        self._is_speaking = speaking
        accent = self._accent if self._accent else "#7289da"
        if speaking and not self._is_muted:
            self._bg.setStyleSheet(
                f"#cardBg {{ background: #1a1b1e; border-radius: 10px; border: 3px solid {accent}; }}"
            )
        else:
            self._bg.setStyleSheet(
                "#cardBg { background: #1a1b1e; border-radius: 10px; border: 3px solid transparent; }"
            )

    def set_muted(self, muted: bool):
        self._is_muted = muted
        self._mute_icon.setVisible(muted)
        if muted:
            self.set_speaking(False)

    def set_sharing(self, sharing: bool):
        self._is_sharing = sharing
        self._view_stack.setCurrentIndex(1 if sharing else 0)

    def update_frame(self, jpeg_bytes: bytes):
        if not self._is_sharing or self._screen_lbl.size().isEmpty():
            return
        img = QImage()
        if img.loadFromData(jpeg_bytes, "JPEG"):
            if self._screen_lbl.size().width() <= 0 or self._screen_lbl.size().height() <= 0:
                return
            pix = QPixmap.fromImage(img)
            scaled = pix.scaled(
                self._screen_lbl.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._screen_lbl.setPixmap(scaled)

    # ── context menu (volume, local mute) ───────────────────────────────────

    def contextMenuEvent(self, event):
        if self._is_self:
            return

        menu = QMenu(self)
        # Only override the embedded QLabel font — global QMenu colours apply
        menu.setStyleSheet(
            "QLabel { font-size: 12px; font-weight: 600; background: transparent; }"
        )

        title = QLabel("Громкость пользователя")
        act_title = QWidgetAction(menu)
        act_title.setDefaultWidget(title)
        menu.addAction(act_title)

        from ui.app import MainWindow
        from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
        from PySide6.QtCore import Qt as _Qt
        main_win = next(
            (w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow)),
            None,
        )

        # Volume row: slider + % label
        vol_widget = QWidget()
        vol_widget.setFixedWidth(260)
        vol_lay = QHBoxLayout(vol_widget)
        vol_lay.setContentsMargins(8, 4, 8, 4)
        vol_lay.setSpacing(8)

        slider = QSlider(_Qt.Horizontal)
        slider.setRange(0, 200)
        current_vol = 100
        if main_win:
            current_vol = int(main_win._audio.get_peer_volume(self.device_id) * 100)
        slider.setValue(current_vol)
        slider.setFixedWidth(170)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { background: #4f545c; height: 4px; border-radius: 2px; }"
            f"QSlider::handle:horizontal {{ background: {self._accent}; width: 14px;"
            f"  height: 14px; border-radius: 7px; margin: -5px 0; }}"
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
            act_mute.triggered.connect(
                lambda v: main_win._audio.set_peer_local_mute(self.device_id, v)
            )

        menu.exec_(event.globalPos())

    def mousePressEvent(self, event):
        from PySide6.QtCore import Qt
        if event.button() == Qt.LeftButton and self._is_sharing:
            self.watch_screen_requested.emit(self.device_id)
        super().mousePressEvent(event)


# ── Container ──────────────────────────────────────────────────────────────────

class VoiceGridWidget(QWidget):
    """Scrollable grid container for VoicePeerCards."""

    volume_changed = Signal(str, float)
    watch_screen_requested = Signal(str)

    def __init__(self, accent_color: str = "#7289da", parent=None):
        super().__init__(parent)
        self._accent = accent_color
        self._cards: Dict[str, VoicePeerCard] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: #111214; }")

        self.container = GridContainer()
        self.container.setStyleSheet("background: #111214;")

        self.scroll.setWidget(self.container)
        lay.addWidget(self.scroll)

    # ── accent propagation ───────────────────────────────────────────────────

    def set_accent(self, color: str):
        self._accent = color
        for card in self._cards.values():
            card._accent = color
            card.set_speaking(card._is_speaking)

    # ── peer management ──────────────────────────────────────────────────────

    def add_peer(self, peer_info: dict, is_self: bool = False):
        did = peer_info["device_id"]
        if did in self._cards:
            return
        card = VoicePeerCard(
            did,
            peer_info["nickname"],
            peer_info.get("avatar_color", "#7289da"),
            accent_color=self._accent,
            is_self=is_self,
        )
        card.volume_changed.connect(self.volume_changed.emit)
        card.watch_screen_requested.connect(self.watch_screen_requested.emit)
        self._cards[did] = card
        self.container.addCard(card)

    def remove_peer(self, device_id: str):
        if device_id in self._cards:
            card = self._cards.pop(device_id)
            self.container.removeCard(card)
            card.deleteLater()

    def update_voice(self, device_id: str, speaking: bool):
        if device_id in self._cards:
            self._cards[device_id].set_speaking(speaking)

    def update_muted(self, device_id: str, muted: bool):
        if device_id in self._cards:
            self._cards[device_id].set_muted(muted)

    def update_screen_state(self, device_id: str, sharing: bool):
        if device_id in self._cards:
            self._cards[device_id].set_sharing(sharing)

    def update_frame(self, device_id: str, jpeg_bytes: bytes):
        if device_id in self._cards:
            self._cards[device_id].update_frame(jpeg_bytes)
