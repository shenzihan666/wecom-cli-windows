"""FastAPI application: wiring, lifespan (poller), static UI, routers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import http_router, logs_router
from .config import settings
from .core.media import tool_exists
from .core.runtime_settings import get_poll_sec
from .db import database
from .services import service_registry
from .subprocess import account_manager, account_process_manager

logger = logging.getLogger(__name__)

# Main process logs to console only (per-account workers own the file logs).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def _check_media_tools() -> None:
    """Warn (don't fail) if ffmpeg/ffprobe can't be found anywhere.

    Checks the vendored ``ffmpeg/`` + ``bin/`` dirs and PATH. A missing ffmpeg
    only breaks AMR/audio transcoding, so we keep booting.
    """
    missing = [name for name in ("ffmpeg", "ffprobe") if not tool_exists(name)]
    if missing:
        logger.warning(
            "%s not found in ./ffmpeg, ./bin, or PATH. "
            "Audio/video transcoding will fail. Install ffmpeg to fix this.",
            ", ".join(missing),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    _check_media_tools()

    database.connect()

    killed = account_process_manager.cleanup_orphans()
    if killed:
        logger.info("Cleaned up %d orphaned poll-worker process tree(s)", killed)

    poll_sec = get_poll_sec()
    for account in account_manager.list():
        svc = service_registry.get(account.id)
        svc.load_state()
        if account_manager.is_enabled(account.id):
            account_process_manager.start(account, poll_sec)

    logger.info(
        "WeCom DM sync: http://%s:%s  (accounts=%d, poll=%ss)",
        settings.host,
        settings.port,
        len(account_manager.list()),
        poll_sec,
    )
    try:
        yield
    finally:
        account_process_manager.stop_all()
        database.close()


app = FastAPI(title="WeCom DM Sync", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(http_router)
app.include_router(logs_router)

# Serve the built Vue 3 + Element Plus SPA from frontend/dist.
# Run `vp build` inside frontend/ to (re)generate it.
_DIST = settings.frontend_dist

if (_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa(full_path: str) -> FileResponse:
    """SPA entry + static passthrough. API/media routes are matched first."""
    index_file = _DIST / "index.html"
    if full_path:
        candidate = (_DIST / full_path).resolve()
        # Serve real files (favicon.svg, icons.svg, ...) that live under dist,
        # guarding against path traversal; otherwise fall back to the SPA shell.
        if _DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(index_file)
