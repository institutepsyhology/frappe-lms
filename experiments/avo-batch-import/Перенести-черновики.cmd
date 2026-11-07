@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\.."
set "AVO_JOURNAL_MODE="
if exist "exports\lesson-content\mv-centr-remote-journal.enabled" set "AVO_JOURNAL_MODE=--remote-journal"
py -3.12 "%~dp0frappe_batch_import.py" --from-course 13 --apply %AVO_JOURNAL_MODE%
echo.
echo Перенос завершён или остановлен. Подробности записаны в журнал.
pause
