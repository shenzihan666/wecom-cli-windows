"""Per-account DM sync engine: poll loop, disk cache, conversation state, send.

Ported from the original experimental ``server.py`` module globals into a
single account-scoped object so multiple accounts can run concurrently.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from collections import Counter
from datetime import datetime

from ..core import media as media_core
from ..core.rpc import time_window
from ..core.wecom_api import get_messages, get_userlist, preview_text, send_text
from ..subprocess import DEFAULT_ACCOUNT, Account


# --------------------------------------------------------------------------- #
# Pure helpers (no state) — kept module-level so they stay easy to unit test.
# --------------------------------------------------------------------------- #
def infer_self_userid(conversations: dict[str, dict]) -> str:
    """In a 1:1 DM, senders who are not the chat peer are the logged-in user."""
    votes: Counter[str] = Counter()
    for peer, conv in conversations.items():
        for m in conv.get("messages") or []:
            uid = m.get("userid") or ""
            if uid and uid != peer:
                votes[uid] += 1
    return votes.most_common(1)[0][0] if votes else ""


def soft_key(m: dict) -> tuple:
    mt = m.get("msgtype")
    if mt == "text":
        body = (m.get("text") or {}).get("content") or ""
    else:
        obj = m.get(mt) or {}
        body = obj.get("media_id") or obj.get("local_file") or mt or ""
    return (m.get("userid"), mt, body)


def merge_messages(
    api_msgs: list[dict], prev_msgs: list[dict] | None, self_userid: str
) -> list[dict]:
    """Keep self-sent pending bubbles until WeCom API reflects them.

    Send succeeds before get_message sees it; a naive replace makes replies
    vanish briefly.
    """
    merged = list(api_msgs)
    api_soft = {soft_key(m) for m in api_msgs}
    for m in prev_msgs or []:
        if not m.get("_pending"):
            continue
        if m.get("userid") != self_userid:
            continue
        if soft_key(m) in api_soft:
            continue
        merged.append(dict(m))
    merged.sort(key=lambda x: x.get("send_time") or "")
    return merged


def conv_from_msgs(userid: str, name: str, msgs: list[dict]) -> dict:
    if not msgs:
        return {
            "userid": userid,
            "name": name,
            "messages": [],
            "last_time": "",
            "last_preview": "",
            "has_messages": False,
        }
    last = msgs[-1]
    return {
        "userid": userid,
        "name": name,
        "messages": msgs,
        "last_time": last.get("send_time") or "",
        "last_preview": preview_text(last),
        "has_messages": True,
    }


# --------------------------------------------------------------------------- #
# Account-scoped sync engine
# --------------------------------------------------------------------------- #
class SyncService:
    def __init__(self, account: Account | None = None) -> None:
        self.account = account or DEFAULT_ACCOUNT
        self._lock = threading.RLock()
        self._conversations: dict[str, dict] = {}
        self._users: dict[str, str] = {}
        self._last_sync: str | None = None
        self._syncing = False
        self._error: str | None = None

        self._self_from_config = (self.account.self_userid or "").strip()
        self.self_userid = self._self_from_config

        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- config passthrough ------------------------------------------------ #
    @property
    def _config_dir(self) -> str | None:
        return self.account.config_dir

    # ---- self userid ------------------------------------------------------- #
    def _set_self_userid(self, uid: str, reason: str) -> None:
        if not uid or uid == self.self_userid:
            return
        self.self_userid = uid
        name = self._users.get(uid) or uid
        print(f"[{self.account.id}] self_userid={uid} ({name}) via {reason}")

    # ---- cache ------------------------------------------------------------- #
    def load_cache(self) -> None:
        path = self.account.cache_path
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text("utf-8"))
            with self._lock:
                self._users.clear()
                self._users.update(data.get("users") or {})
                self._conversations.clear()
                self._conversations.update(data.get("conversations") or {})
                self._last_sync = data.get("last_sync")
                if not self._self_from_config:
                    cached_self = (data.get("self_userid") or "").strip()
                    if cached_self:
                        self._set_self_userid(cached_self, "cache")
                    else:
                        inferred = infer_self_userid(self._conversations)
                        if inferred:
                            self._set_self_userid(inferred, "cache-infer")
            print(
                f"[{self.account.id}] loaded cache: {len(self._conversations)} "
                f"conversations (last_sync={self._last_sync})"
            )
        except Exception:
            traceback.print_exc()

    def save_cache(self) -> None:
        path = self.account.cache_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {
                    "last_sync": self._last_sync,
                    "self_userid": self.self_userid,
                    "users": dict(self._users),
                    "conversations": dict(self._conversations),
                }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
            tmp.replace(path)
        except Exception:
            traceback.print_exc()

    # ---- enrichment -------------------------------------------------------- #
    def _enrich(self, m: dict, prev_msgs: list[dict] | None = None) -> dict:
        """Attach local media filename when present / downloadable."""
        out = dict(m)
        mt = m.get("msgtype")
        if mt not in ("image", "voice", "file", "video"):
            return out
        obj = dict(m.get(mt) or {})
        mid = obj.get("media_id")
        if not mid:
            out[mt] = obj
            return out

        # media_id rotates; reuse local_file from same userid/time/type
        if not obj.get("local_file") and prev_msgs:
            key = (m.get("userid"), m.get("send_time"), mt)
            for p in prev_msgs:
                if (p.get("userid"), p.get("send_time"), p.get("msgtype")) != key:
                    continue
                prev_obj = p.get(mt) or {}
                if prev_obj.get("local_file"):
                    obj["local_file"] = prev_obj["local_file"]
                    obj["content_type"] = prev_obj.get("content_type") or ""
                    break

        if not obj.get("local_file"):
            try:
                info = media_core.fetch_media(
                    mid, mt, m.get("send_time") or "", config_dir=self._config_dir
                )
                if info:
                    obj["local_file"] = info["filename"]
                    obj["content_type"] = info.get("content_type") or ""
            except Exception:
                pass
        out[mt] = obj
        return out

    # ---- sync -------------------------------------------------------------- #
    def sync_once(self) -> None:
        with self._lock:
            if self._syncing:
                return
            self._syncing = True
            prev_convs = {k: dict(v) for k, v in self._conversations.items()}
        try:
            begin, end = time_window()
            users_raw = get_userlist(config_dir=self._config_dir)
            users = {u["userid"]: (u.get("name") or u["userid"]) for u in users_raw}
            fresh: dict[str, dict] = {}
            for uid, name in users.items():
                if uid == self.self_userid:
                    continue
                try:
                    msgs = get_messages(uid, begin, end, chat_type=1, config_dir=self._config_dir)
                except Exception as e:
                    with self._lock:
                        self._error = f"get_message {uid}: {e}"
                    # keep previous conversation on transient failure
                    if uid in prev_convs:
                        fresh[uid] = prev_convs[uid]
                    continue
                prev_msgs = (prev_convs.get(uid) or {}).get("messages") or []
                enriched = [self._enrich(m, prev_msgs) for m in msgs]
                merged = merge_messages(enriched, prev_msgs, self.self_userid)
                fresh[uid] = conv_from_msgs(uid, name, merged)
            if not self._self_from_config:
                inferred = infer_self_userid(fresh) or infer_self_userid(prev_convs)
                if inferred:
                    self._set_self_userid(inferred, "dm-infer")
                    fresh.pop(inferred, None)
            with self._lock:
                self._users.clear()
                self._users.update(users)
                self._conversations.clear()
                self._conversations.update(fresh)
                self._last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._error = None
            self.save_cache()
        except Exception as e:
            with self._lock:
                self._error = str(e)
                traceback.print_exc()
        finally:
            with self._lock:
                self._syncing = False

    def _refresh_one(self, userid: str) -> None:
        try:
            begin, end = time_window()
            msgs = get_messages(userid, begin, end, chat_type=1, config_dir=self._config_dir)
            with self._lock:
                name = (
                    self._users.get(userid)
                    or (self._conversations.get(userid) or {}).get("name")
                    or userid
                )
                prev_msgs = list((self._conversations.get(userid) or {}).get("messages") or [])
            enriched = [self._enrich(m, prev_msgs) for m in msgs]
            merged = merge_messages(enriched, prev_msgs, self.self_userid)
            with self._lock:
                self._conversations[userid] = conv_from_msgs(userid, name, merged)
            self.save_cache()
        except Exception:
            traceback.print_exc()

    # ---- poll loop --------------------------------------------------------- #
    def start_polling(self, poll_sec: float) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                self.sync_once()
                self._stop.wait(poll_sec)

        self._poll_thread = threading.Thread(
            target=_loop, name=f"poll-{self.account.id}", daemon=True
        )
        self._poll_thread.start()

    def stop_polling(self) -> None:
        self._stop.set()

    # ---- read APIs --------------------------------------------------------- #
    def conversations_list(self) -> dict:
        with self._lock:
            items = list(self._conversations.values())
            sync = self._last_sync
            err = self._error
        with_msg = [c for c in items if c.get("has_messages")]
        without = [c for c in items if not c.get("has_messages")]
        with_msg.sort(key=lambda c: c.get("last_time") or "", reverse=True)
        without.sort(key=lambda c: c.get("name") or "")
        ordered = with_msg + without
        return {
            "self_userid": self.self_userid,
            "last_sync": sync,
            "error": err,
            "conversations": [
                {
                    "userid": c["userid"],
                    "name": c["name"],
                    "last_time": c.get("last_time") or "",
                    "last_preview": c.get("last_preview") or "",
                    "has_messages": bool(c.get("has_messages")),
                    "msg_count": len(c.get("messages") or []),
                }
                for c in ordered
            ],
        }

    def messages_for(self, userid: str) -> dict:
        with self._lock:
            conv = self._conversations.get(userid)
            users = dict(self._users)
            sync = self._last_sync
        if not conv:
            return {
                "userid": userid,
                "name": users.get(userid, userid),
                "messages": [],
                "last_sync": sync,
                "self_userid": self.self_userid,
            }
        return {
            "userid": userid,
            "name": conv["name"],
            "messages": conv.get("messages") or [],
            "last_sync": sync,
            "self_userid": self.self_userid,
            "users": users,
        }

    def status(self, poll_sec: float) -> dict:
        with self._lock:
            return {
                "account_id": self.account.id,
                "self_userid": self.self_userid,
                "last_sync": self._last_sync,
                "syncing": self._syncing,
                "error": self._error,
                "poll_sec": poll_sec,
            }

    # ---- write API --------------------------------------------------------- #
    def do_send(self, userid: str, content: str) -> dict:
        content = (content or "").strip()
        if not userid or not content:
            return {"ok": False, "error": "userid and content required"}
        data = send_text(userid, content, chat_type=1, config_dir=self._config_dir)
        if data.get("errcode") not in (0, None):
            return {"ok": False, "error": data.get("errmsg") or str(data), "raw": data}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = {
            "userid": self.self_userid,
            "send_time": now,
            "msgtype": "text",
            "text": {"content": content},
            "_pending": True,  # until next get_message includes it
        }
        with self._lock:
            conv = self._conversations.get(userid)
            if not conv:
                name = self._users.get(userid, userid)
                conv = conv_from_msgs(userid, name, [])
                self._conversations[userid] = conv
            conv["messages"].append(msg)
            conv["last_time"] = now
            conv["last_preview"] = content
            conv["has_messages"] = True
        self.save_cache()

        # delayed refresh so API has time to index; merge keeps pending if still missing
        def _later() -> None:
            time.sleep(2.0)
            self._refresh_one(userid)

        threading.Thread(target=_later, daemon=True).start()
        return {"ok": True, "message": msg}
