"""Persistence for registered accounts and global app settings.

Accounts and settings are tiny, low-write tables so a straightforward
read/write-through repository (no in-memory caching) is plenty.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from .database import Database, database


class AccountRow(TypedDict):
    id: str
    name: str
    config_dir: str | None
    self_userid: str
    enabled: bool


class AccountsRepository:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or database

    def list_accounts(self) -> list[AccountRow]:
        conn = self._db.connect()
        with self._db.lock:
            rows = conn.execute(
                "SELECT id, name, config_dir, self_userid, enabled FROM accounts "
                "ORDER BY created_at"
            ).fetchall()
        return [
            AccountRow(
                id=row["id"],
                name=row["name"],
                config_dir=row["config_dir"],
                self_userid=row["self_userid"] or "",
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def upsert_account(
        self,
        account_id: str,
        *,
        name: str,
        config_dir: str | None,
        self_userid: str = "",
        enabled: bool = True,
    ) -> None:
        conn = self._db.connect()
        with self._db.lock:
            conn.execute(
                "INSERT INTO accounts (id, name, config_dir, self_userid, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, config_dir=excluded.config_dir, "
                "self_userid=excluded.self_userid, enabled=excluded.enabled",
                (
                    account_id,
                    name,
                    config_dir,
                    self_userid,
                    1 if enabled else 0,
                    datetime.now().isoformat(),
                ),
            )

    def set_enabled(self, account_id: str, enabled: bool) -> None:
        conn = self._db.connect()
        with self._db.lock:
            conn.execute(
                "UPDATE accounts SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, account_id),
            )

    def delete_account(self, account_id: str) -> None:
        conn = self._db.connect()
        with self._db.lock:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        conn = self._db.connect()
        with self._db.lock:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        conn = self._db.connect()
        with self._db.lock:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


accounts_repository = AccountsRepository()
