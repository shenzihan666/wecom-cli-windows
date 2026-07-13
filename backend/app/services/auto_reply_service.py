"""Detect unreplied DMs and send AI-generated replies via SyncService.do_send."""

from __future__ import annotations

import logging
from typing import Any

from ..ai import AIClient, message_content, message_inbound_key
from ..core.runtime_settings import AiSettings, get_ai_settings
from ..db import blacklist_repository, reply_cursor_repository
from .sync_service import SyncService

logger = logging.getLogger(__name__)

# Cap work per poll cycle so one busy account cannot stall forever.
_MAX_REPLIES_PER_CYCLE = 3


class AutoReplyService:
    def __init__(
        self,
        sync: SyncService,
        ai_settings: AiSettings | None = None,
        *,
        max_replies: int = _MAX_REPLIES_PER_CYCLE,
    ) -> None:
        self._sync = sync
        self._settings = ai_settings or get_ai_settings()
        self._max_replies = max(1, int(max_replies))
        self._account_id = sync.account.id

    def process_once(self) -> int:
        """Find unreplied peers and send up to ``max_replies`` AI replies.

        Returns the number of messages successfully sent.
        """
        if not self._settings.enabled:
            return 0

        self_userid, conversations = self._sync.snapshot_conversations()
        if not self_userid:
            logger.debug("[%s] auto-reply skipped: self_userid unknown", self._account_id)
            return 0

        candidates = self._find_unreplied(conversations, self_userid)
        if not candidates:
            return 0

        client = AIClient(
            self._settings.server_url,
            timeout_sec=self._settings.timeout_sec,
            system_prompt=self._settings.system_prompt,
            reply_max_length=self._settings.reply_max_length,
        )

        sent = 0
        for peer, conv, last_msg, inbound_key in candidates[: self._max_replies]:
            if blacklist_repository.is_blacklisted(self._account_id, peer):
                logger.info("[%s] skip blacklisted peer=%s", self._account_id, peer)
                continue

            cursor = reply_cursor_repository.get(self._account_id, peer)
            if cursor == inbound_key:
                continue

            latest_text = message_content(last_msg)
            if not latest_text:
                continue

            history = (conv.get("messages") or [])[-self._settings.history_limit :]
            customer_name = conv.get("name") or peer

            reply = client.generate_reply(
                customer_name=customer_name,
                latest_message=latest_text,
                history=history,
                self_userid=self_userid,
                account_id=self._account_id,
                peer_userid=peer,
            )
            if not reply:
                logger.warning("[%s] no AI reply for peer=%s", self._account_id, peer)
                continue

            if client.is_human_request(reply):
                logger.info(
                    "[%s] human-transfer for peer=%s; not sending",
                    self._account_id,
                    peer,
                )
                # Mark cursor so we do not re-trigger on the same inbound forever.
                reply_cursor_repository.set(self._account_id, peer, inbound_key)
                continue

            # Final blacklist gate before send.
            if blacklist_repository.is_blacklisted(self._account_id, peer):
                logger.info("[%s] blacklisted before send peer=%s", self._account_id, peer)
                continue

            result = self._sync.do_send(peer, reply)
            if not result.get("ok"):
                logger.error(
                    "[%s] send failed peer=%s err=%s",
                    self._account_id,
                    peer,
                    result.get("error"),
                )
                continue

            reply_cursor_repository.set(self._account_id, peer, inbound_key)
            sent += 1
            logger.info("[%s] auto-replied peer=%s", self._account_id, peer)

        return sent

    def _find_unreplied(
        self,
        conversations: dict[str, dict[str, Any]],
        self_userid: str,
    ) -> list[tuple[str, dict[str, Any], dict[str, Any], str]]:
        """Return (peer, conv, last_inbound_msg, inbound_key) needing a reply."""
        out: list[tuple[str, dict[str, Any], dict[str, Any], str]] = []
        for peer, conv in conversations.items():
            if peer == self_userid:
                continue
            msgs = list(conv.get("messages") or [])
            if not msgs:
                continue
            msgs.sort(key=lambda m: m.get("send_time") or "")
            last = msgs[-1]
            sender = last.get("userid") or ""
            if not sender or sender == self_userid:
                continue
            # Text-only replies for now.
            if (last.get("msgtype") or "") != "text":
                continue
            if not message_content(last):
                continue
            inbound_key = message_inbound_key(last)
            cursor = reply_cursor_repository.get(self._account_id, peer)
            if cursor == inbound_key:
                continue
            out.append((peer, conv, last, inbound_key))

        # Prefer most recently messaged peers first.
        out.sort(key=lambda item: item[2].get("send_time") or "", reverse=True)
        return out
