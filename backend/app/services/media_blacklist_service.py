"""Automatically blacklist peers when newly synced inbound media is observed."""

from __future__ import annotations

import logging
from collections import Counter

from ..db import BlacklistRepository, blacklist_repository

logger = logging.getLogger(__name__)

_CUSTOMER_MEDIA_TYPES = frozenset({"image", "video"})
_AUTO_BLACKLIST_REASON = "对方发送图片或视频（自动拉黑）"


def media_message_key(message: dict) -> tuple:
    """Return a media identity that stays stable when ``media_id`` rotates."""
    message_id = message.get("msgid") or message.get("msg_id") or message.get("message_id")
    if message_id:
        return ("id", str(message_id))
    return (
        "fallback",
        message.get("userid") or "",
        message.get("send_time") or "",
        message.get("msgtype") or "",
    )


def find_new_customer_media(
    prev_msgs: list[dict] | None,
    current_msgs: list[dict] | None,
    peer: str,
    *,
    peer_existed: bool,
    baseline_time: str,
) -> list[dict]:
    """Find newly observed inbound images/videos without trusting rotating media IDs."""

    def is_customer_media(message: dict) -> bool:
        return (message.get("userid") or "") == peer and (
            message.get("msgtype") or ""
        ) in _CUSTOMER_MEDIA_TYPES

    # A Counter preserves multiple same-type messages sent in the same second
    # when the upstream API does not expose a message ID.
    previous = Counter(
        media_message_key(message) for message in (prev_msgs or []) if is_customer_media(message)
    )
    added: list[dict] = []
    for message in current_msgs or []:
        if not is_customer_media(message):
            continue
        key = media_message_key(message)
        if previous[key] > 0:
            previous[key] -= 1
            continue
        # A contact can first appear with several days of history. Only treat
        # messages newer than the established account baseline as incremental.
        if not peer_existed:
            send_time = message.get("send_time") or ""
            if not send_time or send_time <= baseline_time:
                continue
        added.append(message)
    return added


class MediaBlacklistService:
    """Apply the inbound-media blacklist policy to conversation updates."""

    def __init__(
        self,
        account_id: str,
        repository: BlacklistRepository | None = None,
    ) -> None:
        self._account_id = account_id
        self._repository = repository or blacklist_repository

    def process(
        self,
        prev_conversations: dict[str, dict],
        current_conversations: dict[str, dict],
        baseline_time: str | None,
    ) -> None:
        """Process one sync update without allowing policy errors to stop sync."""
        if not baseline_time:
            return
        for peer, conversation in current_conversations.items():
            previous = prev_conversations.get(peer)
            added = find_new_customer_media(
                (previous or {}).get("messages") or [],
                conversation.get("messages") or [],
                peer,
                peer_existed=previous is not None,
                baseline_time=baseline_time,
            )
            if not added:
                continue
            try:
                if self._repository.is_blacklisted(self._account_id, peer):
                    continue
                self._repository.add(
                    self._account_id,
                    peer,
                    name=conversation.get("name") or peer,
                    reason=_AUTO_BLACKLIST_REASON,
                )
                media_types = sorted({message.get("msgtype") or "" for message in added})
                logger.info(
                    "[%s] auto-blacklisted peer=%s for inbound media=%s",
                    self._account_id,
                    peer,
                    ",".join(media_types),
                )
            except Exception:
                logger.exception(
                    "[%s] auto-blacklist failed for peer=%s",
                    self._account_id,
                    peer,
                )
