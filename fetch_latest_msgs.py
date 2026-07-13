#!/usr/bin/env python3
"""Fetch latest WeCom messages via wecom-cli. No AI required.

ponytail: chat list often omits DMs, so also probe every contact userid.
Ceiling: only last ~6 days (API 7-day limit). Upgrade: enterprise session archive.
"""
from __future__ import annotations

import json
import subprocess
import sys

from wecom_rpc import get_messages, get_userlist, preview_text, rpc, time_window


def main() -> int:
    begin, end = time_window()
    print(f"range: {begin} ~ {end}\n")

    users = {
        u["userid"]: u.get("name") or u["userid"] for u in get_userlist()
    }

    chats = rpc(
        ["msg", "get_msg_chat_list", json.dumps({"begin_time": begin, "end_time": end})]
    ).get("chats") or []

    targets: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for c in chats:
        cid = c["chat_id"]
        name = c.get("chat_name") or cid
        ctype = 2 if str(cid).startswith("wr") else 1
        targets.append((ctype, cid, name))
        seen.add(cid)
    for uid, name in users.items():
        if uid not in seen:
            targets.append((1, uid, name))

    any_msg = False
    for ctype, cid, name in targets:
        msgs = get_messages(cid, begin, end, chat_type=ctype)
        if not msgs:
            continue
        any_msg = True
        kind = "群" if ctype == 2 else "私聊"
        print(f"### {kind} {name} ({cid})  {len(msgs)} msgs")
        for m in msgs:
            who = users.get(m.get("userid"), m.get("userid"))
            print(f"  {m.get('send_time')}  {who}: {preview_text(m)}")
        print()

    if not any_msg:
        print("(no messages in window)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError:
        print("wecom-cli not found in PATH", file=sys.stderr)
        raise SystemExit(1)
    except subprocess.CalledProcessError as e:
        print(e.output or e, file=sys.stderr)
        raise SystemExit(e.returncode or 1)
