#!/usr/bin/env python3
"""Local WeCom DM sync web UI. Polls wecom-cli; DMs only; text send.

ponytail: in-memory cache + 5s poll. Ceiling: ~6 day history, no push. Upgrade: session archive / webhook.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from wecom_rpc import (
    MEDIA_DIR,
    ROOT,
    fetch_media,
    get_messages,
    get_userlist,
    preview_text,
    send_text,
    time_window,
)

HOST = os.environ.get("WECOM_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("WECOM_WEB_PORT", "8765"))
# Empty = auto-detect from DM senders (wecom-cli has no "whoami"). Env wins if set.
_SELF_FROM_ENV = os.environ.get("SELF_USERID", "").strip()
SELF_USERID = _SELF_FROM_ENV
POLL_SEC = float(os.environ.get("WECOM_POLL_SEC", "5"))
STATIC_DIR = ROOT / "static"
CACHE_PATH = ROOT / "data" / "cache.json"

_lock = threading.RLock()
# userid -> {userid, name, messages[], last_time, last_preview}
_conversations: dict[str, dict] = {}
_users: dict[str, str] = {}
_last_sync: str | None = None
_syncing = False
_error: str | None = None


def _infer_self_userid(conversations: dict[str, dict]) -> str:
    """In a 1:1 DM, senders who are not the chat peer are the logged-in user."""
    from collections import Counter

    votes: Counter[str] = Counter()
    for peer, conv in conversations.items():
        for m in conv.get("messages") or []:
            uid = m.get("userid") or ""
            if uid and uid != peer:
                votes[uid] += 1
    return votes.most_common(1)[0][0] if votes else ""


def _set_self_userid(uid: str, reason: str) -> None:
    global SELF_USERID
    if not uid or uid == SELF_USERID:
        return
    SELF_USERID = uid
    name = _users.get(uid) or uid
    print(f"self_userid={uid} ({name}) via {reason}")


def _load_cache() -> None:
    global _last_sync
    if not CACHE_PATH.is_file():
        return
    try:
        data = json.loads(CACHE_PATH.read_text("utf-8"))
        with _lock:
            _users.clear()
            _users.update(data.get("users") or {})
            _conversations.clear()
            _conversations.update(data.get("conversations") or {})
            _last_sync = data.get("last_sync")
            if not _SELF_FROM_ENV:
                cached_self = (data.get("self_userid") or "").strip()
                if cached_self:
                    _set_self_userid(cached_self, "cache")
                else:
                    inferred = _infer_self_userid(_conversations)
                    if inferred:
                        _set_self_userid(inferred, "cache-infer")
        print(f"loaded cache: {len(_conversations)} conversations (last_sync={_last_sync})")
    except Exception:
        traceback.print_exc()


def _save_cache() -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            payload = {
                "last_sync": _last_sync,
                "self_userid": SELF_USERID,
                "users": dict(_users),
                "conversations": dict(_conversations),
            }
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
        tmp.replace(CACHE_PATH)
    except Exception:
        traceback.print_exc()


def _enrich(m: dict, prev_msgs: list[dict] | None = None) -> dict:
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
            info = fetch_media(mid, mt, m.get("send_time") or "")
            if info:
                obj["local_file"] = info["filename"]
                obj["content_type"] = info.get("content_type") or ""
        except Exception:
            pass
    out[mt] = obj
    return out


def _soft_key(m: dict) -> tuple:
    mt = m.get("msgtype")
    if mt == "text":
        body = (m.get("text") or {}).get("content") or ""
    else:
        obj = m.get(mt) or {}
        body = obj.get("media_id") or obj.get("local_file") or mt or ""
    return (m.get("userid"), mt, body)


def _merge_messages(api_msgs: list[dict], prev_msgs: list[dict] | None) -> list[dict]:
    """Keep self-sent pending bubbles until WeCom API reflects them.

    ponytail: send succeeds before get_message sees it; naive replace makes replies vanish briefly.
    """
    merged = list(api_msgs)
    api_soft = {_soft_key(m) for m in api_msgs}
    for m in prev_msgs or []:
        if not m.get("_pending"):
            continue
        if m.get("userid") != SELF_USERID:
            continue
        if _soft_key(m) in api_soft:
            continue
        merged.append(dict(m))
    merged.sort(key=lambda x: x.get("send_time") or "")
    return merged


def _conv_from_msgs(userid: str, name: str, msgs: list[dict]) -> dict:
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


def _sync_once() -> None:
    global _last_sync, _syncing, _error
    with _lock:
        if _syncing:
            return
        _syncing = True
        prev_convs = {k: dict(v) for k, v in _conversations.items()}
    try:
        begin, end = time_window()
        users_raw = get_userlist()
        users = {u["userid"]: (u.get("name") or u["userid"]) for u in users_raw}
        fresh: dict[str, dict] = {}
        for uid, name in users.items():
            if uid == SELF_USERID:
                continue
            try:
                msgs = get_messages(uid, begin, end, chat_type=1)
            except Exception as e:
                with _lock:
                    _error = f"get_message {uid}: {e}"
                # keep previous conversation on transient failure
                if uid in prev_convs:
                    fresh[uid] = prev_convs[uid]
                continue
            prev_msgs = (prev_convs.get(uid) or {}).get("messages") or []
            enriched = [_enrich(m, prev_msgs) for m in msgs]
            merged = _merge_messages(enriched, prev_msgs)
            fresh[uid] = _conv_from_msgs(uid, name, merged)
        if not _SELF_FROM_ENV:
            inferred = _infer_self_userid(fresh) or _infer_self_userid(prev_convs)
            if inferred:
                _set_self_userid(inferred, "dm-infer")
                fresh.pop(inferred, None)
        with _lock:
            _users.clear()
            _users.update(users)
            _conversations.clear()
            _conversations.update(fresh)
            _last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _error = None
        _save_cache()
    except Exception as e:
        with _lock:
            _error = str(e)
            traceback.print_exc()
    finally:
        with _lock:
            _syncing = False


def _poll_loop() -> None:
    while True:
        _sync_once()
        time.sleep(POLL_SEC)


def _conversations_list() -> dict:
    with _lock:
        items = list(_conversations.values())
        sync = _last_sync
        err = _error
    with_msg = [c for c in items if c.get("has_messages")]
    without = [c for c in items if not c.get("has_messages")]
    with_msg.sort(key=lambda c: c.get("last_time") or "", reverse=True)
    without.sort(key=lambda c: c.get("name") or "")
    ordered = with_msg + without
    return {
        "self_userid": SELF_USERID,
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


def _messages_for(userid: str) -> dict:
    with _lock:
        conv = _conversations.get(userid)
        users = dict(_users)
        sync = _last_sync
    if not conv:
        return {
            "userid": userid,
            "name": users.get(userid, userid),
            "messages": [],
            "last_sync": sync,
            "self_userid": SELF_USERID,
        }
    return {
        "userid": userid,
        "name": conv["name"],
        "messages": conv.get("messages") or [],
        "last_sync": sync,
        "self_userid": SELF_USERID,
        "users": users,
    }


def _do_send(userid: str, content: str) -> dict:
    content = (content or "").strip()
    if not userid or not content:
        return {"ok": False, "error": "userid and content required"}
    data = send_text(userid, content, chat_type=1)
    if data.get("errcode") not in (0, None):
        return {"ok": False, "error": data.get("errmsg") or str(data), "raw": data}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = {
        "userid": SELF_USERID,
        "send_time": now,
        "msgtype": "text",
        "text": {"content": content},
        "_pending": True,  # until next get_message includes it
    }
    with _lock:
        conv = _conversations.get(userid)
        if not conv:
            name = _users.get(userid, userid)
            conv = _conv_from_msgs(userid, name, [])
            _conversations[userid] = conv
        conv["messages"].append(msg)
        conv["last_time"] = now
        conv["last_preview"] = content
        conv["has_messages"] = True
    _save_cache()

    # delayed refresh so API has time to index; merge keeps pending if still missing
    def _later() -> None:
        time.sleep(2.0)
        _refresh_one(userid)

    threading.Thread(target=_later, daemon=True).start()
    return {"ok": True, "message": msg}


def _refresh_one(userid: str) -> None:
    try:
        begin, end = time_window()
        msgs = get_messages(userid, begin, end, chat_type=1)
        with _lock:
            name = _users.get(userid) or (_conversations.get(userid) or {}).get("name") or userid
            prev_msgs = list((_conversations.get(userid) or {}).get("messages") or [])
        enriched = [_enrich(m, prev_msgs) for m in msgs]
        merged = _merge_messages(enriched, prev_msgs)
        with _lock:
            _conversations[userid] = _conv_from_msgs(userid, name, merged)
        _save_cache()
    except Exception:
        traceback.print_exc()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/conversations":
            self._json(200, _conversations_list())
            return

        if path == "/api/messages":
            qs = parse_qs(parsed.query)
            userid = (qs.get("userid") or [""])[0]
            if not userid:
                self._json(400, {"error": "userid required"})
                return
            self._json(200, _messages_for(userid))
            return

        if path == "/api/status":
            with _lock:
                self._json(
                    200,
                    {
                        "self_userid": SELF_USERID,
                        "last_sync": _last_sync,
                        "syncing": _syncing,
                        "error": _error,
                        "poll_sec": POLL_SEC,
                    },
                )
            return

        if path.startswith("/media/"):
            name = unquote(path[len("/media/") :])
            if ".." in name or name.startswith("/"):
                self._json(400, {"error": "bad path"})
                return
            fp = MEDIA_DIR / name
            if not fp.is_file():
                self.send_error(404)
                return
            self._serve_file(fp)
            return

        if path in ("/", "/index.html"):
            fp = STATIC_DIR / "index.html"
            self._bytes(200, fp.read_bytes(), "text/html; charset=utf-8")
            return

        # static assets under /static/
        if path.startswith("/static/"):
            rel = unquote(path[len("/static/") :])
            fp = STATIC_DIR / rel
            if not fp.is_file():
                self.send_error(404)
                return
            self._serve_file(fp)
            return

        self.send_error(404)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/media/"):
            name = unquote(path[len("/media/") :])
            fp = MEDIA_DIR / name
            if fp.is_file() and ".." not in name:
                ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
                size = fp.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self._cors()
                self.end_headers()
                return
        self.send_error(404)

    def _serve_file(self, fp: Path) -> None:
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        data = fp.read_bytes()
        size = len(data)
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                start_s, end_s = rng.replace("bytes=", "").split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                end = min(end, size - 1)
                if start < 0 or start > end:
                    raise ValueError("bad range")
                chunk = data[start : end + 1]
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self._cors()
                self.end_headers()
                self.wfile.write(chunk)
                return
            except ValueError:
                pass
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/send":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        result = _do_send(body.get("userid") or "", body.get("content") or "")
        self._json(200 if result.get("ok") else 400, result)


def main() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _load_cache()
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"WeCom DM sync: http://{HOST}:{PORT}  (self={SELF_USERID}, poll={POLL_SEC}s)")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
