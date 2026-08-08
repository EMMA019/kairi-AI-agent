@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "KAIRI_RELEASE=1"
set "ALLOW_OPEN_CORS=0"
REM Radar/briefing schedulers OFF by default (set KAIRI_ENABLE_SCHEDULERS=1 to enable)
if not defined KAIRI_ENABLE_SCHEDULERS set "KAIRI_ENABLE_SCHEDULERS=0"

echo ========================================
echo   Kairi Desktop
echo   Market companion chat (BYOK)
echo ========================================
echo.

REM --- Prefer bundled embeddable Python (no system Python required) ---
if exist "runtime\python\python.exe" (
  set "PYEXE=runtime\python\python.exe"
  set "USE_EMBED=1"
  echo [info] Using bundled Python: runtime\python
  goto :deps_and_launch
)

REM --- Fallback: system Python + local .venv ---
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PYLAUNCH=py -3"
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set "PYLAUNCH=python"
  ) else (
    echo [ERROR] Python not found.
    echo.
    echo If this zip has no runtime\python, ask the packager to run:
    echo   powershell -File scripts\prepare_embedded_python.ps1
    echo   powershell -File scripts\build_booth_zip.ps1
    echo.
    echo For development: install Python 3.11+ from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH".
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  %PYLAUNCH% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
)
set "PYEXE=.venv\Scripts\python.exe"
set "USE_EMBED=0"

:deps_and_launch
if not exist "frontend\dist\index.html" (
  echo [ERROR] frontend\dist is missing. The package may be incomplete.
  pause
  exit /b 1
)

if not exist "backend\storage\settings.json" (
  if exist "backend\storage\settings.example.json" (
    echo [info] Creating settings.json from example...
    copy /Y "backend\storage\settings.example.json" "backend\storage\settings.json" >nul
  )
)

if "%USE_EMBED%"=="1" (
  if not exist "runtime\python\.kairi_deps_ok" (
    echo [2/3] Installing dependencies into bundled Python.
    "%PYEXE%" -m pip install --upgrade pip >nul
    "%PYEXE%" -m pip install -r "backend\requirements.txt"
    if errorlevel 1 (
      echo [ERROR] pip install failed.
      pause
      exit /b 1
    )
    echo ok>"runtime\python\.kairi_deps_ok"
  ) else (
    echo [2/3] Dependencies already present in bundled Python.
  )
) else (
  echo [2/3] Checking dependencies...
  "%PYEXE%" -m pip install --upgrade pip >nul
  "%PYEXE%" -m pip install -r "backend\requirements.txt"
  if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
  )
)

echo [3/3] Starting (browser will open)...
echo First run: paste your DeepSeek API key in the wizard (it will be verified).
echo If port 8000 is busy, another port is chosen automatically.
echo Data folder: backend\storage  (keep this when updating the zip)
echo To quit: Ctrl+C in this window.
echo.
"%PYEXE%" "kairi_desktop.py"
pause
