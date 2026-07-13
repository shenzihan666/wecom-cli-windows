"""FastAPI application: wiring, lifespan (poller), static UI, routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import settings
from .db import database
from .services import service_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    database.connect()
    svc = service_registry.get("default")
    svc.load_state()
    svc.start_polling(settings.poll_sec)
    print(
        f"WeCom DM sync: http://{settings.host}:{settings.port}  "
        f"(self={svc.self_userid or 'auto'}, poll={settings.poll_sec}s)"
    )
    try:
        yield
    finally:
        for s in service_registry.all():
            s.stop_polling()
        database.close()


app = FastAPI(title="WeCom DM Sync", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(router)

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
