"""SQLite connection manager.

One connection per process, guarded by a lock for in-process (thread) safety.
Each account's poll-worker subprocess opens its own connection to the same
file, so cross-process write contention is handled by SQLite itself: WAL mode
keeps reads non-blocking, and ``busy_timeout`` makes concurrent writers wait
briefly instead of failing immediately.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    account_id  TEXT PRIMARY KEY,
    self_userid TEXT,
    last_sync   TEXT
);

CREATE TABLE IF NOT EXISTS users (
    account_id TEXT NOT NULL,
    userid     TEXT NOT NULL,
    name       TEXT,
    PRIMARY KEY (account_id, userid)
);

CREATE TABLE IF NOT EXISTS conversations (
    account_id TEXT NOT NULL,
    userid     TEXT NOT NULL,
    name       TEXT,
    PRIMARY KEY (account_id, userid)
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    peer       TEXT NOT NULL,
    send_time  TEXT,
    sender     TEXT,
    msgtype    TEXT,
    pending    INTEGER NOT NULL DEFAULT 0,
    payload    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_acct_peer ON messages (account_id, peer, id);

CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    config_dir  TEXT,
    self_userid TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS blacklist (
    account_id TEXT NOT NULL,
    userid     TEXT NOT NULL,
    name       TEXT,
    reason     TEXT,
    created_at TEXT,
    PRIMARY KEY (account_id, userid)
);

CREATE TABLE IF NOT EXISTS reply_cursors (
    account_id        TEXT NOT NULL,
    peer              TEXT NOT NULL,
    last_inbound_key  TEXT NOT NULL,
    replied_at        TEXT,
    PRIMARY KEY (account_id, peer)
);
"""


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or settings.db_path
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            # Each account's poll-worker subprocess now writes to this same
            # file from its own connection/process; give concurrent writers
            # a chance to wait instead of failing immediately with
            # "database is locked".
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.executescript(_SCHEMA)
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


database = Database()
