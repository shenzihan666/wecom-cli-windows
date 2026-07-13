@echo off
REM Start backend (FastAPI) + frontend (Vite) for local development.
REM Usage: dev.bat  (double-click or run from cmd)

setlocal
title WeCom Dev Launcher
cd /d "%~dp0"

set BACKEND_PORT=8765
set FRONTEND_PORT=5173

echo Cleaning up ports %BACKEND_PORT% and %FRONTEND_PORT% ...
call :KillPort %BACKEND_PORT%
call :KillPort %FRONTEND_PORT%

REM Close leftover windows from a previous run, if any
taskkill /FI "WINDOWTITLE eq WeCom Backend*"  /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq WeCom Frontend*" /T /F >nul 2>&1

echo Starting backend  -^> http://127.0.0.1:%BACKEND_PORT%
start "WeCom Backend" cmd /k "cd /d "%~dp0" && uv run python backend/run.py"

echo Starting frontend -^> http://127.0.0.1:%FRONTEND_PORT% (proxies /api,/media)
start "WeCom Frontend" cmd /k "cd /d "%~dp0frontend" && pnpm dev"

echo.
echo Both running in separate windows.
echo Press any key in THIS window to stop both and close their windows...
echo.
pause >nul

echo.
echo Stopping...
taskkill /FI "WINDOWTITLE eq WeCom Backend*"  /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq WeCom Frontend*" /T /F >nul 2>&1
call :KillPort %BACKEND_PORT%
call :KillPort %FRONTEND_PORT%
echo Done.
endlocal
exit /b 0

:KillPort
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    if not "%%P"=="0" (
        echo Port %PORT% in use by PID %%P - killing
        taskkill /PID %%P /T /F >nul 2>&1
    )
)
goto :eof
