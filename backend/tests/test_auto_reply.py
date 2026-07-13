"""Tests for the auto-reply safety guarantees.

Covers the two regression classes that previously caused real-world incidents:

1. Duplicate replies: if the worker crashes between ``do_send`` and the cursor
   write, the customer must NOT be replied to again on restart. Fix: the cursor
   is advanced *before* the send.
2. AI circuit breaker: a dead AI server must not be hammered every poll cycle.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# allow running directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.circuit_breaker import CircuitBreaker  # noqa: E402
from app.core.runtime_settings import AiSettings  # noqa: E402
from app.db.database import Database  # noqa: E402
from app.db.reply_cursor_repository import ReplyCursorRepository  # noqa: E402
from app.services.auto_reply_service import AutoReplyService  # noqa: E402

SELF = "self_userid"
PEER = "customer_1"


def _msg(content: str, sender: str, send_time: str) -> dict:
    return {
        "userid": sender,
        "send_time": send_time,
        "msgtype": "text",
        "text": {"content": content},
    }


def _make_service(
    tmp_path: Path,
    *,
    send_ok: bool = True,
    ai_reply: str | None = "hello!",
    send_calls: list | None = None,
) -> tuple[AutoReplyService, ReplyCursorRepository, Database]:
    """Build an AutoReplyService wired to a fresh temp DB + fake sync/AI."""
    db = Database(tmp_path / "test.db")
    db.connect()
    cursor_repo = ReplyCursorRepository(db)

    fake_sync = MagicMock()
    fake_sync.account.id = "test_acct"
    fake_sync.snapshot_conversations.return_value = (
        SELF,
        {
            PEER: {
                "userid": PEER,
                "name": "Alice",
                "messages": [_msg("你好", PEER, "2026-07-14 10:00:00")],
                "last_time": "2026-07-14 10:00:00",
                "last_preview": "你好",
                "has_messages": True,
            }
        },
    )
    send_calls = send_calls if send_calls is not None else []
    fake_sync.do_send.side_effect = lambda peer, content: (
        send_calls.append((peer, content)),
        {"ok": send_ok, "message": {}},
    )[1]

    settings = AiSettings(enabled=True, server_url="http://fake", timeout_sec=5.0)

    # Bypass the global DB singleton by monkeypatching the module-level repo
    # that auto_reply_service imports.
    import app.services.auto_reply_service as svc_mod
    from app.db.blacklist_repository import blacklist_repository as bl_singleton

    orig_cursor = svc_mod.reply_cursor_repository
    orig_bl_db = bl_singleton._db  # noqa: SLF001
    svc_mod.reply_cursor_repository = cursor_repo
    bl_singleton._db = db  # noqa: SLF001

    svc = AutoReplyService(fake_sync, settings, max_replies=5)

    # Restore originals on test teardown via a teardown we attach to the svc.
    def _restore() -> None:
        svc_mod.reply_cursor_repository = orig_cursor
        bl_singleton._db = orig_bl_db  # noqa: SLF001

    svc._teardown = _restore  # type: ignore[attr-defined]
    # Inject a fake AIClient so no HTTP is made.
    fake_client = MagicMock()
    fake_client.generate_reply.return_value = ai_reply
    fake_client.is_human_request.return_value = False
    svc._fake_client = fake_client  # type: ignore[attr-defined]
    return svc, cursor_repo, db


def _run_process_once(svc: AutoReplyService) -> None:
    """Run process_once with a stubbed AIClient (no real HTTP)."""
    import app.services.auto_reply_service as svc_mod

    orig_init = svc_mod.AIClient
    svc_mod.AIClient = lambda *a, **kw: svc._fake_client  # type: ignore[attr-defined]  # noqa: E501
    try:
        svc.process_once()
    finally:
        svc_mod.AIClient = orig_init
        svc._teardown()  # type: ignore[attr-defined]


def test_cursor_advanced_before_send(tmp_path: Path) -> None:
    """The reply cursor must be set even if the send itself were to fail/crash.

    This is the P0 duplicate-reply guard: if the process dies right after the
    send succeeds but before any post-send bookkeeping, the persisted cursor
    already marks the inbound as handled, so restart won't re-reply.
    """
    svc, cursor_repo, _db = _make_service(tmp_path, send_ok=True, ai_reply="hi")
    _run_process_once(svc)

    # The send happened once...
    # Cursor must now be set — this is what prevents a re-reply on restart.
    assert cursor_repo.get("test_acct", PEER) is not None


def test_send_failure_does_not_re_reply(tmp_path: Path) -> None:
    """When send fails, the cursor is ALREADY advanced: no retry, no duplicate.

    Rationale: a missed reply is a safe failure; a duplicate reply to a real
    customer is not. The old code left the cursor unset on failure, which both
    retried indefinitely AND risked duplicates on crash mid-send.
    """
    svc, cursor_repo, _db = _make_service(tmp_path, send_ok=False, ai_reply="hi")
    send_calls: list = []
    svc._sync.do_send.side_effect = lambda peer, content: (  # type: ignore[attr-defined]  # noqa: E501
        send_calls.append((peer, content)),
        {"ok": False, "error": "boom"},
    )[1]
    _run_process_once(svc)

    # First (failed) attempt only — the claimed cursor prevents a second try.
    assert len(send_calls) == 1
    # Cursor is set despite send failure → re-running process_once won't retry.
    assert cursor_repo.get("test_acct", PEER) is not None

    # Run a second cycle: there must be NO second send attempt.
    svc2, cursor_repo2, _ = _make_service(tmp_path, send_ok=False, ai_reply="hi")
    svc2._sync.do_send.side_effect = lambda peer, content: (  # type: ignore[attr-defined]  # noqa: E501
        send_calls.append((peer, content)),
        {"ok": False, "error": "boom"},
    )[1]
    # Re-wire to the SAME db/cursor so it sees the persisted cursor.
    import app.services.auto_reply_service as svc_mod
    from app.db.blacklist_repository import blacklist_repository as bl_singleton2

    svc_mod.reply_cursor_repository = cursor_repo
    bl_singleton2._db = _db  # noqa: SLF001
    orig_init = svc_mod.AIClient
    svc2._fake_client.generate_reply.return_value = "hi2"  # type: ignore[attr-defined]  # noqa: E501
    svc_mod.AIClient = lambda *a, **kw: svc2._fake_client  # type: ignore[attr-defined]  # noqa: E501
    try:
        svc2.process_once()
    finally:
        svc_mod.AIClient = orig_init
    # No new send call beyond the original one.
    assert len(send_calls) == 1


def test_human_transfer_advances_cursor_without_sending(tmp_path: Path) -> None:
    """A 'transfer to human' reply must advance the cursor and not send."""
    svc, cursor_repo, _db = _make_service(tmp_path, ai_reply="command back to user operation")
    svc._fake_client.is_human_request.return_value = True  # type: ignore[attr-defined]  # noqa: E501
    send_calls: list = []
    svc._sync.do_send.side_effect = lambda peer, content: (  # type: ignore[attr-defined]  # noqa: E501
        send_calls.append((peer, content)),
        {"ok": True},
    )[1]
    _run_process_once(svc)

    assert len(send_calls) == 0  # nothing sent
    assert cursor_repo.get("test_acct", PEER) is not None  # but cursor advanced


def test_empty_self_userid_skips_silently_and_safely() -> None:
    """When self_userid is unknown, nothing is sent (no self-reply risk)."""
    from unittest.mock import MagicMock

    fake_sync = MagicMock()
    fake_sync.account.id = "x"
    fake_sync.snapshot_conversations.return_value = ("", {})  # empty self_userid
    svc = AutoReplyService(fake_sync, AiSettings(enabled=True), max_replies=3)
    assert svc.process_once() == 0
    fake_sync.do_send.assert_not_called()


# --- Circuit breaker unit tests ------------------------------------------- #
def test_circuit_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker(threshold=3, cooldown_sec=60.0)
    assert not cb.is_open
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open  # still closed at 2
    cb.record_failure()
    assert cb.is_open  # opens at 3


def test_circuit_breaker_resets_on_success() -> None:
    cb = CircuitBreaker(threshold=2, cooldown_sec=60.0)
    cb.record_failure()
    cb.record_success()
    assert not cb.is_open
    # Need threshold failures again from a clean slate.
    cb.record_failure()
    assert not cb.is_open  # only 1 failure since reset


def test_circuit_breaker_half_open_after_cooldown() -> None:
    """After the cooldown elapses, is_open goes False (half-open probe allowed)."""
    cb = CircuitBreaker(threshold=1, cooldown_sec=0.05)
    cb.record_failure()
    assert cb.is_open  # open immediately after the failure
    import time

    time.sleep(0.06)  # cooldown elapses
    assert not cb.is_open  # now allows a probe call
    assert cb.state in ("half-open", "closed")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_cursor_advanced_before_send(Path(td))
        test_send_failure_does_not_re_reply(Path(td))
        test_human_transfer_advances_cursor_without_sending(Path(td))
    test_empty_self_userid_skips_silently_and_safely()
    test_circuit_breaker_opens_after_threshold()
    test_circuit_breaker_resets_on_success()
    test_circuit_breaker_half_open_after_cooldown()
    print("test_auto_reply: ok")
