"""Auto compact 阈值、熔断与 Agent 钩子单测。"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from icecode.agent import Agent
from icecode.compact.autocompact import (
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
    get_autocompact_threshold,
    should_autocompact,
)
from icecode.compact.full_compact import CompactError
from icecode.compact.windows import get_buffer_threshold
from icecode.config import Config
from icecode.llm.base import LLMProvider, LLMResponse, Message, TextBlock, Usage
from icecode.session import append_usage_snapshot, load_session_state
from icecode.tools.registry import build_empty_registry


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, texts: list[str] | None = None) -> None:
        self.model = "fake-model"
        self.texts = list(texts or ["ok"])
        self.calls: list[dict[str, Any]] = []

    def create_message(
        self,
        messages: list[Message],
        system: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        self.calls.append(
            {"messages": messages, "system": system, "tools": tools, "max_tokens": max_tokens}
        )
        text = self.texts.pop(0) if self.texts else "ok"
        return LLMResponse(
            content=[TextBlock(text=text)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=5, output_tokens=2),
        )


def _agent(
    provider: FakeProvider | None = None,
    session_path: Path | None = None,
    **cfg_kw,
) -> Agent:
    defaults: dict = dict(
        enable_tools=False,
        enable_streaming=False,
        enable_microcompact=False,
        enable_autocompact=True,
        compact_reserved_output_tokens=100,
        autocompact_buffer_tokens=100,
        context_window_override=2000,
    )
    defaults.update(cfg_kw)
    cfg = Config(**defaults)
    return Agent(
        provider=provider or FakeProvider(),
        registry=build_empty_registry(),
        cfg=cfg,
        console=Console(file=io.StringIO()),
        session_path=session_path,
    )


def test_get_buffer_threshold_alias() -> None:
    assert get_buffer_threshold(100_000, 13_000) == 87_000


def test_get_autocompact_threshold() -> None:
    # 2000 - 100 reserved - 100 buffer = 1800
    assert get_autocompact_threshold(
        "fake-model", 100, 100, override=2000
    ) == 1800


def test_get_autocompact_threshold_invalid() -> None:
    with pytest.raises(ValueError):
        get_autocompact_threshold("fake-model", -1, 100, override=2000)
    with pytest.raises(ValueError):
        get_autocompact_threshold("fake-model", 100, 100, override=50)


def test_should_autocompact_inclusive() -> None:
    assert should_autocompact(1800, 1800) is True
    assert should_autocompact(1801, 1800) is True
    assert should_autocompact(1799, 1800) is False


def test_maybe_autocompact_triggers_when_over_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent(FakeProvider(texts=["摘要内容"]))
    agent.messages = [Message.user_text("long " * 200)]
    called: list[str] = []
    orig = agent._apply_full_compact

    def wrapped(trigger: str) -> None:
        called.append(trigger)
        orig(trigger)

    monkeypatch.setattr(agent, "_apply_full_compact", wrapped)
    monkeypatch.setattr("icecode.agent.estimate_context_tokens", lambda *a, **k: 9999)
    agent._maybe_autocompact()
    assert called == ["auto"]
    assert agent._autocompact_consecutive_failures == 0
    assert len(agent.messages) == 1
    assert "摘要内容" in agent.messages[0].text()


def test_maybe_autocompact_skips_when_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent()
    agent.messages = [Message.user_text("hi")]
    monkeypatch.setattr("icecode.agent.estimate_context_tokens", lambda *a, **k: 10)
    agent._maybe_autocompact()
    assert agent.messages[0].text() == "hi"
    assert len(agent.provider.calls) == 0  # type: ignore[attr-defined]


def test_maybe_autocompact_fail_closed_invalid_config() -> None:
    agent = _agent(compact_reserved_output_tokens=10**9)  # 有效窗口必 ≤0
    agent.messages = [Message.user_text("hi")]
    agent._maybe_autocompact()
    assert agent.messages[0].text() == "hi"


def test_circuit_breaker_stops_after_three_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent()
    agent.messages = [Message.user_text("hi")]
    n = {"calls": 0}

    def boom(*a, **k):
        n["calls"] += 1
        raise CompactError("fail")

    monkeypatch.setattr("icecode.agent.run_full_compact", boom)
    monkeypatch.setattr("icecode.agent.estimate_context_tokens", lambda *a, **k: 9999)

    for _ in range(5):
        agent._maybe_autocompact()

    assert n["calls"] == MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES
    assert agent._autocompact_consecutive_failures == MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES
    assert agent.messages[0].text() == "hi"


def test_microcompact_runs_before_autocompact(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _agent()
    order: list[str] = []
    monkeypatch.setattr(
        agent, "_maybe_microcompact", lambda: order.append("mc")
    )
    monkeypatch.setattr(
        agent, "_maybe_autocompact", lambda: order.append("ac")
    )
    agent.run_turn("hello")
    assert order == ["mc", "ac"]


def test_run_turn_persists_usage_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    agent = _agent(FakeProvider(texts=["reply"]), session_path=path, enable_autocompact=False)
    agent.run_turn("hello")
    state = load_session_state(path)
    assert len(state.messages) >= 2
    assert state.last_usage.input_tokens == 5
    assert state.last_usage.output_tokens == 2
    assert state.last_usage_message_index == len(state.messages)


def test_resume_after_compact_does_not_keep_stale_usage(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    agent = _agent(FakeProvider(texts=["摘要"]), session_path=path)
    agent.messages = [Message.user_text("old " * 50)]
    agent.last_call_usage = Usage(input_tokens=50_000, output_tokens=10)
    agent.last_call_message_index = 1
    append_usage_snapshot(path, agent.last_call_usage, 1)

    agent._apply_full_compact("auto")
    state = load_session_state(path)
    assert state.last_usage.input_tokens == 0
    assert state.last_usage.output_tokens == 0
    assert len(state.messages) == 1
    assert "摘要" in state.messages[0].text()
