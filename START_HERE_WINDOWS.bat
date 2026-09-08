@echo off
chcp 65001 >nul
cd /d %~dp0

if not exist .venv\Scripts\activate.bat (
  echo [!] Chua co moi truong .venv hoac bi loi. Dang chay setup truoc...
  call setup_windows.bat
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [LOI] Khong kich hoat duoc .venv. Dang chay lai setup_windows.bat...
  call setup_windows.bat
  if errorlevel 1 exit /b 1
  call .venv\Scripts\activate.bat
)

if not exist print\lantern_template_balloon.png python tools\generate_template.py
if not exist print\lantern_template_round.png python tools\generate_template.py
if not exist print\lantern_template_rectangle.png python tools\generate_template.py

python run.py
pause
