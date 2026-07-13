"""HTTP endpoints. Mirrors the original experimental server's API surface."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from ..config import settings
from ..core.runtime_settings import get_ai_settings, get_poll_sec, set_ai_settings, set_poll_sec
from ..db import blacklist_repository
from ..schemas import (
    AccountCreateRequest,
    AccountItem,
    AccountsResponse,
    BlacklistAddRequest,
    BlacklistItem,
    BlacklistResponse,
    ConversationsResponse,
    MessagesResponse,
    SendRequest,
    SendResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StatusResponse,
)
from ..services import SyncService, service_registry
from ..subprocess import account_manager, account_process_manager
from .deps import get_service

router = APIRouter()


def _settings_payload() -> dict:
    ai = get_ai_settings()
    return {
        "poll_sec": get_poll_sec(),
        "ai_enabled": ai.enabled,
        "ai_server_url": ai.server_url,
        "ai_timeout_sec": ai.timeout_sec,
        "ai_system_prompt": ai.system_prompt,
        "ai_reply_max_length": ai.reply_max_length,
        "ai_history_limit": ai.history_limit,
    }


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
    return svc.status(get_poll_sec())


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


# --------------------------------------------------------------------------- #
# Accounts (客服管理): CRUD + start/pause, backed by one poll-worker subprocess
# per account (see app.subprocess.process_manager).
# --------------------------------------------------------------------------- #
def _account_item(account) -> AccountItem:  # noqa: ANN001 - Account, avoids import cycle in type hint
    svc = service_registry.get(account.id)
    st = svc.status(get_poll_sec())
    proc_state = account_process_manager.status(account.id)
    return AccountItem(
        id=account.id,
        name=account.name,
        config_dir=account.config_dir,
        self_userid=st["self_userid"],
        last_sync=st["last_sync"],
        state=proc_state["state"],
        error=st["error"],
    )


@router.get("/api/accounts", response_model=AccountsResponse)
def list_accounts() -> dict:
    return {"accounts": [_account_item(a) for a in account_manager.list()]}


@router.post("/api/accounts", response_model=AccountItem)
def create_account(body: AccountCreateRequest) -> AccountItem:
    # Empty name → placeholder; poll worker fills WeCom display name on first sync.
    name = (body.name or "").strip() or "未命名"
    config_dir = (body.config_dir or "").strip() or None
    if account_manager.config_dir_in_use(config_dir):
        raise HTTPException(status_code=400, detail="config_dir already used by another account")
    account = account_manager.add(
        name=name,
        config_dir=config_dir,
        self_userid=(body.self_userid or "").strip(),
        enabled=False,
    )
    return _account_item(account)


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str) -> dict:
    if len(account_manager.list()) <= 1:
        raise HTTPException(status_code=400, detail="cannot delete the last remaining account")
    try:
        account_manager.get(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}") from None
    account_process_manager.stop(account_id)
    service_registry.remove(account_id)
    account_manager.remove(account_id)
    return {"ok": True}


@router.post("/api/accounts/{account_id}/start", response_model=AccountItem)
def start_account(account_id: str) -> AccountItem:
    try:
        account = account_manager.get(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}") from None
    ok = account_process_manager.start(account, get_poll_sec())
    if not ok:
        raise HTTPException(status_code=500, detail="failed to start account")
    account_manager.set_enabled(account_id, True)
    return _account_item(account)


@router.post("/api/accounts/{account_id}/pause", response_model=AccountItem)
def pause_account(account_id: str) -> AccountItem:
    try:
        account = account_manager.get(account_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}") from None
    account_process_manager.pause(account_id)
    account_manager.set_enabled(account_id, False)
    return _account_item(account)


# --------------------------------------------------------------------------- #
# Global settings (poll interval + AI auto-reply).
# --------------------------------------------------------------------------- #
@router.get("/api/settings", response_model=SettingsResponse)
def get_settings() -> dict:
    return _settings_payload()


@router.put("/api/settings", response_model=SettingsResponse)
def update_settings(body: SettingsUpdateRequest) -> dict:
    if body.poll_sec <= 0:
        raise HTTPException(status_code=400, detail="poll_sec must be positive")
    if body.ai_timeout_sec <= 0:
        raise HTTPException(status_code=400, detail="ai_timeout_sec must be positive")
    if body.ai_reply_max_length <= 0:
        raise HTTPException(status_code=400, detail="ai_reply_max_length must be positive")
    if body.ai_history_limit <= 0:
        raise HTTPException(status_code=400, detail="ai_history_limit must be positive")

    prev_poll = get_poll_sec()
    set_poll_sec(body.poll_sec)
    set_ai_settings(
        enabled=body.ai_enabled,
        server_url=body.ai_server_url,
        timeout_sec=body.ai_timeout_sec,
        system_prompt=body.ai_system_prompt,
        reply_max_length=body.ai_reply_max_length,
        history_limit=body.ai_history_limit,
    )

    # Restart running workers only when poll interval changes.
    if body.poll_sec != prev_poll:
        for account in account_manager.list():
            if account_process_manager.status(account.id)["state"] == "running":
                account_process_manager.stop(account.id)
                account_process_manager.start(account, body.poll_sec)

    return _settings_payload()


# --------------------------------------------------------------------------- #
# Blacklist (per-account; used by auto-reply).
# --------------------------------------------------------------------------- #
@router.get("/api/blacklist", response_model=BlacklistResponse)
def list_blacklist(account: str = Query(default="default")) -> dict:
    try:
        account_manager.get(account)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account}") from None
    items = blacklist_repository.list_for_account(account)
    return {"items": [BlacklistItem(**row) for row in items]}


@router.post("/api/blacklist", response_model=BlacklistItem)
def add_blacklist(
    body: BlacklistAddRequest,
    account: str = Query(default="default"),
) -> BlacklistItem:
    try:
        account_manager.get(account)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account}") from None
    userid = (body.userid or "").strip()
    if not userid:
        raise HTTPException(status_code=400, detail="userid required")
    row = blacklist_repository.add(
        account,
        userid,
        name=(body.name or "").strip(),
        reason=(body.reason or "").strip(),
    )
    return BlacklistItem(**row)


@router.delete("/api/blacklist/{userid}")
def remove_blacklist(userid: str, account: str = Query(default="default")) -> dict:
    try:
        account_manager.get(account)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown account: {account}") from None
    userid = (userid or "").strip()
    if not userid:
        raise HTTPException(status_code=400, detail="userid required")
    ok = blacklist_repository.remove(account, userid)
    if not ok:
        raise HTTPException(status_code=404, detail="not in blacklist")
    return {"ok": True}
