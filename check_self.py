#!/usr/bin/env python3
"""Minimal self-check for pending-message merge. No wecom-cli / network."""
from __future__ import annotations

import os

# server imports wecom_rpc; keep SELF stable for assertions
os.environ.setdefault("SELF_USERID", "WangGuoZheng")

from server import SELF_USERID, _merge_messages, _soft_key  # noqa: E402


def test_pending_kept_until_api_has_it() -> None:
    api = [
        {
            "userid": "other",
            "send_time": "2026-07-11 15:00:00",
            "msgtype": "text",
            "text": {"content": "hi"},
        }
    ]
    prev = [
        {
            "userid": SELF_USERID,
            "send_time": "2026-07-11 15:01:00",
            "msgtype": "text",
            "text": {"content": "reply"},
            "_pending": True,
        }
    ]
    merged = _merge_messages(api, prev)
    assert len(merged) == 2
    assert merged[-1]["text"]["content"] == "reply"
    assert merged[-1].get("_pending") is True


def test_pending_dropped_when_api_reflects() -> None:
    api = [
        {
            "userid": SELF_USERID,
            "send_time": "2026-07-11 15:01:02",
            "msgtype": "text",
            "text": {"content": "reply"},
        }
    ]
    prev = [
        {
            "userid": SELF_USERID,
            "send_time": "2026-07-11 15:01:00",
            "msgtype": "text",
            "text": {"content": "reply"},
            "_pending": True,
        }
    ]
    merged = _merge_messages(api, prev)
    assert len(merged) == 1
    assert not merged[0].get("_pending")
    assert _soft_key(merged[0]) == (SELF_USERID, "text", "reply")


if __name__ == "__main__":
    test_pending_kept_until_api_has_it()
    test_pending_dropped_when_api_reflects()
    print("check_self: ok")
