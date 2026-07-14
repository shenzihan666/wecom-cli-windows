"""Tests for incremental inbound-media auto-blacklisting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# allow running directly from the repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.sync_service as sync_module  # noqa: E402
from app.services.media_blacklist_service import (  # noqa: E402
    MediaBlacklistService,
    find_new_customer_media,
)
from app.services.sync_service import SyncService  # noqa: E402
from app.subprocess import Account  # noqa: E402

PEER = "customer_1"
SELF = "self_userid"
BASELINE = "2026-07-14 10:00:00"


def _msg(
    msgtype: str,
    sender: str,
    send_time: str,
    *,
    msgid: str = "",
    media_id: str = "",
) -> dict:
    message = {
        "userid": sender,
        "send_time": send_time,
        "msgtype": msgtype,
    }
    if msgid:
        message["msgid"] = msgid
    if msgtype in {"image", "video"}:
        message[msgtype] = {"media_id": media_id or f"{msgtype}-media"}
    elif msgtype == "text":
        message["text"] = {"content": "hello"}
    return message


@pytest.mark.parametrize("msgtype", ["image", "video"])
def test_detects_new_customer_image_and_video(msgtype: str) -> None:
    current = [_msg(msgtype, PEER, "2026-07-14 10:00:01")]
    added = find_new_customer_media([], current, PEER, peer_existed=True, baseline_time=BASELINE)
    assert added == current


def test_ignores_text_and_self_sent_media() -> None:
    current = [
        _msg("text", PEER, "2026-07-14 10:00:01"),
        _msg("image", SELF, "2026-07-14 10:00:02"),
        _msg("video", PEER, "2026-07-14 10:00:03"),
    ]
    added = find_new_customer_media([], current, PEER, peer_existed=True, baseline_time=BASELINE)
    assert [m["msgtype"] for m in added] == ["video"]


def test_repeated_poll_and_rotating_media_id_are_not_new() -> None:
    previous = [
        _msg(
            "image",
            PEER,
            "2026-07-14 10:00:01",
            media_id="old-rotating-id",
        )
    ]
    current = [
        _msg(
            "image",
            PEER,
            "2026-07-14 10:00:01",
            media_id="new-rotating-id",
        )
    ]
    assert (
        find_new_customer_media(
            previous,
            current,
            PEER,
            peer_existed=True,
            baseline_time=BASELINE,
        )
        == []
    )


def test_counter_detects_second_same_type_message_in_same_second() -> None:
    previous = [_msg("image", PEER, "2026-07-14 10:00:01")]
    current = [
        _msg("image", PEER, "2026-07-14 10:00:01"),
        _msg("image", PEER, "2026-07-14 10:00:01"),
    ]
    added = find_new_customer_media(
        previous,
        current,
        PEER,
        peer_existed=True,
        baseline_time=BASELINE,
    )
    assert len(added) == 1


def test_new_peer_only_counts_messages_after_baseline() -> None:
    old_image = _msg("image", PEER, "2026-07-14 09:59:59")
    new_video = _msg("video", PEER, "2026-07-14 10:00:01")
    added = find_new_customer_media(
        [],
        [old_image, new_video],
        PEER,
        peer_existed=False,
        baseline_time=BASELINE,
    )
    assert added == [new_video]


class _FakeBlacklistRepository:
    def __init__(
        self,
        *,
        existing: set[str] | None = None,
        fail_for: set[str] | None = None,
    ) -> None:
        self.existing = set(existing or ())
        self.fail_for = set(fail_for or ())
        self.added: list[tuple[str, str, str, str]] = []

    def is_blacklisted(self, account_id: str, userid: str) -> bool:
        if userid in self.fail_for:
            raise RuntimeError("database unavailable")
        return userid in self.existing

    def add(
        self,
        account_id: str,
        userid: str,
        *,
        name: str = "",
        reason: str = "",
    ) -> dict:
        self.added.append((account_id, userid, name, reason))
        self.existing.add(userid)
        return {}


def _conversation(peer: str, name: str, messages: list[dict]) -> dict:
    return {"userid": peer, "name": name, "messages": messages}


def test_first_sync_establishes_baseline_without_blacklisting() -> None:
    repo = _FakeBlacklistRepository()
    service = MediaBlacklistService("acct", repo)
    fresh = {PEER: _conversation(PEER, "Alice", [_msg("image", PEER, "2026-07-14 09:00:00")])}

    service.process({}, fresh, None)

    assert repo.added == []


def test_existing_blacklist_is_idempotent() -> None:
    repo = _FakeBlacklistRepository(existing={PEER})
    service = MediaBlacklistService("acct", repo)
    prev = {PEER: _conversation(PEER, "Alice", [])}
    fresh = {PEER: _conversation(PEER, "Alice", [_msg("video", PEER, "2026-07-14 10:00:01")])}

    service.process(prev, fresh, BASELINE)

    assert repo.added == []


def test_single_conversation_refresh_also_applies_rule(monkeypatch) -> None:
    repo = _FakeBlacklistRepository()
    monkeypatch.setattr(
        sync_module,
        "get_messages",
        lambda *args, **kwargs: [_msg("image", PEER, "2026-07-14 10:00:01", msgid="new-image")],
    )
    media_blacklist = MediaBlacklistService("acct", repo)
    service = SyncService(
        Account(id="acct", name="Account"),
        update_handlers=[media_blacklist.process],
    )
    service._last_sync = BASELINE
    service._users[PEER] = "Alice"
    service._conversations[PEER] = _conversation(PEER, "Alice", [])
    monkeypatch.setattr(service, "save_state", lambda: None)

    service._refresh_one(PEER)

    assert len(repo.added) == 1
    assert repo.added[0][1] == PEER


def test_repository_failure_for_one_peer_does_not_block_others() -> None:
    bad_peer = "customer_bad"
    good_peer = "customer_good"
    repo = _FakeBlacklistRepository(fail_for={bad_peer})
    service = MediaBlacklistService("acct", repo)
    prev = {
        bad_peer: _conversation(bad_peer, "Bad", []),
        good_peer: _conversation(good_peer, "Good", []),
    }
    fresh = {
        bad_peer: _conversation(bad_peer, "Bad", [_msg("image", bad_peer, "2026-07-14 10:00:01")]),
        good_peer: _conversation(
            good_peer, "Good", [_msg("video", good_peer, "2026-07-14 10:00:02")]
        ),
    }

    service.process(prev, fresh, BASELINE)

    assert len(repo.added) == 1
    account_id, userid, name, reason = repo.added[0]
    assert (account_id, userid, name) == ("acct", good_peer, "Good")
    assert "自动拉黑" in reason
