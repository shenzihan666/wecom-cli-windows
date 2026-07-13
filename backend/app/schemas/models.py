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
