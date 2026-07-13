"""AI auto-reply package: prompt building + HTTP client."""

from .client import HUMAN_REQUEST_COMMAND, AIClient
from .prompt import build_reply_prompt, message_content, message_inbound_key

__all__ = [
    "AIClient",
    "HUMAN_REQUEST_COMMAND",
    "build_reply_prompt",
    "message_content",
    "message_inbound_key",
]
