"""
network_dialog.py — Dialog to Join or Create a network.
Similar to the old SetupDialog but focused on networking only.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QStackedWidget, QWidget
)
from PySide6.QtCore import Qt, QTimer


STYLE = """
QDialog {
    background: #000000;
}
QLabel#title {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
    font-family: 'Segoe UI';
}
QLabel.field-label {
    color: #b5bac1; font-size: 11px; font-weight: 800;
    font-family: 'Segoe UI'; letter-spacing: 0.5px;
}
QLineEdit {
    background: #0a0a0a;
    border: 1px solid #222222;
    border-radius: 4px;
    color: #dbdee1;
    font-size: 14px;
    padding: 10px;
}
QLineEdit:focus {
    border-color: #7289da;
}
QPushButton#btn-back {
    background: transparent;
    color: #b5bac1;
    border: none;
    font-size: 14px;
    font-weight: 600;
}
QPushButton#btn-back:hover {
    color: white;
    text-decoration: underline;
}
QPushButton#btn-confirm {
    background: #5865f2;
    color: white;
    border: none;
    border-radius: 4px;
    font-weight: 600;
    padding: 10px;
}
QPushButton#btn-confirm:hover {
    background: #4752c4;
}
QPushButton.mode-btn {
    background: #0a0a0a;
    color: #dbdee1;
    border: 2px solid #222222;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 700;
    padding: 20px;
    text-align: left;
}
QPushButton.mode-btn:hover {
    background: #111111;
    border-color: #5865f2;
}
"""


class NetworkDialog(QDialog):
    def __init__(self, mode="join", async_loop=None, parent=None):
        """mode: 'join' or 'create'"""
        super().__init__(parent)
        self.setFixedSize(450, 500)
        self.setWindowTitle("Добавить сеть")
        self.setStyleSheet(STYLE)
        self._async_loop = async_loop
        self.result_data = None
        self._mode = mode
        
        # Scanner stuff
        self._networks = []
        self._scan_thread = None
        
        self._build_ui()
        if self._mode == "join":
            self._start_scan()


    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(15)

        title_text = "➕ Создать новую сеть" if self._mode == "create" else "🔍 Поиск сетей поблизости"
        title = QLabel(title_text, objectName="title")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        self._stack = QStackedWidget()
        lay.addWidget(self._stack)

        # --- View 1: Create or Manual Join (actually manual join is gone now, it's scan) ---
        if self._mode == "create":
            create_w = QWidget()
            cl = QVBoxLayout(create_w)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(12)

            cl.addWidget(self._field_label("НАЗВАНИЕ СЕТИ"))
            self._net_edit = QLineEdit(placeholderText="Например: Моя банда")
            cl.addWidget(self._net_edit)

            cl.addWidget(self._field_label("ПАРОЛЬ"))
            self._pass_edit = QLineEdit(placeholderText="Пароль")
            self._pass_edit.setEchoMode(QLineEdit.Password)
            cl.addWidget(self._pass_edit)

            cl.addWidget(self._field_label("ПОДТВЕРЖДЕНИЕ ПАРОЛЯ"))
            self._pass2_edit = QLineEdit(placeholderText="Повторите пароль")
            self._pass2_edit.setEchoMode(QLineEdit.Password)
            cl.addWidget(self._pass2_edit)
            
            self._stack.addWidget(create_w)
        else:
            # Join/Scan View
            scan_w = QWidget()
            sl = QVBoxLayout(scan_w)
            sl.setContentsMargins(0, 0, 0, 0)
            sl.setSpacing(10)

            self._scan_status = QLabel("🔎 Сканирую Radmin VPN… (4 сек)")
            self._scan_status.setStyleSheet("color: #7289da; font-weight: 600; font-family: 'Segoe UI';")
            self._scan_status.setAlignment(Qt.AlignCenter)
            sl.addWidget(self._scan_status)

            from PySide6.QtWidgets import QScrollArea
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
            self._list_w = QWidget()
            self._list_lay = QVBoxLayout(self._list_w)
            self._list_lay.setAlignment(Qt.AlignTop)
            self._list_lay.setSpacing(6)
            scroll.setWidget(self._list_w)
            sl.addWidget(scroll)

            self._stack.addWidget(scan_w)

        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet("color: #f04747; font-size: 12px;")
        lay.addWidget(self._err_lbl)

        lay.addStretch()

        btns = QHBoxLayout()
        btn_back = QPushButton("Отмена", objectName="btn-back")
        btn_back.clicked.connect(self.reject)
        btns.addWidget(btn_back)

        if self._mode == "create":
            btn_confirm = QPushButton("Создать", objectName="btn-confirm")
            btn_confirm.setFixedHeight(40)
            btn_confirm.clicked.connect(self._on_confirm_create)
            btns.addWidget(btn_confirm)
        else:
            self._btn_rescan = QPushButton("Пересканировать", objectName="btn-confirm")
            self._btn_rescan.setFixedHeight(40)
            self._btn_rescan.clicked.connect(self._start_scan)
            self._btn_rescan.hide()
            btns.addWidget(self._btn_rescan)
        
        lay.addLayout(btns)


    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #b9bbbe; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
        return lbl

    def _on_confirm_create(self):
        name = self._net_edit.text().strip()
        pw = self._pass_edit.text()
        if not name:
            self._err_lbl.setText("Введите название")
            return
        if len(pw) < 4:
            self._err_lbl.setText("Пароль должен быть от 4 символов")
            return
        if pw != self._pass2_edit.text():
            self._err_lbl.setText("Пароли не совпадают")
            return
            
        # Duplicate name check
        from core.identity import load_config
        cfg = load_config()
        if cfg and any(n["name"].lower() == name.lower() for n in cfg.get("networks", [])):
            self._err_lbl.setText("Сеть с таким названием уже есть")
            return

        self.result_data = (name, pw)
        self.accept()

    def _start_scan(self):
        if hasattr(self, "_scanning") and self._scanning: return
        self._scanning = True
        
        if self._btn_rescan: self._btn_rescan.hide()

        self._scan_status.setText("🔎 Сканирую Radmin VPN")
        self._dots = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_dots)
        self._timer.start(500)

        # Clear list
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        from PySide6.QtCore import QThread, QObject, Signal
        class Worker(QObject):
            done = Signal(list)
            def run(self, loop):
                from core.network_scanner import NetworkScanner
                import asyncio
                fut = asyncio.run_coroutine_threadsafe(NetworkScanner().scan(duration=4.0), loop)
                try: res = fut.result(timeout=6.0)
                except: res = []
                self.done.emit(res)

        self._scan_thread = QThread()
        self._worker = Worker()
        self._worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(lambda: self._worker.run(self._async_loop))
        self._worker.done.connect(self._on_scan_done)
        self._scan_thread.start()

    def _update_dots(self):
        self._dots = (self._dots + 1) % 4
        self._scan_status.setText("🔎 Сканирую Radmin VPN" + "." * self._dots)

    def _on_scan_done(self, results):
        self._scanning = False
        if hasattr(self, "_timer"): self._timer.stop()

        self._scan_thread.quit()
        self._scan_thread.wait()

        self._scan_status.setText(f"Найдено сетей: {len(results)}")
        if self._btn_rescan: self._btn_rescan.show()
        
        for net in results:
            name = net.get("name") or f"Неизвестная сеть ({net['network_id'][:8]})"
            btn = QPushButton(f"{name} ({len(net['users'])} онлайн)")
            btn.setStyleSheet("""
                QPushButton { 
                    background: #0a0a0a; color: #dbdee1; border: 1px solid #222222; 
                    padding: 12px; border-radius: 6px; text-align: left; font-family: 'Segoe UI'; font-size: 14px;
                }
                QPushButton:hover { background: #111111; border-color: #7289da; color: white; }
            """)
            btn.clicked.connect(lambda _, n=net: self._on_net_selected(n))
            self._list_lay.addWidget(btn)



    def _on_net_selected(self, net):
        from PySide6.QtWidgets import QInputDialog
        # Ensure we have a name for the join flow
        display_name = net.get("name") or f"Unknown Group ({net['network_id'][:8]})"
        
        pw, ok = QInputDialog.getText(
            self, f"Вход в «{display_name}»",
            "Введите пароль сети:", QLineEdit.Password
        )
        if not ok or not pw: return
        
        from core.identity import make_network_id
        # Use the name from the packet if it exists, else we can't really verify via ID 
        # unless we know what name was used to create it. 
        # Discord-style: usually the name is fixed.
        join_name = net.get("name") or ""
        
        if make_network_id(join_name, pw) == net["network_id"]:
            self.result_data = (join_name, pw)
            self.accept()

        else:
            self._err_lbl.setText("Неверный пароль")

