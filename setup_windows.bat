@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d %~dp0

echo.
echo ========================================
echo   Lantern Sky - Setup He Thong Windows
echo ========================================
echo.

:: [Buoc 0] Tu dong cap nhat Git (neu co)
where git >nul 2>nul
if not errorlevel 1 (
  if exist .git (
    echo [Git] Dang kiem tra va dong bo code moi nhat...
    git pull --autostash
    if errorlevel 1 (
      echo [!] Khong the pull Git luc nay (co the do mat mang hoac sua code offline).
      echo [!] Van tiep tuc setup voi ban code hien tai...
    ) else (
      echo [Git] Da dong bo ma nguon moi nhat thanh cong.
    )
    echo.
  )
)

:: [Buoc 1] Tim kiem Python 3.10+
set "PYTHON_CMD="

:: Kiem tra launcher "py -3"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    goto python_found
  )
)

:: Kiem tra lenh "python"
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=python"
    goto python_found
  )
)

:: Kiem tra cac thu muc cai dat Python pho bien tren Windows
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
  "C:\Python310\python.exe"
  "C:\Program Files\Python313\python.exe"
  "C:\Program Files\Python312\python.exe"
  "C:\Program Files\Python311\python.exe"
  "C:\Program Files\Python310\python.exe"
) do (
  if exist %%P (
    %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 (
      set "PYTHON_CMD=%%P"
      goto python_found
    )
  )
)

:python_missing
echo =====================================================================
echo [LOI] Khong tim thay Python 3.10+ tren may tinh!
echo.
echo Huong dan:
echo 1. Tai Python 3.11 hoac 3.12 tu: https://www.python.org/downloads/
echo 2. Khi cai dat, NHO TICK CHON vao o: "Add python.exe to PATH"
echo 3. Chay lai file setup_windows.bat nay.
echo =====================================================================
echo.
pause
exit /b 1

:python_found
echo [1/5] Su dung Python: %PYTHON_CMD%

:: Kiem tra neu thu muc .venv cu bi loi / hong
if exist .venv (
  if not exist .venv\Scripts\activate.bat (
    echo [!] Phat hien moi truong .venv cu bi hong, dang khoi phuc lai...
    rmdir /s /q .venv >nul 2>nul
  )
)

:: Tao moi .venv neu chua co
if not exist .venv (
  echo [1/5] Dang tao moi truong ao .venv...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo [LOI] Khong the tao .venv. Kiem tra quyen ghi thu muc hoac dung luong o dia.
    goto fail
  )
) else (
  echo [1/5] Moi truong .venv da san sang.
)

:: [Buoc 2] Kich hoat moi truong ao
echo [2/5] Kich hoat .venv...
call .venv\Scripts\activate.bat
if errorlevel 1 goto fail

:: [Buoc 3] Kiem tra va dam bao co pip
echo [3/5] Kiem tra trinh quan ly goi pip...
python -m pip --version >nul 2>nul
if errorlevel 1 (
  echo [3/5] Dang cai dat pip cho .venv qua ensurepip...
  python -m ensurepip --upgrade >nul 2>nul
)

:: Thu cap nhat pip (neu loi do quyen file hoac mang thi bo qua van chay tiep)
python -m pip install --upgrade pip --no-warn-script-location >nul 2>nul

:: [Buoc 4] Cai dat dependencies voi co che Retry tu dong
echo [4/5] Dang cai dat cac thu vien (FastAPI, OpenCV, Pillow...)...
python -m pip install -r requirements.txt --prefer-binary --no-warn-script-location
if errorlevel 1 (
  echo.
  echo [!] Co the do mang yeu hoac timeout. Dang thu lai voi retry cao hon...
  python -m pip install -r requirements.txt --prefer-binary --no-warn-script-location --retries 5 --timeout 45
  if errorlevel 1 (
    echo [LOI] Khong the cai dat cac thu vien Python. Kiem tra lai ket noi Internet.
    goto fail
  )
)

:: [Buoc 5] Tao cac thu muc can thiet va template in
echo [5/5] Khoi tao thu muc du lieu va templates...
if not exist data\lanterns mkdir data\lanterns
if not exist data\backgrounds mkdir data\backgrounds
if not exist data\original mkdir data\original
if not exist data\corrected mkdir data\corrected
if not exist print mkdir print

python tools\generate_template.py
if errorlevel 1 (
  echo [CANH BAO] Khong the tao template tu dong, dang thu lai...
  python tools\generate_template.py
)

:: Chay self-test kiem tra OpenCV & thuat toan
echo Dang kiem tra tinh toan ven he thong (Self-test)...
python tools\self_test.py
if errorlevel 1 (
  echo [CANH BAO] Self-test gap canh bao, nhung he thong van co the hoat dong.
) else (
  echo [Self-Test] Tat ca cac module scan, template va storage deu hoat dong tot.
)

echo.
echo =====================================================================
echo  SETUP HOAN TAT THANH CONG!
echo =====================================================================
echo.
echo Cach khoi dong he thong:
echo  - Double click vao file: START_HERE_WINDOWS.bat (hoac run_windows.bat)
echo  - Giao dien Dieu Khien:  http://127.0.0.1:8000/control
echo  - Giao dien Man Hinh Chieu: http://127.0.0.1:8000/display
echo.
pause
exit /b 0

:fail
echo.
echo =====================================================================
echo [LOI] Qua trinh setup gap su co giua chung.
echo Vui long chup anh man hinh dong loi ben tren de duoc tro giup.
echo =====================================================================
echo.
pause
exit /b 1