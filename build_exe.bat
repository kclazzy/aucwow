@echo off
rem Сборка одного файла ForeverDeals.exe (нужен установленный Python 3.10+ с tkinter).
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconsole --onefile --name ForeverDeals app.py
echo.
echo Готово: dist\ForeverDeals.exe
pause
