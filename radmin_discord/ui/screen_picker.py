"""
screen_picker.py — Dialog to choose what to stream:
  - Monitor (all via mss)
  - Application window (via ctypes EnumWindows on Windows)

Also lets user pick quality preset and FPS.
"""
import ctypes
import ctypes.wintypes
import io
import logging
from typing import Optional

import mss
from PIL import Image
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QSlider,
    QGroupBox, QSplitter, QWidget, QFrame,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QImage, QColor

from shared.protocol import QUALITY_PRESETS, FPS_OPTIONS

logger = logging.getLogger("screen_picker")

STYLE = """
QDialog { background: #36393f; }
QLabel#title {
    color: #ffffff; font-size: 15px; font-weight: 700;
    font-family: 'Segoe UI'; padding: 4px 0;
}
QListWidget {
    background: #2f3136; border: none; border-radius: 4px;
    color: #dcddde; font-size: 13px; font-family: 'Segoe UI';
    outline: 0;
}
QListWidget::item { padding: 8px 12px; border-radius: 3px; }
QListWidget::item:selected { background: #7289da; color: white; }
QListWidget::item:hover:!selected { background: #393c43; }
QLabel.lbl {
    color: #b9bbbe; font-size: 11px; font-weight: 700;
    font-family: 'Segoe UI'; letter-spacing: 1px;
}
QComboBox {
    background: #40444b; border: 1px solid #202225; border-radius: 4px;
    color: #dcddde; font-size: 13px; font-family: 'Segoe UI'; padding: 8px 10px;
}
QComboBox QAbstractItemView { background: #2f3136; color: #dcddde;
    selection-background-color: #7289da; }
QComboBox::drop-down { border: none; width: 20px; }
QSlider::groove:horizontal { background: #4f545c; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #7289da; width: 14px; height: 14px;
    border-radius: 7px; margin: -5px 0;
}
QSlider::sub-page:horizontal { background: #7289da; border-radius: 2px; }
QLabel#preview-lbl { background: #202225; border-radius: 4px; }
QPushButton#btn-start {
    background: #7289da; color: white; border: none; border-radius: 4px;
    font-size: 14px; font-weight: 600; font-family: 'Segoe UI'; padding: 10px 0;
}
QPushButton#btn-start:hover { background: #677bc4; }
QPushButton#btn-cancel {
    background: transparent; color: #b9bbbe; border: none;
    font-size: 13px; font-family: 'Segoe UI'; padding: 10px;
}
QPushButton#btn-cancel:hover { color: white; }
QGroupBox {
    color: #96989d; font-size: 11px; font-weight: 700;
    font-family: 'Segoe UI'; border: 1px solid #40444b;
    border-radius: 6px; margin-top: 12px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; }
"""


def _is_cloaked(hwnd) -> bool:
    """Returns True if window is cloaked by DWM (e.g. UWP background apps)."""
    try:
        DWMWA_CLOAKED = 14
        cloaked = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return cloaked.value != 0
    except Exception:
        return False


def _list_windows():
    """Return list of visible windows with title + rect (Windows only)."""
    results = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _):
        try:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            # Skip cloaked windows (UWP background, etc.)
            if _is_cloaked(hwnd):
                return True
            # Skip tool windows (system trays, overlays, etc.)
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            WS_EX_TOOLWINDOW = 0x00000080
            if ex_style & WS_EX_TOOLWINDOW:
                return True
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length < 1:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            skip = {
                "Program Manager", "MSCTFIME UI", "RadminDiscord",
                "Radmin Discord", "Windows Shell Experience Host",
                "RadCord", "Default IME", "NVIDIA GeForce Overlay",
            }
            if not title or title in skip:
                return True
            rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 100 and h > 100:
                results.append({
                    "hwnd": hwnd,
                    "title": title,
                    "rect": (rect.left, rect.top, rect.right, rect.bottom),
                })
        except Exception:
            pass
        return True

    ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return results


def _capture_thumbnail(source: dict, size=(320, 180)) -> Optional[QPixmap]:
    """Capture a small thumbnail of the selected source."""
    try:
        if source["type"] == "monitor":
            with mss.mss() as sct:
                idx = source.get("monitor_index", 1)
                monitors = sct.monitors
                if idx >= len(monitors):
                    idx = 1
                raw = sct.grab(monitors[idx])
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        else:  # window
            from PIL import ImageGrab
            rect = source.get("rect", (0, 0, 800, 600))
            img = ImageGrab.grab(bbox=rect)

        img = img.resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qimg = QImage.fromData(buf.getvalue(), "PNG")
        return QPixmap.fromImage(qimg)
    except Exception as e:
        logger.debug(f"Thumbnail error: {e}")
        return None


class ScreenPickerDialog(QDialog):
    """Returns a dict: {type, monitor_index|hwnd|rect, quality_index, fps}"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор источника трансляции")
        self.setMinimumSize(780, 520)
        self.resize(860, 560)
        self.setStyleSheet(STYLE)
        self._result_data: Optional[dict] = None
        self._sources: list = []
        self._build_ui()
        self._populate_sources()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("🖥  Выберите источник трансляции", objectName="title")
        root.addWidget(title)

        # Main split: source list | preview
        split = QHBoxLayout()
        split.setSpacing(16)

        # Left — source list
        left = QVBoxLayout()
        left.setSpacing(6)
        src_lbl = QLabel("ИСТОЧНИК")
        src_lbl.setProperty("class", "lbl")
        src_lbl.setStyleSheet("color:#b9bbbe;font-size:11px;font-weight:700;"
                               "font-family:'Segoe UI';letter-spacing:1px;")
        left.addWidget(src_lbl)

        self._list = QListWidget()
        self._list.setMinimumWidth(300)
        self._list.currentRowChanged.connect(self._on_source_changed)
        left.addWidget(self._list, 1)
        split.addLayout(left, 1)

        # Right — preview
        right = QVBoxLayout()
        right.setSpacing(6)
        prev_lbl = QLabel("ПРЕДПРОСМОТР")
        prev_lbl.setProperty("class", "lbl")
        prev_lbl.setStyleSheet("color:#b9bbbe;font-size:11px;font-weight:700;"
                                "font-family:'Segoe UI';letter-spacing:1px;")
        right.addWidget(prev_lbl)

        self._preview = QLabel(objectName="preview-lbl")
        self._preview.setFixedSize(400, 225)
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setText("Выберите источник")
        self._preview.setStyleSheet(
            "color:#72767d;font-size:13px;font-family:'Segoe UI';"
            "background:#202225;border-radius:4px;"
        )
        right.addWidget(self._preview)
        right.addStretch()
        split.addLayout(right)
        root.addLayout(split, 1)

        # Quality + FPS row
        settings_row = QHBoxLayout()
        settings_row.setSpacing(20)

        # Quality
        q_col = QVBoxLayout()
        q_col.setSpacing(6)
        q_lbl = QLabel("КАЧЕСТВО")
        q_lbl.setStyleSheet("color:#b9bbbe;font-size:11px;font-weight:700;"
                             "font-family:'Segoe UI';letter-spacing:1px;")
        q_col.addWidget(q_lbl)
        self._quality_combo = QComboBox()
        for label, *_ in QUALITY_PRESETS:
            self._quality_combo.addItem(label)
        self._quality_combo.setCurrentIndex(2)  # 720p default
        q_col.addWidget(self._quality_combo)
        settings_row.addLayout(q_col)

        # FPS
        fps_col = QVBoxLayout()
        fps_col.setSpacing(6)
        fps_lbl = QLabel("ЧАСТОТА КАДРОВ")
        fps_lbl.setStyleSheet("color:#b9bbbe;font-size:11px;font-weight:700;"
                               "font-family:'Segoe UI';letter-spacing:1px;")
        fps_col.addWidget(fps_lbl)

        fps_inner = QHBoxLayout()
        self._fps_slider = QSlider(Qt.Horizontal)
        self._fps_slider.setMinimum(0)
        self._fps_slider.setMaximum(len(FPS_OPTIONS) - 1)
        self._fps_slider.setValue(3)   # 30fps default
        self._fps_slider.setTickPosition(QSlider.TicksBelow)
        self._fps_slider.setTickInterval(1)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        fps_inner.addWidget(self._fps_slider)
        self._fps_val_lbl = QLabel("30 fps")
        self._fps_val_lbl.setStyleSheet(
            "color:#7289da;font-size:13px;font-weight:700;font-family:'Segoe UI';"
        )
        self._fps_val_lbl.setFixedWidth(55)
        fps_inner.addWidget(self._fps_val_lbl)
        fps_col.addLayout(fps_inner)
        settings_row.addLayout(fps_col, 1)
        root.addLayout(settings_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Отмена", objectName="btn-cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        self._start_btn = QPushButton("▶  Начать трансляцию", objectName="btn-start")
        self._start_btn.setFixedWidth(220)
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        root.addLayout(btn_row)

    def _populate_sources(self):
        self._sources.clear()
        self._list.clear()

        # Monitors
        try:
            with mss.mss() as sct:
                monitors = sct.monitors[1:]  # skip "all monitors" entry
                for i, m in enumerate(monitors, 1):
                    self._sources.append({
                        "type": "monitor",
                        "monitor_index": i,
                        "label": f"🖥  Монитор {i}  ({m['width']}×{m['height']})",
                    })
        except Exception:
            pass

        # Windows
        try:
            for w in _list_windows():
                self._sources.append({
                    "type": "window",
                    "hwnd": w["hwnd"],
                    "rect": w["rect"],
                    "label": f"🪟  {w['title'][:55]}",
                })
        except Exception:
            pass

        for s in self._sources:
            self._list.addItem(QListWidgetItem(s["label"]))

        if self._sources:
            self._list.setCurrentRow(0)

    def _on_source_changed(self, row: int):
        if row < 0 or row >= len(self._sources):
            return
        self._start_btn.setEnabled(True)
        src = self._sources[row]
        px = _capture_thumbnail(src)
        if px:
            scaled = px.scaled(400, 225, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview.setPixmap(scaled)
            self._preview.setText("")
        else:
            self._preview.setText("Нет предпросмотра")

    def _on_fps_changed(self, idx: int):
        fps = FPS_OPTIONS[idx]
        self._fps_val_lbl.setText(f"{fps} fps")

    def _on_start(self):
        row = self._list.currentRow()
        if row < 0:
            return
        src = dict(self._sources[row])
        qi = self._quality_combo.currentIndex()
        fi = self._fps_slider.value()
        _, w, h, q = QUALITY_PRESETS[qi]
        src["quality_index"] = qi
        src["width"] = w
        src["height"] = h
        src["jpeg_quality"] = q
        src["fps"] = FPS_OPTIONS[fi]
        self._result_data = src
        self.accept()

    def get_result(self) -> Optional[dict]:
        return self._result_data
