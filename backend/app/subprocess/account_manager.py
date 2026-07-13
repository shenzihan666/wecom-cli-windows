"""Account registry for routing wecom-cli calls to the right credential sandbox.

Accounts are persisted (see ``AccountsRepository``) so accounts added through
the UI survive a backend restart. ``config_dir=None`` means "use the ambient
wecom-cli config" (today's single-account behaviour, kept as the ``default``
account for backwards compatibility with existing ``data/`` folders).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from ..config import settings
from ..db import accounts_repository


@dataclass(frozen=True)
class Account:
    """One WeCom login. ``config_dir=None`` uses the ambient wecom-cli config."""

    id: str = "default"
    name: str = "default"
    config_dir: str | None = None
    # Explicit self userid override; empty means auto-detect from DM senders.
    self_userid: str = ""


DEFAULT_ACCOUNT = Account(
    id="default",
    name="default",
    config_dir=None,
    self_userid=settings.self_userid,
)


class AccountManager:
    """Thread-safe registry of :class:`Account`, backed by SQLite."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accounts: dict[str, Account] = {}
        self._load()

    def _load(self) -> None:
        rows = accounts_repository.list_accounts()
        if not rows:
            # First run (or pre-multi-account DB): seed the default account so
            # existing single-account deployments keep working unchanged.
            self._accounts[DEFAULT_ACCOUNT.id] = DEFAULT_ACCOUNT
            accounts_repository.upsert_account(
                DEFAULT_ACCOUNT.id,
                name=DEFAULT_ACCOUNT.name,
                config_dir=DEFAULT_ACCOUNT.config_dir,
                self_userid=DEFAULT_ACCOUNT.self_userid,
                enabled=True,
            )
            return
        for row in rows:
            self._accounts[row["id"]] = Account(
                id=row["id"],
                name=row["name"],
                config_dir=row["config_dir"],
                self_userid=row["self_userid"],
            )

    def get(self, account_id: str = "default") -> Account:
        with self._lock:
            if account_id not in self._accounts:
                raise KeyError(f"unknown account: {account_id}")
            return self._accounts[account_id]

    def list(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    def is_enabled(self, account_id: str) -> bool:
        for row in accounts_repository.list_accounts():
            if row["id"] == account_id:
                return row["enabled"]
        return False

    def config_dir_in_use(self, config_dir: str | None) -> bool:
        if not config_dir:
            return False
        with self._lock:
            return any(a.config_dir == config_dir for a in self._accounts.values())

    def add(
        self,
        name: str,
        config_dir: str | None = None,
        self_userid: str = "",
        enabled: bool = False,
    ) -> Account:
        with self._lock:
            account_id = uuid.uuid4().hex[:8]
            while account_id in self._accounts:
                account_id = uuid.uuid4().hex[:8]
            account = Account(
                id=account_id,
                name=name,
                config_dir=config_dir or None,
                self_userid=self_userid,
            )
            self._accounts[account_id] = account
            accounts_repository.upsert_account(
                account_id,
                name=name,
                config_dir=account.config_dir,
                self_userid=self_userid,
                enabled=enabled,
            )
            return account

    def remove(self, account_id: str) -> None:
        with self._lock:
            self._accounts.pop(account_id, None)
            accounts_repository.delete_account(account_id)

    def set_enabled(self, account_id: str, enabled: bool) -> None:
        accounts_repository.set_enabled(account_id, enabled)


account_manager = AccountManager()
