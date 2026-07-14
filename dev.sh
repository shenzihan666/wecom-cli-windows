#!/usr/bin/env bash
# Start backend (FastAPI) + frontend (Vite) for local development (macOS/Linux).
# Usage: ./dev.sh
#
# Mirror of dev.bat. Backend runs in the foreground in this terminal; the
# frontend opens in the background. Press Ctrl-C to stop both.

set -euo pipefail
cd "$(dirname "$0")"

BACKEND_PORT=8765
FRONTEND_PORT=5173

cleanup() {
  echo
  echo "Stopping..."
  jobs -p | xargs -r kill 2>/dev/null || true
  # Free the dev ports if anything is still listening on them.
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    [ -n "$pids" ] && kill $pids 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "Starting backend -> http://127.0.0.1:${BACKEND_PORT}"
uv run python backend/run.py &
BACKEND_PID=$!

echo "Starting frontend -> http://127.0.0.1:${FRONTEND_PORT} (proxies /api,/media,/ws)"
(
  cd frontend
  pnpm dev
) &
FRONTEND_PID=$!

echo
echo "Backend PID=${BACKEND_PID}, Frontend PID=${FRONTEND_PID}"
echo "Press Ctrl-C to stop both."

# Wait for either to exit, then tear everything down via the trap.
# NOTE: do NOT use `wait -n` — it needs bash >= 4.3 and macOS ships bash 3.2.
# Poll both PIDs instead so we tear down as soon as either one dies.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 0.5
done
echo
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend (PID $BACKEND_PID) exited."
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "Frontend (PID $FRONTEND_PID) exited."
fi
