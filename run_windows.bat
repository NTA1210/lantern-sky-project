@echo off
cd /d %~dp0

if not exist .venv (
  call setup_windows.bat
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
python run.py
pause
