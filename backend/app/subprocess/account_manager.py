"""Account registry for routing wecom-cli calls to the right credential sandbox.

Today: a single default account (ambient wecom-cli config).
Later: multiple accounts, each with its own ``config_dir``, cache file and —
eventually — a dedicated long-lived wecom-cli worker process.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import settings


@dataclass(frozen=True)
class Account:
    """One WeCom login. ``config_dir=None`` uses the ambient wecom-cli config."""

    id: str = "default"
    name: str = "default"
    config_dir: str | None = None
    # Explicit self userid override; empty means auto-detect from DM senders.
    self_userid: str = ""

    @property
    def cache_path(self) -> Path:
        if self.id == "default":
            return settings.cache_path
        return settings.data_dir / f"cache_{self.id}.json"


DEFAULT_ACCOUNT = Account(
    id="default",
    name="default",
    config_dir=None,
    self_userid=settings.self_userid,
)


class AccountManager:
    """Thread-safe registry of :class:`Account`.

    Stub for multi-account: currently seeded with the default account only.
    Future work: spawn/track a wecom-cli worker per account here.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accounts: dict[str, Account] = {DEFAULT_ACCOUNT.id: DEFAULT_ACCOUNT}

    def get(self, account_id: str = "default") -> Account:
        with self._lock:
            if account_id not in self._accounts:
                raise KeyError(f"unknown account: {account_id}")
            return self._accounts[account_id]

    def list(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def register(self, account: Account) -> Account:
        with self._lock:
            self._accounts[account.id] = account
            return account


account_manager = AccountManager()
