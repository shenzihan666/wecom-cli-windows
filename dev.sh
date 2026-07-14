#!/usr/bin/env bash
# Launch the Electron desktop app in development mode (macOS/Linux).
#
# Electron's main process owns the full stack: it spawns the FastAPI backend
# (uv run python backend/run.py) and the Vite dev server (pnpm dev), polls
# them until healthy, then opens a BrowserWindow at the Vite URL (HMR).
# Closing the window tears down both child processes via tree-kill, so there
# is no manual port cleanup to do here anymore.
#
# Usage: ./dev.sh

set -euo pipefail
cd "$(dirname "$0")"

exec pnpm electron:dev
