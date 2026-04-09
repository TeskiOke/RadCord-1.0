@echo off
echo ========================================
echo   Radmin Discord — Build
echo ========================================

echo.
echo [1/3] Installing dependencies...
pip install -r requirements.txt

echo.
echo [2/3] Building executable...
pyinstaller --noconfirm --onefile --windowed ^
  --name "RadminDiscord" ^
  --add-data "shared;shared" ^
  --hidden-import "websockets" ^
  --hidden-import "sounddevice" ^
  --hidden-import "numpy" ^
  --hidden-import "PIL" ^
  --hidden-import "mss" ^
  --hidden-import "PySide6.QtWidgets" ^
  --hidden-import "PySide6.QtCore" ^
  --hidden-import "PySide6.QtGui" ^
  main.py

echo.
echo [3/3] Done!
echo Executable: dist\RadminDiscord.exe
echo.
pause
