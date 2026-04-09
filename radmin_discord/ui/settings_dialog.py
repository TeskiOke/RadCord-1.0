"""
settings_dialog.py — Tabbed settings window.

Tabs:
  0 Профиль   — nickname, avatar color
  1 Микрофон  — input device, sensitivity threshold
  2 Динамик   — output device
  3 Сеть      — browse / change network
"""
import asyncio
import logging
from typing import Optional

import sounddevice as sd
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QWidget, QComboBox, QSlider,
    QScrollArea, QSizePolicy, QFrame, QTextEdit,
    QProgressBar,
)

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QFont

from core.identity import save_config, make_network_id
from shared.protocol import AVATAR_COLORS

logger = logging.getLogger("settings")

STYLE = """
QDialog { background: #000000; }
QTabWidget::pane { background: #000000; border: 2px solid #111111; border-top: none; }
QTabBar { background: #000000; }
QTabBar::tab {
    background: #000000; color: #96989d;
    font-family: 'Segoe UI'; font-size: 13px;
    padding: 12px 24px; border: none; min-width: 120px;
}
QTabBar::tab:selected { background: #050505; color: #ffffff; border-bottom: 2px solid #7289da; }
QTabBar::tab:hover:!selected { background: #111111; color: #dcddde; }

QWidget#tab-content { background: #000000; }

QLabel.section {
    color: #ffffff; font-size: 16px; font-weight: 700; font-family: 'Segoe UI';
}
QLabel.hint { color: #80848e; font-size: 12px; font-family: 'Segoe UI'; }
QLabel.field-label {
    color: #b5bac1; font-size: 11px; font-weight: 800;
    font-family: 'Segoe UI'; letter-spacing: 0.5px;
}

QLineEdit, QComboBox {
    background: #0a0a0a; border: 1px solid #222222; border-radius: 4px;
    color: #dbdee1; font-size: 14px; font-family: 'Segoe UI'; padding: 10px 12px;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #7289da; }

QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView {
    background: #000000; color: #dbdee1; border: 1px solid #222222;
    selection-background-color: #7289da;
}

QSlider::groove:horizontal { background: #1a1a1a; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #7289da; width: 16px; height: 16px;
    border-radius: 8px; margin: -5px 0;
}
QSlider::sub-page:horizontal { background: #7289da; border-radius: 3px; }

QPushButton#btn-save {
    background: #7289da; color: white; border: none; border-radius: 4px;
    font-size: 14px; font-weight: 600; font-family: 'Segoe UI'; padding: 12px 40px;
}
QPushButton#btn-save:hover { background: #5865f2; }
QPushButton#btn-cancel {
    background: transparent; color: #b5bac1; border: none;
    font-size: 14px; font-family: 'Segoe UI'; padding: 10px 16px;
}
QPushButton#btn-cancel:hover { color: white; text-decoration: underline; }

QProgressBar#mic-meter {
    background: #111111; border: 1px solid #222222; border-radius: 4px; text-align: center;
}
QProgressBar#mic-meter::chunk { background: #23a559; border-radius: 2px; }

QFrame#divider { background: #1a1a1a; max-height: 1px; }
"""


class ColorSwatch(QWidget):

    clicked = Signal(str)

    def __init__(self, color: str, selected: bool = False, size: int = 32):
        super().__init__()
        self._color    = color
        self._selected = selected
        self._size     = size
        self.setFixedSize(size + 8, size + 8)
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, v: bool):
        self._selected = v
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit(self._color)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._selected:
            p.setBrush(QBrush(QColor("white")))
            p.setPen(Qt.NoPen)
            p.drawEllipse(0, 0, self._size + 8, self._size + 8)
        p.setBrush(QBrush(QColor(self._color)))
        p.setPen(Qt.NoPen)
        offset = 4 if self._selected else 0
        p.drawEllipse(offset, offset, self._size, self._size)


class _ScanWorker(QObject):
    done = Signal(list)

    def __init__(self, loop):
        super().__init__()
        self._loop = loop

    def run(self):
        from core.network_scanner import NetworkScanner
        import asyncio, concurrent.futures
        fut = asyncio.run_coroutine_threadsafe(
            NetworkScanner().scan(duration=4.0), self._loop
        )
        try:
            results = fut.result(timeout=6.0)
        except Exception:
            results = []
        self.done.emit(results)


class SettingsDialog(QDialog):
    # Emitted when settings are saved: (config_dict, list of changed keys)
    saved = Signal(dict, list)
    rms_received = Signal(float)

    def done(self, result: int):
        if self._mic_test_active:
            self._toggle_mic_test()
        super().done(result)

    def __init__(self, config: dict, audio_mgr, async_loop, parent=None):
        super().__init__(parent)
        self._config     = dict(config)
        self._audio      = audio_mgr
        self._loop       = async_loop
        self._avatar_color = config.get("avatar_color", AVATAR_COLORS[0])
        self._swatches: list[ColorSwatch] = []
        self._scan_thread: Optional[QThread] = None

        self._mic_test_active = False


        self.setWindowTitle("Настройки — RadCord")
        self.setMinimumSize(600, 500)
        self.resize(640, 540)
        
        self._app_color = config.get("app_color", "#7289da")
        self.setStyleSheet(STYLE.replace("#7289da", self._app_color))
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.addTab(self._tab_profile(), "👤  Профиль")
        self._tabs.addTab(self._tab_appearance(), "🎨  Внешний вид")
        self._tabs.addTab(self._tab_mic(),     "🎤  Микрофон")
        self._tabs.addTab(self._tab_speaker(), "🔊  Динамик")
        self._tabs.addTab(self._tab_audio_mixer(), "🎚  Звук")
        self._tabs.addTab(self._tab_hotkeys(),  "⌨️  Горячие клавиши")
        self._tabs.addTab(self._tab_logs(),    "📝  Логи")
        root.addWidget(self._tabs, 1)



        # Bottom buttons
        bottom = QWidget()
        bottom.setObjectName("settings-bottom")
        bottom.setStyleSheet("background:#050505; border-top:1px solid #111111;")
        btn_lay = QHBoxLayout(bottom)
        btn_lay.setContentsMargins(16, 12, 16, 12)
        btn_lay.addStretch()
        cancel = QPushButton("Отмена", objectName="btn-cancel")
        cancel.clicked.connect(self.reject)
        btn_lay.addWidget(cancel)
        save = QPushButton("Сохранить", objectName="btn-save")
        save.clicked.connect(self._on_save)
        btn_lay.addWidget(save)
        root.addWidget(bottom)
        
    def closeEvent(self, event):
        # Stop mic test if closing
        if self._mic_test_active:
            self._toggle_mic_test()
        super().closeEvent(event)


    # ── Tab helpers ──────────────────────────────────────────────────────────

    def _tab_profile(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Профиль пользователя"))

        lay.addWidget(self._field_lbl("НИКНЕЙМ"))
        self._nick_edit = QLineEdit(self._config.get("nickname", ""))
        lay.addWidget(self._nick_edit)

        lay.addWidget(self._field_lbl("ЦВЕТ АВАТАРА"))
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        for color in AVATAR_COLORS:
            sw = ColorSwatch(color, selected=(color == self._avatar_color))
            sw.clicked.connect(self._on_color_clicked)
            self._swatches.append(sw)
            swatch_row.addWidget(sw)
        swatch_row.addStretch()
        lay.addLayout(swatch_row)

        lay.addStretch()
        return w

    def _tab_appearance(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Тема оформления"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Темная (Modern Black)", "Светлая (Clean White)"])
        current_theme = self._config.get("theme", "dark")
        self._theme_combo.setCurrentIndex(0 if current_theme == "dark" else 1)
        lay.addWidget(self._theme_combo)

        lay.addWidget(self._section("Цвет приложения (Акцент)"))
        self._app_color_btn = QPushButton("Выбрать цвет…")
        self._app_color_btn.setStyleSheet(f"background: {self._app_color}; color: white; border-radius: 4px; padding: 8px; font-weight: bold;")
        self._app_color_btn.clicked.connect(self._on_pick_app_color)
        lay.addWidget(self._app_color_btn)

        lay.addStretch()
        return w

    def _on_pick_app_color(self):
        from PySide6.QtWidgets import QColorDialog
        col = QColorDialog.getColor(QColor(self._app_color), self, "Выбор цвета ПО")
        if col.isValid():
            self._app_color = col.name()
            self._app_color_btn.setStyleSheet(f"background: {self._app_color}; color: white; border-radius: 4px; padding: 8px; font-weight: bold;")


    def _tab_logs(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Логи приложения"))
        
        from core.logger_setup import get_logs
        self._logs_edit = QTextEdit()
        self._logs_edit.setReadOnly(True)
        self._logs_edit.setPlainText(get_logs())
        self._logs_edit.setStyleSheet("""
            QTextEdit {
                background: #1e1f22; color: #dcddde; border: 1px solid #202225;
                font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;
            }
        """)
        lay.addWidget(self._logs_edit, 1)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("Скопировать в буфер")
        btn_copy.clicked.connect(self._on_copy_logs)
        btn_row.addWidget(btn_copy)

        btn_save = QPushButton("Сохранить в файл…")
        btn_save.clicked.connect(self._on_save_logs_to_file)
        btn_row.addWidget(btn_save)
        
        lay.addLayout(btn_row)
        return w

    def _on_copy_logs(self):
        from PySide6.QtGui import QGuiApplication
        clip = QGuiApplication.clipboard()
        clip.setText(self._logs_edit.toPlainText())

    def _on_save_logs_to_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить логи", "analog_ds_logs.txt", "Text Files (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._logs_edit.toPlainText())

    def _tab_mic(self) -> QWidget:

        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Устройство ввода"))

        lay.addWidget(self._field_lbl("МИКРОФОН"))
        self._mic_combo = QComboBox()
        self._mic_combo.addItem("По умолчанию (системный)")
        saved_mic = self._config.get("audio_input_device")
        self._mic_input_devices = [None]  # index 0 = default
        try:
            default_api = sd.default.hostapi
            devs = sd.query_devices()
            for i, d in enumerate(devs):
                if d.get("max_input_channels", 0) > 0 and d.get("hostapi", -1) == default_api:
                    self._mic_combo.addItem(f"  {d['name']}")
                    self._mic_input_devices.append(i)
                    if i == saved_mic:
                        self._mic_combo.setCurrentIndex(len(self._mic_input_devices) - 1)
        except Exception:
            pass
        lay.addWidget(self._mic_combo)

        lay.addWidget(self._field_lbl("ЧУВСТВИТЕЛЬНОСТЬ (VAD порог)"))
        hint = QLabel("Меньше = чувствительнее. Увеличь, если слышен фоновый шум.")
        hint.setProperty("class", "hint")
        lay.addWidget(hint)
        row = QHBoxLayout()
        self._sens_slider = QSlider(Qt.Horizontal)
        self._sens_slider.setRange(50, 2000)
        self._sens_slider.setValue(self._config.get("vad_threshold", 400))
        self._sens_slider.valueChanged.connect(self._on_vad_changed)
        row.addWidget(self._sens_slider)

        self._sens_val = QLabel(str(self._sens_slider.value()))
        self._sens_val.setStyleSheet(
            f"color:{self._app_color};font-size:13px;font-weight:700;font-family:'Segoe UI';"
        )
        self._sens_val.setFixedWidth(50)
        row.addWidget(self._sens_val)
        lay.addLayout(row)

        # MIC TEST AREA
        lay.addSpacing(16)
        lay.addWidget(self._section("Проверка микрофона"))
        
        self._mic_test_btn = QPushButton("Начать проверку (эхо)")
        self._mic_test_btn.setStyleSheet("""
            QPushButton { background: #313338; color: white; border: 1px solid #222222; padding: 10px; border-radius: 3px; }
            QPushButton:hover { background: #35373c; }
        """)
        self._mic_test_btn.clicked.connect(self._toggle_mic_test)
        lay.addWidget(self._mic_test_btn)

        self._mic_meter = QProgressBar()
        self._mic_meter.setRange(0, 100)
        self._mic_meter.setValue(0)
        self._mic_meter.setTextVisible(False)
        self._mic_meter.setFixedHeight(12)
        self._mic_meter.setStyleSheet(
            "QProgressBar { background: #202225; border-radius: 6px; border: 1px solid #111; }"
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #43b581, stop:0.8 #faa61a, stop:1 #f04747); border-radius: 6px; }"
        )
        lay.addWidget(self._mic_meter)

        lay.addStretch()
        return w

    def _on_vad_changed(self, v: int):
        self._sens_val.setText(str(v))
        if hasattr(self._audio, "vad_threshold"):
            self._audio.vad_threshold = v
            logger.info(f"VAD threshold updated real-time: {v}")

    def _toggle_mic_test(self):
        self._mic_test_active = not self._mic_test_active
        self._audio.mic_test_active = self._mic_test_active
        if self._mic_test_active:
            self._mic_test_btn.setText("Остановить проверку")
            self._mic_test_btn.setStyleSheet("background: #f23f43; color: white; border-radius: 3px; padding: 10px;")
            from PySide6.QtCore import Qt
            try: self.rms_received.connect(self._on_mic_level, Qt.QueuedConnection) 
            except: pass
            self._audio.on_rms_level = self.rms_received.emit
            logger.info("Mic echo test STARTED.")
        else:
            self._mic_test_btn.setText("Начать проверку (эхо)")
            self._mic_test_btn.setStyleSheet("background: #313338; color: white; border: 1px solid #222222; padding: 10px; border-radius: 3px;")
            self._audio.on_rms_level = None
            try: self.rms_received.disconnect(self._on_mic_level)
            except: pass
            self._mic_meter.setValue(0)
            logger.info("Mic echo test STOPPED.")

    def _on_mic_level(self, rms: float):
        # Scale RMS to 0-100 logic: average voice peaks around 2000-4000. So divide by 30-40, let's use 30.
        level = min(100, int(rms / 30))
        self._mic_meter.setValue(level)




    def _tab_speaker(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Устройство вывода"))

        lay.addWidget(self._field_lbl("ДИНАМИК / НАУШНИКИ"))
        self._spk_combo = QComboBox()
        self._spk_combo.addItem("По умолчанию (системный)")
        saved_spk = self._config.get("audio_output_device")
        self._spk_output_devices = [None]
        try:
            default_api = sd.default.hostapi
            devs = sd.query_devices()
            for i, d in enumerate(devs):
                if d.get("max_output_channels", 0) > 0 and d.get("hostapi", -1) == default_api:
                    self._spk_combo.addItem(f"  {d['name']}")
                    self._spk_output_devices.append(i)
                    if i == saved_spk:
                        self._spk_combo.setCurrentIndex(len(self._spk_output_devices) - 1)
        except Exception:
            pass
        lay.addWidget(self._spk_combo)

        lay.addStretch()
        return w


    # ── Audio Mixer ───────────────────────────────────────────────────────────

    def _tab_audio_mixer(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Громкость"))

        def _make_vol_row(label: str, config_key: str, default: int = 100):
            lay.addWidget(self._field_lbl(label))
            row = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 200)
            slider.setValue(self._config.get(config_key, default))
            pct = QLabel(f"{slider.value()}%")
            pct.setStyleSheet(f"color:{self._app_color};font-size:13px;font-weight:700;font-family:'Segoe UI';min-width:46px;")
            slider.setStyleSheet(
                f"QSlider::groove:horizontal{{background:#1a1a1a;height:6px;border-radius:3px;}}"
                f"QSlider::handle:horizontal{{background:{self._app_color};width:16px;height:16px;border-radius:8px;margin:-5px 0;}}"
                f"QSlider::sub-page:horizontal{{background:{self._app_color};border-radius:3px;}}"
            )
            slider.valueChanged.connect(lambda v: pct.setText(f"{v}%"))
            row.addWidget(slider)
            row.addWidget(pct)
            lay.addLayout(row)
            return slider

        self._master_vol_slider = _make_vol_row(
            "ОБЩАЯ ГРОМКОСТЬ ПРИЛОЖЕНИЯ", "master_volume", 100
        )
        hint = QLabel("Глобальная громкость — влияет на всё.")
        hint.setProperty("class", "hint"); lay.addWidget(hint)

        self._peers_vol_slider = _make_vol_row(
            "ГРОМКОСТЬ УЧАСТНИКОВ", "peers_volume", 100
        )
        hint2 = QLabel("Снизь, если все слышно слишком громко.")
        hint2.setProperty("class", "hint"); lay.addWidget(hint2)

        self._ui_vol_slider = _make_vol_row(
            "СИСТЕМНЫЕ ЗВУКИ ПО", "ui_volume", 100
        )
        hint3 = QLabel("Уведомления, звуки входа/выхода из ГК.")
        hint3.setProperty("class", "hint"); lay.addWidget(hint3)

        lay.addStretch()
        return w

    # ── Hotkeys ───────────────────────────────────────────────────────────────

    def _tab_hotkeys(self) -> QWidget:
        w = QWidget(objectName="tab-content")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        lay.addWidget(self._section("Горячие клавиши"))

        hint = QLabel("Нажмите на поле и нажмите нужную клавишу или выберите кнопку мыши из списка.")
        hint.setProperty("class", "hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        hotkeys = self._config.get("hotkeys", {})

        def _make_hotkey_row(label: str, config_key: str):
            lay.addWidget(self._field_lbl(label))
            row = QHBoxLayout()

            field = QLineEdit()
            field.setPlaceholderText("Не назначено")
            field.setReadOnly(True)
            field.setText(hotkeys.get(config_key, ""))
            field.setStyleSheet(
                "QLineEdit{background:#0a0a0a;border:1px solid #222;border-radius:4px;"
                "color:#dbdee1;font-size:14px;font-family:'Segoe UI';padding:10px 12px;}"
                "QLineEdit:focus{border:1px solid " + self._app_color + ";}"
            )

            # Capture keyboard press
            def _on_key(e, f=field):
                from PySide6.QtCore import Qt as _Qt
                key = e.key()
                mods = e.modifiers()
                parts = []
                if mods & _Qt.ControlModifier: parts.append("ctrl")
                if mods & _Qt.AltModifier: parts.append("alt")
                if mods & _Qt.ShiftModifier: parts.append("shift")
                key_name = e.text().lower().strip()
                if not key_name or key in (_Qt.Key_Control, _Qt.Key_Alt, _Qt.Key_Shift, _Qt.Key_Meta):
                    return
                parts.append(key_name)
                f.setText("+".join(parts))

            field.keyPressEvent = _on_key

            clear_btn = QPushButton("✕")
            clear_btn.setFixedSize(36, 36)
            clear_btn.setStyleSheet(
                "QPushButton{background:#1a1a1a;color:#b5bac1;border:1px solid #222;"
                "border-radius:4px;font-size:14px;}"
                "QPushButton:hover{background:#222;color:white;}"
            )
            clear_btn.clicked.connect(lambda: field.setText(""))

            # Mouse button combo
            mouse_combo = QComboBox()
            mouse_combo.addItems(["— мышь —", "mouse4", "mouse5", "mouse3 (СКМ)"])
            mouse_combo.setFixedWidth(150)
            cur = hotkeys.get(config_key, "")
            if cur in ("mouse4", "mouse5", "mouse3"):
                mouse_combo.setCurrentText(cur)
            mouse_combo.currentIndexChanged.connect(
                lambda i, c=mouse_combo, f=field: f.setText(c.currentText()) if i > 0 else None
            )

            row.addWidget(field, 1)
            row.addWidget(clear_btn)
            row.addWidget(mouse_combo)
            lay.addLayout(row)
            return field

        self._hk_mute   = _make_hotkey_row("МУТ / РАЗМУТ МИКРОФОНА", "hotkey_mute")
        self._hk_deafen = _make_hotkey_row("ПОЛНЫЙ МУТ / РАЗМУТ (НАУШНИКИ)", "hotkey_deafen")

        lay.addStretch()
        return w

    # ── Network scan ──────────────────────────────────────────────────────────

    def _start_scan(self):
        self._scan_btn.setEnabled(False)
        self._scan_status.setText("⏳ Сканирую…")
        # Clear old results
        while self._net_list_lay.count() > 1:
            item = self._net_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._scan_thread = QThread()
        self._worker = _ScanWorker(self._loop)
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _on_scan_done(self, networks: list):
        self._scan_btn.setEnabled(True)
        if not networks:
            self._scan_status.setText("Сети не найдены")
            return
        self._scan_status.setText(f"Найдено сетей: {len(networks)}")
        for net in networks:
            row = self._make_net_row(net)
            count = self._net_list_lay.count()
            self._net_list_lay.insertWidget(count - 1, row)

    def _make_net_row(self, net: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:#2f3136;border-radius:6px;")
        w.setFixedHeight(52)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 12, 0)
        lbl = QLabel(
            f"<b>{net['name']}</b>  "
            f"<span style='color:#72767d;font-size:11px;'>"
            f"{len(net['users'])} онлайн: {', '.join(net['users'][:3])}"
            f"{'…' if len(net['users']) > 3 else ''}</span>"
        )
        lbl.setStyleSheet("color:#dcddde;font-size:13px;font-family:'Segoe UI';")
        lbl.setTextFormat(Qt.RichText)
        lay.addWidget(lbl, 1)

        join_btn = QPushButton("Войти")
        join_btn.setProperty("class", "net-row-btn")
        join_btn.setStyleSheet(STYLE)
        join_btn.clicked.connect(lambda _, n=net: self._join_network(n))
        lay.addWidget(join_btn)
        return w

    def _join_network(self, net: dict):
        from PySide6.QtWidgets import QInputDialog
        pw, ok = QInputDialog.getText(
            self, f"Войти в «{net['name']}»",
            "Введите пароль сети:", QLineEdit.Password
        )
        if not ok or not pw:
            return
        candidate_id = make_network_id(net["name"], pw)
        if candidate_id == net["network_id"]:
            self._config["network_name"] = net["name"]
            self._config["network_id"]   = candidate_id
            self._scan_status.setText(f"✅ Присоединился к «{net['name']}»!")
        else:
            self._scan_status.setText("❌ Неверный пароль")

    # ── Save ─────────────────────────────────────────────────────────────────

    def _on_save(self):
        changed = []
        new_nick = self._nick_edit.text().strip()
        if new_nick and new_nick != self._config.get("nickname"):
            self._config["nickname"] = new_nick
            changed.append("nickname")

        if self._avatar_color != self._config.get("avatar_color"):
            old_val = self._config.get("avatar_color")
            self._config["avatar_color"] = self._avatar_color
            changed.append("avatar_color")
            logger.info(f"Setting updated: avatar_color changed from {old_val} to {self._avatar_color}")

        new_theme = "dark" if self._theme_combo.currentIndex() == 0 else "light"
        if new_theme != self._config.get("theme"):
            old_val = self._config.get("theme")
            self._config["theme"] = new_theme
            changed.append("theme")
            logger.info(f"Setting updated: theme changed from {old_val} to {new_theme}")

        if self._app_color != self._config.get("app_color"):
            old_val = self._config.get("app_color")
            self._config["app_color"] = self._app_color
            changed.append("app_color")
            logger.info(f"Setting updated: app_color changed from {old_val} to {self._app_color}")

        mic_idx = self._mic_combo.currentIndex()
        new_mic = self._mic_input_devices[mic_idx] if mic_idx < len(self._mic_input_devices) else None
        if new_mic != self._config.get("audio_input_device"):
            self._config["audio_input_device"] = new_mic
            changed.append("audio_input")

        spk_idx = self._spk_combo.currentIndex()
        new_spk = self._spk_output_devices[spk_idx] if spk_idx < len(self._spk_output_devices) else None
        if new_spk != self._config.get("audio_output_device"):
            self._config["audio_output_device"] = new_spk
            changed.append("audio_output")

        new_thresh = self._sens_slider.value()
        if new_thresh != self._config.get("vad_threshold", 400):
            self._config["vad_threshold"] = new_thresh
            changed.append("vad_threshold")

        # Audio mixer volumes
        for key, slider in [
            ("master_volume", self._master_vol_slider),
            ("peers_volume",  self._peers_vol_slider),
            ("ui_volume",     self._ui_vol_slider),
        ]:
            val = slider.value()
            if val != self._config.get(key, 100):
                self._config[key] = val
                changed.append(key)

        # Hotkeys
        hk_mute   = self._hk_mute.text().strip()
        hk_deafen = self._hk_deafen.text().strip()
        hotkeys = self._config.get("hotkeys", {})
        if hk_mute != hotkeys.get("hotkey_mute", ""):
            hotkeys["hotkey_mute"] = hk_mute
            changed.append("hotkeys")
        if hk_deafen != hotkeys.get("hotkey_deafen", ""):
            hotkeys["hotkey_deafen"] = hk_deafen
            changed.append("hotkeys")
        self._config["hotkeys"] = hotkeys

        from core.identity import save_config
        save_config(self._config)
        self.saved.emit(self._config, changed)
        logger.info("Settings saved successfully.")
        
        # Flash button green briefly to indicate success
        btn = self.sender() # Assume button was clicked
        if hasattr(btn, "setText"):
            old_text = btn.text()
            btn.setText("✔ Сохранено")
            btn.setStyleSheet("background: #43b581; color: white; padding: 10px 24px; border-radius: 4px; font-weight: 600;")
            
            # Reset button after 1.5 seconds
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self._reset_save_btn(btn, old_text))

    def _reset_save_btn(self, btn, text):
        try:
            btn.setText(text)
            btn.setStyleSheet("QPushButton { background: #5865f2; color: white; padding: 10px 24px; border-radius: 4px; font-weight: 600; font-size: 14px; } QPushButton:hover { background: #4752c4; }")
        except RuntimeError:
            pass # Button might be deleted



    # ── Widget helpers ────────────────────────────────────────────────────────

    def _on_color_clicked(self, color: str):
        self._avatar_color = color
        for sw in self._swatches:
            sw.set_selected(sw._color == color)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#dcddde;font-size:14px;font-weight:600;font-family:'Segoe UI';")
        return lbl

    @staticmethod
    def _field_lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#b9bbbe;font-size:11px;font-weight:700;"
                          "font-family:'Segoe UI';letter-spacing:1px;")
        return lbl

    @staticmethod
    def _divider() -> QFrame:
        f = QFrame(objectName="divider")
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("background:#40444b;max-height:1px;")
        return f
