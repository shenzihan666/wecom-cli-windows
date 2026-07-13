"""Tracks which inbound messages have already been auto-replied to."""

from __future__ import annotations

from datetime import datetime

from .database import Database, database


class ReplyCursorRepository:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or database

    def get(self, account_id: str, peer: str) -> str | None:
        conn = self._db.connect()
        with self._db.lock:
            row = conn.execute(
                "SELECT last_inbound_key FROM reply_cursors WHERE account_id = ? AND peer = ?",
                (account_id, peer),
            ).fetchone()
        return row["last_inbound_key"] if row is not None else None

    def set(self, account_id: str, peer: str, last_inbound_key: str) -> None:
        now = datetime.now().isoformat()
        conn = self._db.connect()
        with self._db.lock:
            conn.execute(
                "INSERT INTO reply_cursors (account_id, peer, last_inbound_key, replied_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(account_id, peer) DO UPDATE SET "
                "last_inbound_key=excluded.last_inbound_key, replied_at=excluded.replied_at",
                (account_id, peer, last_inbound_key, now),
            )


reply_cursor_repository = ReplyCursorRepository()
