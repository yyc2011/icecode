"""usage 累加、session 持久化、DeepSeek/Anthropic 流式 mock。"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from icecode.llm.base import (
    Message,
    StreamDone,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    accumulate_usage,
)
from icecode.llm.anthropic_provider import AnthropicProvider
from icecode.llm.deepseek_provider import DeepSeekProvider
from icecode.session import (
    append_message,
    latest_session,
    list_sessions,
    load_transcript,
    message_from_dict,
    message_to_dict,
    sanitize_workdir,
    session_dir_for,
    transcript_path,
)

# ---------- usage ----------


def test_accumulate_usage() -> None:
    total = Usage(input_tokens=10, output_tokens=5)
    new = Usage(input_tokens=3, output_tokens=7)
    result = accumulate_usage(total, new)
    assert result.input_tokens == 13
    assert result.output_tokens == 12
    # 原对象不变
    assert total.input_tokens == 10


# ---------- session ----------


def test_sanitize_workdir_stable_and_distinct() -> None:
    a = sanitize_workdir("/tmp/foo/bar")
    b = sanitize_workdir("/tmp/foo/bar")
    c = sanitize_workdir("/tmp/foo/baz")
    assert a == b
    assert a != c
    assert "/" not in a


def test_append_and_load_transcript_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ICECODE_HOME", str(tmp_path / "home"))
    workdir = str(tmp_path / "proj")
    path = transcript_path(workdir, "abc123")

    m1 = Message.user_text("你好")
    m2 = Message.assistant([TextBlock(text="嗨"), ToolUseBlock(id="t1", name="read_file", input={"path": "a.py"})])
    append_message(path, m1)
    append_message(path, m2)

    loaded = load_transcript(path)
    assert len(loaded) == 2
    assert loaded[0].role == "user"
    assert loaded[0].text() == "你好"
    assert loaded[1].role == "assistant"
    assert loaded[1].text() == "嗨"
    tools = [b for b in loaded[1].content if isinstance(b, ToolUseBlock)]
    assert tools[0].name == "read_file"
    assert tools[0].input == {"path": "a.py"}


def test_message_dict_roundtrip() -> None:
    msg = Message.tool_results(
        [ToolResultBlock(tool_use_id="t1", content="ok", is_error=False)]
    )
    restored = message_from_dict(message_to_dict(msg))
    assert restored.role == "user"
    assert restored.content[0].tool_use_id == "t1"  # type: ignore[union-attr]
    assert restored.content[0].content == "ok"  # type: ignore[union-attr]


def test_list_sessions_sorted_by_mtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ICECODE_HOME", str(tmp_path / "home"))
    workdir = str(tmp_path / "proj")

    p1 = transcript_path(workdir, "sess1")
    append_message(p1, Message.user_text("first"))
    time.sleep(0.05)
    p2 = transcript_path(workdir, "sess2")
    append_message(p2, Message.user_text("second longer preview message here"))

    sessions = list_sessions(workdir)
    assert len(sessions) == 2
    assert sessions[0].session_id == "sess2"
    assert sessions[1].session_id == "sess1"
    assert "second" in sessions[0].preview

    latest = latest_session(workdir)
    assert latest is not None
    assert latest.session_id == "sess2"


def test_latest_session_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ICECODE_HOME", str(tmp_path / "home"))
    workdir = str(tmp_path / "emptyproj")
    session_dir_for(workdir)  # 创建空目录
    assert latest_session(workdir) is None


# ---------- DeepSeek streaming mock ----------


def _ns(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


def test_deepseek_stream_text_and_tool_calls() -> None:
    provider = DeepSeekProvider.__new__(DeepSeekProvider)
    provider._model = "deepseek-chat"

    # chunk1: text
    # chunk2: tool_call start
    # chunk3: tool_call args continue
    # chunk4: finish + usage-only style
    chunks = [
        _ns(
            usage=None,
            choices=[
                _ns(
                    finish_reason=None,
                    delta=_ns(content="Hello", tool_calls=None),
                )
            ],
        ),
        _ns(
            usage=None,
            choices=[
                _ns(
                    finish_reason=None,
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id="call_1",
                                function=_ns(name="read_file", arguments='{"path":'),
                            )
                        ],
                    ),
                )
            ],
        ),
        _ns(
            usage=None,
            choices=[
                _ns(
                    finish_reason="tool_calls",
                    delta=_ns(
                        content=None,
                        tool_calls=[
                            _ns(
                                index=0,
                                id=None,
                                function=_ns(name=None, arguments='"a.py"}'),
                            )
                        ],
                    ),
                )
            ],
        ),
        _ns(
            usage=_ns(prompt_tokens=11, completion_tokens=4),
            choices=[],
        ),
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter(chunks)
    provider._client = mock_client

    events = list(
        provider.stream_message(
            messages=[Message.user_text("hi")],
            system="sys",
            tools=[],
        )
    )

    deltas = [e for e in events if isinstance(e, TextDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert len(deltas) == 1
    assert deltas[0].text == "Hello"
    assert len(dones) == 1
    resp = dones[0].response
    assert resp.stop_reason == "tool_use"
    assert resp.usage.input_tokens == 11
    assert resp.usage.output_tokens == 4
    assert resp.text() == "Hello"
    tools = resp.tool_uses()
    assert len(tools) == 1
    assert tools[0].id == "call_1"
    assert tools[0].name == "read_file"
    assert tools[0].input == {"path": "a.py"}


# ---------- Anthropic streaming mock ----------


def test_anthropic_stream_text_and_tool_use() -> None:
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._model = "claude-sonnet-4-6"

    events_in = [
        _ns(
            type="message_start",
            message=_ns(usage=_ns(input_tokens=20, output_tokens=0)),
        ),
        _ns(
            type="content_block_start",
            index=0,
            content_block=_ns(type="text"),
        ),
        _ns(
            type="content_block_delta",
            index=0,
            delta=_ns(type="text_delta", text="Hi "),
        ),
        _ns(
            type="content_block_delta",
            index=0,
            delta=_ns(type="text_delta", text="there"),
        ),
        _ns(type="content_block_stop", index=0),
        _ns(
            type="content_block_start",
            index=1,
            content_block=_ns(type="tool_use", id="toolu_1", name="grep_search"),
        ),
        _ns(
            type="content_block_delta",
            index=1,
            delta=_ns(type="input_json_delta", partial_json='{"pattern":'),
        ),
        _ns(
            type="content_block_delta",
            index=1,
            delta=_ns(type="input_json_delta", partial_json='"foo"}'),
        ),
        _ns(type="content_block_stop", index=1),
        _ns(
            type="message_delta",
            delta=_ns(stop_reason="tool_use"),
            usage=_ns(output_tokens=9),
        ),
        _ns(type="message_stop"),
    ]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = iter(events_in)
    provider._client = mock_client

    events = list(
        provider.stream_message(
            messages=[Message.user_text("hi")],
            system="sys",
            tools=[],
        )
    )

    deltas = [e for e in events if isinstance(e, TextDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert [d.text for d in deltas] == ["Hi ", "there"]
    assert len(dones) == 1
    resp = dones[0].response
    assert resp.stop_reason == "tool_use"
    assert resp.usage.input_tokens == 20
    assert resp.usage.output_tokens == 9
    assert resp.text() == "Hi there"
    tools = resp.tool_uses()
    assert len(tools) == 1
    assert tools[0].id == "toolu_1"
    assert tools[0].name == "grep_search"
    assert tools[0].input == {"pattern": "foo"}
