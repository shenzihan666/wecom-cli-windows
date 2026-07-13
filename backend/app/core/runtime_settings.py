"""Mutable, DB-persisted app settings (currently just the poll interval).

Kept separate from ``config.Settings`` (env-sourced, effectively read-only at
runtime): this module is for settings the UI can change and that must survive
a restart.
"""

from __future__ import annotations

from ..config import settings
from ..db import accounts_repository

_POLL_SEC_KEY = "poll_sec"


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
