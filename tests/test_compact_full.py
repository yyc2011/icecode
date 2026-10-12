"""Full compact 摘要重建单测。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from icecode.agent import Agent
from icecode.compact.full_compact import CompactError, FullCompactResult, run_full_compact
from icecode.compact.prompt import build_compact_user_message
from icecode.config import Config
from icecode.llm.base import LLMProvider, LLMResponse, Message, TextBlock, Usage
from icecode.session import load_session_state, message_to_dict
from icecode.tools.registry import build_empty_registry


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(
        self,
        text: str = "摘要正文",
        usage: Usage | None = None,
        error: Exception | None = None,
    ) -> None:
        self.model = "fake-model"
        self.text = text
        self.usage = usage or Usage(input_tokens=12, output_tokens=8)
        self.error = error
        self.calls: list[dict] = []

    def create_message(
        self,
        messages: list[Message],
        system: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "system": system,
                "tools": tools,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        content = [TextBlock(text=self.text)] if self.text else []
        return LLMResponse(content=content, stop_reason="end_turn", usage=self.usage)


def _agent(provider: FakeProvider, session_path: Path | None = None, **cfg_kw) -> Agent:
    defaults: dict = dict(
        enable_tools=False,
        enable_streaming=False,
        enable_microcompact=False,
        enable_autocompact=False,
        compact_reserved_output_tokens=256,
    )
    defaults.update(cfg_kw)
    cfg = Config(**defaults)
    return Agent(
        provider=provider,
        registry=build_empty_registry(),
        cfg=cfg,
        console=Console(file=io.StringIO()),
        session_path=session_path,
    )


def test_run_full_compact_success() -> None:
    provider = FakeProvider(text="  用户想改 foo.py  ")
    messages = [Message.user_text("请改 foo.py")]
    result = run_full_compact(messages, provider, reserved_output_tokens=256)
    assert isinstance(result, FullCompactResult)
    assert result.summary_text == "用户想改 foo.py"
    assert result.usage.input_tokens == 12
    assert result.pre_compact_tokens > 0
    assert provider.calls[0]["tools"] == []
    assert "禁止调用任何工具" in provider.calls[0]["system"]
    for msg in provider.calls[0]["messages"]:
        assert "usage" not in message_to_dict(msg)


def test_run_full_compact_empty_messages() -> None:
    with pytest.raises(CompactError, match="没有足够"):
        run_full_compact([], FakeProvider(), reserved_output_tokens=256)


def test_run_full_compact_empty_text() -> None:
    with pytest.raises(CompactError, match="未返回文本"):
        run_full_compact(
            [Message.user_text("hi")],
            FakeProvider(text=""),
            reserved_output_tokens=256,
        )


def test_run_full_compact_provider_error() -> None:
    with pytest.raises(CompactError, match="摘要调用失败"):
        run_full_compact(
            [Message.user_text("hi")],
            FakeProvider(error=RuntimeError("boom")),
            reserved_output_tokens=256,
        )


def test_apply_full_compact_replaces_messages_and_clears_usage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "s.jsonl"
    provider = FakeProvider(text="已完成读文件，下一步改 bar.py")
    agent = _agent(provider, session_path=path)
    agent.messages = [
        Message.user_text("读 bar.py"),
        Message.assistant([TextBlock(text="好的")]),
    ]
    agent.last_call_usage = Usage(input_tokens=9000, output_tokens=20)
    agent.last_call_message_index = 2
    agent.total_usage = Usage(input_tokens=100, output_tokens=10)

    agent._apply_full_compact("auto")

    assert len(agent.messages) == 1
    assert agent.messages[0].role == "user"
    body = agent.messages[0].text()
    assert "已完成读文件，下一步改 bar.py" in body
    assert body == build_compact_user_message(
        "已完成读文件，下一步改 bar.py", str(path)
    )
    assert agent.last_call_usage.input_tokens == 0
    assert agent.last_call_usage.output_tokens == 0
    assert agent.last_call_message_index == 0
    assert agent.total_usage.input_tokens == 112
    assert agent.total_usage.output_tokens == 18

    state = load_session_state(path)
    assert len(state.messages) == 1
    assert state.messages[0].text() == body
    assert state.last_usage.input_tokens == 0
    assert state.last_usage_message_index == 0
    raw = path.read_text(encoding="utf-8")
    assert '"type": "compact_boundary"' in raw
    assert '"trigger": "auto"' in raw
