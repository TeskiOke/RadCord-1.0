"""
main.py — Entry point for Radmin Discord.

1. Load or create config (SetupDialog on first run)
2. Start asyncio event loop in a background thread
3. Launch PySide6 main window
"""
import sys
import asyncio
import threading
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.logger_setup import setup_logging
setup_logging()

import traceback
import os
import datetime
from PySide6.QtWidgets import QMessageBox

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.getLogger().critical(f"Unhandled exception:\\n{err_msg}")
    
    try:
        crash_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", f"crash_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        os.makedirs(os.path.dirname(crash_file), exist_ok=True)
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write(err_msg)
    except:
        pass

    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Критическая ошибка RadCord")
        msg.setText("Произошла фатальная ошибка и программа будет закрыта.\\nЛог ошибки сохранен в папке logs.")
        msg.setDetailedText(err_msg)
        msg.exec()
    except:
        pass

sys.excepthook = global_exception_handler
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RadCord")
    app.setOrganizationName("RadminDiscord")

    # Global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # ── Config ────────────────────────────────────────────────────────────────
    from core.identity import load_config
    
    config = load_config()

    if config is None:
        from ui.setup_dialog import SetupDialog
        dlg = SetupDialog()
        if dlg.exec() != SetupDialog.Accepted:
            sys.exit(0)
        config = dlg.get_config()

    # ── asyncio event loop in background thread ───────────────────────────────
    async_loop = asyncio.new_event_loop()

    def _run_loop():
        asyncio.set_event_loop(async_loop)
        async_loop.run_forever()

    bg_thread = threading.Thread(target=_run_loop, daemon=True, name="AsyncLoop")
    bg_thread.start()

    # ── Main window ───────────────────────────────────────────────────────────
    from ui.app import MainWindow
    window = MainWindow(config, async_loop)
    window.show()

    exit_code = app.exec()

    # ── Clean shutdown ────────────────────────────────────────────────────────
    async_loop.call_soon_threadsafe(async_loop.stop)
    bg_thread.join(timeout=2)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
