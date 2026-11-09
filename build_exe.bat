@echo off
rem Сборка одного файла ForeverDeals.exe (нужен установленный Python 3.10+ с tkinter).
python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconsole --onefile --name ForeverDeals --add-data "forever_deals/mobile;forever_deals/mobile" app.py
echo.
echo Готово: dist\ForeverDeals.exe
pause
