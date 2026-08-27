@echo off
setlocal
cd /d %~dp0

echo.
echo ========================================
echo  Lantern Sky - Windows setup
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay Python launcher "py".
  echo Cai Python 3.11+ tu https://www.python.org/downloads/windows/
  echo Nho tick "Add python.exe to PATH" khi cai.
  echo.
  pause
  exit /b 1
)

py -3 --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Khong tim thay Python 3.
  echo Hay cai Python 3.11+ roi chay lai file nay.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo [1/5] Tao moi moi truong ao .venv...
  py -3 -m venv .venv
  if errorlevel 1 goto fail
) else (
  echo [1/5] Da co .venv, bo qua buoc tao moi.
)

echo [2/5] Kich hoat .venv...
call .venv\Scripts\activate.bat
if errorlevel 1 goto fail

echo [3/5] Cap nhat pip...
python -m pip install --upgrade pip
if errorlevel 1 goto fail

echo [4/5] Cai thu vien Python...
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo [5/5] Tao template va chay self-test...
python tools\generate_template.py
if errorlevel 1 goto fail
python tools\self_test.py
if errorlevel 1 goto fail

echo.
echo ========================================
echo  Setup xong.
echo ========================================
echo.
echo De chay app: double click START_HERE_WINDOWS.bat
echo Hoac chay: run_windows.bat
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Setup bi loi. Hay xem dong loi ngay phia tren.
echo Neu loi lien quan camera thi van co the setup xong, nhung luc chay can cap quyen camera.
echo.
pause
exit /b 1
