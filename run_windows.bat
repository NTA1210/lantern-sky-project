@echo off
cd /d %~dp0

if not exist .venv (
  call setup_windows.bat
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
if not exist print\lantern_template.png python tools\generate_template.py
if not exist print\lantern_template_balloon.png python tools\generate_template.py
if not exist print\lantern_template_round.png python tools\generate_template.py
if not exist print\lantern_template_rectangle.png python tools\generate_template.py
python run.py
pause
