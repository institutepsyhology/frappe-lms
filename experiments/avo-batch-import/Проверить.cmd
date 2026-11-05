@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\.."
py -3.12 "%~dp0frappe_batch_import.py" --from-course 13
echo.
echo Проверка завершена. Результаты записаны в журнал переноса.
pause
