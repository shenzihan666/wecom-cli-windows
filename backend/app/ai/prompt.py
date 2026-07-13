"""XML prompt construction for AI auto-reply (aligned with android_run)."""

from __future__ import annotations

from typing import Any


def message_content(msg: dict[str, Any]) -> str:
    """Extract displayable text from a wecom-cli message dict."""
    mt = msg.get("msgtype") or ""
    if mt == "text":
        return ((msg.get("text") or {}).get("content") or "").strip()
    if mt == "image":
        return "[图片]"
    if mt == "voice":
        return "[语音]"
    if mt == "video":
        return "[视频]"
    if mt == "file":
        return "[文件]"
    return f"[{mt}]" if mt else ""


def message_inbound_key(msg: dict[str, Any]) -> str:
    """Stable key for an inbound message (dedup / reply cursor)."""
    mt = msg.get("msgtype") or ""
    if mt == "text":
        body = ((msg.get("text") or {}).get("content") or "").strip()
    else:
        obj = msg.get(mt) or {}
        body = str(obj.get("media_id") or obj.get("local_file") or mt or "")
    sender = msg.get("userid") or ""
    send_time = msg.get("send_time") or ""
    return f"{send_time}|{sender}|{mt}|{body}"


def build_reply_prompt(
    *,
    customer_name: str,
    history: list[dict[str, Any]],
    latest_message: str,
    system_prompt: str = "",
    reply_max_length: int = 50,
    self_userid: str = "",
) -> str:
    """Build an XML-structured chatInput for the external AI /chat endpoint."""
    lines: list[str] = []
    for msg in history:
        content = message_content(msg)
        if not content:
            continue
        sender = msg.get("userid") or ""
        role = "AGENT" if self_userid and sender == self_userid else "CUSTOMER"
        lines.append(f"{role}: {content}")

    history_block = "\n".join(lines) if lines else "无历史消息"
    style = (system_prompt or "").strip() or "使用礼貌、友好的语气。"
    name = customer_name or "客户"
    max_len = max(1, int(reply_max_length))

    return f"""<task>
为 {name} 的最新消息生成一条合适的回复。
</task>

<context>
<scenario>企微私聊实时回复</scenario>
<customer_name>{name}</customer_name>
<situation>客户发送了新消息，需要及时、恰当地回复。</situation>
</context>

<conversation_history count="{len(lines)}">
{history_block}
</conversation_history>

<latest_customer_message>
{latest_message}
</latest_customer_message>

<system_prompt>
{style}
</system_prompt>

<requirements>
<functional>
1. 针对客户的最新消息进行回复
2. 回复要解决客户的问题或回应客户的诉求
3. 保持对话的连贯性和上下文关联
</functional>
<content_rules>
1. 仔细阅读完整对话历史，理解客户需求和背景
2. 回复要自然、礼貌，与之前的对话风格保持一致
3. 简洁明了，建议控制在 {max_len} 字以内
4. 不要重复之前已经说过的内容
</content_rules>
</requirements>

<constraints>
<special_commands>
如果客户要求转人工、找真人客服、或表示要人工服务，直接返回: command back to user operation
</special_commands>
</constraints>

<output_format>
直接输出回复消息文本，不要包含任何解释、标签或格式标记。
</output_format>"""
