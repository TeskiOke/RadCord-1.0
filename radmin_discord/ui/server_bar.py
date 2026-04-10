"""
server_bar.py — Discord-style vertical bar on the left with server icons.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QFrame, QMenu
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QBrush, QFont

class ServerIcon(QPushButton):
    """Circular icon for a server/network."""
    clicked_id = Signal(str)
    delete_requested = Signal(str)
    rename_requested = Signal(str, str)

    def __init__(self, net_id: str, name: str, active: bool = False, parent=None):
        super().__init__(parent)
        self.net_id = net_id
        self.name = name
        self._active = active
        self.setFixedSize(48, 48)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)
        self.clicked.connect(lambda: self.clicked_id.emit(self.net_id))

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw sidebar indicator (the little white pill on the left)
        if self._active:
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(-4, 12, 8, 24, 4, 4)
        elif self.underMouse():
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(-4, 18, 8, 12, 4, 4)

        # Draw circle background
        accent = getattr(self.parent(), "_accent", "#5865f2")
        bg_col = QColor(accent) if self._active else QColor("#36393f")
        if self.underMouse() and not self._active:
            bg_col = QColor(accent)

        
        # Border radius: 50% for circle, or rounded rect (Discord uses squircles)
        radius = 16 if self._active or self.underMouse() else 24
        
        painter.setBrush(QBrush(bg_col))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), radius, radius)

        # Draw text (First Letter)
        painter.setPen(QColor("#dcddde"))
        font = QFont("Segoe UI", 13, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self.name[:1].upper())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_rename = menu.addAction("✏️ Переименовать")
        act_del = menu.addAction("❌ Удалить группу")
        action = menu.exec_(event.globalPos())
        if action == act_del:
            self.delete_requested.emit(self.net_id)
        elif action == act_rename:
            self.rename_requested.emit(self.net_id, self.name)


class ServerBar(QWidget):
    network_selected = Signal(str) # net_id
    add_requested = Signal()
    remove_requested = Signal(str) # net_id
    rename_requested = Signal(str, str) # net_id, old_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(72)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        
        self._icons = {}
        self._active_id = None
        
        self._build_ui()

    def _build_ui(self):
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.lay.setSpacing(8)
        self.lay.setAlignment(Qt.AlignTop)

        # Home / Discord Icon placeholder?
        # For now just start with networks

        self.list_lay = QVBoxLayout()
        self.list_lay.setSpacing(8)
        self.lay.addLayout(self.list_lay)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: #35363c; max-height: 2px; margin: 0 8px;")
        self.lay.addWidget(line)

        # Add Button
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(48, 48)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #36393f;
                color: #43b581;
                font-size: 24px;
                font-weight: 300;
                border: none;
                border-radius: 24px;
            }
            QPushButton:hover {
                background: #43b581;
                color: white;
                border-radius: 16px;
            }
        """)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.add_requested.emit)
        self.lay.addWidget(self.add_btn)

        self.lay.addStretch()

    def set_networks(self, networks: list, active_id: str = None):
        # Clear existing
        for i in reversed(range(self.list_lay.count())):
            self.list_lay.itemAt(i).widget().setParent(None)
        self._icons.clear()

        self._active_id = active_id

        for net in networks:
            icon = ServerIcon(net["id"], net["name"], active=(net["id"] == active_id))
            icon.clicked_id.connect(self.network_selected.emit)
            icon.delete_requested.connect(self.remove_requested.emit)
            icon.rename_requested.connect(self.rename_requested.emit)
            self.list_lay.addWidget(icon)
            self._icons[net["id"]] = icon

    def set_active(self, net_id: str):
        self._active_id = net_id
        for did, icon in self._icons.items():
            icon.set_active(did == net_id)

    def set_accent(self, color: str):
        self._accent = color
        self.add_btn.setStyleSheet(f"""
            QPushButton {{
                background: #36393f;
                color: {color};
                font-size: 24px;
                font-weight: 300;
                border: none;
                border-radius: 24px;
            }}
            QPushButton:hover {{
                background: {color};
                color: white;
                border-radius: 16px;
            }}
        """)
        self.update()

