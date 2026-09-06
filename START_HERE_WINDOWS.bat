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

if not exist print\lantern_template_balloon.png python tools\generate_template.py
if not exist print\lantern_template_round.png python tools\generate_template.py
if not exist print\lantern_template_rectangle.png python tools\generate_template.py

python run.py
pause
