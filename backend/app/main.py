"""FastAPI application: wiring, lifespan (poller), static UI, routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import settings
from .services import service_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.static_dir.mkdir(parents=True, exist_ok=True)

    svc = service_registry.get("default")
    svc.load_cache()
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


app = FastAPI(title="WeCom DM Sync", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(router)

if settings.static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")
