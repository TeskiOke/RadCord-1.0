"""
screen_view.py — Floating window that displays a peer's screen share.
Receives QPixmap via signal; scales to fit the window.
"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QImage, QFont


STYLE = """
QDialog {
    background: #1e2124;
}
QLabel#title {
    color: #dcddde;
    font-size: 13px;
    font-family: 'Segoe UI';
    font-weight: 600;
    padding: 6px 12px;
}
QLabel#screen {
    background: #000000;
}
QPushButton#btn-close {
    background: #f04747;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QPushButton#btn-close:hover {
    background: #d84040;
}
"""


class ScreenViewWindow(QDialog):
    def __init__(self, peer_nickname: str, parent=None):
        super().__init__(parent)
        self.peer_nickname = peer_nickname
        self.setWindowTitle(f"Экран — {peer_nickname}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setMinimumSize(400, 300)
        self.resize(1280, 720)
        self.setStyleSheet(STYLE)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Top bar
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self._title_lbl = QLabel(f"🖥  Экран: {self.peer_nickname}", objectName="title")
        bar.addWidget(self._title_lbl)
        bar.addStretch()

        btn = QPushButton("✕  Закрыть", objectName="btn-close")
        btn.clicked.connect(self.close)
        bar.addWidget(btn)

        bar_widget_bg = QLabel()
        bar_widget_bg.setFixedHeight(36)
        bar_widget_bg.setStyleSheet("background:#2f3136;")
        bar_layout = QVBoxLayout(bar_widget_bg)
        bar_layout.setContentsMargins(0,0,0,0)
        inner_bar = QHBoxLayout()
        inner_bar.setContentsMargins(8,0,8,0)
        inner_bar.addWidget(self._title_lbl)
        inner_bar.addStretch()
        inner_bar.addWidget(btn)
        bar_widget_bg.setLayout(inner_bar)
        lay.addWidget(bar_widget_bg)

        # Screen label
        self._screen_lbl = QLabel(objectName="screen")
        self._screen_lbl.setAlignment(Qt.AlignCenter)
        self._screen_lbl.setText("Ожидание кадров…")
        self._screen_lbl.setStyleSheet("color: #72767d; font-size: 14px;"
                                        "font-family: 'Segoe UI'; background: #000;")
        lay.addWidget(self._screen_lbl, 1)

    def update_frame(self, jpeg_bytes: bytes):
        """Call from the main thread with raw JPEG bytes."""
        img = QImage.fromData(jpeg_bytes, "JPEG")
        if img.isNull():
            return
        px = QPixmap.fromImage(img)
        scaled = px.scaled(self._screen_lbl.size(), Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        self._screen_lbl.setPixmap(scaled)

    def closeEvent(self, event):
        self._screen_lbl.clear()
        self._screen_lbl.setText("Ожидание кадров…")
        super().closeEvent(event)
