@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\.."
py -3.12 "%~dp0frappe_batch_import.py" --apply
echo.
echo Перенос завершён или остановлен. Подробности записаны в журнал.
pause
