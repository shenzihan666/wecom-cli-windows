"""Per-account blacklist of contacts that should not receive auto-replies."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from .database import Database, database


class BlacklistRow(TypedDict):
    account_id: str
    userid: str
    name: str
    reason: str
    created_at: str


class BlacklistRepository:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or database

    def list_for_account(self, account_id: str) -> list[BlacklistRow]:
        conn = self._db.connect()
        with self._db.lock:
            rows = conn.execute(
                "SELECT account_id, userid, name, reason, created_at FROM blacklist "
                "WHERE account_id = ? ORDER BY created_at DESC",
                (account_id,),
            ).fetchall()
        return [
            BlacklistRow(
                account_id=row["account_id"],
                userid=row["userid"],
                name=row["name"] or "",
                reason=row["reason"] or "",
                created_at=row["created_at"] or "",
            )
            for row in rows
        ]

    def is_blacklisted(self, account_id: str, userid: str) -> bool:
        conn = self._db.connect()
        with self._db.lock:
            row = conn.execute(
                "SELECT 1 FROM blacklist WHERE account_id = ? AND userid = ?",
                (account_id, userid),
            ).fetchone()
        return row is not None

    def add(
        self,
        account_id: str,
        userid: str,
        *,
        name: str = "",
        reason: str = "",
    ) -> BlacklistRow:
        userid = (userid or "").strip()
        if not userid:
            raise ValueError("userid required")
        now = datetime.now().isoformat()
        conn = self._db.connect()
        with self._db.lock:
            conn.execute(
                "INSERT INTO blacklist (account_id, userid, name, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, userid) DO UPDATE SET "
                "name=excluded.name, reason=excluded.reason",
                (account_id, userid, name or "", reason or "", now),
            )
            row = conn.execute(
                "SELECT account_id, userid, name, reason, created_at FROM blacklist "
                "WHERE account_id = ? AND userid = ?",
                (account_id, userid),
            ).fetchone()
        return BlacklistRow(
            account_id=row["account_id"],
            userid=row["userid"],
            name=row["name"] or "",
            reason=row["reason"] or "",
            created_at=row["created_at"] or "",
        )

    def remove(self, account_id: str, userid: str) -> bool:
        conn = self._db.connect()
        with self._db.lock:
            cur = conn.execute(
                "DELETE FROM blacklist WHERE account_id = ? AND userid = ?",
                (account_id, userid),
            )
            return cur.rowcount > 0


blacklist_repository = BlacklistRepository()
