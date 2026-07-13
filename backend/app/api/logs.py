"""WebSocket log streaming endpoint.

One connection per account subscribes to a *tail* of that account's worker log
file (``data/logs/{account_id}.log``). On connect we send the last ~200 lines as
history, then stream new lines as the worker writes them.

Heartbeat contract
------------------
The frontend sends an application-level ``"ping"`` text frame roughly every 25s
and treats silence beyond ~35s as fatal (it closes and reconnects). The server
only replies with ``"pong"``. The 90s ``receive_text`` timeout below is a
backstop in case both the app heartbeat and the transport ping go silent: it
probes with one final ``send_text`` and breaks out if that write fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Lines of history replayed immediately when a client connects.
_HISTORY_LINES = 200
# Poll interval for the tail loop when no new data is available.
_TAIL_POLL_SEC = 0.2

# Parse worker log lines like:
#   2026-07-14 10:30:00,123 INFO [poll_worker] actual message
# Non-matching lines (e.g. raw prints before logging is configured) are kept as
# INFO with the current timestamp so nothing is lost on the frontend.
_LOG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]?\d*)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\b\s*(?:\[[^\]]*\]\s*)?(?P<msg>.*)$"
)


def _log_path(account_id: str) -> Path:
    return settings.logs_dir / f"{account_id}.log"


def _parse_line(raw: str) -> dict:
    m = _LOG_RE.match(raw.rstrip("\n"))
    if m:
        return {
            "timestamp": m.group("ts"),
            "level": m.group("level"),
            "message": m.group("msg"),
        }
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": "INFO",
        "message": raw.rstrip("\n"),
    }


def _tail_history(path: Path, n: int) -> list[str]:
    """Return the last ``n`` lines of ``path`` (without trailing newlines)."""
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            # deque(maxlen=n) keeps only the trailing n lines cheaply.
            from collections import deque

            return list(deque(f, maxlen=n))
    except OSError:
        return []


@router.websocket("/ws/logs/{account_id}")
async def websocket_logs(websocket: WebSocket, account_id: str) -> None:
    """Stream a single account's worker log file to the client."""
    await websocket.accept()
    path = _log_path(account_id)
    client_tag = f"{account_id}@{id(websocket):x}"

    # Replay recent history first, so a freshly opened panel isn't blank.
    for line in _tail_history(path, _HISTORY_LINES):
        try:
            await websocket.send_json(_parse_line(line))
        except Exception:
            # Client gone before we finish history -- nothing else to do.
            await websocket.close()
            return

    try:
        await websocket.send_json(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "level": "INFO",
                "message": f"已连接到 {account_id} 日志流",
            }
        )
    except Exception:
        await websocket.close()
        return

    # Open the file and seek to end; subsequent reads pick up only new bytes.
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        # No log yet (account never started). Send a notice and still tail so
        # logs appear the moment the worker starts writing.
        try:
            await websocket.send_json(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "level": "WARNING",
                    "message": "日志文件尚未创建，等待 worker 启动…",
                }
            )
        except Exception:
            await websocket.close()
            return
        f = None

    disconnect_reason = "unknown"
    try:
        while True:
            new_lines: list[str] = []
            if f is not None:
                chunk = f.read()
                while chunk:
                    if "\n" in chunk:
                        head, chunk = chunk.split("\n", 1)
                        new_lines.append(head)
                    else:
                        # Partial line without newline; hold for next iteration.
                        f.seek(f.tell() - len(chunk.encode("utf-8", errors="replace")))
                        break
                # Re-open if the file was rotated under us (size shrank or moved).
                _check_rotation(path, f)

            for line in new_lines:
                try:
                    await websocket.send_json(_parse_line(line))
                except Exception:
                    disconnect_reason = "send-failed"
                    raise

            if new_lines:
                continue  # drain anything pending before sleeping

            # No new data. Besides sleeping, honour the heartbeat contract:
            # if the client is silent for 90s we probe once and bail on failure.
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=90.0)
            except TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:
                    disconnect_reason = "inactivity-probe-failed"
                    break
                continue

            if data == "ping":
                try:
                    await websocket.send_text("pong")
                except Exception:
                    disconnect_reason = "pong-send-failed"
                    break
            elif data == "pong":
                continue
            # Any other inbound text is ignored: this channel is server -> client.

    except WebSocketDisconnect as e:
        disconnect_reason = f"client-disconnect:{e.code}"
    except Exception as e:  # noqa: BLE001 - want to log any unexpected failure
        disconnect_reason = f"server-error:{type(e).__name__}"
        logger.warning("websocket_logs unexpected error for %s: %s", client_tag, e)
    finally:
        logger.info("websocket_logs closed client=%s reason=%s", client_tag, disconnect_reason)
        if f is not None:
            try:
                f.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


def _check_rotation(path: Path, f) -> None:
    """Re-open the file handle if it was rotated/truncated (size < offset)."""
    try:
        if path.is_file() and path.stat().st_size < f.tell():
            f.seek(0)
    except OSError:
        pass
