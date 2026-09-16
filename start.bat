@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запуск NRI Projects API...
start "" http://127.0.0.1:8000
python -m uvicorn app.main:app --port 8000
pause
