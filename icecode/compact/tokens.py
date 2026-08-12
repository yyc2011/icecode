"""上下文 token 粗估（窗口占用，非会话累计计费）。"""

from __future__ import annotations

import json

from icecode.llm.base import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)


def estimate_text_tokens(text: str, bytes_per_token: int = 4) -> int:
    """按字符长度粗估 token 数（默认约 4 字符 ≈ 1 token）。"""
    if bytes_per_token <= 0:
        raise ValueError(f"bytes_per_token must be > 0, got {bytes_per_token}")
    return round(len(text) / bytes_per_token)


def estimate_message_tokens(message: Message) -> int:
    """估算单条消息的 token（按 content block 分派）。"""
    total = 0
    for block in message.content:
        if isinstance(block, TextBlock):
            total += estimate_text_tokens(block.text)
        elif isinstance(block, ToolUseBlock):
            payload = json.dumps(block.input, ensure_ascii=False, separators=(",", ":"))
            total += estimate_text_tokens(block.name) + estimate_text_tokens(payload)
        elif isinstance(block, ToolResultBlock):
            total += estimate_text_tokens(block.content)
        else:
            total += estimate_text_tokens(str(block))
    return total


def estimate_messages_tokens(messages: list[Message]) -> int:
    """估算消息列表的 token 合计。"""
    return sum(estimate_message_tokens(m) for m in messages)


def estimate_context_tokens(
    messages: list[Message],
    last_usage: Usage,
    last_usage_index: int,
) -> int:
    """估算当前上下文窗口占用。

    有上一次 API usage 时：usage 基线 + 该索引之后新增消息的粗估。
    无 usage（input/output 均为 0）时：对全部消息做粗估。
    """
    if last_usage.input_tokens == 0 and last_usage.output_tokens == 0:
        return estimate_messages_tokens(messages)

    baseline = last_usage.input_tokens + last_usage.output_tokens
    if last_usage_index < 0:
        last_usage_index = 0
    if last_usage_index >= len(messages):
        return baseline
    return baseline + estimate_messages_tokens(messages[last_usage_index:])
