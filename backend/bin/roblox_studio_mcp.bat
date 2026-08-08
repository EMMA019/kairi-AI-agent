@echo off
REM ============================================================
REM  Kairi - Roblox Studio built-in MCP server launcher
REM  Resolves the newest StudioMCP.exe and launches it.
REM
REM  Search order:
REM    1. %ROBLOX_VERSIONS_DIR% (manual override)
REM    2. %LOCALAPPDATA%\Roblox\Versions (standard install)
REM    3. <drive>:\Roblox\Versions for C/D/E/F (custom install)
REM  Newest file wins, so Studio auto-updates are tolerated.
REM  stdio handles are inherited directly by StudioMCP.exe.
REM ============================================================
setlocal EnableDelayedExpansion

set "MCP_EXE="

if defined ROBLOX_VERSIONS_DIR (
    for /f "delims=" %%i in ('dir /b /s /o-d "%ROBLOX_VERSIONS_DIR%\StudioMCP.exe" 2^>nul') do (
        if not defined MCP_EXE set "MCP_EXE=%%i"
    )
)

if not defined MCP_EXE (
    for /f "delims=" %%i in ('dir /b /s /o-d "%LOCALAPPDATA%\Roblox\Versions\StudioMCP.exe" 2^>nul') do (
        if not defined MCP_EXE set "MCP_EXE=%%i"
    )
)

if not defined MCP_EXE (
    for %%d in (C D E F) do (
        if not defined MCP_EXE (
            for /f "delims=" %%i in ('dir /b /s /o-d "%%d:\Roblox\Versions\StudioMCP.exe" 2^>nul') do (
                if not defined MCP_EXE set "MCP_EXE=%%i"
            )
        )
    )
)

if not defined MCP_EXE (
    echo [Kairi] StudioMCP.exe not found. 1>&2
    echo [Kairi] Update Roblox Studio, or set ROBLOX_VERSIONS_DIR to your Versions folder. 1>&2
    exit /b 1
)

"%MCP_EXE%" %*
