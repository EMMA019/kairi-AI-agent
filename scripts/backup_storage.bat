@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "SRC=backend\storage"
if not exist "%SRC%" (
  echo [ERROR] %SRC% not found.
  pause
  exit /b 1
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "DEST=kairi_storage_backup_%STAMP%"
echo Copying %SRC% -^> %DEST% ...
xcopy "%SRC%" "%DEST%\" /E /I /H /Y >nul
if errorlevel 1 (
  echo [ERROR] Copy failed.
  pause
  exit /b 1
)
echo Done: %CD%\%DEST%
echo Keep this folder when you unpack a new Kairi zip, then copy it back to backend\storage.
pause
