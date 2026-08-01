"""tool_use / tool_result 配对修复与 Agent 判定。"""

from __future__ import annotations

from icecode.llm.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from icecode.llm.deepseek_provider import DeepSeekProvider
from icecode.llm.pairing import (
    SYNTHETIC_TOOL_RESULT_PLACEHOLDER,
    ensure_tool_result_pairing,
)


def test_ensure_pairing_inserts_synthetic_before_user_text() -> None:
    messages = [
        Message.user_text("写个贪吃蛇"),
        Message.assistant(
            [ToolUseBlock(id="call_1", name="write_file", input={})]
        ),
        Message.user_text("这个html的路径是什么"),
    ]
    fixed = ensure_tool_result_pairing(messages)
    assert len(fixed) == 3
    assert fixed[1].role == "assistant"
    assert fixed[2].role == "user"
    assert isinstance(fixed[2].content[0], ToolResultBlock)
    assert fixed[2].content[0].tool_use_id == "call_1"
    assert fixed[2].content[0].is_error is True
    assert fixed[2].content[0].content == SYNTHETIC_TOOL_RESULT_PLACEHOLDER
    assert isinstance(fixed[2].content[1], TextBlock)
    assert "路径" in fixed[2].content[1].text


def test_ensure_pairing_noop_when_complete() -> None:
    messages = [
        Message.user_text("hi"),
        Message.assistant(
            [ToolUseBlock(id="call_1", name="read_file", input={"path": "a.py"})]
        ),
        Message.tool_results(
            [ToolResultBlock(tool_use_id="call_1", content="ok")]
        ),
    ]
    fixed = ensure_tool_result_pairing(messages)
    assert len(fixed) == 3
    assert isinstance(fixed[2].content[0], ToolResultBlock)
    assert fixed[2].content[0].content == "ok"
    assert fixed[2].content[0].is_error is False


def test_deepseek_wire_repairs_dangling_tool_use() -> None:
    provider = DeepSeekProvider.__new__(DeepSeekProvider)
    messages = [
        Message.user_text("写个贪吃蛇"),
        Message.assistant(
            [ToolUseBlock(id="call_1", name="write_file", input={})]
        ),
        Message.user_text("路径？"),
    ]
    wire = provider._to_wire_messages(messages, "sys")
    # system + user + assistant(tool_calls) + tool + user
    roles = [m["role"] for m in wire]
    assert roles == ["system", "user", "assistant", "tool", "user"]
    assert wire[3]["tool_call_id"] == "call_1"
    assert wire[4]["content"] == "路径？"


def test_deepseek_from_wire_stop_reason_follows_tool_calls() -> None:
    """有 tool_calls 时即使 finish_reason=stop 也视为 tool_use。"""
    from types import SimpleNamespace

    provider = DeepSeekProvider.__new__(DeepSeekProvider)
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="read_file",
                                arguments='{"path":"a.py"}',
                            ),
                        )
                    ],
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
    )
    out = provider._from_wire_response(resp)
    assert out.stop_reason == "tool_use"
    assert len(out.tool_uses()) == 1
