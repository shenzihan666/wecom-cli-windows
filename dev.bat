@echo off
REM Launch the Electron desktop app in development mode (Windows).
REM
REM Electron's main process owns the full stack: it spawns the FastAPI backend
REM (uv run python backend/run.py) and the Vite dev server (pnpm dev), polls
REM them until healthy, then opens a BrowserWindow at the Vite URL (HMR).
REM Closing the window tears down both child processes, so there is no manual
REM port cleanup to do here anymore.
REM
REM Usage: dev.bat  (double-click or run from cmd)

setlocal
cd /d "%~dp0"

call pnpm electron:dev

endlocal
