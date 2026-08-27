@echo off
cd /d %~dp0

if not exist .venv (
  echo Chua co .venv. Dang chay setup truoc...
  call setup_windows.bat
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo Khong kich hoat duoc .venv. Hay chay lai setup_windows.bat
  pause
  exit /b 1
)

python run.py
pause
