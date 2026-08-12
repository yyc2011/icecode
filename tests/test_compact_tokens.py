"""上下文 token 粗估单测。"""

from __future__ import annotations

from icecode.compact.tokens import (
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from icecode.llm.base import Message, TextBlock, ToolResultBlock, ToolUseBlock, Usage


def test_estimate_text_tokens_basic_ratio() -> None:
    assert estimate_text_tokens("abcd") == 1  # 4/4
    assert estimate_text_tokens("abcdefgh") == 2  # 8/4
    assert estimate_text_tokens("abc") == 1  # round(3/4)=1
    assert estimate_text_tokens("") == 0


def test_estimate_message_tokens_by_block() -> None:
    msg = Message(
        role="assistant",
        content=[
            TextBlock(text="hello"),  # 5 → 1
            ToolUseBlock(id="t1", name="read_file", input={"path": "a.py"}),
        ],
    )
    # name + json input both counted
    assert estimate_message_tokens(msg) > 0


def test_estimate_context_tokens_with_usage_baseline() -> None:
    messages = [
        Message.user_text("hi"),  # before index — not counted again
        Message.assistant([TextBlock(text="ok")]),
        Message.tool_results(
            [ToolResultBlock(tool_use_id="t1", content="x" * 40)]  # 10 tokens
        ),
    ]
    usage = Usage(input_tokens=100, output_tokens=50)
    # last_usage_index=2 → only messages[2:] estimated
    result = estimate_context_tokens(messages, usage, last_usage_index=2)
    assert result == 150 + estimate_messages_tokens(messages[2:])


def test_estimate_context_tokens_fallback_when_no_usage() -> None:
    messages = [
        Message.user_text("hello world"),
        Message.assistant([TextBlock(text="reply text here")]),
    ]
    result = estimate_context_tokens(messages, Usage(), last_usage_index=0)
    assert result == estimate_messages_tokens(messages)


def test_estimate_context_tokens_index_past_end() -> None:
    messages = [Message.user_text("only")]
    usage = Usage(input_tokens=10, output_tokens=5)
    assert estimate_context_tokens(messages, usage, last_usage_index=99) == 15
