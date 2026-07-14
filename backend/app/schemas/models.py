"""API models. Message payloads stay loosely typed (dict) because wecom-cli
returns many msgtype-specific shapes (text/image/voice/file/video)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConversationItem(BaseModel):
    userid: str
    name: str
    last_time: str = ""
    last_preview: str = ""
    has_messages: bool = False
    msg_count: int = 0


class ConversationsResponse(BaseModel):
    self_userid: str = ""
    last_sync: str | None = None
    error: str | None = None
    conversations: list[ConversationItem] = Field(default_factory=list)


class MessagesResponse(BaseModel):
    userid: str
    name: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    last_sync: str | None = None
    self_userid: str = ""
    users: dict[str, str] = Field(default_factory=dict)


class StatusResponse(BaseModel):
    account_id: str = "default"
    self_userid: str = ""
    last_sync: str | None = None
    syncing: bool = False
    error: str | None = None
    poll_sec: float = 5.0


class SendRequest(BaseModel):
    userid: str
    content: str


class SendResponse(BaseModel):
    ok: bool
    message: dict[str, Any] | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


class AccountItem(BaseModel):
    id: str
    name: str
    config_dir: str | None = None
    self_userid: str = ""
    last_sync: str | None = None
    state: str = "stopped"  # "stopped" | "running" | "paused"
    error: str | None = None


class AccountsResponse(BaseModel):
    accounts: list[AccountItem] = Field(default_factory=list)


class AccountCreateRequest(BaseModel):
    name: str = ""  # optional; empty → auto-fill from contacts after sync
    config_dir: str | None = None
    self_userid: str = ""


class SettingsResponse(BaseModel):
    poll_sec: float = 5.0
    ai_enabled: bool = False
    ai_server_url: str = "http://localhost:8080"
    ai_timeout_sec: float = 15.0
    ai_system_prompt: str = ""
    ai_reply_max_length: int = 50


class SettingsUpdateRequest(BaseModel):
    poll_sec: float
    ai_enabled: bool = False
    ai_server_url: str = "http://localhost:8080"
    ai_timeout_sec: float = 15.0
    ai_system_prompt: str = ""
    ai_reply_max_length: int = 50


class BlacklistItem(BaseModel):
    account_id: str
    userid: str
    name: str = ""
    reason: str = ""
    created_at: str = ""


class BlacklistResponse(BaseModel):
    items: list[BlacklistItem] = Field(default_factory=list)


class BlacklistAddRequest(BaseModel):
    userid: str
    name: str = ""
    reason: str = ""
