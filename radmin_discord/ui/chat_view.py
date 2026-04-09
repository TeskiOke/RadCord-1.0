"""
chat_view.py — Scrollable chat message area.
Renders messages with avatar circles, nickname, timestamp, and content.
"""
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel,
    QHBoxLayout, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QFont, QBrush, QPen


def _time_str(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


class AvatarLabel(QLabel):
    """Circular colored avatar with initials."""
    def __init__(self, letter: str, color: str, size: int = 36, parent=None):
        super().__init__(parent)
        self._letter = letter.upper()[:1]
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, self.width(), self.height())
        p.setPen(QPen(QColor("white")))
        font = QFont("Segoe UI", max(1, int(self.width() * 0.38)))
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, self._letter)


class MessageWidget(QWidget):
    """Single chat message row."""
    def __init__(self, msg: dict, show_header: bool = True, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("msg-widget")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 4 if not show_header else 10, 16, 2)
        outer.setSpacing(12)
        outer.setAlignment(Qt.AlignTop)

        color = msg.get("avatar_color", "#7289da")
        nick  = msg.get("nickname", "?")

        if show_header:
            av = AvatarLabel(nick[:1], color)
            outer.addWidget(av, 0, Qt.AlignTop)
        else:
            spacer = QLabel()
            spacer.setFixedWidth(36)
            outer.addWidget(spacer)

        right = QVBoxLayout()
        right.setSpacing(2)
        right.setContentsMargins(0, 0, 0, 0)

        if show_header:
            head = QHBoxLayout()
            head.setSpacing(8)
            name_lbl = QLabel(nick)
            name_lbl.setStyleSheet(
                f"color: {color}; font-size: 14px; font-weight: 700;"
                "font-family: 'Segoe UI';"
            )
            head.addWidget(name_lbl)
            ts_lbl = QLabel(_time_str(msg.get("ts", int(time.time()))))
            ts_lbl.setStyleSheet(
                "color: #72767d; font-size: 11px; font-family: 'Segoe UI';"
            )
            head.addWidget(ts_lbl)
            head.addStretch()
            right.addLayout(head)

        content = QLabel(msg.get("content", ""))
        content.setStyleSheet(
            "color: #dcddde; font-size: 14px; font-family: 'Segoe UI';"
        )
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right.addWidget(content)

        outer.addLayout(right, 1)

    def enterEvent(self, event):
        self.setStyleSheet("#msg-widget { background: #0c0c0c; }")

    def leaveEvent(self, event):
        self.setStyleSheet("#msg-widget { background: transparent; }")



class ChatView(QWidget):
    """Scrollable list of messages for one channel."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_sender: str | None = None
        self._last_ts: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background: #000000; }
            QScrollBar:vertical {
                background: #000000; width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #111111; border-radius: 4px; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #1a1a1a;
            }
        """)

        self._container = QWidget()
        self._container.setStyleSheet("background: #000000;")
        self._msg_layout = QVBoxLayout(self._container)
        self._msg_layout.setSpacing(0)
        self._msg_layout.setContentsMargins(16, 8, 16, 8)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

    def add_message(self, msg: dict):
        if not msg: return

        sender_id = msg.get("from", "")
        ts        = msg.get("ts", 0)

        # Group consecutive messages from same user (within 5 minutes)
        show_header = (
            sender_id != self._last_sender
            or (ts - self._last_ts) > 300
        )
        self._last_sender = sender_id
        self._last_ts     = ts

        widget = MessageWidget(msg, show_header=show_header)
        # Insert before the trailing stretch
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, widget)

        # Auto-scroll to bottom after layout update
        QTimer.singleShot(30, self._scroll_to_bottom)

    def clear(self):
        self._last_sender = None
        self._last_ts = 0
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
