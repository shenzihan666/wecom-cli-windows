"""HTTP endpoints. Mirrors the original experimental server's API surface."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..config import settings
from ..schemas import (
    ConversationsResponse,
    MessagesResponse,
    SendRequest,
    SendResponse,
    StatusResponse,
)
from ..services import SyncService
from .deps import get_service

router = APIRouter()


@router.get("/api/conversations", response_model=ConversationsResponse)
def conversations(svc: SyncService = Depends(get_service)) -> dict:
    return svc.conversations_list()


@router.get("/api/messages", response_model=MessagesResponse)
def messages(userid: str, svc: SyncService = Depends(get_service)) -> dict:
    if not userid:
        raise HTTPException(status_code=400, detail="userid required")
    return svc.messages_for(userid)


@router.get("/api/status", response_model=StatusResponse)
def status(svc: SyncService = Depends(get_service)) -> dict:
    return svc.status(settings.poll_sec)


@router.post("/api/send", response_model=SendResponse)
def send(body: SendRequest, svc: SyncService = Depends(get_service)) -> JSONResponse:
    result = svc.do_send(body.userid, body.content)
    return JSONResponse(status_code=200 if result.get("ok") else 400, content=result)


@router.get("/media/{filename:path}")
def media(filename: str) -> FileResponse:
    name = unquote(filename)
    if ".." in name or name.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="bad path")
    fp = (settings.media_dir / name).resolve()
    # ensure the resolved path stays inside media_dir
    if settings.media_dir.resolve() not in fp.parents and fp != settings.media_dir.resolve():
        raise HTTPException(status_code=400, detail="bad path")
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # FileResponse serves Range requests (206) automatically.
    return FileResponse(fp)
