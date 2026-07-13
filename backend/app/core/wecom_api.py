"""Typed-ish wrappers around individual wecom-cli commands.

These are 1:1 with wecom-cli verbs (contact/msg). No caching, no state.
"""

from __future__ import annotations

import json
from pathlib import Path

from .rpc import rpc


def get_userlist(config_dir: str | Path | None = None) -> list[dict]:
    return rpc(["contact", "get_userlist", "{}"], config_dir=config_dir).get("userlist") or []


def get_messages(
    chatid: str,
    begin: str,
    end: str,
    chat_type: int = 1,
    config_dir: str | Path | None = None,
) -> list[dict]:
    msgs: list[dict] = []
    cursor = ""
    while True:
        payload: dict = {
            "chat_type": chat_type,
            "chatid": chatid,
            "begin_time": begin,
            "end_time": end,
        }
        if cursor:
            payload["cursor"] = cursor
        data = rpc(
            ["msg", "get_message", json.dumps(payload, ensure_ascii=False)],
            config_dir=config_dir,
        )
        if data.get("errcode"):
            return []
        msgs.extend(data.get("messages") or [])
        cursor = data.get("next_cursor") or ""
        if not cursor:
            break
    return msgs


def send_text(
    chatid: str,
    content: str,
    chat_type: int = 1,
    config_dir: str | Path | None = None,
) -> dict:
    payload = {
        "chat_type": chat_type,
        "chatid": chatid,
        "msgtype": "text",
        "text": {"content": content},
    }
    return rpc(
        ["msg", "send_message", json.dumps(payload, ensure_ascii=False)],
        config_dir=config_dir,
    )


def preview_text(m: dict) -> str:
    mt = m.get("msgtype")
    if mt == "text":
        return (m.get("text") or {}).get("content") or ""
    return f"[{mt}]"
