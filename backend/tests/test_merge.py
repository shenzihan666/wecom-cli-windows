"""Merge self-check for pending-message logic. No wecom-cli / network."""

from __future__ import annotations

import sys
from pathlib import Path

# allow running directly: `uv run python backend/tests/test_merge.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.sync_service import merge_messages, soft_key  # noqa: E402

SELF = "test_self_userid"


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
            "userid": SELF,
            "send_time": "2026-07-11 15:01:00",
            "msgtype": "text",
            "text": {"content": "reply"},
            "_pending": True,
        }
    ]
    merged = merge_messages(api, prev, SELF)
    assert len(merged) == 2
    assert merged[-1]["text"]["content"] == "reply"
    assert merged[-1].get("_pending") is True


def test_pending_dropped_when_api_reflects() -> None:
    api = [
        {
            "userid": SELF,
            "send_time": "2026-07-11 15:01:02",
            "msgtype": "text",
            "text": {"content": "reply"},
        }
    ]
    prev = [
        {
            "userid": SELF,
            "send_time": "2026-07-11 15:01:00",
            "msgtype": "text",
            "text": {"content": "reply"},
            "_pending": True,
        }
    ]
    merged = merge_messages(api, prev, SELF)
    assert len(merged) == 1
    assert not merged[0].get("_pending")
    assert soft_key(merged[0]) == (SELF, "text", "reply")


if __name__ == "__main__":
    test_pending_kept_until_api_has_it()
    test_pending_dropped_when_api_reflects()
    print("test_merge: ok")
