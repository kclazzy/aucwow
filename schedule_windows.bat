@echo off
rem Ежедневный запуск в 20:00 без окна: отчёт сохраняется в %USERPROFILE%\.forever_deals\reports
rem После запуска HTML-отчёт откроется в браузере. Если приложение уже открыто, оно само запустит поиск вечером. Эта задача нужна, когда оно закрыто.
schtasks /Create /SC DAILY /ST 20:00 /TN "WoWForeverDeals" /TR "pythonw \"%~dp0app.py\" --run-once --open" /F
echo Задача WoWForeverDeals создана. Удалить: schtasks /Delete /TN WoWForeverDeals /F
pause
