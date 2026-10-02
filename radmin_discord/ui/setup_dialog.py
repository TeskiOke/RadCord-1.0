"""
setup_dialog.py — First-run wizard:
1. Profile: Nickname, Avatar Color, Theme, App Color.
2. Mode: Create Network or Find Network.
3. Network Settings: Network Name, Password.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QRadioButton, QColorDialog, QStackedWidget,
    QWidget, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

from core.identity import create_profile
import random

STYLE = """
QDialog {
    background: #1e2124;
}
QLabel {
    font-family: 'Segoe UI';
}
QLabel#title {
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
}
QLabel#subtitle {
    color: #72767d;
    font-size: 13px;
}
QLineEdit {
    background: #40444b;
    border: 1px solid #202225;
    border-radius: 4px;
    color: #dcddde;
    font-size: 14px;
    font-family: 'Segoe UI';
    padding: 10px 12px;
    selection-background-color: #7289da;
}
QLineEdit:focus {
    border: 1px solid #7289da;
    background: #484c54;
}
QPushButton {
    font-family: 'Segoe UI';
}
QPushButton.wizard-btn {
    background: #7289da;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 600;
    padding: 12px 0;
}
QPushButton.wizard-btn:hover { background: #677bc4; }
QPushButton.wizard-btn:pressed { background: #5b6eae; }

QPushButton.back-btn {
    background: transparent;
    color: #99aab5;
    border: 1px solid #99aab5;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 600;
    padding: 12px 0;
}
QPushButton.back-btn:hover { background: #2c2f33; color: white; border-color: white; }

QPushButton.big-action-btn {
    background: #2b2d31;
    color: #ffffff;
    border: 2px solid #1e1f22;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 700;
    padding: 24px 0;
}
QPushButton.big-action-btn:hover { background: #313338; border-color: #7289da; }

QRadioButton {
    color: #dcddde;
    font-size: 14px;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid #b9bbbe;
    background: transparent;
}
QRadioButton::indicator:checked {
    border: 2px solid #7289da;
    background: #7289da;
}

QLabel#err {
    color: #f04747;
    font-size: 12px;
}
"""

class SetupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self._config = None
        self.setWindowTitle("RadCord — Настройка")
        self.setFixedSize(500, 600)
        self.setStyleSheet(STYLE)
        
        self._theme = "dark"
        self._app_color = "#7289da"
        self._avatar_color = "#7289da"
        self._mode = "create" # "create" or "join"

        self._build_ui()

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(40, 24, 40, 24)
        root_lay.setSpacing(0)

        # Title
        title_lbl = QLabel("📡  RadCord", objectName="title")
        title_lbl.setAlignment(Qt.AlignCenter)
        root_lay.addWidget(title_lbl)
        root_lay.addSpacing(4)

        self._subtitle = QLabel("Привет! Давай настроим твой профиль.", objectName="subtitle")
        self._subtitle.setAlignment(Qt.AlignCenter)
        root_lay.addWidget(self._subtitle)
        root_lay.addSpacing(24)

        self._stack = QStackedWidget()
        
        self._stack.addWidget(self._page_profile())
        
        root_lay.addWidget(self._stack, 1)

        # Error label at bottom
        self._err_lbl = QLabel("", objectName="err")
        self._err_lbl.setAlignment(Qt.AlignCenter)
        root_lay.addWidget(self._err_lbl)
        root_lay.addSpacing(4)

        self._stack.setCurrentIndex(0)

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #b9bbbe; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        return lbl

    def _page_profile(self) -> QWidget:
        def rgb2hex(r, g, b): return f"#{r:02x}{g:02x}{b:02x}"
        preset_colors = [
            rgb2hex(114,137,218), rgb2hex(67,181,129), rgb2hex(250,166,26), 
            rgb2hex(240,71,71), rgb2hex(233,30,99), rgb2hex(156,39,176)
        ]
        self._avatar_color = random.choice(preset_colors)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        
        lay.addWidget(self._field_label("НИКНЕЙМ"))
        lay.addSpacing(6)
        self._nick_edit = QLineEdit(placeholderText="Как тебя зовут?")
        lay.addWidget(self._nick_edit)
        lay.addSpacing(16)

        lay.addWidget(self._field_label("ЦВЕТ АВАТАРА"))
        lay.addSpacing(6)
        av_lay = QHBoxLayout()
        for hex_color in preset_colors:
            btn = QPushButton()
            btn.setFixedSize(32, 32)
            btn.setStyleSheet(f"background: {hex_color}; border-radius: 16px;")
            btn.clicked.connect(lambda _, c=hex_color: self._set_avatar_color(c))
            av_lay.addWidget(btn)
        av_lay.addStretch()
        lay.addLayout(av_lay)
        self._av_indicator = QLabel("Выбранный цвет")
        self._av_indicator.setStyleSheet(f"color: {self._avatar_color}; font-weight: bold; margin-top: 4px;")
        lay.addWidget(self._av_indicator)
        lay.addSpacing(16)

        lay.addWidget(self._field_label("ЦВЕТ ПРИЛОЖЕНИЯ (RGB)"))
        lay.addSpacing(6)
        app_color_lay = QHBoxLayout()
        self._app_color_btn = QPushButton("Выбрать цвет (Пипетка)")
        self._app_color_btn.setStyleSheet(f"background: {self._app_color}; color: white; padding: 6px; border-radius:4px; font-weight: bold;")
        self._app_color_btn.clicked.connect(self._pick_app_color)
        app_color_lay.addWidget(self._app_color_btn)
        app_color_lay.addStretch()
        lay.addLayout(app_color_lay)
        lay.addSpacing(16)

        lay.addWidget(self._field_label("ТЕМА ОФОРМЛЕНИЯ"))
        lay.addSpacing(6)
        theme_lay = QHBoxLayout()
        self._rb_dark = QRadioButton("Темная")
        self._rb_dark.setChecked(True)
        self._rb_light = QRadioButton("Светлая")
        self._rb_sys = QRadioButton("Системная")
        theme_lay.addWidget(self._rb_dark)
        theme_lay.addWidget(self._rb_light)
        theme_lay.addWidget(self._rb_sys)
        theme_lay.addStretch()
        lay.addLayout(theme_lay)
        
        lay.addStretch()

        btn_finish = QPushButton("Завершить настройку", objectName="btn-finish")
        btn_finish.setProperty("class", "wizard-btn")
        btn_finish.clicked.connect(self._on_finish)
        lay.addWidget(btn_finish)
        
        return w

    def _set_avatar_color(self, hex_color: str):
        self._avatar_color = hex_color
        self._av_indicator.setStyleSheet(f"color: {self._avatar_color}; font-weight: bold; margin-top: 4px;")

    def _pick_app_color(self):
        col = QColorDialog.getColor(QColor(self._app_color), self, "Выбери акцентный цвет ПО")
        if col.isValid():
            self._app_color = col.name()
            self._app_color_btn.setStyleSheet(f"background: {self._app_color}; color: white; padding: 6px; border-radius:4px; font-weight: bold;")
            # Live preview update in style
            self.setStyleSheet(STYLE.replace("#7289da", self._app_color))

    def _on_finish(self):
        nick = self._nick_edit.text().strip()
        if not nick:
            self._err_lbl.setText("Введи никнейм перед продолжением")
            return
        if len(nick) > 32:
            self._err_lbl.setText("Никнейм не больше 32 символов")
            return

        if self._rb_light.isChecked(): self._theme = "light"
        elif self._rb_sys.isChecked(): self._theme = "system"
        else: self._theme = "dark"

        from core.identity import create_profile
        self._config = create_profile(
            nickname=nick,
            theme=self._theme,
            app_color=self._app_color,
            avatar_color=self._avatar_color
        )
        self.accept()

    def get_config(self) -> dict:
        return self._config
