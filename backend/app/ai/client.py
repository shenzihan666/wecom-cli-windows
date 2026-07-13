"""Synchronous AI HTTP client for poll-worker auto-reply."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from .prompt import build_reply_prompt

HUMAN_REQUEST_COMMAND = "command back to user operation"

logger = logging.getLogger(__name__)


class AIClient:
    """Talks to an external AI server using the android_run /chat protocol."""

    def __init__(
        self,
        server_url: str,
        *,
        timeout_sec: float = 15.0,
        system_prompt: str = "",
        reply_max_length: int = 50,
    ) -> None:
        self.server_url = (server_url or "").rstrip("/")
        self.timeout_sec = max(1.0, float(timeout_sec))
        self.system_prompt = system_prompt or ""
        self.reply_max_length = max(1, int(reply_max_length))

    def is_human_request(self, reply: str | None) -> bool:
        if not reply:
            return False
        return HUMAN_REQUEST_COMMAND in reply.lower()

    def generate_reply(
        self,
        *,
        customer_name: str,
        latest_message: str,
        history: list[dict[str, Any]],
        self_userid: str = "",
        account_id: str = "",
        peer_userid: str = "",
    ) -> str | None:
        if not self.server_url:
            logger.warning("AI server_url empty; skip generate_reply")
            return None

        prompt = build_reply_prompt(
            customer_name=customer_name,
            history=history,
            latest_message=latest_message,
            system_prompt=self.system_prompt,
            reply_max_length=self.reply_max_length,
            self_userid=self_userid,
        )
        session_id = f"reply_{account_id}_{peer_userid}_{int(datetime.now().timestamp())}"
        payload = {
            "chatInput": prompt,
            "sessionId": session_id,
            "username": f"wecom_{account_id or 'default'}",
            "message_type": "text",
            "metadata": {
                "source": "auto_reply_service",
                "account_id": account_id,
                "peer_userid": peer_userid,
                "customer_name": customer_name,
                "original_message": latest_message,
            },
        }

        url = f"{self.server_url}/chat"
        logger.info(
            "AI request account=%s peer=%s customer=%s url=%s",
            account_id,
            peer_userid,
            customer_name,
            url,
        )
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(
                    "AI HTTP %s for %s: %s",
                    resp.status_code,
                    customer_name,
                    resp.text[:500],
                )
                return None
            data = resp.json()
            if data.get("success") and data.get("output"):
                output = str(data["output"]).strip()
                logger.info("AI reply for %s: %s", customer_name, output[:200])
                return output or None
            logger.warning("AI response not successful for %s: %s", customer_name, data)
            return None
        except httpx.TimeoutException:
            logger.error(
                "AI timeout after %ss for %s (%s)",
                self.timeout_sec,
                customer_name,
                url,
            )
            return None
        except Exception:
            logger.exception("AI request failed for %s (%s)", customer_name, url)
            return None
