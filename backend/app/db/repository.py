"""Read/write the full sync snapshot for one account.

Mirrors the previous JSON-cache semantics: every save is a full replace of the
account's rows inside a single transaction, so persistence stays consistent
with the in-memory working set that the sync engine rebuilds each poll.
"""

from __future__ import annotations

import json
from typing import TypedDict

from .database import Database, database


class AccountSnapshot(TypedDict):
    self_userid: str
    last_sync: str | None
    users: dict[str, str]
    conversations: dict[str, dict]  # userid -> {"name": str, "messages": list[dict]}


class AccountRepository:
    def __init__(self, db: Database | None = None) -> None:
        self._db = db or database

    def load(self, account_id: str) -> AccountSnapshot | None:
        conn = self._db.connect()
        with self._db.lock:
            meta = conn.execute(
                "SELECT self_userid, last_sync FROM meta WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if meta is None:
                return None

            users = {
                row["userid"]: row["name"]
                for row in conn.execute(
                    "SELECT userid, name FROM users WHERE account_id = ?", (account_id,)
                )
            }

            conversations: dict[str, dict] = {}
            for row in conn.execute(
                "SELECT userid, name FROM conversations WHERE account_id = ?", (account_id,)
            ):
                conversations[row["userid"]] = {"name": row["name"], "messages": []}

            for row in conn.execute(
                "SELECT peer, payload FROM messages WHERE account_id = ? ORDER BY id",
                (account_id,),
            ):
                conv = conversations.setdefault(row["peer"], {"name": row["peer"], "messages": []})
                conv["messages"].append(json.loads(row["payload"]))

        return AccountSnapshot(
            self_userid=meta["self_userid"] or "",
            last_sync=meta["last_sync"],
            users=users,
            conversations=conversations,
        )

    def save(
        self,
        account_id: str,
        *,
        self_userid: str,
        last_sync: str | None,
        users: dict[str, str],
        conversations: dict[str, dict],
    ) -> None:
        conn = self._db.connect()
        with self._db.lock:
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM messages WHERE account_id = ?", (account_id,))
                conn.execute("DELETE FROM conversations WHERE account_id = ?", (account_id,))
                conn.execute("DELETE FROM users WHERE account_id = ?", (account_id,))

                conn.execute(
                    "INSERT INTO meta (account_id, self_userid, last_sync) VALUES (?, ?, ?) "
                    "ON CONFLICT(account_id) DO UPDATE SET self_userid=excluded.self_userid, "
                    "last_sync=excluded.last_sync",
                    (account_id, self_userid, last_sync),
                )

                if users:
                    conn.executemany(
                        "INSERT INTO users (account_id, userid, name) VALUES (?, ?, ?)",
                        [(account_id, uid, name) for uid, name in users.items()],
                    )

                conv_rows = []
                msg_rows = []
                for userid, conv in conversations.items():
                    conv_rows.append((account_id, userid, conv.get("name") or userid))
                    for m in conv.get("messages") or []:
                        msg_rows.append(
                            (
                                account_id,
                                userid,
                                m.get("send_time") or "",
                                m.get("userid") or "",
                                m.get("msgtype") or "",
                                1 if m.get("_pending") else 0,
                                json.dumps(m, ensure_ascii=False),
                            )
                        )

                if conv_rows:
                    conn.executemany(
                        "INSERT INTO conversations (account_id, userid, name) VALUES (?, ?, ?)",
                        conv_rows,
                    )
                if msg_rows:
                    conn.executemany(
                        "INSERT INTO messages "
                        "(account_id, peer, send_time, sender, msgtype, pending, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        msg_rows,
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def has_data(self, account_id: str) -> bool:
        conn = self._db.connect()
        with self._db.lock:
            row = conn.execute("SELECT 1 FROM meta WHERE account_id = ?", (account_id,)).fetchone()
        return row is not None
