"""Mutable, DB-persisted app settings (poll interval + AI auto-reply).

Kept separate from ``config.Settings`` (env-sourced, effectively read-only at
runtime): this module is for settings the UI can change and that must survive
a restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import settings
from ..db import accounts_repository

_POLL_SEC_KEY = "poll_sec"
_AI_ENABLED_KEY = "ai_enabled"
_AI_SERVER_URL_KEY = "ai_server_url"
_AI_TIMEOUT_SEC_KEY = "ai_timeout_sec"
_AI_SYSTEM_PROMPT_KEY = "ai_system_prompt"
_AI_REPLY_MAX_LENGTH_KEY = "ai_reply_max_length"

_DEFAULT_AI_SERVER_URL = "http://localhost:8080"
_DEFAULT_AI_TIMEOUT_SEC = 15.0
_DEFAULT_AI_REPLY_MAX_LENGTH = 50


@dataclass(frozen=True)
class AiSettings:
    enabled: bool = False
    server_url: str = _DEFAULT_AI_SERVER_URL
    timeout_sec: float = _DEFAULT_AI_TIMEOUT_SEC
    system_prompt: str = ""
    reply_max_length: int = _DEFAULT_AI_REPLY_MAX_LENGTH


def get_poll_sec() -> float:
    raw = accounts_repository.get_setting(_POLL_SEC_KEY)
    if raw is None:
        return settings.poll_sec
    try:
        return float(raw)
    except ValueError:
        return settings.poll_sec


def set_poll_sec(value: float) -> None:
    accounts_repository.set_setting(_POLL_SEC_KEY, str(value))


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _as_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def get_ai_settings() -> AiSettings:
    return AiSettings(
        enabled=_as_bool(accounts_repository.get_setting(_AI_ENABLED_KEY), False),
        server_url=(
            accounts_repository.get_setting(_AI_SERVER_URL_KEY) or _DEFAULT_AI_SERVER_URL
        ).strip()
        or _DEFAULT_AI_SERVER_URL,
        timeout_sec=_as_float(
            accounts_repository.get_setting(_AI_TIMEOUT_SEC_KEY),
            _DEFAULT_AI_TIMEOUT_SEC,
        ),
        system_prompt=accounts_repository.get_setting(_AI_SYSTEM_PROMPT_KEY) or "",
        reply_max_length=_as_int(
            accounts_repository.get_setting(_AI_REPLY_MAX_LENGTH_KEY),
            _DEFAULT_AI_REPLY_MAX_LENGTH,
        ),
    )


def set_ai_settings(
    *,
    enabled: bool,
    server_url: str,
    timeout_sec: float,
    system_prompt: str,
    reply_max_length: int,
) -> AiSettings:
    url = (server_url or "").strip() or _DEFAULT_AI_SERVER_URL
    accounts_repository.set_setting(_AI_ENABLED_KEY, "true" if enabled else "false")
    accounts_repository.set_setting(_AI_SERVER_URL_KEY, url)
    accounts_repository.set_setting(_AI_TIMEOUT_SEC_KEY, str(timeout_sec))
    accounts_repository.set_setting(_AI_SYSTEM_PROMPT_KEY, system_prompt or "")
    accounts_repository.set_setting(_AI_REPLY_MAX_LENGTH_KEY, str(int(reply_max_length)))
    return get_ai_settings()
