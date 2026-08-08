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
    echo If this copy has no runtime\python, bundle it with:
    echo   powershell -File scripts\prepare_embedded_python.ps1
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
REM --- Frontend build: source repo has no committed dist ---
if exist "frontend\dist\index.html" goto :frontend_ready
echo [info] frontend\dist not found - building from source...
where npm >nul 2>&1
if errorlevel 1 goto :no_npm
pushd frontend
echo [2.5/3] npm install - first build may take a while...
call npm install
if errorlevel 1 goto :npm_install_failed
call npm run build
popd
if exist "frontend\dist\index.html" goto :frontend_ready
echo [ERROR] npm run build failed or produced no dist.
goto :dev_mode_hint

:no_npm
echo [ERROR] Node.js / npm not found, and frontend\dist is missing.
goto :dev_mode_hint

:npm_install_failed
popd
echo [ERROR] npm install failed.
goto :dev_mode_hint

:frontend_ready
if not exist "backend\storage\settings.json" (
  if exist "backend\storage\settings.example.json" (
    echo [info] Creating settings.json from example...
    copy /Y "backend\storage\settings.example.json" "backend\storage\settings.json" >nul
  )
)

if "%USE_EMBED%"=="1" goto :install_embed
echo [2/3] Checking dependencies...
"%PYEXE%" -m pip install --upgrade pip >nul
"%PYEXE%" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :pip_failed
goto :launch

:install_embed
if exist "runtime\python\.kairi_deps_ok" goto :launch
echo [2/3] Installing dependencies into bundled Python...
"%PYEXE%" -m pip install --upgrade pip >nul
"%PYEXE%" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :pip_failed
echo ok>"runtime\python\.kairi_deps_ok"
goto :launch

:pip_failed
echo [ERROR] pip install failed.
pause
exit /b 1

:launch
echo [3/3] Starting with browser opening...
echo First run: paste your DeepSeek API key in the wizard, it will be verified.
echo If port 8000 is busy, another port is chosen automatically.
echo Data folder: backend\storage - keep this when updating.
echo To quit: Ctrl+C in this window.
echo.
"%PYEXE%" "kairi_desktop.py"
pause
goto :eof

:dev_mode_hint
echo.
echo ================================================================
echo  frontend\dist could not be built automatically.
echo  Run the development servers instead:
echo.
echo  Terminal 1, backend:
echo    cd backend
echo    python -m venv .venv
echo    .venv\Scripts\activate
echo    pip install -r requirements.txt
echo    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
echo.
echo  Terminal 2, frontend:
echo    cd frontend
echo    npm install
echo    npm run dev
echo.
echo  Then open http://localhost:5173
echo ================================================================
pause
